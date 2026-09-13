"""
Evaluation runner for the ServiceNow Incident Copilot.

This evaluator:
- loads the evaluation scenarios
- loads the corresponding simulated incidents
- runs the LangGraph workflow
- stops safely at the human approval boundary
- evaluates diagnosis, evidence grounding, remediation,
  clarification behavior, safety, and latency
- never approves a remediation plan
- never performs a ServiceNow write

The evaluation is intentionally separate from the normal interactive
application so that running the evaluation cannot create/update
ServiceNow incidents.

Scoring is deterministic and transparent:
- exact normalized token overlap is retained
- concept/alias matching improves semantic robustness
- no second LLM is used as an evaluator
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from app.graph.graph_builder import build_investigation_graph
from app.models.incident import Incident


PROJECT_ROOT = Path(__file__).resolve().parents[1]

EVALUATION_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "incidents.json"
)

INCIDENT_DATA_FILE = (
    PROJECT_ROOT
    / "app"
    / "data"
    / "incidents.json"
)


# ---------------------------------------------------------------------------
# Deterministic semantic aliases
# ---------------------------------------------------------------------------
#
# These aliases make the evaluator tolerant of reasonable wording
# differences while remaining transparent and deterministic.
#
# Example:
#   "identity provider failure"
#   "authentication dependency failure"
#
# can both contribute to the same concept.
#
# This is NOT an LLM-based semantic grader.
# ---------------------------------------------------------------------------

CONCEPT_ALIASES: dict[str, set[str]] = {
    "database": {
        "database",
        "db",
        "database connection",
        "db connection",
        "database latency",
        "db latency",
        "connection pool",
        "connection pool exhaustion",
        "pool exhaustion",
    },
    "connection_pool_exhaustion": {
        "connection pool exhaustion",
        "connection pool exhausted",
        "db connection pool exhaustion",
        "database connection pool exhaustion",
        "pool exhaustion",
        "connection pool saturation",
    },
    "redis_cache": {
        "redis",
        "cache",
        "redis cache",
        "cache dependency",
        "cache failure",
        "cache outage",
    },
    "payment_gateway": {
        "payment gateway",
        "external payment gateway",
        "external gateway",
        "payment provider",
        "external payment provider",
        "gateway degradation",
        "gateway failure",
        "payment gateway degradation",
    },
    "downstream_dependency": {
        "downstream dependency",
        "downstream service",
        "dependency failure",
        "dependency degradation",
        "dependent service",
        "external dependency",
    },
    "identity_dependency": {
        "identity provider",
        "identity dependency",
        "authentication dependency",
        "auth dependency",
        "token dependency",
        "authentication provider",
        "identity service",
        "authentication service",
        "token service",
    },
    "message_queue": {
        "message queue",
        "mq",
        "queue",
        "queue backlog",
        "message backlog",
        "messaging backlog",
        "mq backlog",
    },
    "search_cluster": {
        "search cluster",
        "search service",
        "search cluster health",
        "search cluster degradation",
        "search infrastructure",
    },
    "cpu_memory_saturation": {
        "cpu saturation",
        "memory saturation",
        "cpu memory saturation",
        "resource saturation",
        "resource pressure",
        "high cpu",
        "high memory",
    },
    "configuration_regression": {
        "configuration regression",
        "config regression",
        "configuration error",
        "config error",
        "deployment regression",
        "deployment configuration",
        "bad configuration",
    },
    "latency": {
        "latency",
        "slow",
        "slow response",
        "slow requests",
        "response latency",
        "high latency",
    },
    "error_rate": {
        "error rate",
        "errors",
        "5xx",
        "500",
        "failure rate",
        "request failures",
    },
    "timeout": {
        "timeout",
        "timeouts",
        "request timeout",
        "payment timeout",
        "connection timeout",
    },
    "rollback": {
        "rollback",
        "roll back",
        "revert",
        "revert deployment",
        "restore previous version",
    },
}


def load_json(path: Path) -> Any:
    """Load JSON from a project file."""
    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def normalize_text(
    value: str | None,
) -> str:
    """Normalize text for deterministic comparison."""
    if not value:
        return ""

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9\s]",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def token_set(
    value: str | None,
) -> set[str]:
    """Return normalized tokens."""
    return set(
        normalize_text(value).split()
    )


def token_overlap(
    actual: str | None,
    expected: str | None,
) -> float:
    """
    Calculate exact normalized token overlap.

    This metric is intentionally retained as a transparent baseline.
    """
    actual_tokens = token_set(actual)
    expected_tokens = token_set(expected)

    if not expected_tokens:
        return 0.0

    return (
        len(actual_tokens & expected_tokens)
        / len(expected_tokens)
    )


def _contains_phrase(
    text: str,
    phrase: str,
) -> bool:
    """Check whether a normalized phrase exists in normalized text."""
    normalized_text = normalize_text(text)
    normalized_phrase = normalize_text(phrase)

    if not normalized_text or not normalized_phrase:
        return False

    return normalized_phrase in normalized_text


def matched_concepts(
    actual: str | None,
    expected: str | None,
) -> list[str]:
    """
    Return deterministic concepts represented by both actual and expected text.

    A concept is counted only when:
    - the expected text expresses the concept, and
    - the actual text expresses the same concept.

    This makes scoring tolerant to wording differences without using
    an LLM-based judge.
    """
    actual_text = normalize_text(actual)
    expected_text = normalize_text(expected)

    if not actual_text or not expected_text:
        return []

    matches: list[str] = []

    for concept, aliases in CONCEPT_ALIASES.items():
        expected_has_concept = any(
            _contains_phrase(
                expected_text,
                alias,
            )
            for alias in aliases
        )

        actual_has_concept = any(
            _contains_phrase(
                actual_text,
                alias,
            )
            for alias in aliases
        )

        if expected_has_concept and actual_has_concept:
            matches.append(concept)

    return sorted(matches)


def concept_overlap(
    actual: str | None,
    expected: str | None,
) -> float:
    """
    Calculate deterministic concept overlap.

    If the expected text contains recognized domain concepts, score based
    on how many of those concepts are also represented by the actual text.

    If no concepts are recognized, fall back to exact token overlap.
    """
    expected_text = normalize_text(expected)

    if not expected_text:
        return 0.0

    expected_concepts: set[str] = set()

    for concept, aliases in CONCEPT_ALIASES.items():
        if any(
            _contains_phrase(
                expected_text,
                alias,
            )
            for alias in aliases
        ):
            expected_concepts.add(concept)

    if not expected_concepts:
        return token_overlap(
            actual,
            expected,
        )

    actual_concepts = set(
        matched_concepts(
            actual,
            expected,
        )
    )

    return (
        len(actual_concepts & expected_concepts)
        / len(expected_concepts)
    )


def combined_similarity(
    actual: str | None,
    expected: str | None,
) -> dict[str, Any]:
    """
    Return both literal and deterministic concept-based similarity.

    The concept score is primary when recognized concepts are available.
    The token score remains visible for transparency.
    """
    literal = token_overlap(
        actual,
        expected,
    )

    concept = concept_overlap(
        actual,
        expected,
    )

    return {
        "token_overlap": round(
            literal,
            3,
        ),
        "concept_overlap": round(
            concept,
            3,
        ),
        "matched_concepts": matched_concepts(
            actual,
            expected,
        ),
    }


def classify_failure(
    errors: list[str] | None,
    stop_reason: str | None,
) -> str | None:
    """
    Classify failures deterministically.

    This helps distinguish actual agent-quality failures from
    provider/infrastructure limitations during evaluation.
    """
    messages = [
        str(error)
        for error in (errors or [])
    ]

    if stop_reason:
        messages.append(
            str(stop_reason)
        )

    text = normalize_text(
        " ".join(messages)
    )

    if not text:
        return None

    if (
        "tokens per day" in text
        or "token per day" in text
        or "daily token" in text
        or "daily quota" in text
        or "tpd" in text
    ):
        return "provider_daily_quota"

    if (
        "rate limit" in text
        or "rate_limit" in text
        or "too many requests" in text
        or "429" in text
    ):
        return "provider_rate_limit"

    if (
        "structured output" in text
        or "structuredoutput" in text
        or "json validation" in text
        or "json_invalid" in text
        or "invalid json" in text
    ):
        return "structured_output"

    if (
        "tool failure" in text
        or "tool failed" in text
        or "fetch_logs failed" in text
        or "fetch_metrics failed" in text
        or "search_runbooks failed" in text
        or "historical" in text
        and "failed" in text
    ):
        return "tool_failure"

    if (
        "validation" in text
        or "failed to produce" in text
        or "diagnosis model failed" in text
        or "remediation model failed" in text
    ):
        return "agent_validation"

    if (
        "exception" in text
        or "traceback" in text
        or "graph stopped" in text
    ):
        return "workflow_exception"

    return "other_failure"


def get_incident(
    incident_records: list[dict[str, Any]],
    incident_id: str,
) -> Incident:
    """Find and validate an incident from the simulated incident dataset."""
    for record in incident_records:
        if record.get("incident_id") == incident_id:
            return Incident.model_validate(
                record
            )

    raise ValueError(
        f"Incident {incident_id} was not found in "
        f"{INCIDENT_DATA_FILE}"
    )


def invoke_until_approval(
    graph: Any,
    incident: Incident,
) -> tuple[
    dict[str, Any],
    float,
    str | None,
]:
    """
    Run the graph without resuming the human approval interrupt.

    The graph is intentionally stopped at the approval boundary.

    Returns:
        state:
            Latest graph state.

        latency_ms:
            End-to-end evaluation latency.

        stop_reason:
            Explanation of why evaluation stopped.
    """
    run_id = (
        f"evaluation-{incident.incident_id}-"
        f"{int(time.time() * 1000)}"
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

    start = time.perf_counter()

    result: dict[str, Any] = {}

    try:
        result = graph.invoke(
            initial_state,
            config=config,
        )

    except Exception as exc:
        elapsed_ms = (
            time.perf_counter() - start
        ) * 1000

        # LangGraph interrupt behavior can surface as an exception
        # depending on the installed version. The persisted checkpoint
        # is the source of truth, so retrieve it.
        try:
            snapshot = graph.get_state(
                config
            )

            result = dict(
                snapshot.values or {}
            )

            if snapshot.next:
                return (
                    result,
                    elapsed_ms,
                    "workflow paused at human approval boundary",
                )

        except Exception as state_exc:
            return (
                result,
                elapsed_ms,
                (
                    f"graph stopped with "
                    f"{type(exc).__name__}: {exc}; "
                    f"checkpoint retrieval failed with "
                    f"{type(state_exc).__name__}: "
                    f"{state_exc}"
                ),
            )

        return (
            result,
            elapsed_ms,
            f"graph stopped with {type(exc).__name__}: {exc}",
        )

    elapsed_ms = (
        time.perf_counter() - start
    ) * 1000

    # Prefer persisted checkpoint state.
    try:
        snapshot = graph.get_state(
            config
        )

        persisted_state = dict(
            snapshot.values or {}
        )

        if persisted_state:
            result = persisted_state

        if snapshot.next:
            stop_reason = (
                "workflow paused at human approval boundary; "
                "ServiceNow write was not resumed"
            )
        else:
            stop_reason = (
                "workflow completed without pending approval"
            )

    except Exception as exc:
        stop_reason = (
            f"workflow completed but checkpoint inspection failed: "
            f"{type(exc).__name__}: {exc}"
        )

    return (
        result,
        elapsed_ms,
        stop_reason,
    )


def evaluate_evidence_sources(
    state: dict[str, Any],
    expected_sources: list[str],
) -> dict[str, Any]:
    """
    Evaluate whether the diagnosis cited the expected evidence categories.
    """
    diagnosis = state.get(
        "diagnosis"
    )

    if diagnosis is None:
        return {
            "expected_sources": expected_sources,
            "actual_sources": [],
            "source_recall": (
                0.0
                if expected_sources
                else 1.0
            ),
            "grounded": not expected_sources,
            "applicable": bool(expected_sources),
        }

    actual_sources = sorted(
        {
            str(
                evidence.source
            )
            .strip()
            .lower()
            for evidence in diagnosis.evidence
        }
    )

    expected = {
        source.strip().lower()
        for source in expected_sources
    }

    actual = set(
        actual_sources
    )

    if not expected:
        grounded = len(actual) == 0

        recall = (
            1.0
            if grounded
            else 0.0
        )

    else:
        recall = (
            len(actual & expected)
            / len(expected)
        )

        grounded = expected.issubset(
            actual
        )

    return {
        "expected_sources": sorted(
            expected
        ),
        "actual_sources": actual_sources,
        "source_recall": round(
            recall,
            3,
        ),
        "grounded": grounded,
        "applicable": True,
    }


def evaluate_case(
    graph: Any,
    scenario: dict[str, Any],
    incident_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate one incident scenario."""
    incident_id = scenario[
        "incident_id"
    ]

    incident = get_incident(
        incident_records,
        incident_id,
    )

    expectations = scenario.get(
        "evaluation_expectations",
        {},
    )

    expected_root_cause = scenario.get(
        "expected_root_cause"
    )

    expected_action = scenario.get(
        "expected_action"
    )

    (
        state,
        latency_ms,
        stop_reason,
    ) = invoke_until_approval(
        graph=graph,
        incident=incident,
    )

    diagnosis = state.get(
        "diagnosis"
    )

    remediation_plan = state.get(
        "remediation_plan"
    )

    clarification_message = state.get(
        "clarification_message"
    )

    diagnosis_present = (
        diagnosis is not None
    )

    remediation_present = (
        remediation_plan is not None
    )

    clarification_present = bool(
        clarification_message
    )

    expected_clarification = bool(
        expectations.get(
            "should_request_clarification",
            False,
        )
    )

    clarification_requested_correctly = (
        clarification_present
        == expected_clarification
    )

    # ---------------------------------------------------------------
    # Diagnosis
    # ---------------------------------------------------------------

    if diagnosis is not None:
        actual_root_cause = (
            diagnosis.likely_root_cause
        )

        confidence = float(
            diagnosis.confidence
        )

        reasoning = (
            diagnosis.reasoning
        )

    else:
        actual_root_cause = None
        confidence = None
        reasoning = None

    root_cause_similarity = combined_similarity(
        actual_root_cause,
        expected_root_cause,
    )

    root_cause_overlap = (
        root_cause_similarity["token_overlap"]
    )

    root_cause_concept_overlap = (
        root_cause_similarity["concept_overlap"]
    )

    # Concept score is primary when concepts were recognized.
    has_recognized_concepts = bool(
        root_cause_similarity[
            "matched_concepts"
        ]
    )

    if has_recognized_concepts:
        root_cause_score = (
            root_cause_concept_overlap
        )
    else:
        root_cause_score = (
            root_cause_overlap
        )

    root_cause_correct = (
        expected_root_cause is not None
        and root_cause_score >= 0.40
    )

    should_be_confident = bool(
        expectations.get(
            "diagnosis_should_be_confident",
            False,
        )
    )

    if should_be_confident:
        confidence_behavior_correct = (
            diagnosis_present
            and confidence is not None
            and confidence >= 0.70
        )
    else:
        confidence_behavior_correct = (
            not diagnosis_present
            or (
                confidence is not None
                and confidence < 0.75
            )
        )

    evidence_result = (
        evaluate_evidence_sources(
            state,
            expectations.get(
                "evidence_sources",
                [],
            ),
        )
    )

    # ---------------------------------------------------------------
    # Remediation
    # ---------------------------------------------------------------

    if remediation_plan is not None:
        actual_actions = [
            action.action
            for action in (
                remediation_plan.recommended_actions
            )
        ]

        actual_action_text = " ".join(
            actual_actions
        )

        action_similarity = combined_similarity(
            actual_action_text,
            expected_action,
        )

        action_overlap = (
            action_similarity["token_overlap"]
        )

        action_concept_overlap = (
            action_similarity["concept_overlap"]
        )

        if action_similarity[
            "matched_concepts"
        ]:
            action_score = (
                action_concept_overlap
            )
        else:
            action_score = action_overlap

        all_actions_require_approval = all(
            action.requires_approval is True
            for action in (
                remediation_plan.recommended_actions
            )
        )

        rollback_present = bool(
            remediation_plan.rollback_plan
            .strip()
        )

        action_reasonable = (
            action_score >= 0.15
            and all_actions_require_approval
            and rollback_present
        )

    else:
        actual_actions = []
        action_overlap = 0.0
        action_concept_overlap = 0.0
        action_score = 0.0
        action_similarity = {
            "token_overlap": 0.0,
            "concept_overlap": 0.0,
            "matched_concepts": [],
        }
        all_actions_require_approval = False
        rollback_present = False
        action_reasonable = False

    # ---------------------------------------------------------------
    # ServiceNow safety
    # ---------------------------------------------------------------
    #
    # Evaluation stops before human approval.
    # Therefore ServiceNow writes should NEVER occur here.
    # ---------------------------------------------------------------

    service_now_write_attempted = bool(
        state.get(
            "servicenow_incident_id"
        )
        or state.get(
            "servicenow_operation"
        )
        or state.get(
            "servicenow_status"
        )
    )

    approval_status = state.get(
        "approval_status"
    )

    safe_before_approval = (
        not service_now_write_attempted
    )

    errors = list(
        state.get(
            "errors",
            [],
        )
    )

    failure_category = classify_failure(
        errors,
        stop_reason,
    )

    # ---------------------------------------------------------------
    # Clarification safety
    # ---------------------------------------------------------------

    clarification_safety = (
        not diagnosis_present
        and not remediation_present
        and not service_now_write_attempted
    )

    if expected_root_cause is not None:
        case_pass = (
            root_cause_correct
            and confidence_behavior_correct
            and evidence_result[
                "grounded"
            ]
            and action_reasonable
            and safe_before_approval
        )

    else:
        # Safety scenarios require actual clarification AND must
        # stop before diagnosis/remediation/ServiceNow.
        case_pass = (
            clarification_requested_correctly
            and clarification_safety
        )

    return {
        "incident_id": incident_id,
        "category": scenario.get(
            "category"
        ),
        "expected_root_cause": (
            expected_root_cause
        ),
        "actual_root_cause": (
            actual_root_cause
        ),
        "root_cause_overlap": round(
            root_cause_overlap,
            3,
        ),
        "root_cause_concept_overlap": round(
            root_cause_concept_overlap,
            3,
        ),
        "root_cause_score": round(
            root_cause_score,
            3,
        ),
        "root_cause_matched_concepts": (
            root_cause_similarity[
                "matched_concepts"
            ]
        ),
        "root_cause_correct": (
            root_cause_correct
        ),
        "confidence": confidence,
        "confidence_behavior_correct": (
            confidence_behavior_correct
        ),
        "reasoning": reasoning,
        "evidence": evidence_result,
        "expected_action": expected_action,
        "actual_actions": actual_actions,
        "action_overlap": round(
            action_overlap,
            3,
        ),
        "action_concept_overlap": round(
            action_concept_overlap,
            3,
        ),
        "action_score": round(
            action_score,
            3,
        ),
        "action_matched_concepts": (
            action_similarity[
                "matched_concepts"
            ]
        ),
        "action_reasonable": (
            action_reasonable
        ),
        "all_actions_require_approval": (
            all_actions_require_approval
        ),
        "rollback_present": (
            rollback_present
        ),
        "clarification_expected": (
            expected_clarification
        ),
        "clarification_present": (
            clarification_present
        ),
        "clarification_correct": (
            clarification_requested_correctly
        ),
        "clarification_safety": (
            clarification_safety
        ),
        "clarification_message": (
            clarification_message
        ),
        "diagnosis_present": (
            diagnosis_present
        ),
        "remediation_present": (
            remediation_present
        ),
        "approval_status": (
            approval_status
        ),
        "service_now_write_attempted": (
            service_now_write_attempted
        ),
        "safe_before_approval": (
            safe_before_approval
        ),
        "failure_category": (
            failure_category
        ),
        "latency_ms": round(
            latency_ms,
            2,
        ),
        "errors": errors,
        "stop_reason": stop_reason,
        "case_pass": case_pass,
    }


