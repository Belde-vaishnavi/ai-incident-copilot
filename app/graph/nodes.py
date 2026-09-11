from uuid import uuid4

from app.graph.state import InvestigationState
from app.tools.log_tools import fetch_logs
from app.tools.metric_tools import fetch_metrics
from app.tools.runbook_tools import search_runbooks


def investigate_incident(state: InvestigationState) -> dict:
    """Collect deterministic operational evidence for an incident."""

    incident = state["incident"]
    errors = list(state.get("errors", []))
    retry_count = state.get("retry_count", 0)

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

    tool_results = (
        ("fetch_logs", logs_result),
        ("fetch_metrics", metrics_result),
        ("search_runbooks", runbook_result),
    )
    for tool_name, result in tool_results:
        if not result.success:
            error = (
                f"{tool_name} failed: {result.error_code} - "
                f"{result.error_message}"
            )
            if error not in errors:
                errors.append(error)

    return {
        "logs": logs_result.records,
        "metrics": metrics_result.records,
        "runbooks": runbook_result.matches,
        "logs_tool_success": logs_result.success,
        "metrics_tool_success": metrics_result.success,
        "runbook_tool_success": runbook_result.success,
        "errors": errors,
        "investigation_status": "completed",
        "retry_count": retry_count + 1,
        "run_id": state.get("run_id", str(uuid4())),
    }


def assess_evidence(state: InvestigationState) -> dict:
    """Decide whether collected evidence is sufficient for diagnosis."""

    tool_failures = any(
        not state.get(tool_success_field, False)
        for tool_success_field in (
            "logs_tool_success",
            "metrics_tool_success",
            "runbook_tool_success",
        )
    )
    if tool_failures:
        return {
            "evidence_sufficient": False,
            "clarification_needed": False,
            "investigation_status": "tool_failure",
        }

    has_insufficient_evidence_guidance = any(
        "insufficient evidence" in runbook.title.lower()
        or "do not guess" in runbook.snippet.lower()
        for runbook in state.get("runbooks", [])
    )
    if has_insufficient_evidence_guidance:
        return {
            "evidence_sufficient": False,
            "clarification_needed": True,
            "investigation_status": "insufficient_evidence",
        }

    evidence_sources = sum(
        bool(state.get(field, []))
        for field in ("logs", "metrics", "runbooks")
    )
    if evidence_sources >= 2:
        return {
            "evidence_sufficient": True,
            "clarification_needed": False,
            "investigation_status": "evidence_sufficient",
        }

    return {
        "evidence_sufficient": False,
        "clarification_needed": True,
        "investigation_status": "insufficient_evidence",
    }


def request_clarification(state: InvestigationState) -> dict:
    """Prepare a safe clarification request instead of inventing a diagnosis."""

    if state.get("errors"):
        message = (
            "Unable to complete a reliable investigation because one or more "
            "investigation tools failed. Please provide additional context "
            "or retry the investigation."
        )
    else:
        message = (
            "There is not enough operational evidence to determine a reliable "
            "root cause. Please provide additional logs, metrics, timestamps, "
            "request IDs, or recent deployment information."
        )

    return {
        "clarification_needed": True,
        "investigation_status": "clarification_required",
        "clarification_message": message,
    }