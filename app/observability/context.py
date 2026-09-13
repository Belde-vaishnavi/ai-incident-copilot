"""
Execution context for the ServiceNow Incident Copilot.

The current run ID is stored in a ContextVar so that graph nodes,
tools, and other application components can access the current
workflow execution without adding observability parameters to
business/tool function signatures.
"""

from __future__ import annotations

from contextvars import ContextVar


_current_run_id: ContextVar[str | None] = ContextVar(
    "current_run_id",
    default=None,
)


def set_run_id(run_id: str) -> None:
    """
    Set the run ID for the current execution context.
    """

    _current_run_id.set(run_id)


def get_run_id() -> str | None:
    """
    Return the run ID associated with the current execution context.
    """

    return _current_run_id.get()


def clear_run_id() -> None:
    """
    Clear the current run ID.
    """

    _current_run_id.set(None)