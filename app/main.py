import json
import uuid
from pathlib import Path

from langgraph.types import Command

from app.graph.graph_builder import build_investigation_graph
from app.models.incident import Incident
from app.observability.context import (
    clear_run_id,
    set_run_id,
)
from app.observability.tracer import (
    create_tracer,
    get_tracer,
    remove_tracer,
)


INCIDENTS_FILE = (
    Path(__file__).resolve().parent
    / "data"
    / "incidents.json"
)


def load_incident(incident_id: str) -> Incident:
    """
    Load a simulated incident from the controlled evaluation dataset.
    """

    with INCIDENTS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        incidents = json.load(file)

    for incident_data in incidents:
        if incident_data["incident_id"] == incident_id:
            return Incident.model_validate(
                incident_data
            )

    raise ValueError(
        f"Incident not found: {incident_id}"
    )


def run_investigation(
    incident_id: str,
    thread_id: str | None = None,
) -> dict:
    """
    Start the Incident Copilot workflow.

    The workflow will pause at the human approval boundary.

    This helper creates an observability run context so that
    graph nodes and tools can associate their activity with
    the same run ID.
    """

    incident = load_incident(
        incident_id
    )

    graph = build_investigation_graph()

    if thread_id is None:
        thread_id = str(
            uuid.uuid4()
        )

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    tracer = create_tracer()

    set_run_id(
        tracer.run_id
    )

    initial_state = {
        "incident": incident,
        "errors": [],
        "retry_count": 0,
        "investigation_status": "started",
        "run_id": tracer.run_id,
    }

    try:
        result = graph.invoke(
            initial_state,
            config=config,
        )

        return result

    finally:
        clear_run_id()


def print_investigation_summary(
    result: dict,
) -> None:
    """
    Display the investigation and remediation information
    before asking for human approval.
    """

    print(
        "\n" + "=" * 70
    )
    print(
        "SERVICE NOW INCIDENT COPILOT"
    )
    print(
        "=" * 70
    )

    incident = result["incident"]

    print("\nIncident")
    print("--------")
    print(
        "ID:",
        incident.incident_id,
    )
    print(
        "Service:",
        incident.service,
    )
    print(
        "Severity:",
        incident.severity,
    )
    print(
        "Title:",
        incident.title,
    )

    print("\nInvestigation")
    print("-------------")
    print(
        "Logs:",
        len(
            result.get(
                "logs",
                [],
            )
        ),
    )
    print(
        "Metrics:",
        len(
            result.get(
                "metrics",
                [],
            )
        ),
    )
    print(
        "Runbooks:",
        len(
            result.get(
                "runbooks",
                [],
            )
        ),
    )
    print(
        "Historical incidents:",
        len(
            result.get(
                "historical_context",
                [],
            )
        ),
    )

    diagnosis = result.get(
        "diagnosis"
    )

    if diagnosis:
        print("\nDiagnosis")
        print("---------")
        print(
            "Likely root cause:",
            diagnosis.likely_root_cause,
        )
        print(
            "Confidence:",
            diagnosis.confidence,
        )
        print(
            "Reasoning:",
            diagnosis.reasoning,
        )

        print("\nEvidence:")

        for evidence in diagnosis.evidence:
            print(
                f"- [{evidence.source}] "
                f"{evidence.detail}"
            )

    remediation = result.get(
        "remediation_plan"
    )

    if remediation:
        print(
            "\nRemediation Plan"
        )
        print(
            "----------------"
        )
        print(
            "Root cause:",
            remediation.likely_root_cause,
        )
        print(
            "Confidence:",
            remediation.confidence,
        )

        print(
            "\nRecommended actions:"
        )

        for index, action in enumerate(
            remediation.recommended_actions,
            start=1,
        ):
            print(
                f"{index}. "
                f"{action.action}"
            )
            print(
                f"   Risk: "
                f"{action.risk}"
            )
            print(
                "   Requires approval:",
                action.requires_approval,
            )

        print(
            "\nRollback plan:"
        )
        print(
            remediation.rollback_plan
        )


def _record_final_trace(
    result: dict,
) -> None:
    """
    Record and persist the final workflow outcome.
    """

    tracer = get_tracer()

    if tracer is None:
        return

    diagnosis = result.get(
        "diagnosis"
    )

    diagnosis_text = None
    diagnosis_confidence = None

    if diagnosis is not None:
        diagnosis_text = (
            diagnosis.likely_root_cause
        )
        diagnosis_confidence = (
            diagnosis.confidence
        )

    tracer.record_final(
        diagnosis=diagnosis_text,
        diagnosis_confidence=diagnosis_confidence,
        approval_status=result.get(
            "approval_status"
        ),
        servicenow_operation=result.get(
            "servicenow_operation"
        ),
        servicenow_status=result.get(
            "servicenow_status"
        ),
        servicenow_incident_id=result.get(
            "servicenow_incident_id"
        ),
        servicenow_number=result.get(
            "servicenow_number"
        ),
        final_outcome=result.get(
            "final_outcome"
        ),
    )

    trace_path = tracer.save()

    print(
        "\nTrace saved:",
        trace_path,
    )


