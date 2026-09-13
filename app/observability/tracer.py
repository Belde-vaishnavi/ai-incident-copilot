"""
Lightweight structured tracing for the ServiceNow Incident Copilot.

The tracer records:
- run ID
- node execution
- tool execution
- latency
- redacted inputs/outputs
- diagnosis information
- human approval
- ServiceNow operation
- final workflow outcome

Trace files are stored locally under the project's traces/ directory.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.observability.context import get_run_id


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRACE_DIR = PROJECT_ROOT / "traces"

SENSITIVE_KEYS = {
    "password",
    "api_key",
    "authorization",
    "token",
    "secret",
    "access_token",
    "refresh_token",
    "client_secret",
}


T = TypeVar("T")


def _redact(
    value: Any,
    additional_sensitive_keys: set[str] | None = None,
) -> Any:
    """
    Recursively redact sensitive values.

    additional_sensitive_keys allows individual tools to define
    fields that should not be persisted in traces.
    """

    sensitive_keys = SENSITIVE_KEYS.copy()

    if additional_sensitive_keys:
        sensitive_keys.update(
            key.lower()
            for key in additional_sensitive_keys
        )

    if isinstance(value, dict):
        redacted = {}

        for key, item in value.items():
            normalized_key = str(key).lower()

            if normalized_key in sensitive_keys:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(
                    item,
                    additional_sensitive_keys,
                )

        return redacted

    if isinstance(value, list):
        return [
            _redact(
                item,
                additional_sensitive_keys,
            )
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            _redact(
                item,
                additional_sensitive_keys,
            )
            for item in value
        ]

    if hasattr(value, "model_dump"):
        try:
            return _redact(
                value.model_dump(mode="json"),
                additional_sensitive_keys,
            )
        except Exception:
            return str(value)

    if hasattr(value, "dict"):
        try:
            return _redact(
                value.dict(),
                additional_sensitive_keys,
            )
        except Exception:
            return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if (
        isinstance(value, (str, int, float, bool))
        or value is None
    ):
        return value

    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run_id() -> str:
    """
    Create a unique, human-readable workflow run ID.
    """

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    unique_id = uuid.uuid4().hex[:12]

    return f"{timestamp}-{unique_id}"


def _is_graph_interrupt(exc: BaseException) -> bool:
    """
    Detect LangGraph's expected human-in-the-loop interrupt.

    LangGraph can expose GraphInterrupt directly or through
    an exception whose class name contains 'GraphInterrupt'.
    We intentionally avoid importing a version-specific LangGraph
    exception class here.
    """

    exception_name = type(exc).__name__

    if exception_name == "GraphInterrupt":
        return True

    if "GraphInterrupt" in exception_name:
        return True

    text = str(exc)

    return text.startswith("GraphInterrupt:")


class RunTracer:
    """
    Collect structured observability information for one workflow run.
    """

    def __init__(
        self,
        run_id: str | None = None,
    ) -> None:
        self.run_id = run_id or create_run_id()
        self.started_at = _utc_now()

        self.nodes: list[dict[str, Any]] = []
        self.tools: list[dict[str, Any]] = []
        self.final: dict[str, Any] = {}

    def record_node(
        self,
        node: str,
        status: str,
        latency_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        """
        Record execution of one LangGraph node.
        """

        event: dict[str, Any] = {
            "node": node,
            "status": status,
            "timestamp": _utc_now(),
        }

        if latency_ms is not None:
            event["latency_ms"] = round(
                latency_ms,
                2,
            )

        if error:
            event["error"] = error

        self.nodes.append(event)

    def record_tool(
        self,
        tool: str,
        operation: str,
        status: str,
        latency_ms: float | None = None,
        inputs: Any = None,
        output: Any = None,
        error: str | None = None,
        sensitive_keys: set[str] | None = None,
    ) -> None:
        """
        Record execution of one tool call.
        """

        event: dict[str, Any] = {
            "tool": tool,
            "operation": operation,
            "status": status,
            "timestamp": _utc_now(),
        }

        if latency_ms is not None:
            event["latency_ms"] = round(
                latency_ms,
                2,
            )

        if inputs is not None:
            event["inputs"] = _redact(
                inputs,
                sensitive_keys,
            )

        if output is not None:
            event["output"] = _redact(
                output,
                sensitive_keys,
            )

        if error:
            event["error"] = error

        self.tools.append(event)

    def record_final(
        self,
        diagnosis_confidence: float | None = None,
        diagnosis: str | None = None,
        servicenow_operation: str | None = None,
        servicenow_status: str | None = None,
        servicenow_incident_id: str | None = None,
        servicenow_number: str | None = None,
        approval_status: str | None = None,
        final_outcome: str | None = None,
    ) -> None:
        """
        Record final workflow information.
        """

        self.final = {
            "timestamp": _utc_now(),
            "diagnosis_confidence": diagnosis_confidence,
            "diagnosis": diagnosis,
            "approval_status": approval_status,
            "servicenow_operation": servicenow_operation,
            "servicenow_status": servicenow_status,
            "servicenow_incident_id": servicenow_incident_id,
            "servicenow_number": servicenow_number,
            "final_outcome": final_outcome,
        }

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the trace to a JSON-serializable dictionary.
        """

        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "nodes": self.nodes,
            "tools": self.tools,
            "final": self.final,
        }

    def save(self) -> Path:
        """
        Persist the trace to the local traces directory.
        """

        TRACE_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        trace_path = (
            TRACE_DIR
            / f"{self.run_id}.json"
        )

        with trace_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                self.to_dict(),
                file,
                indent=2,
                ensure_ascii=False,
            )

        logger.info(
            "Trace saved: %s",
            trace_path,
        )

        return trace_path


