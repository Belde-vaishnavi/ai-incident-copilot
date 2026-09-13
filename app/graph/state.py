from typing import TypedDict

from app.models.diagnosis import DiagnosisResult
from app.models.incident import Incident
from app.models.investigation import (
    HistoricalIncident,
    LogEntry,
    MetricSnapshot,
    RunbookMatch,
)
from app.models.remediation import RemediationPlan


class InvestigationState(TypedDict, total=False):
    # ---------------------------------------------------------
    # Incident
    # ---------------------------------------------------------
    incident: Incident

    # ---------------------------------------------------------
    # Investigation evidence
    # ---------------------------------------------------------
    logs: list[LogEntry]
    metrics: list[MetricSnapshot]
    runbooks: list[RunbookMatch]
    historical_context: list[HistoricalIncident]

    # ---------------------------------------------------------
    # Tool execution status
    # ---------------------------------------------------------
    logs_tool_success: bool
    metrics_tool_success: bool
    runbook_tool_success: bool
    historical_tool_success: bool

    investigation_status: str

    # ---------------------------------------------------------
    # Evidence assessment
    # ---------------------------------------------------------
    evidence_sufficient: bool
    clarification_needed: bool
    clarification_message: str

    # ---------------------------------------------------------
    # Diagnosis
    # ---------------------------------------------------------
    diagnosis: DiagnosisResult

    # ---------------------------------------------------------
    # Remediation
    # ---------------------------------------------------------
    remediation_plan: RemediationPlan

    # ---------------------------------------------------------
    # Human approval
    # ---------------------------------------------------------
    approval_required: bool
    approval_status: str
    approval_message: str
    rejection_reason: str

    # ---------------------------------------------------------
    # ServiceNow
    # ---------------------------------------------------------
    servicenow_incident_id: str
    servicenow_status: str
    servicenow_number: str
    servicenow_operation: str
    servicenow_error_code: str
    servicenow_error_message: str

    # ---------------------------------------------------------
    # Final workflow result
    # ---------------------------------------------------------
    final_outcome: str

    # ---------------------------------------------------------
    # General workflow errors
    # ---------------------------------------------------------
    errors: list[str]

    # ---------------------------------------------------------
    # Observability
    # ---------------------------------------------------------
    run_id: str
    retry_count: int