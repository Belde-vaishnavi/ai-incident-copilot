"""
Diagnosis agent for the ServiceNow Incident Copilot.

Responsibilities:
1. Format investigation evidence.
2. Build the diagnosis prompt.
3. Call the configured LLM with structured output.
4. Validate the returned DiagnosisResult.
5. Apply deterministic confidence and evidence safety checks.

This agent does not execute remediation or write to ServiceNow.
"""

from app.llm.provider import (
    get_llm,
    invoke_structured_with_retry,
)
from app.models.diagnosis import DiagnosisResult
from app.prompts.diagnosis_prompt import build_diagnosis_prompt


ALLOWED_EVIDENCE_SOURCES = {
    "logs",
    "metrics",
    "runbook",
    "historical",
}


def _format_incident_context(incident) -> str:
    """
    Convert the incident model into concise prompt context.
    """

    return (
        f"Incident ID: {incident.incident_id}\n"
        f"Service: {incident.service}\n"
        f"Severity: {incident.severity}\n"
        f"Title: {incident.title}\n"
        f"Description: {incident.description}\n"
        f"Start time: {incident.start_time.isoformat()}\n"
        f"End time: {incident.end_time.isoformat()}"
    )


def _format_logs(logs) -> str:
    """
    Format current incident logs for the diagnosis prompt.
    """

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
    """
    Format current incident metrics for the diagnosis prompt.
    """

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
    """
    Format runbook matches for the diagnosis prompt.
    """

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
    """
    Format historical incidents for the diagnosis prompt.
    """

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


def _validate_diagnosis(
    diagnosis: DiagnosisResult,
    state: dict,
) -> DiagnosisResult:
    """
    Apply deterministic safety checks to the LLM diagnosis.

    The LLM remains responsible for reasoning, but the application
    enforces basic evidence and confidence constraints.
    """

    if not diagnosis.likely_root_cause.strip():
        raise ValueError(
            "Diagnosis root cause cannot be empty."
        )

    if not diagnosis.reasoning.strip():
        raise ValueError(
            "Diagnosis reasoning cannot be empty."
        )

    if not diagnosis.evidence:
        raise ValueError(
            "Diagnosis must contain at least one evidence item."
        )

    for evidence in diagnosis.evidence:
        source = evidence.source.strip().lower()

        if source not in ALLOWED_EVIDENCE_SOURCES:
            raise ValueError(
                f"Unsupported diagnosis evidence source: "
                f"{evidence.source!r}. "
                f"Allowed sources: {sorted(ALLOWED_EVIDENCE_SOURCES)}"
            )

        if not evidence.detail.strip():
            raise ValueError(
                "Diagnosis evidence detail cannot be empty."
            )

    current_evidence_sources = set()

    if state.get("logs"):
        current_evidence_sources.add("logs")

    if state.get("metrics"):
        current_evidence_sources.add("metrics")

    if state.get("runbooks"):
        current_evidence_sources.add("runbook")

    if state.get("historical_context"):
        current_evidence_sources.add("historical")

    unsupported_sources = {
        evidence.source.strip().lower()
        for evidence in diagnosis.evidence
        if evidence.source.strip().lower()
        not in current_evidence_sources
    }

    if unsupported_sources:
        raise ValueError(
            "Diagnosis references evidence sources that were not "
            f"available during the investigation: "
            f"{sorted(unsupported_sources)}"
        )

    evidence_source_count = len(
        {
            evidence.source.strip().lower()
            for evidence in diagnosis.evidence
        }
    )

    current_source_count = len(current_evidence_sources)

    evidence_has_current_source = bool(
        current_evidence_sources.intersection(
            {"logs", "metrics"}
        )
    )

    if (
        not evidence_has_current_source
        and diagnosis.confidence > 0.74
    ):
        raise ValueError(
            "Diagnosis confidence is too high because the diagnosis "
            "does not contain current incident log or metric evidence."
        )

    if (
        evidence_source_count == 1
        and diagnosis.confidence > 0.89
    ):
        raise ValueError(
            "Diagnosis confidence is too high for a single evidence source."
        )

    if (
        current_source_count >= 2
        and evidence_source_count < 2
    ):
        raise ValueError(
            "Diagnosis should cite multiple evidence sources when "
            "multiple investigation sources are available."
        )

    return diagnosis


def diagnose_incident(state: dict) -> DiagnosisResult:
    """
    Generate and validate a structured diagnosis from investigation
    evidence.
    """

    incident = state.get("incident")

    if incident is None:
        raise ValueError(
            "Cannot diagnose incident because incident state is missing."
        )

    incident_context = _format_incident_context(
        incident
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

    prompt = build_diagnosis_prompt(
        incident_context=incident_context,
        logs_context=logs_context,
        metrics_context=metrics_context,
        runbooks_context=runbooks_context,
        historical_context=historical_context,
    )

    llm = get_llm()

    structured_llm = llm.with_structured_output(
        DiagnosisResult
    )

    try:
        diagnosis = invoke_structured_with_retry(
            structured_llm=structured_llm,
            prompt=prompt,
            operation_name="diagnose_incident",
        )

    except Exception as exc:
        raise ValueError(
            "Diagnosis model failed to produce a structured "
            f"DiagnosisResult: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(diagnosis, DiagnosisResult):
        try:
            diagnosis = DiagnosisResult.model_validate(
                diagnosis
            )

        except Exception as exc:
            raise ValueError(
                "Diagnosis model returned an unexpected structured "
                f"output: {type(diagnosis).__name__}"
            ) from exc

    return _validate_diagnosis(
        diagnosis=diagnosis,
        state=state,
    )