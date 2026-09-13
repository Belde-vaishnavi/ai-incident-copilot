"""
LangGraph nodes for the ServiceNow Incident Copilot.

Each node has one responsibility.

The graph controls orchestration and branching.
The agents perform LLM-based reasoning.
The tools perform external/data operations.
"""

from __future__ import annotations

import re

from app.agents.diagnosis_agent import diagnose_incident
from app.agents.remediation_agent import create_remediation_plan
from app.tools.historical_tools import search_historical_incidents
from app.tools.log_tools import fetch_logs
from app.tools.metric_tools import fetch_metrics
from app.tools.runbook_tools import search_runbooks
from langgraph.types import interrupt


# ----------------------------------------------------------------------
# Evidence safety signals
# ----------------------------------------------------------------------

INSUFFICIENT_CONTEXT_PATTERNS = (
    "not enough information",
    "not enough context",
    "insufficient information",
    "insufficient context",
    "does not provide enough information",
    "does not provide sufficient information",
    "cannot determine",
    "unable to determine",
)

CONFLICTING_EVIDENCE_PATTERNS = (
    "conflicting evidence",
    "conflicting signals",
    "conflicting findings",
    "insufficient to confidently identify a single root cause",
    "multiple possible root causes",
)


def _normalize_description(
    description: str,
) -> str:
    """
    Normalize incident description for deterministic safety checks.
    """
    normalized = description.lower()

    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    )

    return normalized.strip()


def _has_insufficient_context_signal(
    description: str,
) -> bool:
    """
    Detect explicit statements that the incident description lacks
    enough diagnostic context.

    This is intentionally deterministic. We do not ask an LLM to decide
    whether the incident explicitly says that context is missing.
    """
    normalized = _normalize_description(
        description
    )

    return any(
        pattern in normalized
        for pattern in INSUFFICIENT_CONTEXT_PATTERNS
    )


def _has_conflicting_evidence_signal(
    description: str,
) -> bool:
    """
    Detect explicit statements that available evidence is conflicting.

    This prevents evidence-source count from being treated as equivalent
    to evidence consistency.
    """
    normalized = _normalize_description(
        description
    )

    return any(
        pattern in normalized
        for pattern in CONFLICTING_EVIDENCE_PATTERNS
    )


def investigate_incident(
    state: dict,
) -> dict:
    """
    Collect investigation evidence from all configured sources.

    This node does not perform diagnosis or remediation.
    """

    incident = state["incident"]

    logs_result = fetch_logs(
        service=incident.service,
        start_time=incident.start_time,
        end_time=incident.end_time,
    )

    metrics_result = fetch_metrics(
        service=incident.service,
        start_time=incident.start_time,
        end_time=incident.end_time,
    )

    runbook_result = search_runbooks(
        query=incident.description,
        service=incident.service,
        severity=incident.severity,
    )

    errors = list(
        state.get(
            "errors",
            [],
        )
    )

    # --------------------------------------------------------------
    # Historical incident search
    # --------------------------------------------------------------

    try:
        historical_context = search_historical_incidents(
            service=incident.service,
            query=incident.description,
            severity=incident.severity,
        )

        historical_success = True

    except Exception as exc:
        historical_context = []
        historical_success = False

        errors.append(
            "search_historical_incidents failed: "
            f"{type(exc).__name__} - {exc}"
        )

    # --------------------------------------------------------------
    # Record investigation tool failures
    # --------------------------------------------------------------

    if not logs_result.success:
        errors.append(
            "fetch_logs failed: "
            f"{logs_result.error_code} - "
            f"{logs_result.error_message}"
        )

    if not metrics_result.success:
        errors.append(
            "fetch_metrics failed: "
            f"{metrics_result.error_code} - "
            f"{metrics_result.error_message}"
        )

    if not runbook_result.success:
        errors.append(
            "search_runbooks failed: "
            f"{runbook_result.error_code} - "
            f"{runbook_result.error_message}"
        )

    retry_count = state.get(
        "retry_count",
        0,
    )

    return {
        "logs": logs_result.records,
        "metrics": metrics_result.records,
        "runbooks": runbook_result.matches,
        "historical_context": historical_context,
        "logs_tool_success": logs_result.success,
        "metrics_tool_success": metrics_result.success,
        "runbook_tool_success": runbook_result.success,
        "historical_tool_success": historical_success,
        "errors": errors,
        "investigation_status": "completed",
        "retry_count": retry_count + 1,
    }


