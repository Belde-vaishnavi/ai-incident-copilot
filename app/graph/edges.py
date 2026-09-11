def route_after_evidence(state: dict) -> str:
    """
    Decide the next graph step after evidence assessment.

    Possible routes:
        retry
        diagnosis
        clarification
    """

    investigation_status = state.get("investigation_status")
    retry_count = state.get("retry_count", 0)

    # If an investigation tool failed, retry once more.
    if investigation_status == "tool_failure":
        if retry_count < 2:
            return "retry"

        return "clarification"

    # Sufficient evidence allows the workflow to proceed toward diagnosis.
    if state.get("evidence_sufficient", False):
        return "diagnosis"

    # Insufficient evidence requires clarification.
    if state.get("clarification_needed", False):
        return "clarification"

    # Safe default: do not proceed with diagnosis when the state
    # does not explicitly establish sufficient evidence.
    return "clarification"