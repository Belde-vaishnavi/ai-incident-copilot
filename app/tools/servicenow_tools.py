"""
ServiceNow integration tools.

These tools communicate with the ServiceNow Personal Developer Instance
through the Incident Table REST API.

Safety principles:
- ServiceNow writes require explicit human approval.
- Inputs are validated before API calls.
- Create operations use an idempotency marker to prevent duplicates.
- Errors are returned as structured results.
- Sensitive configuration and credentials are never logged.
"""

import hashlib
import logging
import os
from typing import Any

import requests
from dotenv import load_dotenv

from app.models.servicenow import (
    ServiceNowCreateRequest,
    ServiceNowIncident,
    ServiceNowToolResult,
    ServiceNowUpdateRequest,
)

logger = logging.getLogger(__name__)

load_dotenv()

REQUEST_TIMEOUT_SECONDS = 30

# ------------------------------------------------------------------
# Application severity -> ServiceNow impact/urgency mapping
# ------------------------------------------------------------------

SEVERITY_MAPPING = {
    "P1": {
        "impact": "1",
        "urgency": "1",
    },
    "P2": {
        "impact": "2",
        "urgency": "2",
    },
    "P3": {
        "impact": "3",
        "urgency": "3",
    },
}


def _get_severity_mapping(severity: str) -> dict[str, str]:
    """
    Convert the application's P1/P2/P3 severity into the
    ServiceNow impact/urgency representation.

    The mapping is intentionally explicit and deterministic.
    """

    normalized = severity.strip().upper()

    mapping = SEVERITY_MAPPING.get(normalized)

    if mapping is None:
        raise ValueError(
            f"Unsupported severity '{severity}'. "
            "Expected one of: P1, P2, P3."
        )

    return mapping


def _get_configuration() -> tuple[str, str, str]:
    """
    Load and validate ServiceNow configuration.
    """

    instance = os.getenv("SERVICENOW_INSTANCE")
    username = os.getenv("SERVICENOW_USERNAME")
    password = os.getenv("SERVICENOW_PASSWORD")

    if not instance:
        raise ValueError(
            "SERVICENOW_INSTANCE environment variable is required."
        )

    if not username:
        raise ValueError(
            "SERVICENOW_USERNAME environment variable is required."
        )

    if not password:
        raise ValueError(
            "SERVICENOW_PASSWORD environment variable is required."
        )

    instance = instance.rstrip("/")

    if not instance.startswith("https://"):
        raise ValueError(
            "SERVICENOW_INSTANCE must use HTTPS."
        )

    return instance, username, password


def _incident_collection_url(instance: str) -> str:
    return (
        f"{instance}/api/now/table/incident"
    )


