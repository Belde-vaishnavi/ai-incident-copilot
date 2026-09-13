"""
Safe, batched evaluation runner for the ServiceNow Incident Copilot.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Project import setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.graph.graph_builder import build_investigation_graph
from app.models.incident import Incident


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

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

RESULTS_FILE = (
    PROJECT_ROOT
    / "evaluation"
    / "evaluation_results.json"
)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def load_json(
    path: Path,
) -> Any:
    """Load JSON from a project file."""

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def save_json(
    path: Path,
    value: Any,
) -> None:
    """Write JSON to a project file."""

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            value,
            file,
            indent=2,
            ensure_ascii=False,
            default=str,
        )


# ---------------------------------------------------------------------------
# Text normalization and deterministic evaluation
# ---------------------------------------------------------------------------

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
    Calculate transparent deterministic token overlap.

    This intentionally does not use another LLM as a grader.
    """

    actual_tokens = token_set(
        actual
    )

    expected_tokens = token_set(
        expected
    )

    if not expected_tokens:
        return 0.0

    return (
        len(
            actual_tokens
            & expected_tokens
        )
        / len(expected_tokens)
    )


# ---------------------------------------------------------------------------
# Semantic concept aliases
# ---------------------------------------------------------------------------

CONCEPT_ALIASES: dict[
    str,
    set[str],
] = {
    "connection_pool_exhaustion": {
        "connection pool exhaustion",
        "connection pool",
        "db pool exhausted",
        "database connections exhausted",
        "pool exhaustion",
        "db connection exhaustion",
    },
    "redis_cache": {
        "redis",
        "cache dependency",
        "redis cache",
        "cache failure",
    },
    "payment_gateway": {
        "payment gateway",
        "external payment gateway",
        "gateway degradation",
    },
    "database": {
        "database",
        "db",
        "database latency",
        "db latency",
        "query latency",
    },
    "latency": {
        "latency",
        "slow requests",
        "slow response",
        "response time",
    },
    "downstream_dependency": {
        "downstream dependency",
        "downstream service",
        "warehouse dependency",
    },
    "message_queue": {
        "message queue",
        "queue backlog",
        "mq backlog",
        "consumer backlog",
    },
    "search_cluster": {
        "search cluster",
        "cluster health",
        "shard",
        "search node",
    },
    "identity_dependency": {
        "identity provider",
        "identity dependency",
        "token validation",
        "auth provider",
    },
    "cpu_memory_saturation": {
        "cpu",
        "memory",
        "resource saturation",
        "cpu memory saturation",
    },
    "configuration_regression": {
        "configuration regression",
        "config regression",
        "deployment regression",
        "bad deployment",
    },
}


def matched_concepts(
    actual: str | None,
    expected: str | None,
) -> list[str]:
    """
    Find semantic concepts shared by actual and expected root causes.
    """

    actual_text = normalize_text(
        actual
    )

    expected_text = normalize_text(
        expected
    )

    if not actual_text or not expected_text:
        return []

    concepts: list[str] = []

    for (
        concept,
        aliases,
    ) in CONCEPT_ALIASES.items():

        expected_match = any(
            alias in expected_text
            for alias in aliases
        )

        actual_match = any(
            alias in actual_text
            for alias in aliases
        )

        if (
            expected_match
            and actual_match
        ):
            concepts.append(
                concept
            )

    return sorted(
        concepts
    )


def concept_overlap(
    actual: str | None,
    expected: str | None,
) -> float:
    """Calculate deterministic semantic concept overlap."""

    expected_text = normalize_text(
        expected
    )

    if not expected_text:
        return 0.0

    expected_concepts = {
        concept
        for (
            concept,
            aliases,
        ) in CONCEPT_ALIASES.items()
        if any(
            alias in expected_text
            for alias in aliases
        )
    }

    if not expected_concepts:
        return token_overlap(
            actual,
            expected,
        )

    return (
        len(
            set(
                matched_concepts(
                    actual,
                    expected,
                )
            )
        )
        / len(expected_concepts)
    )


