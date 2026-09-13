from app.graph.graph_builder import build_investigation_graph
from app.models.incident import Incident
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INCIDENTS_FILE = (
    PROJECT_ROOT
    / "app"
    / "data"
    / "incidents.json"
)


def load_incident(incident_id: str) -> Incident:
    with INCIDENTS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        records = json.load(file)

    for record in records:
        if record["incident_id"] == incident_id:
            return Incident.model_validate(record)

    raise ValueError(
        f"Incident not found: {incident_id}"
    )


def run_investigation(
    incident_id: str,
) -> dict:
    graph = build_investigation_graph()

    incident = load_incident(
        incident_id
    )

    run_id = (
        f"test-{incident_id}"
    )

    initial_state = {
        "incident": incident,
        "logs": [],
        "metrics": [],
        "runbooks": [],
        "historical_context": [],
        "errors": [],
        "run_id": run_id,
        "retry_count": 0,
        "approval_status": "pending",
    }

    config = {
        "configurable": {
            "thread_id": run_id,
        }
    }

    try:
        graph.invoke(
            initial_state,
            config=config,
        )
    except Exception:
        # The graph is expected to interrupt at the
        # human approval boundary for normal incidents.
        pass

    snapshot = graph.get_state(
        config
    )

    return dict(
        snapshot.values
        or {}
    )


def test_normal_incident_reaches_remediation_boundary():
    result = run_investigation(
        "INC-SIM-001"
    )

    assert result[
        "investigation_status"
    ] == "remediation_plan_completed"

    assert result.get(
        "diagnosis"
    ) is not None

    assert result.get(
        "remediation_plan"
    ) is not None

    assert result.get(
        "approval_status"
    ) == "pending"


def test_insufficient_context_requests_clarification():
    result = run_investigation(
        "INC-SIM-011"
    )

    assert result[
        "investigation_status"
    ] == "insufficient_evidence"

    assert result.get(
        "clarification_needed"
    ) is True

    assert result.get(
        "clarification_message"
    )

    assert result.get(
        "diagnosis"
    ) is None

    assert result.get(
        "remediation_plan"
    ) is None


def test_conflicting_evidence_does_not_claim_diagnosis():
    result = run_investigation(
        "INC-SIM-012"
    )

    assert result[
        "investigation_status"
    ] == "conflicting_evidence"

    assert result.get(
        "clarification_needed"
    ) is True

    assert result.get(
        "clarification_message"
    )

    assert result.get(
        "diagnosis"
    ) is None

    assert result.get(
        "remediation_plan"
    ) is None