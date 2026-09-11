from app.graph.state import InvestigationState


MAX_RETRIES = 2


def route_after_evidence_assessment(state: InvestigationState) -> str:
    """Route to diagnosis boundary, clarification, or a bounded retry."""

    retry_count = state.get("retry_count", 0)

    if state.get("evidence_sufficient"):
        return "diagnosis"

    if retry_count < MAX_RETRIES:
        return "retry"

    return "clarification"