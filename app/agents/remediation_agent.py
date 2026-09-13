"""
Remediation agent for the ServiceNow Incident Copilot.

This module is responsible for:
1. Formatting incident and investigation evidence.
2. Formatting the validated diagnosis.
3. Building the remediation prompt.
4. Calling the configured LLM with structured output.
5. Validating the returned RemediationPlan.

The remediation agent only proposes remediation.

It does NOT:
- execute remediation,
- modify infrastructure,
- modify databases,
- restart services,
- create ServiceNow incidents,
- update ServiceNow incidents.
"""

from app.llm.provider import (
    get_llm,
    invoke_structured_with_retry,
)
from app.models.remediation import RemediationPlan
from app.prompts.remediation_prompt import build_remediation_prompt


ALLOWED_EVIDENCE_SOURCES = {
    "logs",
    "metrics",
    "runbook",
    "historical",
}


def _format_incident_context(incident) -> str:
    """Format the incident into deterministic prompt context."""

    return (
        f"Incident ID: {incident.incident_id}\n"
        f"Service: {incident.service}\n"
        f"Severity: {incident.severity}\n"
        f"Title: {incident.title}\n"
        f"Description: {incident.description}\n"
        f"Start time: {incident.start_time.isoformat()}\n"
        f"End time: {incident.end_time.isoformat()}"
    )


def _format_diagnosis_context(diagnosis) -> str:
    """Format the validated diagnosis into prompt context."""

    if diagnosis is None:
        return "No validated diagnosis is available."

    evidence_lines = []

    for evidence in diagnosis.evidence:
        evidence_lines.append(
            f"- source={evidence.source}: {evidence.detail}"
        )

    evidence_context = (
        "\n".join(evidence_lines)
        if evidence_lines
        else "No diagnosis evidence was provided."
    )

    return (
        f"Likely root cause: {diagnosis.likely_root_cause}\n"
        f"Confidence: {diagnosis.confidence}\n"
        f"Reasoning: {diagnosis.reasoning}\n"
        f"Diagnosis evidence:\n{evidence_context}"
    )


def _format_logs(logs) -> str:
    """Format current incident logs."""

    if not logs:
        return "No log records were available."

    lines = []

    for log in logs:
        error_code = (
            f", error_code={log.error_code}"
            if log.error_code
            else ""
        )

        lines.append(
            f"[{log.timestamp.isoformat()}] "
            f"level={log.level}, "
            f"request_id={log.request_id}"
            f"{error_code}: "
            f"{log.message}"
        )

    return "\n".join(lines)


def _format_metrics(metrics) -> str:
    """Format current incident metrics."""

    if not metrics:
        return "No metric records were available."

    lines = []

    for metric in metrics:
        dependencies = ", ".join(
            f"{dependency.name}={dependency.status}"
            for dependency in metric.dependency_health
        )

        if not dependencies:
            dependencies = "No dependency health data."

        lines.append(
            f"[{metric.timestamp.isoformat()}] "
            f"latency_ms={metric.latency_ms}, "
            f"error_rate_percent={metric.error_rate_percent}, "
            f"cpu_percent={metric.cpu_percent}, "
            f"memory_percent={metric.memory_percent}, "
            f"dependencies={dependencies}"
        )

    return "\n".join(lines)


def _format_runbooks(runbooks) -> str:
    """Format relevant runbook matches."""

    if not runbooks:
        return "No relevant runbooks were found."

    lines = []

    for runbook in runbooks:
        lines.append(
            f"Source ID: {runbook.source_id}\n"
            f"Title: {runbook.title}\n"
            f"Service: {runbook.service}\n"
            f"Severity: {runbook.severity}\n"
            f"Snippet: {runbook.snippet}\n"
            f"Relevance: {runbook.relevance_reasoning}"
        )

    return "\n\n".join(lines)