def main() -> None:
    """
    Interactive Incident Copilot demonstration.
    """

    incident_id = "INC-SIM-001"

    graph = build_investigation_graph()

    thread_id = str(
        uuid.uuid4()
    )

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    incident = load_incident(
        incident_id
    )

    # ---------------------------------------------------------
    # Create observability run
    # ---------------------------------------------------------

    tracer = create_tracer()

    set_run_id(
        tracer.run_id
    )

    print(
        "\nRun ID:",
        tracer.run_id,
    )

    initial_state = {
        "incident": incident,
        "errors": [],
        "retry_count": 0,
        "investigation_status": "started",
        "run_id": tracer.run_id,
    }

    try:

        # ---------------------------------------------------------
        # Run investigation until human approval interrupt
        # ---------------------------------------------------------

        result = graph.invoke(
            initial_state,
            config=config,
        )

        print_investigation_summary(
            result
        )

        # ---------------------------------------------------------
        # Check whether workflow is waiting for human input
        # ---------------------------------------------------------

        snapshot = graph.get_state(
            config
        )

        if not snapshot.next:

            print(
                "\nWorkflow completed."
            )

            print(
                "ServiceNow status:",
                result.get(
                    "servicenow_status"
                ),
            )

            _record_final_trace(
                result
            )

            return

        # ---------------------------------------------------------
        # Human approval
        # ---------------------------------------------------------

        print(
            "\n" + "=" * 70
        )
        print(
            "HUMAN APPROVAL REQUIRED"
        )
        print(
            "=" * 70
        )

        print(
            "\nNo ServiceNow write has been performed."
        )

        while True:

            decision = input(
                "\nApprove remediation? [y/n]: "
            ).strip().lower()

            if decision in {
                "y",
                "yes",
            }:

                human_response = {
                    "decision": "approved",
                }

                break

            if decision in {
                "n",
                "no",
            }:

                reason = input(
                    "Reason for rejection: "
                ).strip()

                human_response = {
                    "decision": "rejected",
                    "reason": (
                        reason
                        or
                        "Human rejected the remediation plan."
                    ),
                }

                break

            print(
                "Please enter 'y' or 'n'."
            )

        # ---------------------------------------------------------
        # Record approval decision
        # ---------------------------------------------------------

        tracer = get_tracer()

        if tracer is not None:

            decision_value = (
                human_response.get(
                    "decision"
                )
            )

            tracer.record_node(
                node="human_approval_decision",
                status=decision_value,
            )

        # ---------------------------------------------------------
        # Resume the paused LangGraph workflow
        # ---------------------------------------------------------

        result = graph.invoke(
            Command(
                resume=human_response
            ),
            config=config,
        )

        # ---------------------------------------------------------
        # Final result
        # ---------------------------------------------------------

        print(
            "\n" + "=" * 70
        )
        print(
            "FINAL OUTCOME"
        )
        print(
            "=" * 70
        )

        print(
            "Approval:",
            result.get(
                "approval_status"
            ),
        )

        print(
            "ServiceNow operation:",
            result.get(
                "servicenow_operation"
            ),
        )

        print(
            "ServiceNow status:",
            result.get(
                "servicenow_status"
            ),
        )

        print(
            "ServiceNow incident:",
            result.get(
                "servicenow_number"
            ),
        )

        print(
            "ServiceNow sys_id:",
            result.get(
                "servicenow_incident_id"
            ),
        )

        print(
            "Outcome:",
            result.get(
                "final_outcome"
            ),
        )

        if result.get(
            "rejection_reason"
        ):

            print(
                "Rejection reason:",
                result[
                    "rejection_reason"
                ],
            )

        if result.get(
            "servicenow_error_message"
        ):

            print(
                "ServiceNow error:",
                result[
                    "servicenow_error_message"
                ],
            )

        if result.get(
            "errors"
        ):

            print("\nErrors:")

            for error in result[
                "errors"
            ]:

                print(
                    "-",
                    error,
                )

        # ---------------------------------------------------------
        # Persist final trace
        # ---------------------------------------------------------

        _record_final_trace(
            result
        )

    finally:

        clear_run_id()

        remove_tracer(
            tracer.run_id
        )


if __name__ == "__main__":
    main()