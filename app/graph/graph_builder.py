from langgraph.checkpoint.memory import MemorySaver
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


def build_investigation_graph():
    """
    Build the explicit LangGraph workflow.

    A MemorySaver checkpointer is used so the workflow can pause at
    the human approval boundary and later resume without repeating
    the investigation or LLM reasoning steps.
    """

    graph = StateGraph(InvestigationState)

    # ---------------------------------------------------------
    # Nodes
    # ---------------------------------------------------------

    graph.add_node(
        "investigate",
        investigate_incident,
    )

    graph.add_node(
        "assess_evidence",
        assess_evidence,
    )

    graph.add_node(
        "diagnosis",
        run_diagnosis,
    )

    graph.add_node(
        "remediation",
        run_remediation_planning,
    )

    graph.add_node(
        "approval",
        request_human_approval,
    )

    graph.add_node(
        "servicenow",
        write_to_servicenow,
    )

    graph.add_node(
        "clarification",
        request_clarification,
    )

    # ---------------------------------------------------------
    # Start
    # ---------------------------------------------------------

    graph.add_edge(
        START,
        "investigate",
    )

    # ---------------------------------------------------------
    # Investigation
    # ---------------------------------------------------------

    graph.add_edge(
        "investigate",
        "assess_evidence",
    )

    graph.add_conditional_edges(
        "assess_evidence",
        route_after_evidence,
        {
            "retry": "investigate",
            "diagnosis": "diagnosis",
            "clarification": "clarification",
        },
    )

    # ---------------------------------------------------------
    # Diagnosis
    # ---------------------------------------------------------

    graph.add_conditional_edges(
        "diagnosis",
        route_after_diagnosis,
        {
            "remediation": "remediation",
            "clarification": "clarification",
        },
    )

    # ---------------------------------------------------------
    # Remediation
    # ---------------------------------------------------------

    graph.add_conditional_edges(
        "remediation",
        route_after_remediation,
        {
            "approval": "approval",
            "clarification": "clarification",
        },
    )

    # ---------------------------------------------------------
    # Human approval
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # ServiceNow
    # ---------------------------------------------------------

    graph.add_edge(
        "servicenow",
        END,
    )

    # ---------------------------------------------------------
    # Clarification
    # ---------------------------------------------------------

    graph.add_edge(
        "clarification",
        END,
    )

    # ---------------------------------------------------------
    # Compile with checkpointing
    # ---------------------------------------------------------

    checkpointer = MemorySaver()

    return graph.compile(
        checkpointer=checkpointer,
    )