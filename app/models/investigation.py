from datetime import datetime

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    incident_id: str = Field(
        ...,
        description="Incident associated with the log.",
    )
    service: str = Field(
        ...,
        description="Service that produced the log.",
    )
    timestamp: datetime = Field(
        ...,
        description="Time when the log was generated.",
    )
    level: str = Field(
        ...,
        description="Log severity such as INFO, WARN, or ERROR.",
    )
    message: str = Field(
        ...,
        description="Log message.",
    )
    request_id: str = Field(
        ...,
        description="Request or correlation identifier.",
    )
    error_code: str | None = Field(
        default=None,
        description="Application error code when available.",
    )


class DependencyHealth(BaseModel):
    name: str = Field(
        ...,
        description="Dependency name.",
    )
    status: str = Field(
        ...,
        description="Dependency health status.",
    )


class MetricSnapshot(BaseModel):
    incident_id: str = Field(
        ...,
        description="Incident associated with the metrics.",
    )
    service: str = Field(
        ...,
        description="Service being measured.",
    )
    timestamp: datetime = Field(
        ...,
        description="Time when the metrics were captured.",
    )
    latency_ms: float = Field(
        ...,
        ge=0,
        description="Observed latency in milliseconds.",
    )
    error_rate_percent: float = Field(
        ...,
        ge=0,
        le=100,
        description="Error rate as a percentage.",
    )
    cpu_percent: float = Field(
        ...,
        ge=0,
        le=100,
        description="CPU utilization percentage.",
    )
    memory_percent: float = Field(
        ...,
        ge=0,
        le=100,
        description="Memory utilization percentage.",
    )
    dependency_health: list[DependencyHealth] = Field(
        default_factory=list,
        description="Health status of relevant dependencies.",
    )


class RunbookMatch(BaseModel):
    source_id: str = Field(
        ...,
        description="Unique runbook source identifier.",
    )
    service: str = Field(
        ...,
        description="Service covered by the runbook.",
    )
    severity: str = Field(
        ...,
        description="Severity covered by the runbook.",
    )
    title: str = Field(
        ...,
        description="Runbook title.",
    )
    snippet: str = Field(
        ...,
        description="Relevant runbook guidance.",
    )
    relevance_reasoning: str = Field(
        ...,
        description="Explanation of why the runbook matched the investigation query.",
    )


class HistoricalIncident(BaseModel):
    historical_incident_id: str = Field(
        ...,
        description="Unique historical incident identifier.",
    )
    service: str = Field(
        ...,
        description="Service affected by the historical incident.",
    )
    severity: str = Field(
        ...,
        description="Historical incident severity.",
    )
    title: str = Field(
        ...,
        description="Historical incident title.",
    )
    symptoms: list[str] = Field(
        default_factory=list,
        description="Symptoms observed during the historical incident.",
    )
    root_cause: str = Field(
        ...,
        description="Known historical root cause.",
    )
    resolution: str = Field(
        ...,
        description="Historical resolution.",
    )
    related_runbook: str | None = Field(
        default=None,
        description="Related runbook source ID.",
    )


# ---------------------------------------------------------------------------
# Typed tool result models
# ---------------------------------------------------------------------------


class LogFetchResult(BaseModel):
    success: bool = Field(
        ...,
        description="Whether the log fetch completed successfully.",
    )
    records: list[LogEntry] = Field(
        default_factory=list,
        description="Fetched log records.",
    )
    error_code: str | None = Field(
        default=None,
        description="Machine-readable error code.",
    )
    error_message: str | None = Field(
        default=None,
        description="Human-readable error message.",
    )


class MetricFetchResult(BaseModel):
    success: bool = Field(
        ...,
        description="Whether the metric fetch completed successfully.",
    )
    records: list[MetricSnapshot] = Field(
        default_factory=list,
        description="Fetched metric snapshots.",
    )
    error_code: str | None = Field(
        default=None,
        description="Machine-readable error code.",
    )
    error_message: str | None = Field(
        default=None,
        description="Human-readable error message.",
    )


class RunbookSearchResult(BaseModel):
    success: bool = Field(
        ...,
        description="Whether the runbook search completed successfully.",
    )
    matches: list[RunbookMatch] = Field(
        default_factory=list,
        description="Matching runbook entries.",
    )
    error_code: str | None = Field(
        default=None,
        description="Machine-readable error code.",
    )
    error_message: str | None = Field(
        default=None,
        description="Human-readable error message.",
    )