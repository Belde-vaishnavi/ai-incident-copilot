def route_after_evidence(state: dict) -> str:
    investigation_status = state.get("investigation_status")
    retry_count = state.get("retry_count", 0)

    if investigation_status == "tool_failure":
        if retry_count < 2:
            return "retry"

        return "clarification"

    if state.get("evidence_sufficient", False):
        return "diagnosis"

    if state.get("clarification_needed", False):
        return "clarification"

    return "clarification"


def route_after_diagnosis(state: dict) -> str:
    if state.get("diagnosis") is not None:
        return "remediation"

    if state.get("investigation_status") == "diagnosis_failure":
        return "clarification"

    return "clarification"


def route_after_remediation(state: dict) -> str:
    if state.get("remediation_plan") is not None:
        return "approval"

    if state.get("investigation_status") == "remediation_plan_failure":
        return "clarification"

    return "clarification"


def route_after_approval(state: dict) -> str:
    """
    Decide what happens after the human approval boundary.

    approved:
        ServiceNow write is allowed.

    rejected:
        No ServiceNow write. Go to clarification/revision.

    pending:
        Stop. Human decision has not yet been supplied.

    anything else:
        Treat as blocked.
    """

    approval_status = state.get("approval_status")

    if approval_status == "approved":
        return "servicenow"

    if approval_status == "rejected":
        return "rejected"

    if approval_status == "pending":
        return "pending"

    return "blocked"