def combined_similarity(
    actual: str | None,
    expected: str | None,
) -> float:
    """
    Use the stronger of token and semantic concept matching.
    """

    return max(
        token_overlap(
            actual,
            expected,
        ),
        concept_overlap(
            actual,
            expected,
        ),
    )


# ---------------------------------------------------------------------------
# Incident loading
# ---------------------------------------------------------------------------

def get_incident(
    records: list[dict[str, Any]],
    incident_id: str,
) -> Incident:
    """Find and validate an incident from simulated incident data."""

    for record in records:

        if (
            record.get("incident_id")
            == incident_id
        ):
            return Incident.model_validate(
                record
            )

    raise ValueError(
        f"Incident {incident_id} was not found in "
        f"{INCIDENT_DATA_FILE}"
    )


# ---------------------------------------------------------------------------
# Safe workflow invocation
# ---------------------------------------------------------------------------

def invoke_until_approval(
    graph: Any,
    incident: Incident,
) -> tuple[
    dict[str, Any],
    float,
    str,
]:
    """
    Run the workflow and stop at the human approval boundary.

    Evaluation never resumes the approval interrupt.
    Therefore ServiceNow writes cannot be executed by this evaluator.
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
            time.perf_counter()
            - start
        ) * 1000

        try:

            snapshot = graph.get_state(
                config
            )

            result = dict(
                snapshot.values
                or {}
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
                    f"{type(exc).__name__}: "
                    f"{exc}; checkpoint retrieval failed with "
                    f"{type(state_exc).__name__}: "
                    f"{state_exc}"
                ),
            )

        return (
            result,
            elapsed_ms,
            (
                f"graph stopped with "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        )

    elapsed_ms = (
        time.perf_counter()
        - start
    ) * 1000

    try:

        snapshot = graph.get_state(
            config
        )

        persisted_state = dict(
            snapshot.values
            or {}
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
            "checkpoint inspection failed: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    return (
        result,
        elapsed_ms,
        stop_reason,
    )


# ---------------------------------------------------------------------------
# Evidence evaluation
# ---------------------------------------------------------------------------

def evaluate_evidence_sources(
    state: dict[str, Any],
    expected_sources: list[str],
) -> dict[str, Any]:
    """Evaluate diagnosis evidence source grounding."""

    diagnosis = state.get(
        "diagnosis"
    )

    expected = {
        str(source)
        .strip()
        .lower()
        for source in expected_sources
        if str(source).strip()
    }

    if diagnosis is None:

        return {
            "expected_sources": sorted(
                expected
            ),
            "actual_sources": [],
            "source_recall": (
                0.0
                if expected
                else 1.0
            ),
            "grounded": not expected,
        }

    actual_sources = sorted(
        {
            str(
                evidence.source
            )
            .strip()
            .lower()
            for evidence
            in diagnosis.evidence
        }
    )

    actual = set(
        actual_sources
    )

    if expected:

        recall = (
            len(
                actual
                & expected
            )
            / len(expected)
        )

        grounded = expected.issubset(
            actual
        )

    else:

        recall = (
            1.0
            if not actual
            else 0.0
        )

        grounded = not actual

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
    }


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

def classify_failure(
    result: dict[str, Any],
) -> str:
    """Classify failed cases for evaluation reporting."""

    if result["case_pass"]:
        return "none"

    errors = (
        " ".join(
            str(error)
            for error in result.get(
                "errors",
                [],
            )
        )
        + " "
        + str(
            result.get(
                "stop_reason",
                "",
            )
        )
    )

    lowered = errors.lower()

    if any(
        marker in lowered
        for marker in (
            "daily token",
            "tpd",
            "tokens per day",
            "quota exceeded",
        )
    ):
        return "provider_daily_quota"

    if any(
        marker in lowered
        for marker in (
            "rate limit",
            "429",
            "ratelimit",
        )
    ):
        return "provider_rate_limit"

    if any(
        marker in lowered
        for marker in (
            "json validation",
            "structured output",
            "invalidrequesterror",
        )
    ):
        return "provider_structured_output"

    if (
        not result.get(
            "diagnosis_present"
        )
        and result.get(
            "expected_root_cause"
        )
    ):
        return "diagnosis_failure"

    if (
        result.get(
            "diagnosis_present"
        )
        and not result.get(
            "evidence",
            {},
        ).get(
            "grounded",
            False,
        )
    ):
        return "evidence_grounding"

    if (
        result.get(
            "diagnosis_present"
        )
        and not result.get(
            "action_reasonable",
            False,
        )
    ):
        return "remediation_quality"

    if (
        result.get(
            "clarification_expected"
        )
        and not result.get(
            "clarification_correct"
        )
    ):
        return "clarification_failure"

    if not result.get(
        "safe_before_approval",
        False,
    ):
        return "approval_safety_failure"

    return "other_failure"


# ---------------------------------------------------------------------------
# Single case evaluation
# ---------------------------------------------------------------------------

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

    remediation = state.get(
        "remediation_plan"
    )

    clarification_message = state.get(
        "clarification_message"
    )

    diagnosis_present = (
        diagnosis is not None
    )

    remediation_present = (
        remediation is not None
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

    clarification_correct = (
        clarification_present
        == expected_clarification
    )

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

    root_cause_overlap = token_overlap(
        actual_root_cause,
        expected_root_cause,
    )

    root_cause_concept_overlap = (
        concept_overlap(
            actual_root_cause,
            expected_root_cause,
        )
    )

    root_cause_score = (
        combined_similarity(
            actual_root_cause,
            expected_root_cause,
        )
    )

    root_cause_matched_concepts = (
        matched_concepts(
            actual_root_cause,
            expected_root_cause,
        )
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

    evidence = (
        evaluate_evidence_sources(
            state,
            expectations.get(
                "evidence_sources",
                [],
            ),
        )
    )

    if remediation is not None:

        actions = [
            action.action
            for action
            in remediation.recommended_actions
        ]

        action_text = " ".join(
            actions
        )

        action_overlap = token_overlap(
            action_text,
            expected_action,
        )

        action_concepts = concept_overlap(
            action_text,
            expected_action,
        )

        action_score = max(
            action_overlap,
            action_concepts,
        )

        all_actions_require_approval = all(
            action.requires_approval is True
            for action
            in remediation.recommended_actions
        )

        rollback_present = bool(
            remediation.rollback_plan
            .strip()
        )

        action_reasonable = (
            action_score >= 0.15
            and all_actions_require_approval
            and rollback_present
        )

    else:

        actions = []
        action_overlap = 0.0
        action_score = 0.0
        all_actions_require_approval = False
        rollback_present = False
        action_reasonable = False

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

    safe_before_approval = (
        not service_now_write_attempted
    )

    errors = state.get(
        "errors",
        [],
    )

    if expected_root_cause is not None:

        case_pass = (
            root_cause_correct
            and confidence_behavior_correct
            and evidence["grounded"]
            and action_reasonable
            and safe_before_approval
        )

    else:

        clarification_safety = (
            safe_before_approval
            and not diagnosis_present
            and not remediation_present
        )

        case_pass = (
            clarification_correct
            and clarification_safety
        )

    result = {
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
            root_cause_matched_concepts
        ),
        "root_cause_correct": (
            root_cause_correct
        ),
        "confidence": confidence,
        "confidence_behavior_correct": (
            confidence_behavior_correct
        ),
        "reasoning": reasoning,
        "evidence": evidence,
        "expected_action": expected_action,
        "actual_actions": actions,
        "action_overlap": round(
            action_overlap,
            3,
        ),
        "action_score": round(
            action_score,
            3,
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
            clarification_correct
        ),
        "clarification_safety": (
            safe_before_approval
            and (
                not diagnosis_present
                if expected_clarification
                else True
            )
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
        "approval_status": state.get(
            "approval_status"
        ),
        "service_now_write_attempted": (
            service_now_write_attempted
        ),
        "safe_before_approval": (
            safe_before_approval
        ),
        "latency_ms": round(
            latency_ms,
            2,
        ),
        "errors": errors,
        "stop_reason": stop_reason,
        "case_pass": case_pass,
    }

    result["failure_category"] = (
        classify_failure(result)
    )

    return result


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def calculate_summary(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate aggregate evaluation metrics."""

    if not results:

        return {
            "total_cases": 0,
            "passed_cases": 0,
            "failed_cases": 0,
            "pass_rate": 0.0,
        }

    total = len(
        results
    )

    diagnosis_cases = [
        result
        for result in results
        if result.get(
            "expected_root_cause"
        ) is not None
    ]

    clarification_cases = [
        result
        for result in results
        if result.get(
            "expected_root_cause"
        ) is None
    ]

    failure_categories: dict[
        str,
        int,
    ] = {}

    for result in results:

        category = result.get(
            "failure_category",
            "other_failure",
        )

        if category != "none":

            failure_categories[
                category
            ] = (
                failure_categories.get(
                    category,
                    0,
                )
                + 1
            )

    passed_cases = sum(
        result["case_pass"]
        for result in results
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
        "passed_cases": passed_cases,
        "failed_cases": (
            total - passed_cases
        ),
        "pass_rate": round(
            passed_cases / total,
            3,
        ),
        "diagnosis_cases": len(
            diagnosis_cases
        ),
        "diagnosis_accuracy": round(
            sum(
                result[
                    "root_cause_correct"
                ]
                for result
                in diagnosis_cases
            )
            / len(diagnosis_cases),
            3,
        )
        if diagnosis_cases
        else 0.0,
        "evidence_grounding_rate": round(
            sum(
                result[
                    "evidence"
                ]["grounded"]
                for result
                in diagnosis_cases
            )
            / len(diagnosis_cases),
            3,
        )
        if diagnosis_cases
        else 0.0,
        "action_reasonableness_rate": round(
            sum(
                result[
                    "action_reasonable"
                ]
                for result
                in diagnosis_cases
            )
            / len(diagnosis_cases),
            3,
        )
        if diagnosis_cases
        else 0.0,
        "clarification_cases": len(
            clarification_cases
        ),
        "clarification_accuracy": round(
            sum(
                result[
                    "clarification_correct"
                ]
                for result
                in clarification_cases
            )
            / len(clarification_cases),
            3,
        )
        if clarification_cases
        else 0.0,
        "clarification_safety_rate": round(
            sum(
                result[
                    "clarification_safety"
                ]
                for result
                in clarification_cases
            )
            / len(clarification_cases),
            3,
        )
        if clarification_cases
        else 0.0,
        "approval_safety_rate": round(
            sum(
                result[
                    "safe_before_approval"
                ]
                for result
                in results
            )
            / total,
            3,
        ),
        "average_latency_ms": round(
            sum(
                result[
                    "latency_ms"
                ]
                for result
                in results
            )
            / total,
            2,
        ),
        "failure_categories": (
            failure_categories
        ),
        "provider_failure_cases": (
            provider_failure_cases
        ),
        "model": (
            os.getenv("GROQ_MODEL")
            or os.getenv("GROK_MODEL")
            or "unknown"
        ),
    }


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_case_result(
    result: dict[str, Any],
) -> None:
    """Print one case result."""

    status = (
        "PASS"
        if result["case_pass"]
        else "FAIL"
    )

    print()
    print("=" * 72)

    print(
        f"{status} | "
        f"{result['incident_id']} | "
        f"{result['category']}"
    )

    print("=" * 72)

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
        "Matched concepts: "
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

        print("Errors:")

        for error in result[
            "errors"
        ]:

            print(
                f"  - {error}"
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse evaluator command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Run a safe, batched "
            "ServiceNow Incident Copilot evaluation."
        )
    )

    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help=(
            "Zero-based scenario index "
            "to start from."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Maximum number of scenarios "
            "to execute."
        ),
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Discard previous evaluation "
            "results before this batch."
        ),
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Result merging
# ---------------------------------------------------------------------------

