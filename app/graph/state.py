from typing import TypedDict

from app.models.incident import Incident
from app.models.investigation import (
    LogEntry,
    MetricSnapshot,
    RunbookMatch,
)


class InvestigationState(TypedDict, total=False):
    """
    Shared state passed between LangGraph investigation nodes.
    """

    # Incident being investigated
    incident: Incident

    # Investigation evidence
    logs: list[LogEntry]
    metrics: list[MetricSnapshot]
    runbooks: list[RunbookMatch]

    # Tool execution status
    logs_tool_success: bool
    metrics_tool_success: bool
    runbook_tool_success: bool

    # Investigation decisions
    investigation_status: str
    evidence_sufficient: bool
    clarification_needed: bool
    clarification_message: str

    # Error and execution tracking
    errors: list[str]
    run_id: str
    retry_count: int