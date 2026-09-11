from app.tools.log_tools import fetch_logs
from app.tools.metric_tools import fetch_metrics
from app.tools.runbook_tools import search_runbooks


def investigate_incident(state: dict) -> dict:
    """
    Investigate an incident using simulated logs, metrics, and runbooks.
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

    errors = list(state.get("errors", []))

    if not logs_result.success:
        errors.append(
            f"fetch_logs failed: "
            f"{logs_result.error_code} - {logs_result.error_message}"
        )

    if not metrics_result.success:
        errors.append(
            f"fetch_metrics failed: "
            f"{metrics_result.error_code} - {metrics_result.error_message}"
        )

    if not runbook_result.success:
        errors.append(
            f"search_runbooks failed: "
            f"{runbook_result.error_code} - {runbook_result.error_message}"
        )

    retry_count = state.get("retry_count", 0)

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
    }


def assess_evidence(state: dict) -> dict:
    """
    Determine whether enough investigation evidence is available
    to proceed toward diagnosis.
    """

    logs = state.get("logs", [])
    metrics = state.get("metrics", [])
    runbooks = state.get("runbooks", [])

    tool_failures = any(
        [
            not state.get("logs_tool_success", False),
            not state.get("metrics_tool_success", False),
            not state.get("runbook_tool_success", False),
        ]
    )

    if tool_failures:
        return {
            "evidence_sufficient": False,
            "clarification_needed": False,
            "investigation_status": "tool_failure",
        }

    evidence_sources = 0

    if logs:
        evidence_sources += 1

    if metrics:
        evidence_sources += 1

    if runbooks:
        evidence_sources += 1

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


def request_clarification(state: dict) -> dict:
    """
    Prepare a clarification request when the investigation cannot
    safely proceed because evidence is insufficient or tools failed.
    """

    incident = state["incident"]
    investigation_status = state.get("investigation_status")

    if investigation_status == "tool_failure":
        errors = state.get("errors", [])

        error_details = (
            "; ".join(errors)
            if errors
            else "One or more investigation tools failed."
        )

        clarification_message = (
            f"Investigation for incident {incident.incident_id} "
            f"affecting {incident.service} could not be completed safely "
            f"because required investigation data was unavailable. "
            f"Details: {error_details}. "
            "Please provide additional incident context or retry the "
            "investigation when the required data sources are available."
        )

    else:
        logs_count = len(state.get("logs", []))
        metrics_count = len(state.get("metrics", []))
        runbooks_count = len(state.get("runbooks", []))

        clarification_message = (
            f"Insufficient evidence to confidently diagnose incident "
            f"{incident.incident_id} affecting {incident.service}. "
            f"Investigation collected {logs_count} log records, "
            f"{metrics_count} metric snapshots, and "
            f"{runbooks_count} relevant runbook matches. "
            "Please provide additional context such as recent deployment "
            "changes, affected endpoints, error messages, dependency status, "
            "or the approximate time when the issue started."
        )

    return {
        "clarification_needed": True,
        "clarification_message": clarification_message,
        "investigation_status": "clarification_required",
    }