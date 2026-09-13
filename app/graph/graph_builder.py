from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app.graph.edges import (
    route_after_approval,
    route_after_diagnosis,
    route_after_evidence,
    route_after_remediation,
)
from app.graph.nodes import (
    assess_evidence,
    investigate_incident,
    request_clarification,
    request_human_approval,
    run_diagnosis,
    run_remediation_planning,
)
from app.graph.servicenow_node import write_to_servicenow
from app.graph.state import InvestigationState
from app.observability.tracer import trace_node


CHECKPOINT_ALLOWED_MSGPACK_MODULES = [
    ("app.models.incident", "Incident"),
    ("app.models.investigation", "LogEntry"),
    ("app.models.investigation", "MetricSnapshot"),
    ("app.models.investigation", "RunbookMatch"),
    ("app.models.investigation", "HistoricalIncident"),
    ("app.models.diagnosis", "DiagnosisEvidence"),
    ("app.models.diagnosis", "DiagnosisResult"),
    ("app.models.remediation", "Evidence"),
    ("app.models.remediation", "RecommendedAction"),
    ("app.models.remediation", "ServiceNowUpdate"),
    ("app.models.remediation", "RemediationPlan"),
]


def build_investigation_graph():
    """
    Build and compile the Incident Copilot LangGraph workflow.

    The graph uses:
    - Explicit typed/shared state.
    - Conditional routing.
    - Retry behavior for investigation tool failures.
    - Diagnosis and remediation stages.
    - Human approval using LangGraph interrupt().
    - ServiceNow write boundary after approval.
    - In-memory checkpointing for the demo.
    - Explicit checkpoint serialization allow-list.
    - Node-level observability instrumentation.
    """

    graph = StateGraph(
        InvestigationState
    )

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    graph.add_node(
        "investigate",
        trace_node(
            "investigate",
            investigate_incident,
        ),
    )

    graph.add_node(
        "assess_evidence",
        trace_node(
            "assess_evidence",
            assess_evidence,
        ),
    )

    graph.add_node(
        "diagnosis",
        trace_node(
            "diagnosis",
            run_diagnosis,
        ),
    )

    graph.add_node(
        "remediation",
        trace_node(
            "remediation",
            run_remediation_planning,
        ),
    )

    graph.add_node(
        "approval",
        trace_node(
            "approval",
            request_human_approval,
        ),
    )

    graph.add_node(
        "servicenow",
        trace_node(
            "servicenow",
            write_to_servicenow,
        ),
    )

    graph.add_node(
        "clarification",
        trace_node(
            "clarification",
            request_clarification,
        ),
    )

    # ------------------------------------------------------------------
    # Initial investigation flow
    # ------------------------------------------------------------------

    graph.add_edge(
        START,
        "investigate",
    )

    graph.add_edge(
        "investigate",
        "assess_evidence",
    )

    # ------------------------------------------------------------------
    # Evidence routing
    # ------------------------------------------------------------------

    graph.add_conditional_edges(
        "assess_evidence",
        route_after_evidence,
        {
            "retry": "investigate",
            "diagnosis": "diagnosis",
            "clarification": "clarification",
        },
    )

    # ------------------------------------------------------------------
    # Diagnosis routing
    # ------------------------------------------------------------------

    graph.add_conditional_edges(
        "diagnosis",
        route_after_diagnosis,
        {
            "remediation": "remediation",
            "clarification": "clarification",
        },
    )

    # ------------------------------------------------------------------
    # Remediation routing
    # ------------------------------------------------------------------

    graph.add_conditional_edges(
        "remediation",
        route_after_remediation,
        {
            "approval": "approval",
            "clarification": "clarification",
        },
    )

    # ------------------------------------------------------------------
    # Human approval routing
    # ------------------------------------------------------------------

    graph.add_conditional_edges(
        "approval",
        route_after_approval,
        {
            "servicenow": "servicenow",
            "rejected": "clarification",
            "pending": END,
            "blocked": "clarification",
        },
    )

    # ------------------------------------------------------------------
    # Terminal paths
    # ------------------------------------------------------------------

    graph.add_edge(
        "servicenow",
        END,
    )

    graph.add_edge(
        "clarification",
        END,
    )

    # ------------------------------------------------------------------
    # Checkpoint configuration
    # ------------------------------------------------------------------

    serde = JsonPlusSerializer(
        allowed_msgpack_modules=(
            CHECKPOINT_ALLOWED_MSGPACK_MODULES
        ),
    )

    checkpointer = MemorySaver(
        serde=serde,
    )

    return graph.compile(
        checkpointer=checkpointer,
    )