def assess_evidence(
    state: dict,
) -> dict:
    """
    Determine whether enough consistent evidence exists to continue
    to diagnosis.

    Safety principle:

        evidence quantity != evidence quality

    The workflow therefore checks:
    1. Required investigation tools succeeded.
    2. The incident explicitly says whether context is insufficient.
    3. The incident explicitly says whether evidence is conflicting.
    4. At least two independent evidence sources are available.

    Explicit insufficient/conflicting signals take precedence over the
    source count.
    """

    incident = state["incident"]

    logs = state.get(
        "logs",
        [],
    )

    metrics = state.get(
        "metrics",
        [],
    )

    runbooks = state.get(
        "runbooks",
        [],
    )

    historical_context = state.get(
        "historical_context",
        [],
    )

    description = incident.description

    # --------------------------------------------------------------
    # Core investigation failures
    # --------------------------------------------------------------

    core_tool_failures = any(
        [
            not state.get(
                "logs_tool_success",
                False,
            ),
            not state.get(
                "metrics_tool_success",
                False,
            ),
            not state.get(
                "runbook_tool_success",
                False,
            ),
        ]
    )

    if core_tool_failures:
        return {
            "evidence_sufficient": False,
            "clarification_needed": False,
            "investigation_status": "tool_failure",
        }

    # --------------------------------------------------------------
    # Explicit insufficient-context safety signal
    # --------------------------------------------------------------

    if _has_insufficient_context_signal(
        description
    ):
        return {
            "evidence_sufficient": False,
            "clarification_needed": True,
            "investigation_status": "insufficient_evidence",
        }

    # --------------------------------------------------------------
    # Explicit conflicting-evidence safety signal
    # --------------------------------------------------------------

    if _has_conflicting_evidence_signal(
        description
    ):
        return {
            "evidence_sufficient": False,
            "clarification_needed": True,
            "investigation_status": "conflicting_evidence",
        }

    # --------------------------------------------------------------
    # Count independent evidence sources
    # --------------------------------------------------------------

    evidence_sources = 0

    if logs:
        evidence_sources += 1

    if metrics:
        evidence_sources += 1

    if runbooks:
        evidence_sources += 1

    if historical_context:
        evidence_sources += 1

    # --------------------------------------------------------------
    # Evidence sufficient
    # --------------------------------------------------------------

    if evidence_sources >= 2:
        return {
            "evidence_sufficient": True,
            "clarification_needed": False,
            "investigation_status": "evidence_sufficient",
        }

    # --------------------------------------------------------------
    # Evidence insufficient
    # --------------------------------------------------------------

    return {
        "evidence_sufficient": False,
        "clarification_needed": True,
        "investigation_status": "insufficient_evidence",
    }


def run_diagnosis(
    state: dict,
) -> dict:
    """
    Run the diagnosis agent.

    The diagnosis agent returns a validated DiagnosisResult.
    """

    try:
        diagnosis = diagnose_incident(
            state
        )

        return {
            "diagnosis": diagnosis,
            "investigation_status": "diagnosis_completed",
        }

    except Exception as exc:
        errors = list(
            state.get(
                "errors",
                [],
            )
        )

        errors.append(
            "diagnose_incident failed: "
            f"{type(exc).__name__} - {exc}"
        )

        return {
            "errors": errors,
            "investigation_status": "diagnosis_failure",
        }


def run_remediation_planning(
    state: dict,
) -> dict:
    """
    Run the remediation planning agent.

    This node creates a remediation proposal only.

    It does NOT:
    - execute remediation,
    - modify infrastructure,
    - modify databases,
    - restart services,
    - create ServiceNow incidents,
    - update ServiceNow incidents.
    """

    try:
        remediation_plan = create_remediation_plan(
            state
        )

        return {
            "remediation_plan": remediation_plan,
            "investigation_status": (
                "remediation_plan_completed"
            ),
        }

    except Exception as exc:
        errors = list(
            state.get(
                "errors",
                [],
            )
        )

        errors.append(
            "create_remediation_plan failed: "
            f"{type(exc).__name__} - {exc}"
        )

        return {
            "errors": errors,
            "investigation_status": (
                "remediation_plan_failure"
            ),
        }


