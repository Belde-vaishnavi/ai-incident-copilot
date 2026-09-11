from typing import TypedDict

from app.models.incident import Incident
from app.models.investigation import LogEntry, MetricSnapshot, RunbookMatch


class InvestigationState(TypedDict, total=False):
    incident: Incident
    logs: list[LogEntry]
    metrics: list[MetricSnapshot]
    runbooks: list[RunbookMatch]

    logs_tool_success: bool
    metrics_tool_success: bool
    runbook_tool_success: bool

    investigation_status: str
    evidence_sufficient: bool
    clarification_needed: bool
    clarification_message: str

    errors: list[str]
    run_id: str
    retry_count: int