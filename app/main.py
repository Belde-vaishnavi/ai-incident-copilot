import json
from pathlib import Path

from app.graph.graph_builder import build_investigation_graph
from app.models.incident import Incident


INCIDENTS_FILE = Path(__file__).resolve().parent / "data" / "incidents.json"


def load_incident(incident_id: str) -> Incident:
    with INCIDENTS_FILE.open("r", encoding="utf-8") as file:
        incidents = json.load(file)

    for incident_data in incidents:
        if incident_data["incident_id"] == incident_id:
            return Incident.model_validate(incident_data)

    raise ValueError(f"Incident not found: {incident_id}")


def run_investigation(incident_id: str) -> dict:
    incident = load_incident(incident_id)
    graph = build_investigation_graph()
    initial_state = {
        "incident": incident,
        "errors": [],
        "retry_count": 0,
        "investigation_status": "started",
    }
    return graph.invoke(initial_state)


def main() -> None:
    result = run_investigation("INC-SIM-001")

    print("\n=== Investigation Result ===")
    print("Incident:", result["incident"].incident_id)
    print("Status:", result.get("investigation_status"))
    print("Logs:", len(result.get("logs", [])))
    print("Metrics:", len(result.get("metrics", [])))
    print("Runbooks:", len(result.get("runbooks", [])))
    print("Evidence sufficient:", result.get("evidence_sufficient"))
    print("Clarification needed:", result.get("clarification_needed"))
    print("Retry count:", result.get("retry_count"))

    if result.get("errors"):
        print("Errors:")
        for error in result["errors"]:
            print("-", error)

    if result.get("clarification_message"):
        print("Clarification:")
        print(result["clarification_message"])


if __name__ == "__main__":
    main()
