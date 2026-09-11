from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """Evidence supporting the incident diagnosis."""

    source: str = Field(
        ...,
        description="Evidence source such as logs, metrics, runbook, or history."
    )
    detail: str = Field(
        ...,
        description="Specific evidence supporting the diagnosis."
    )


class RecommendedAction(BaseModel):
    """A proposed remediation action."""

    action: str = Field(
        ...,
        description="Specific action proposed to remediate the incident."
    )
    risk: str = Field(
        ...,
        description="Risk associated with executing the action."
    )
    requires_approval: bool = Field(
        default=True,
        description="Whether human approval is required before execution."
    )


class ServiceNowUpdate(BaseModel):
    """Information that can be written to a ServiceNow incident."""

    short_description: str = Field(
        ...,
        description="Short ServiceNow incident description."
    )
    severity: str = Field(
        ...,
        description="ServiceNow incident severity."
    )
    work_notes: str = Field(
        ...,
        description="AI-generated investigation and remediation summary."
    )


class RemediationPlan(BaseModel):
    """Structured diagnosis and remediation plan."""

    incident_summary: str = Field(
        ...,
        description="Concise summary of the incident."
    )

    likely_root_cause: str = Field(
        ...,
        description="Most likely root cause based on available evidence."
    )

    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="Confidence in the diagnosis from 0 to 1."
    )

    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Evidence supporting the diagnosis."
    )

    recommended_actions: list[RecommendedAction] = Field(
        default_factory=list,
        description="Proposed remediation actions."
    )

    rollback_plan: str = Field(
        ...,
        description="Plan for safely reversing the remediation if necessary."
    )

    servicenow_update: ServiceNowUpdate = Field(
        ...,
        description="Structured information prepared for ServiceNow."
    )