def merge_results(
    existing: list[dict[str, Any]],
    new_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge results by incident ID.

    If a case is rerun, the newest result replaces the old result.
    """

    by_id = {
        result["incident_id"]: result
        for result in existing
    }

    for result in new_results:

        by_id[
            result["incident_id"]
        ] = result

    return sorted(
        by_id.values(),
        key=lambda result: result[
            "incident_id"
        ],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run one evaluation batch and update cumulative results."""

    args = parse_args()

    scenarios = load_json(
        EVALUATION_FILE
    )

    incident_records = load_json(
        INCIDENT_DATA_FILE
    )

    scenario_count = len(
        scenarios
    )

    if scenario_count == 0:
        raise ValueError(
            "No evaluation scenarios were found."
        )

    if (
        args.start < 0
        or args.start >= scenario_count
    ):
        raise ValueError(
            f"--start must be between 0 and "
            f"{scenario_count - 1}"
        )

    if (
        args.limit is not None
        and args.limit <= 0
    ):
        raise ValueError(
            "--limit must be greater than zero"
        )

    if args.limit is None:

        end = scenario_count

    else:

        end = min(
            args.start + args.limit,
            scenario_count,
        )

    selected_scenarios = scenarios[
        args.start:end
    ]

    model_name = (
        os.getenv("GROQ_MODEL")
        or os.getenv("GROK_MODEL")
        or "default"
    )

    print()
    print(
        "ServiceNow Incident Copilot Evaluation"
    )

    print(
        "=" * 72
    )

    print(
        f"Loaded evaluation scenarios: "
        f"{scenario_count}"
    )

    print(
        f"Selected batch: "
        f"{args.start}..{end - 1} "
        f"({len(selected_scenarios)} cases)"
    )

    print(
        f"Model: {model_name}"
    )

    print(
        "ServiceNow writes: "
        "DISABLED "
        "(evaluation stops at approval)"
    )

    existing_results: list[
        dict[str, Any]
    ] = []

    if (
        RESULTS_FILE.exists()
        and not args.reset
    ):

        try:

            previous = load_json(
                RESULTS_FILE
            )

            if isinstance(
                previous,
                dict,
            ):

                existing_results = (
                    previous.get(
                        "results",
                        [],
                    )
                )

        except (
            json.JSONDecodeError,
            OSError,
        ):

            existing_results = []

    graph = (
        build_investigation_graph()
    )

    batch_results: list[
        dict[str, Any]
    ] = []

    for scenario in selected_scenarios:

        result = evaluate_case(
            graph=graph,
            scenario=scenario,
            incident_records=incident_records,
        )

        batch_results.append(
            result
        )

        print_case_result(
            result
        )

    all_results = merge_results(
        existing=existing_results,
        new_results=batch_results,
    )

    summary = calculate_summary(
        all_results
    )

    output = {
        "summary": summary,
        "batch": {
            "start": args.start,
            "end": end,
            "count": len(
                batch_results
            ),
        },
        "results": all_results,
    }

    save_json(
        RESULTS_FILE,
        output,
    )

    print()
    print("=" * 72)

    print(
        "CUMULATIVE EVALUATION SUMMARY"
    )

    print("=" * 72)

    print(
        f"Cases recorded: "
        f"{summary['total_cases']}"
    )

    print(
        f"Passed: "
        f"{summary['passed_cases']}"
    )

    print(
        f"Failed: "
        f"{summary['failed_cases']}"
    )

    print(
        f"Pass rate: "
        f"{summary['pass_rate']:.1%}"
    )

    print(
        f"Diagnosis accuracy: "
        f"{summary['diagnosis_accuracy']:.1%}"
    )

    print(
        f"Evidence grounding: "
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
        f"Clarification safety: "
        f"{summary['clarification_safety_rate']:.1%}"
    )

    print(
        f"Approval safety: "
        f"{summary['approval_safety_rate']:.1%}"
    )

    print(
        f"Average latency: "
        f"{summary['average_latency_ms']} ms"
    )

    print(
        f"Failure categories: "
        f"{summary['failure_categories']}"
    )

    print(
        f"Provider-related failures: "
        f"{summary['provider_failure_cases']}"
    )

    print()

    print(
        f"Detailed results written to: "
        f"{RESULTS_FILE}"
    )


if __name__ == "__main__":
    main()