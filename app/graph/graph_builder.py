from langgraph.graph import END, START, StateGraph

from app.graph.edges import route_after_evidence_assessment
from app.graph.nodes import assess_evidence, investigate_incident, request_clarification
from app.graph.state import InvestigationState


def build_investigation_graph():
    """Build and compile the Phase 4 investigation workflow."""

    graph = StateGraph(InvestigationState)
    graph.add_node("investigate", investigate_incident)
    graph.add_node("assess_evidence", assess_evidence)
    graph.add_node("clarification", request_clarification)

    graph.add_edge(START, "investigate")
    graph.add_edge("investigate", "assess_evidence")
    graph.add_conditional_edges(
        "assess_evidence",
        route_after_evidence_assessment,
        {
            "diagnosis": END,
            "clarification": "clarification",
            "retry": "investigate",
        },
    )
    graph.add_edge("clarification", END)

    return graph.compile()