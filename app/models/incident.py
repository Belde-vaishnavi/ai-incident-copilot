from datetime import datetime

from pydantic import BaseModel, Field


class Incident(BaseModel):
    """Represents an incident submitted to the Incident Copilot."""

    incident_id: str = Field(..., description="Unique incident identifier.")
    service: str = Field(..., description="Affected service.")
    severity: str = Field(..., description="Incident severity, for example P1 or P2.")
    title: str = Field(..., description="Short incident title.")
    description: str = Field(..., description="Detailed incident description.")
    start_time: datetime = Field(..., description="Incident investigation start time.")
    end_time: datetime = Field(..., description="Incident investigation end time.")
    
    expected_root_cause: str | None = Field(
        default=None,
        description="Evaluation-only expected root cause."
    )
    
    expected_action: str | None = Field(
        default=None,
        description="Evaluation-only expected remediation action."
    )