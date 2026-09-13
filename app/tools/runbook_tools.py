import json
from pathlib import Path

from app.models.investigation import (
    RunbookMatch,
    RunbookSearchResult,
)
from app.observability.tracer import trace_tool


DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "runbooks.json"


@trace_tool(
    tool_name="search_runbooks",
    operation="search_runbooks",
)
def search_runbooks(
    query: str,
    service: str,
    severity: str,
) -> RunbookSearchResult:
    """
    Search simulated runbooks using the incident query,
    service, and severity.
    """

    if not query or not query.strip():
        return RunbookSearchResult(
            success=False,
            matches=[],
            error_code="INVALID_QUERY",
            error_message="Query is required.",
        )

    if not service or not service.strip():
        return RunbookSearchResult(
            success=False,
            matches=[],
            error_code="INVALID_SERVICE",
            error_message="Service is required.",
        )

    if not severity or not severity.strip():
        return RunbookSearchResult(
            success=False,
            matches=[],
            error_code="INVALID_SEVERITY",
            error_message="Severity is required.",
            )

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            runbooks = json.load(file)

        query_terms = set(query.lower().split())

        normalized_service = service.strip().lower()
        normalized_severity = severity.strip().lower()

        matches = []

        for runbook in runbooks:

            runbook_service = str(
                runbook.get("service", "")
            ).lower()

            runbook_severity = str(
                runbook.get("severity", "")
            ).lower()

            if runbook_service != normalized_service:
                continue

            if runbook_severity != normalized_severity:
                continue

            searchable_text = " ".join(
                [
                    str(runbook.get("title", "")),
                    str(runbook.get("snippet", "")),
                    " ".join(runbook.get("keywords", [])),
                ]
            ).lower()

            matched_terms = [
                term
                for term in query_terms
                if term in searchable_text
            ]

            if not matched_terms:
                continue

            relevance_reasoning = (
                f"Matched service '{service}', "
                f"severity '{severity}', "
                f"and query terms: "
                f"{', '.join(sorted(matched_terms))}."
            )

            matches.append(
                RunbookMatch(
                    source_id=runbook["source_id"],
                    service=runbook["service"],
                    severity=runbook["severity"],
                    title=runbook["title"],
                    snippet=runbook["snippet"],
                    relevance_reasoning=relevance_reasoning,
                )
            )

        return RunbookSearchResult(
            success=True,
            matches=matches,
            error_code=None,
            error_message=None,
        )

    except FileNotFoundError:
        return RunbookSearchResult(
            success=False,
            matches=[],
            error_code="RUNBOOK_DATA_NOT_FOUND",
            error_message=(
                f"Runbook data file not found: {DATA_FILE}"
            ),
        )

    except json.JSONDecodeError:
        return RunbookSearchResult(
            success=False,
            matches=[],
            error_code="INVALID_RUNBOOK_DATA",
            error_message=(
                "The simulated runbook dataset contains invalid JSON."
            ),
        )

    except Exception as exc:
        return RunbookSearchResult(
            success=False,
            matches=[],
            error_code="RUNBOOK_SEARCH_ERROR",
            error_message=str(exc),
        )