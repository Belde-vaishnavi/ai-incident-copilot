from app.main import run_investigation


def test_normal_incident_reaches_evidence_boundary():
    result = run_investigation("INC-SIM-001")

    assert result["investigation_status"] == "evidence_sufficient"
    assert result["evidence_sufficient"] is True
    assert result["clarification_needed"] is False
    assert result["logs"]
    assert result["metrics"]
    assert result["runbooks"]


def test_insufficient_context_requests_clarification():
    result = run_investigation("INC-SIM-011")

    assert result["investigation_status"] == "clarification_required"
    assert result["clarification_needed"] is True
    assert "not enough operational evidence" in result["clarification_message"]


def test_conflicting_evidence_does_not_claim_diagnosis():
    result = run_investigation("INC-SIM-012")

    assert result["investigation_status"] == "evidence_sufficient"
    assert result["evidence_sufficient"] is True
    assert "likely_root_cause" not in result