def _format_historical_context(historical_context) -> str:
    """Format historical incident context."""

    if not historical_context:
        return "No relevant historical incidents were found."

    lines = []

    for historical in historical_context:
        symptoms = ", ".join(historical.symptoms)

        lines.append(
            f"Historical incident ID: "
            f"{historical.historical_incident_id}\n"
            f"Service: {historical.service}\n"
            f"Severity: {historical.severity}\n"
            f"Title: {historical.title}\n"
            f"Symptoms: {symptoms}\n"
            f"Known root cause: {historical.root_cause}\n"
            f"Resolution: {historical.resolution}\n"
            f"Related runbook: "
            f"{historical.related_runbook or 'None'}"
        )

    return "\n\n".join(lines)


def _validate_remediation_plan(
    plan: RemediationPlan,
    state: dict,
) -> RemediationPlan:
    """
    Apply deterministic safety validation to the generated plan.

    The LLM is responsible for proposing the plan.
    This function is responsible for enforcing non-negotiable safety rules.
    """

    incident = state.get("incident")
    diagnosis = state.get("diagnosis")

    if incident is None:
        raise ValueError(
            "Cannot validate remediation plan because incident state is missing."
        )

    if diagnosis is None:
        raise ValueError(
            "Cannot validate remediation plan because validated diagnosis is missing."
        )

    # ---------------------------------------------------------
    # Basic plan validation
    # ---------------------------------------------------------

    if not plan.incident_summary.strip():
        raise ValueError(
            "Remediation plan incident_summary cannot be empty."
        )

    if not plan.likely_root_cause.strip():
        raise ValueError(
            "Remediation plan likely_root_cause cannot be empty."
        )

    if not plan.rollback_plan.strip():
        raise ValueError(
            "Remediation plan rollback_plan cannot be empty."
        )

    if not plan.recommended_actions:
        raise ValueError(
            "Remediation plan must contain at least one recommended action."
        )

    # ---------------------------------------------------------
    # Root cause consistency
    # ---------------------------------------------------------

    diagnosis_root_cause = (
        diagnosis.likely_root_cause.strip().lower()
    )

    plan_root_cause = (
        plan.likely_root_cause.strip().lower()
    )

    if not diagnosis_root_cause:
        raise ValueError(
            "Validated diagnosis root cause cannot be empty."
        )

    if not plan_root_cause:
        raise ValueError(
            "Remediation root cause cannot be empty."
        )

    diagnosis_tokens = {
        token
        for token in diagnosis_root_cause.replace(",", " ").split()
        if len(token) > 3
    }

    plan_tokens = {
        token
        for token in plan_root_cause.replace(",", " ").split()
        if len(token) > 3
    }

    if diagnosis_tokens and not diagnosis_tokens.intersection(
        plan_tokens
    ):
        raise ValueError(
            "Remediation plan root cause is inconsistent with "
            "the validated diagnosis."
        )

    # ---------------------------------------------------------
    # Confidence consistency
    # ---------------------------------------------------------

    if abs(plan.confidence - diagnosis.confidence) > 0.15:
        raise ValueError(
            "Remediation plan confidence differs too much from "
            "the validated diagnosis confidence."
        )

    # ---------------------------------------------------------
    # Evidence validation
    # ---------------------------------------------------------

    if not plan.evidence:
        raise ValueError(
            "Remediation plan must contain supporting evidence."
        )

    available_sources = set()

    if state.get("logs"):
        available_sources.add("logs")

    if state.get("metrics"):
        available_sources.add("metrics")

    if state.get("runbooks"):
        available_sources.add("runbook")

    if state.get("historical_context"):
        available_sources.add("historical")

    for evidence in plan.evidence:
        source = evidence.source.strip().lower()

        if source not in ALLOWED_EVIDENCE_SOURCES:
            raise ValueError(
                f"Unsupported remediation evidence source: {evidence.source}"
            )

        if source not in available_sources:
            raise ValueError(
                "Remediation plan cites unavailable evidence source: "
                f"{source}"
            )

        if not evidence.detail.strip():
            raise ValueError(
                "Remediation evidence detail cannot be empty."
            )

    # ---------------------------------------------------------
    # Action safety validation
    # ---------------------------------------------------------

    for action in plan.recommended_actions:

        if not action.action.strip():
            raise ValueError(
                "Recommended remediation action cannot be empty."
            )

        if not action.risk.strip():
            raise ValueError(
                "Recommended remediation action risk cannot be empty."
            )

        # Hard safety boundary.
        if action.requires_approval is not True:
            raise ValueError(
                "Every remediation action must require human approval."
            )

    # ---------------------------------------------------------
    # ServiceNow preparation validation
    # ---------------------------------------------------------

    servicenow_update = plan.servicenow_update

    if not servicenow_update.short_description.strip():
        raise ValueError(
            "ServiceNow short_description cannot be empty."
        )

    if not servicenow_update.severity.strip():
        raise ValueError(
            "ServiceNow severity cannot be empty."
        )

    if not servicenow_update.work_notes.strip():
        raise ValueError(
            "ServiceNow work_notes cannot be empty."
        )

    if (
        servicenow_update.severity.strip().lower()
        != incident.severity.strip().lower()
    ):
        raise ValueError(
            "Proposed ServiceNow severity must match "
            "the current incident severity."
        )

    # ---------------------------------------------------------
    # ServiceNow execution claim validation
    # ---------------------------------------------------------

    prohibited_execution_phrases = [
        "already executed",
        "has been executed",
        "executed successfully",
        "remediation completed",
        "change completed",
        "incident resolved",
        "service restarted",
        "database changed",
        "deployment completed",
        "updated servicenow",
        "created servicenow",
    ]

    work_notes_lower = (
        servicenow_update.work_notes.lower()
    )

    for phrase in prohibited_execution_phrases:
        if phrase in work_notes_lower:
            raise ValueError(
                "ServiceNow work_notes contain a prohibited "
                f"execution claim: '{phrase}'."
            )

    return plan