def _incident_record_url(
    instance: str,
    incident_id: str,
) -> str:
    return (
        f"{_incident_collection_url(instance)}/{incident_id}"
    )


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Return a logging-safe payload.

    Work notes may contain operational information, so they are
    summarized rather than logged verbatim.
    """

    redacted = dict(payload)

    if "work_notes" in redacted:
        redacted["work_notes"] = (
            "[REDACTED_WORK_NOTES]"
        )

    if "description" in redacted:
        redacted["description"] = (
            "[REDACTED_DESCRIPTION]"
        )

    return redacted


def _build_idempotency_key(
    idempotency_key: str,
) -> str:
    """
    Hash the supplied idempotency key before placing it into
    ServiceNow work notes.
    """

    return hashlib.sha256(
        idempotency_key.encode("utf-8")
    ).hexdigest()


def _parse_incident(
    data: dict[str, Any],
) -> ServiceNowIncident:
    """
    Convert a ServiceNow API response into our typed model.
    """

    return ServiceNowIncident(
        sys_id=str(data["sys_id"]),
        number=str(data["number"]),
        short_description=str(
            data.get("short_description", "")
        ),
        state=(
            str(data["state"])
            if data.get("state") is not None
            else None
        ),
        impact=(
            str(data["impact"])
            if data.get("impact") is not None
            else None
        ),
        urgency=(
            str(data["urgency"])
            if data.get("urgency") is not None
            else None
        ),
        priority=(
            str(data["priority"])
            if data.get("priority") is not None
            else None
        ),
    )


def get_servicenow_incident(
    incident_id: str,
) -> ServiceNowToolResult:
    """
    Read an existing ServiceNow incident.

    This operation is read-only and does not require approval.
    """

    if not incident_id or not incident_id.strip():
        return ServiceNowToolResult(
            success=False,
            operation="get",
            error_code="INVALID_INCIDENT_ID",
            error_message="incident_id is required.",
        )

    try:
        instance, username, password = (
            _get_configuration()
        )

        url = _incident_record_url(
            instance,
            incident_id.strip(),
        )

        response = requests.get(
            url,
            auth=(username, password),
            headers={
                "Accept": "application/json",
            },
            params={
                "sysparm_fields": (
                    "sys_id,number,short_description,"
                    "state,impact,urgency,priority"
                )
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        logger.info(
            "ServiceNow GET incident completed: "
            "status=%s",
            response.status_code,
        )

        if response.status_code == 404:
            return ServiceNowToolResult(
                success=False,
                operation="get",
                error_code="INCIDENT_NOT_FOUND",
                error_message=(
                    f"ServiceNow incident '{incident_id}' "
                    "was not found."
                ),
            )

        if response.status_code != 200:
            return ServiceNowToolResult(
                success=False,
                operation="get",
                error_code="SERVICENOW_GET_FAILED",
                error_message=(
                    f"ServiceNow returned HTTP "
                    f"{response.status_code}."
                ),
            )

        body = response.json()

        record = body.get("result")

        if not record:
            return ServiceNowToolResult(
                success=False,
                operation="get",
                error_code="INVALID_SERVICENOW_RESPONSE",
                error_message=(
                    "ServiceNow returned no incident record."
                ),
            )

        return ServiceNowToolResult(
            success=True,
            operation="get",
            incident=_parse_incident(record),
        )

    except requests.RequestException as exc:
        logger.exception(
            "ServiceNow GET request failed."
        )

        return ServiceNowToolResult(
            success=False,
            operation="get",
            error_code="SERVICENOW_CONNECTION_ERROR",
            error_message=str(exc),
        )

    except Exception as exc:
        logger.exception(
            "Unexpected ServiceNow GET failure."
        )

        return ServiceNowToolResult(
            success=False,
            operation="get",
            error_code="SERVICENOW_GET_ERROR",
            error_message=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


def _find_existing_by_idempotency_key(
    instance: str,
    username: str,
    password: str,
    idempotency_hash: str,
) -> ServiceNowIncident | None:
    """
    Search ServiceNow work notes for an existing idempotency marker.
    """

    marker = (
        f"AI-COPILOT-IDEMPOTENCY:"
        f"{idempotency_hash}"
    )

    response = requests.get(
        _incident_collection_url(instance),
        auth=(username, password),
        headers={
            "Accept": "application/json",
        },
        params={
            "sysparm_query": (
                f"work_notesLIKE{marker}"
            ),
            "sysparm_fields": (
                "sys_id,number,short_description,"
                "state,impact,urgency,priority"
            ),
            "sysparm_limit": "1",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code != 200:
        logger.warning(
            "Idempotency lookup returned HTTP %s.",
            response.status_code,
        )
        return None

    body = response.json()

    records = body.get("result", [])

    if not records:
        return None

    return _parse_incident(records[0])


def create_servicenow_incident(
    title: str,
    description: str,
    severity: str,
    work_notes: str,
    idempotency_key: str,
    approval_status: str,
) -> ServiceNowToolResult:
    """
    Create a ServiceNow incident.

    This operation is blocked unless the human approval status is
    exactly 'approved'.
    """

    # --------------------------------------------------------------
    # HARD APPROVAL BOUNDARY
    # --------------------------------------------------------------

    if approval_status != "approved":
        logger.warning(
            "ServiceNow CREATE blocked: approval_status=%r",
            approval_status,
        )

        return ServiceNowToolResult(
            success=False,
            operation="create",
            error_code="APPROVAL_REQUIRED",
            error_message=(
                "ServiceNow incident creation requires "
                "explicit human approval."
            ),
        )

    # --------------------------------------------------------------
    # Validate application input
    # --------------------------------------------------------------

    try:
        request = ServiceNowCreateRequest(
            title=title,
            description=description,
            severity=severity,
            work_notes=work_notes,
            idempotency_key=idempotency_key,
        )

        severity_mapping = _get_severity_mapping(
            request.severity
        )

    except ValueError as exc:
        return ServiceNowToolResult(
            success=False,
            operation="create",
            error_code="INVALID_INPUT",
            error_message=str(exc),
        )

    # --------------------------------------------------------------
    # Configuration
    # --------------------------------------------------------------

    try:
        instance, username, password = (
            _get_configuration()
        )

        idempotency_hash = _build_idempotency_key(
            request.idempotency_key
        )

        # ----------------------------------------------------------
        # Duplicate prevention
        # ----------------------------------------------------------

        existing = _find_existing_by_idempotency_key(
            instance=instance,
            username=username,
            password=password,
            idempotency_hash=idempotency_hash,
        )

        if existing is not None:
            logger.info(
                "ServiceNow CREATE prevented duplicate: "
                "number=%s",
                existing.number,
            )

            return ServiceNowToolResult(
                success=True,
                operation="create_duplicate_prevented",
                incident=existing,
            )

        # ----------------------------------------------------------
        # Build ServiceNow payload
        # ----------------------------------------------------------

        final_work_notes = (
            f"{request.work_notes}\n\n"
            f"AI-COPILOT-IDEMPOTENCY:{idempotency_hash}"
        )

        payload = {
            "short_description": request.title,
            "description": request.description,
            "impact": severity_mapping["impact"],
            "urgency": severity_mapping["urgency"],
            "work_notes": final_work_notes,
        }

        logger.info(
            "Creating ServiceNow incident with payload=%s",
            _redact_payload(payload),
        )

        # ----------------------------------------------------------
        # POST
        # ----------------------------------------------------------

        response = requests.post(
            _incident_collection_url(instance),
            auth=(username, password),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        logger.info(
            "ServiceNow CREATE completed: status=%s",
            response.status_code,
        )

        if response.status_code != 201:
            return ServiceNowToolResult(
                success=False,
                operation="create",
                error_code="SERVICENOW_CREATE_FAILED",
                error_message=(
                    f"ServiceNow returned HTTP "
                    f"{response.status_code}."
                ),
            )

        body = response.json()

        record = body.get("result")

        if not record:
            return ServiceNowToolResult(
                success=False,
                operation="create",
                error_code="INVALID_SERVICENOW_RESPONSE",
                error_message=(
                    "ServiceNow returned no created "
                    "incident record."
                ),
            )

        return ServiceNowToolResult(
            success=True,
            operation="create",
            incident=_parse_incident(record),
        )

    except requests.RequestException as exc:
        logger.exception(
            "ServiceNow CREATE request failed."
        )

        return ServiceNowToolResult(
            success=False,
            operation="create",
            error_code="SERVICENOW_CONNECTION_ERROR",
            error_message=str(exc),
        )

    except Exception as exc:
        logger.exception(
            "Unexpected ServiceNow CREATE failure."
        )

        return ServiceNowToolResult(
            success=False,
            operation="create",
            error_code="SERVICENOW_CREATE_ERROR",
            error_message=(
                f"{type(exc).__name__}: {exc}"
            ),
        )


def update_servicenow_incident(
    incident_id: str,
    state: str,
    work_notes: str,
    approval_status: str,
    impact: str | None = None,
    urgency: str | None = None,
) -> ServiceNowToolResult:
    """
    Update an existing ServiceNow incident.

    This operation is blocked unless the human approval status is
    exactly 'approved'.
    """

    # --------------------------------------------------------------
    # HARD APPROVAL BOUNDARY
    # --------------------------------------------------------------

    if approval_status != "approved":
        logger.warning(
            "ServiceNow UPDATE blocked: approval_status=%r",
            approval_status,
        )

        return ServiceNowToolResult(
            success=False,
            operation="update",
            error_code="APPROVAL_REQUIRED",
            error_message=(
                "ServiceNow incident update requires "
                "explicit human approval."
            ),
        )

    # --------------------------------------------------------------
    # Validate input
    # --------------------------------------------------------------

    try:
        request = ServiceNowUpdateRequest(
            incident_id=incident_id,
            state=state,
            work_notes=work_notes,
            impact=impact,
            urgency=urgency,
        )

    except ValueError as exc:
        return ServiceNowToolResult(
            success=False,
            operation="update",
            error_code="INVALID_INPUT",
            error_message=str(exc),
        )

    # --------------------------------------------------------------
    # Configuration
    # --------------------------------------------------------------

    try:
        instance, username, password = (
            _get_configuration()
        )

        payload = {
            "state": request.state,
            "work_notes": request.work_notes,
        }

        if request.impact is not None:
            payload["impact"] = request.impact

        if request.urgency is not None:
            payload["urgency"] = request.urgency

        logger.info(
            "Updating ServiceNow incident=%s payload=%s",
            request.incident_id,
            _redact_payload(payload),
        )

        response = requests.patch(
            _incident_record_url(
                instance,
                request.incident_id,
            ),
            auth=(username, password),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        logger.info(
            "ServiceNow UPDATE completed: status=%s",
            response.status_code,
        )

        if response.status_code == 404:
            return ServiceNowToolResult(
                success=False,
                operation="update",
                error_code="INCIDENT_NOT_FOUND",
                error_message=(
                    f"ServiceNow incident "
                    f"'{request.incident_id}' was not found."
                ),
            )

        if response.status_code != 200:
            return ServiceNowToolResult(
                success=False,
                operation="update",
                error_code="SERVICENOW_UPDATE_FAILED",
                error_message=(
                    f"ServiceNow returned HTTP "
                    f"{response.status_code}."
                ),
            )

        body = response.json()

        record = body.get("result")

        if not record:
            return ServiceNowToolResult(
                success=False,
                operation="update",
                error_code="INVALID_SERVICENOW_RESPONSE",
                error_message=(
                    "ServiceNow returned no updated "
                    "incident record."
                ),
            )

        return ServiceNowToolResult(
            success=True,
            operation="update",
            incident=_parse_incident(record),
        )

    except requests.RequestException as exc:
        logger.exception(
            "ServiceNow UPDATE request failed."
        )

        return ServiceNowToolResult(
            success=False,
            operation="update",
            error_code="SERVICENOW_CONNECTION_ERROR",
            error_message=str(exc),
        )

    except Exception as exc:
        logger.exception(
            "Unexpected ServiceNow UPDATE failure."
        )

        return ServiceNowToolResult(
            success=False,
            operation="update",
            error_code="SERVICENOW_UPDATE_ERROR",
            error_message=(
                f"{type(exc).__name__}: {exc}"
            ),
        )