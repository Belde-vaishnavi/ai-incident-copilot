import json
from pathlib import Path

from app.models.investigation import HistoricalIncident
from app.observability.tracer import trace_tool


DATA_FILE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "historical_incidents.json"
)


@trace_tool(
    tool_name="search_historical_incidents",
    operation="search_historical_incidents",
)
def search_historical_incidents(
    service: str,
    query: str,
    severity: str,
) -> list[HistoricalIncident]:
    """
    Search simulated historical incidents for relevant
    operational context.

    Matching is deterministic so the investigation context
    remains reproducible during evaluation.
    """

    if not service or not service.strip():
        raise ValueError("service is required")

    if not query or not query.strip():
        raise ValueError("query is required")

    if not severity or not severity.strip():
        raise ValueError("severity is required")

    try:
        with DATA_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            records = json.load(file)

    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Historical incident data file not found: {DATA_FILE}"
        ) from exc

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Historical incident data contains invalid JSON."
        ) from exc

    query_tokens = {
        token.lower()
        for token in query.replace(
            ",",
            " ",
        ).split()
        if len(token) > 2
    }

    matches: list[HistoricalIncident] = []

    for record in records:
        if record.get("service") != service:
            continue

        if record.get("severity") != severity:
            continue

        searchable_text = " ".join(
            [
                record.get("title", ""),
                record.get("root_cause", ""),
                record.get("resolution", ""),
                " ".join(
                    record.get(
                        "symptoms",
                        [],
                    )
                ),
            ]
        ).lower()

        if not query_tokens:
            matches.append(
                HistoricalIncident(**record)
            )
            continue

        if any(
            token in searchable_text
            for token in query_tokens
        ):
            matches.append(
                HistoricalIncident(**record)
            )

    return matches