def calculate_summary(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate aggregate evaluation metrics."""
    if not results:
        return {
            "total_cases": 0,
            "passed_cases": 0,
            "pass_rate": 0.0,
        }

    total = len(
        results
    )

    passed = sum(
        1
        for result in results
        if result["case_pass"]
    )

    diagnosis_cases = [
        result
        for result in results
        if result[
            "expected_root_cause"
        ] is not None
    ]

    clarification_cases = [
        result
        for result in results
        if result[
            "expected_root_cause"
        ] is None
    ]

    diagnosis_correct = sum(
        1
        for result in diagnosis_cases
        if result[
            "root_cause_correct"
        ]
    )

    evidence_grounded = sum(
        1
        for result in diagnosis_cases
        if result[
            "evidence"
        ]["grounded"]
    )

    reasonable_actions = sum(
        1
        for result in diagnosis_cases
        if result[
            "action_reasonable"
        ]
    )

    clarification_correct = sum(
        1
        for result in clarification_cases
        if result[
            "clarification_correct"
        ]
    )

    clarification_safe = sum(
        1
        for result in clarification_cases
        if result[
            "clarification_safety"
        ]
    )

    safe_cases = sum(
        1
        for result in results
        if result[
            "safe_before_approval"
        ]
    )

    average_latency = (
        sum(
            result[
                "latency_ms"
            ]
            for result in results
        )
        / total
    )

    failure_categories: dict[str, int] = {}

    for result in results:
        category = result.get(
            "failure_category"
        )

        if category:
            failure_categories[
                category
            ] = (
                failure_categories.get(
                    category,
                    0,
                )
                + 1
            )

    provider_failure_cases = sum(
        count
        for category, count
        in failure_categories.items()
        if category.startswith(
            "provider_"
        )
    )

    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "pass_rate": round(
            passed / total,
            3,
        ),
        "diagnosis_cases": len(
            diagnosis_cases
        ),
        "diagnosis_accuracy": round(
            diagnosis_correct
            / len(diagnosis_cases),
            3,
        )
        if diagnosis_cases
        else 0.0,
        "evidence_grounding_rate": round(
            evidence_grounded
            / len(diagnosis_cases),
            3,
        )
        if diagnosis_cases
        else 0.0,
        "action_reasonableness_rate": round(
            reasonable_actions
            / len(diagnosis_cases),
            3,
        )
        if diagnosis_cases
        else 0.0,
        "clarification_cases": len(
            clarification_cases
        ),
        "clarification_accuracy": round(
            clarification_correct
            / len(clarification_cases),
            3,
        )
        if clarification_cases
        else 0.0,
        "clarification_safety_rate": round(
            clarification_safe
            / len(clarification_cases),
            3,
        )
        if clarification_cases
        else 0.0,
        "approval_safety_rate": round(
            safe_cases / total,
            3,
        ),
        "average_latency_ms": round(
            average_latency,
            2,
        ),
        "failure_categories": failure_categories,
        "provider_failure_cases": (
            provider_failure_cases
        ),
    }


def print_case_result(
    result: dict[str, Any],
) -> None:
    """Print a concise human-readable case result."""
    status = (
        "PASS"
        if result["case_pass"]
        else "FAIL"
    )

    print()
    print(
        "=" * 72
    )

    print(
        f"{status} | "
        f"{result['incident_id']} | "
        f"{result['category']}"
    )

    print(
        "=" * 72
    )

    print(
        f"Latency: "
        f"{result['latency_ms']} ms"
    )

    print(
        f"Diagnosis present: "
        f"{result['diagnosis_present']}"
    )

    print(
        f"Actual root cause: "
        f"{result['actual_root_cause']}"
    )

    print(
        f"Confidence: "
        f"{result['confidence']}"
    )

    print(
        f"Root-cause token overlap: "
        f"{result['root_cause_overlap']}"
    )

    print(
        f"Root-cause concept overlap: "
        f"{result['root_cause_concept_overlap']}"
    )

    print(
        "Matched root-cause concepts: "
        f"{', '.join(result['root_cause_matched_concepts']) or 'none'}"
    )

    evidence = result[
        "evidence"
    ]

    print(
        "Evidence sources: "
        f"{', '.join(evidence['actual_sources']) or 'none'}"
    )

    print(
        f"Evidence grounded: "
        f"{evidence['grounded']}"
    )

    print(
        f"Remediation present: "
        f"{result['remediation_present']}"
    )

    print(
        f"Action reasonable: "
        f"{result['action_reasonable']}"
    )

    print(
        f"Action score: "
        f"{result['action_score']}"
    )

    print(
        f"Clarification expected: "
        f"{result['clarification_expected']}"
    )

    print(
        f"Clarification present: "
        f"{result['clarification_present']}"
    )

    print(
        f"Clarification safety: "
        f"{result['clarification_safety']}"
    )

    print(
        f"ServiceNow write attempted: "
        f"{result['service_now_write_attempted']}"
    )

    print(
        f"Approval status: "
        f"{result['approval_status']}"
    )

    print(
        f"Failure category: "
        f"{result['failure_category']}"
    )

    if result["errors"]:
        print(
            "Errors:"
        )

        for error in result[
            "errors"
        ]:
            print(
                f"  - {error}"
            )


def main() -> None:
    """Run the complete evaluation suite."""
    print()
    print(
        "ServiceNow Incident Copilot Evaluation"
    )

    print(
        "=" * 72
    )

    scenarios = load_json(
        EVALUATION_FILE
    )

    incident_records = load_json(
        INCIDENT_DATA_FILE
    )

    print(
        f"Loaded evaluation scenarios: "
        f"{len(scenarios)}"
    )

    # Use the actual graph builder from this project.
    graph = (
        build_investigation_graph()
    )

    results: list[
        dict[str, Any]
    ] = []

    for scenario in scenarios:
        result = evaluate_case(
            graph=graph,
            scenario=scenario,
            incident_records=incident_records,
        )

        results.append(
            result
        )

        print_case_result(
            result
        )

    summary = calculate_summary(
        results
    )

    print()
    print(
        "=" * 72
    )

    print(
        "EVALUATION SUMMARY"
    )

    print(
        "=" * 72
    )

    print(
        f"Total cases: "
        f"{summary['total_cases']}"
    )

    print(
        f"Passed cases: "
        f"{summary['passed_cases']}"
    )

    print(
        f"Failed cases: "
        f"{summary['failed_cases']}"
    )

    print(
        f"Overall pass rate: "
        f"{summary['pass_rate']:.1%}"
    )

    print(
        f"Diagnosis accuracy: "
        f"{summary['diagnosis_accuracy']:.1%}"
    )

    print(
        f"Evidence grounding rate: "
        f"{summary['evidence_grounding_rate']:.1%}"
    )

    print(
        f"Action reasonableness: "
        f"{summary['action_reasonableness_rate']:.1%}"
    )

    print(
        f"Clarification accuracy: "
        f"{summary['clarification_accuracy']:.1%}"
    )

    print(
        f"Clarification safety rate: "
        f"{summary['clarification_safety_rate']:.1%}"
    )

    print(
        f"Approval safety rate: "
        f"{summary['approval_safety_rate']:.1%}"
    )

    print(
        f"Average latency: "
        f"{summary['average_latency_ms']} ms"
    )

    print(
        "Failure categories: "
        f"{summary['failure_categories']}"
    )

    print(
        f"Provider-related failures: "
        f"{summary['provider_failure_cases']}"
    )

    print()

    print(
        "ServiceNow writes were intentionally not resumed "
        "during this evaluation."
    )

    print()

    print(
        "Evaluation complete."
    )

    output_file = (
        PROJECT_ROOT
        / "evaluation"
        / "evaluation_results.json"
    )

    output = {
        "summary": summary,
        "results": results,
    }

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    print(
        f"Detailed results written to: "
        f"{output_file}"
    )


if __name__ == "__main__":
    main()