def create_remediation_plan(state: dict) -> RemediationPlan:
    """
    Generate and validate a structured remediation plan.

    This function only creates a proposal.
    It does not execute any operational action.
    """

    incident = state.get("incident")

    if incident is None:
        raise ValueError(
            "Cannot create remediation plan because incident state is missing."
        )

    diagnosis = state.get("diagnosis")

    if diagnosis is None:
        raise ValueError(
            "Cannot create remediation plan because validated diagnosis is missing."
        )

    incident_context = _format_incident_context(
        incident
    )

    diagnosis_context = _format_diagnosis_context(
        diagnosis
    )

    logs_context = _format_logs(
        state.get("logs", [])
    )

    metrics_context = _format_metrics(
        state.get("metrics", [])
    )

    runbooks_context = _format_runbooks(
        state.get("runbooks", [])
    )

    historical_context = _format_historical_context(
        state.get("historical_context", [])
    )

    prompt = build_remediation_prompt(
        incident_context=incident_context,
        diagnosis_context=diagnosis_context,
        logs_context=logs_context,
        metrics_context=metrics_context,
        runbooks_context=runbooks_context,
        historical_context=historical_context,
    )

    llm = get_llm()

    structured_llm = llm.with_structured_output(
        RemediationPlan
    )

    try:
        plan = invoke_structured_with_retry(
            structured_llm=structured_llm,
            prompt=prompt,
            operation_name="create_remediation_plan",
        )

    except Exception as exc:
        raise ValueError(
            "Remediation model failed to produce a structured "
            f"RemediationPlan: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(plan, RemediationPlan):
        try:
            plan = RemediationPlan.model_validate(
                plan
            )

        except Exception as exc:
            raise ValueError(
                "Remediation model returned an unexpected structured "
                f"output: {type(plan).__name__}"
            ) from exc

    return _validate_remediation_plan(
        plan=plan,
        state=state,
    )