_TRACERS: dict[str, RunTracer] = {}


def get_tracer() -> RunTracer | None:
    """
    Return the tracer associated with the current workflow run.
    """

    run_id = get_run_id()

    if run_id is None:
        return None

    return _TRACERS.get(run_id)


def create_tracer(
    run_id: str | None = None,
) -> RunTracer:
    """
    Create and register a tracer for the current workflow run.
    """

    tracer = RunTracer(
        run_id=run_id
    )

    _TRACERS[tracer.run_id] = tracer

    return tracer


def remove_tracer(
    run_id: str,
) -> None:
    """
    Remove a tracer from the in-memory registry.
    """

    _TRACERS.pop(
        run_id,
        None,
    )


def trace_node(
    node_name: str,
    function: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    """
    Decorate a LangGraph node with latency and execution tracing.

    Expected human-in-the-loop GraphInterrupt exceptions are recorded
    as 'interrupted' rather than 'error'. The interrupt payload is not
    persisted into the trace.
    """

    @wraps(function)
    def wrapped(
        state: dict[str, Any],
    ) -> dict[str, Any]:
        tracer = get_tracer()

        started = time.perf_counter()

        try:
            result = function(state)

            latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            if tracer is not None:
                tracer.record_node(
                    node=node_name,
                    status="success",
                    latency_ms=latency_ms,
                )

            return result

        except Exception as exc:
            latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            if tracer is not None:
                if _is_graph_interrupt(exc):
                    tracer.record_node(
                        node=node_name,
                        status="interrupted",
                        latency_ms=latency_ms,
                    )
                else:
                    tracer.record_node(
                        node=node_name,
                        status="error",
                        latency_ms=latency_ms,
                        error=(
                            f"{type(exc).__name__}: {exc}"
                        ),
                    )

            raise

    return wrapped


def trace_tool(
    tool_name: str,
    operation: str | None = None,
    sensitive_keys: set[str] | None = None,
) -> Callable[
    [Callable[..., T]],
    Callable[..., T],
]:
    """
    Decorate a tool with structured tracing.

    The decorator:
    - preserves the original function signature
    - captures inputs
    - captures successful outputs
    - captures exceptions
    - records latency
    - applies sensitive-value redaction
    """

    def decorator(
        function: Callable[..., T],
    ) -> Callable[..., T]:

        @wraps(function)
        def wrapped(
            *args: Any,
            **kwargs: Any,
        ) -> T:
            tracer = get_tracer()

            started = time.perf_counter()

            bound_inputs: dict[str, Any]

            try:
                signature = inspect.signature(
                    function
                )

                bound = signature.bind_partial(
                    *args,
                    **kwargs,
                )

                bound_inputs = dict(
                    bound.arguments
                )

            except Exception:
                bound_inputs = {
                    "args": args,
                    "kwargs": kwargs,
                }

            try:
                result = function(
                    *args,
                    **kwargs,
                )

                latency_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                if tracer is not None:
                    tracer.record_tool(
                        tool=tool_name,
                        operation=(
                            operation
                            or function.__name__
                        ),
                        status="success",
                        latency_ms=latency_ms,
                        inputs=bound_inputs,
                        output=result,
                        sensitive_keys=sensitive_keys,
                    )

                return result

            except Exception as exc:
                latency_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                if tracer is not None:
                    if _is_graph_interrupt(exc):
                        tracer.record_tool(
                            tool=tool_name,
                            operation=(
                                operation
                                or function.__name__
                            ),
                            status="interrupted",
                            latency_ms=latency_ms,
                            inputs=bound_inputs,
                            sensitive_keys=sensitive_keys,
                        )
                    else:
                        tracer.record_tool(
                            tool=tool_name,
                            operation=(
                                operation
                                or function.__name__
                            ),
                            status="error",
                            latency_ms=latency_ms,
                            inputs=bound_inputs,
                            error=(
                                f"{type(exc).__name__}: {exc}"
                            ),
                            sensitive_keys=sensitive_keys,
                        )

                raise

        return wrapped

    return decorator


def timed_call(
    function: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> tuple[T, float]:
    """
    Execute a function and return its result plus latency.
    """

    started = time.perf_counter()

    result = function(
        *args,
        **kwargs,
    )

    latency_ms = (
        time.perf_counter()
        - started
    ) * 1000

    return result, latency_ms