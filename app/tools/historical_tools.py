import json
from pathlib import Path

from app.models.investigation import (
    HistoricalIncident,
)


DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "historical_incidents.json"


def search_historical_incidents(
    service: str,
    query: str,
    severity: str,
) -> list[HistoricalIncident]:
    """
    Search simulated historical incidents for relevant operational context.

    Matching is deterministic so the investigation context is reproducible
    during evaluation.
    """

    if not service:
        raise ValueError("service is required")

    if not query:
        raise ValueError("query is required")

    if not severity:
        raise ValueError("severity is required")

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
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
        for token in query.replace(",", " ").split()
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
                " ".join(record.get("symptoms", [])),
            ]
        ).lower()

        if not query_tokens:
            matches.append(HistoricalIncident(**record))
            continue

        if any(token in searchable_text for token in query_tokens):
            matches.append(HistoricalIncident(**record))

    return matches