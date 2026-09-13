import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.investigation import (
    DependencyHealth,
    MetricFetchResult,
    MetricSnapshot,
)
from app.observability.tracer import trace_tool


DATA_FILE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "metrics.json"
)


@trace_tool(
    tool_name="fetch_metrics",
    operation="fetch_metrics",
)
def fetch_metrics(
    service: str,
    start_time: datetime,
    end_time: datetime,
) -> MetricFetchResult:
    """
    Fetch simulated metrics for a service within a specified time window.

    The tool is read-only and returns structured success/error information.
    """

    if not service or not service.strip():
        return MetricFetchResult(
            success=False,
            records=[],
            error_code="INVALID_SERVICE",
            error_message="Service is required.",
        )

    if start_time >= end_time:
        return MetricFetchResult(
            success=False,
            records=[],
            error_code="INVALID_TIME_RANGE",
            error_message="start_time must be earlier than end_time.",
        )

    try:
        with DATA_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            raw_metrics = json.load(file)

        if start_time.tzinfo is None:
            start_time = start_time.replace(
                tzinfo=timezone.utc
            )

        if end_time.tzinfo is None:
            end_time = end_time.replace(
                tzinfo=timezone.utc
            )

        records = []

        for raw_metric in raw_metrics:
            if raw_metric.get("service") != service:
                continue

            timestamp = datetime.fromisoformat(
                raw_metric["timestamp"].replace(
                    "Z",
                    "+00:00",
                )
            )

            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(
                    tzinfo=timezone.utc
                )

            if start_time <= timestamp <= end_time:
                dependency_health = [
                    DependencyHealth(
                        name=name,
                        status=status,
                    )
                    for name, status in raw_metric.get(
                        "dependency_health",
                        {},
                    ).items()
                ]

                metric_data = {
                    **raw_metric,
                    "dependency_health": dependency_health,
                }

                records.append(
                    MetricSnapshot.model_validate(
                        metric_data
                    )
                )

        return MetricFetchResult(
            success=True,
            records=records,
            error_code=None,
            error_message=None,
        )

    except FileNotFoundError:
        return MetricFetchResult(
            success=False,
            records=[],
            error_code="METRIC_DATA_NOT_FOUND",
            error_message=(
                f"Metric data file not found: {DATA_FILE}"
            ),
        )

    except json.JSONDecodeError:
        return MetricFetchResult(
            success=False,
            records=[],
            error_code="INVALID_METRIC_DATA",
            error_message=(
                "The simulated metrics dataset contains invalid JSON."
            ),
        )

    except Exception as exc:
        return MetricFetchResult(
            success=False,
            records=[],
            error_code="METRIC_FETCH_ERROR",
            error_message=str(exc),
        )