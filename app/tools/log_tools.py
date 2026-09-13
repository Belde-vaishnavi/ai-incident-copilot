import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.investigation import LogEntry, LogFetchResult
from app.observability.tracer import trace_tool


DATA_FILE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "logs.json"
)


@trace_tool(
    tool_name="fetch_logs",
    operation="fetch_logs",
)
def fetch_logs(
    service: str,
    start_time: datetime,
    end_time: datetime,
) -> LogFetchResult:
    """
    Fetch simulated logs for a service within a specified time window.

    The tool is read-only and returns structured success/error information.
    """

    if not service or not service.strip():
        return LogFetchResult(
            success=False,
            records=[],
            error_code="INVALID_SERVICE",
            error_message="Service is required.",
        )

    if start_time >= end_time:
        return LogFetchResult(
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
            raw_logs = json.load(file)

        if start_time.tzinfo is None:
            start_time = start_time.replace(
                tzinfo=timezone.utc
            )

        if end_time.tzinfo is None:
            end_time = end_time.replace(
                tzinfo=timezone.utc
            )

        records = []

        for raw_log in raw_logs:
            if raw_log.get("service") != service:
                continue

            timestamp = datetime.fromisoformat(
                raw_log["timestamp"].replace(
                    "Z",
                    "+00:00",
                )
            )

            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(
                    tzinfo=timezone.utc
                )

            if start_time <= timestamp <= end_time:
                records.append(
                    LogEntry.model_validate(raw_log)
                )

        return LogFetchResult(
            success=True,
            records=records,
            error_code=None,
            error_message=None,
        )

    except FileNotFoundError:
        return LogFetchResult(
            success=False,
            records=[],
            error_code="LOG_DATA_NOT_FOUND",
            error_message=(
                f"Log data file not found: {DATA_FILE}"
            ),
        )

    except json.JSONDecodeError:
        return LogFetchResult(
            success=False,
            records=[],
            error_code="INVALID_LOG_DATA",
            error_message=(
                "The simulated logs dataset contains invalid JSON."
            ),
        )

    except Exception as exc:
        return LogFetchResult(
            success=False,
            records=[],
            error_code="LOG_FETCH_ERROR",
            error_message=str(exc),
        )