def request_human_approval(
    state: dict,
) -> dict:
    """
    Human approval boundary.

    The workflow pauses here before any ServiceNow write.

    The remediation plan is presented to the human through LangGraph's
    interrupt mechanism.

    Resume value must contain:

        {
            "decision": "approved"
        }

    or:

        {
            "decision": "rejected",
            "reason": "..."
        }
    """

    remediation_plan = state.get(
        "remediation_plan"
    )

    if remediation_plan is None:
        message = (
            "Human approval cannot be requested because the "
            "remediation plan is missing."
        )

        return {
            "approval_status": "blocked",
            "approval_required": True,
            "approval_message": message,
            "errors": list(
                state.get(
                    "errors",
                    [],
                )
            ) + [message],
        }

    # --------------------------------------------------------------
    # Safety validation
    # --------------------------------------------------------------

    for action in (
        remediation_plan.recommended_actions
    ):
        if action.requires_approval is not True:
            message = (
                "Approval blocked because a remediation action "
                "does not require explicit human approval."
            )

            return {
                "approval_status": "blocked",
                "approval_required": True,
                "approval_message": message,
                "errors": list(
                    state.get(
                        "errors",
                        [],
                    )
                ) + [message],
            }

    # --------------------------------------------------------------
    # If a decision was already supplied, preserve it.
    #
    # This is useful when the node is resumed.
    # --------------------------------------------------------------

    existing_status = state.get(
        "approval_status"
    )

    if existing_status in {
        "approved",
        "rejected",
    }:
        return {
            "approval_status": existing_status,
            "approval_required": True,
        }

    # --------------------------------------------------------------
    # Build human-readable approval request
    # --------------------------------------------------------------

    approval_request = {
        "type": "human_approval_required",
        "message": (
            "The AI Incident Copilot has completed investigation, "
            "diagnosis, and remediation planning. Review the proposed "
            "remediation before allowing any ServiceNow write."
        ),
        "incident_id": state[
            "incident"
        ].incident_id,
        "service": state[
            "incident"
        ].service,
        "severity": state[
            "incident"
        ].severity,
        "diagnosis": {
            "root_cause": state[
                "diagnosis"
            ].likely_root_cause,
            "confidence": state[
                "diagnosis"
            ].confidence,
            "reasoning": state[
                "diagnosis"
            ].reasoning,
        },
        "remediation_plan": (
            remediation_plan.model_dump()
        ),
        "allowed_decisions": [
            "approved",
            "rejected",
        ],
    }

    # --------------------------------------------------------------
    # PAUSE WORKFLOW
    # --------------------------------------------------------------

    human_response = interrupt(
        approval_request
    )

    # --------------------------------------------------------------
    # Validate resume response
    # --------------------------------------------------------------

    if not isinstance(
        human_response,
        dict,
    ):
        message = (
            "Invalid human approval response. Expected an object "
            "containing a decision."
        )

        return {
            "approval_status": "blocked",
            "approval_required": True,
            "approval_message": message,
            "errors": list(
                state.get(
                    "errors",
                    [],
                )
            ) + [message],
        }

    decision = str(
        human_response.get(
            "decision",
            "",
        )
    ).strip().lower()

    if decision == "approved":
        return {
            "approval_status": "approved",
            "approval_required": True,
            "approval_message": (
                "Human approved the remediation plan."
            ),
            "rejection_reason": "",
        }

    if decision == "rejected":
        reason = str(
            human_response.get(
                "reason",
                "Human rejected the remediation plan.",
            )
        ).strip()

        return {
            "approval_status": "rejected",
            "approval_required": True,
            "approval_message": (
                "Human rejected the remediation plan."
            ),
            "rejection_reason": reason,
        }

    message = (
        "Invalid approval decision. Expected 'approved' or 'rejected'."
    )

    return {
        "approval_status": "blocked",
        "approval_required": True,
        "approval_message": message,
        "errors": list(
            state.get(
                "errors",
                [],
            )
        ) + [message],
    }


