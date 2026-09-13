from pydantic import BaseModel, Field


class DiagnosisEvidence(BaseModel):
    """
    A single piece of evidence supporting the diagnosis.
    """

    source: str = Field(
        ...,
        description=(
            "Evidence source. Expected values include logs, metrics, "
            "runbook, or historical."
        ),
    )

    detail: str = Field(
        ...,
        min_length=1,
        description="Specific evidence supporting the diagnosis.",
    )


class DiagnosisResult(BaseModel):
    """
    Structured diagnosis produced by the diagnosis agent.
    """

    likely_root_cause: str = Field(
        ...,
        min_length=1,
        description=(
            "The most likely root cause of the incident based only "
            "on the available investigation evidence."
        ),
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in the diagnosis represented as a value "
            "between 0 and 1."
        ),
    )

    reasoning: str = Field(
        ...,
        min_length=1,
        description=(
            "Concise explanation connecting the available evidence "
            "to the proposed root cause."
        ),
    )

    evidence: list[DiagnosisEvidence] = Field(
        default_factory=list,
        description="Evidence supporting the proposed root cause.",
    )