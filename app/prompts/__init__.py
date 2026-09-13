"""
Prompt templates used by the ServiceNow Incident Copilot.
"""

from app.prompts.diagnosis_prompt import (
    DIAGNOSIS_SYSTEM_PROMPT,
    build_diagnosis_prompt,
)

from app.prompts.remediation_prompt import (
    REMEDIATION_SYSTEM_PROMPT,
    build_remediation_prompt,
)


__all__ = [
    "DIAGNOSIS_SYSTEM_PROMPT",
    "REMEDIATION_SYSTEM_PROMPT",
    "build_diagnosis_prompt",
    "build_remediation_prompt",
]