def request_clarification(
    state: dict,
) -> dict:
    """
    Produce a human-readable clarification message when
    investigation or reasoning cannot safely continue.
    """

    incident = state["incident"]

    investigation_status = state.get(
        "investigation_status"
    )

    # --------------------------------------------------------------
    # Tool failure
    # --------------------------------------------------------------

    if investigation_status == "tool_failure":

        errors = state.get(
            "errors",
            [],
        )

        error_details = (
            "; ".join(errors)
            if errors
            else "One or more investigation tools failed."
        )

        clarification_message = (
            f"Investigation for incident "
            f"{incident.incident_id} affecting "
            f"{incident.service} could not be completed safely "
            f"because required investigation data was unavailable. "
            f"Details: {error_details}. "
            "Please provide additional incident context or retry "
            "the investigation when the required data sources "
            "are available."
        )

    # --------------------------------------------------------------
    # Diagnosis failure
    # --------------------------------------------------------------

    elif investigation_status == "diagnosis_failure":

        clarification_message = (
            f"The investigation for incident "
            f"{incident.incident_id} completed, but the diagnosis "
            "model did not return a valid structured diagnosis. "
            "Please retry the diagnosis after verifying model "
            "availability and structured-output handling."
        )

    # --------------------------------------------------------------
    # Remediation planning failure
    # --------------------------------------------------------------

    elif (
        investigation_status
        == "remediation_plan_failure"
    ):

        clarification_message = (
            f"The diagnosis for incident "
            f"{incident.incident_id} was completed, but the "
            "remediation planning step did not return a valid "
            "safe structured remediation plan. "
            "No operational action was executed. "
            "Please retry remediation planning after verifying "
            "model availability and structured-output validation."
        )

    # --------------------------------------------------------------
    # Approval blocked
    # --------------------------------------------------------------

    elif investigation_status == "approval_blocked":

        clarification_message = (
            f"Human approval for incident "
            f"{incident.incident_id} could not be established safely. "
            "No remediation action and no ServiceNow write should "
            "be performed."
        )

    # --------------------------------------------------------------
    # Approval rejected
    # --------------------------------------------------------------

    elif investigation_status == "approval_rejected":

        rejection_reason = state.get(
            "rejection_reason",
            "No rejection reason was provided.",
        )

        clarification_message = (
            f"Human approval was rejected for incident "
            f"{incident.incident_id}.\n\n"
            f"Reason: {rejection_reason}\n\n"
            "No remediation action was executed and no ServiceNow "
            "write should occur."
        )

    # --------------------------------------------------------------
    # Conflicting evidence
    # --------------------------------------------------------------

    elif investigation_status == "conflicting_evidence":

        logs_count = len(
            state.get(
                "logs",
                [],
            )
        )

        metrics_count = len(
            state.get(
                "metrics",
                [],
            )
        )

        runbooks_count = len(
            state.get(
                "runbooks",
                [],
            )
        )

        historical_count = len(
            state.get(
                "historical_context",
                [],
            )
        )

        clarification_message = (
            f"Conflicting evidence was detected for incident "
            f"{incident.incident_id} affecting "
            f"{incident.service}. "
            f"Investigation collected "
            f"{logs_count} log records, "
            f"{metrics_count} metric snapshots, "
            f"{runbooks_count} relevant runbook matches, "
            f"and {historical_count} historical incident matches. "
            "The available evidence does not support confidently "
            "selecting a single root cause. "
            "Please provide additional context or investigation "
            "data before proposing remediation."
        )

    # --------------------------------------------------------------
    # Insufficient evidence
    # --------------------------------------------------------------

    else:

        logs_count = len(
            state.get(
                "logs",
                [],
            )
        )

        metrics_count = len(
            state.get(
                "metrics",
                [],
            )
        )

        runbooks_count = len(
            state.get(
                "runbooks",
                [],
            )
        )

        historical_count = len(
            state.get(
                "historical_context",
                [],
            )
        )

        clarification_message = (
            f"Insufficient evidence to confidently diagnose "
            f"incident {incident.incident_id} affecting "
            f"{incident.service}. "
            f"Investigation collected "
            f"{logs_count} log records, "
            f"{metrics_count} metric snapshots, "
            f"{runbooks_count} relevant runbook matches, "
            f"and {historical_count} historical incident matches. "
            "Please provide additional context such as recent "
            "deployment changes, affected endpoints, error "
            "messages, dependency status, or the approximate "
            "time when the issue started."
        )

    return {
        "clarification_needed": True,
        "clarification_message": clarification_message,
    }