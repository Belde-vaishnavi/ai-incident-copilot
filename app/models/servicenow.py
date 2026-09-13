from pydantic import BaseModel, Field


class ServiceNowCreateRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        description="Short description/title for the ServiceNow incident.",
    )

    description: str = Field(
        ...,
        min_length=1,
        description="Detailed incident description.",
    )

    severity: str = Field(
        ...,
        min_length=1,
        description="Incident severity, for example P1, P2, or P3.",
    )

    work_notes: str = Field(
        ...,
        min_length=1,
        description="AI-generated triage and remediation proposal.",
    )

    idempotency_key: str = Field(
        ...,
        min_length=1,
        description="Stable key used to prevent duplicate incident creation.",
    )


class ServiceNowUpdateRequest(BaseModel):
    incident_id: str = Field(
        ...,
        min_length=1,
        description="ServiceNow incident sys_id.",
    )

    state: str = Field(
        ...,
        min_length=1,
        description="Target ServiceNow incident state.",
    )

    work_notes: str = Field(
        ...,
        min_length=1,
        description="Work notes to append to the incident.",
    )

    impact: str | None = Field(
        default=None,
        description="ServiceNow impact value.",
    )

    urgency: str | None = Field(
        default=None,
        description="ServiceNow urgency value.",
    )


class ServiceNowIncident(BaseModel):
    sys_id: str = Field(
        ...,
        min_length=1,
        description="ServiceNow sys_id.",
    )

    number: str = Field(
        ...,
        min_length=1,
        description="Human-readable ServiceNow incident number.",
    )

    short_description: str = Field(
        ...,
        min_length=1,
        description="ServiceNow short description.",
    )

    state: str | None = Field(
        default=None,
        description="Current ServiceNow incident state.",
    )

    impact: str | None = Field(
        default=None,
        description="ServiceNow impact value.",
    )

    urgency: str | None = Field(
        default=None,
        description="ServiceNow urgency value.",
    )

    priority: str | None = Field(
        default=None,
        description="ServiceNow calculated priority.",
    )


class ServiceNowToolResult(BaseModel):
    success: bool = Field(
        ...,
        description="Whether the ServiceNow operation succeeded.",
    )

    operation: str = Field(
        ...,
        min_length=1,
        description="Operation performed.",
    )

    incident: ServiceNowIncident | None = Field(
        default=None,
        description="Created or updated incident when successful.",
    )

    error_code: str | None = Field(
        default=None,
        description="Machine-readable error code.",
    )

    error_message: str | None = Field(
        default=None,
        description="Human-readable error message.",
    )