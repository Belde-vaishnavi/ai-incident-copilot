from langgraph.graph import END, START, StateGraph

from app.graph.edges import route_after_evidence
from app.graph.nodes import (
    assess_evidence,
    investigate_incident,
    request_clarification,
)
from app.graph.state import InvestigationState


def build_investigation_graph():
    """
    Build and compile the incident investigation workflow.

    Workflow:
        START
          ↓
        investigate
          ↓
        assess_evidence
          ↓
        conditional routing
          ├── retry → investigate
          ├── diagnosis → END
          └── clarification → clarification → END
    """

    graph = StateGraph(InvestigationState)

    # Register workflow nodes
    graph.add_node("investigate", investigate_incident)
    graph.add_node("assess_evidence", assess_evidence)
    graph.add_node("clarification", request_clarification)

    # Initial workflow
    graph.add_edge(START, "investigate")
    graph.add_edge("investigate", "assess_evidence")

    # Conditional routing after evidence assessment
    graph.add_conditional_edges(
        "assess_evidence",
        route_after_evidence,
        {
            "retry": "investigate",
            "diagnosis": END,
            "clarification": "clarification",
        },
    )

    # Clarification is currently a terminal path.
    graph.add_edge("clarification", END)

    return graph.compile()