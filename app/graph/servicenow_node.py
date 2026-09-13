"""
LangGraph node responsible for ServiceNow writes.

This node is the workflow-level ServiceNow boundary.

Safety rules:
- Never write unless approval_status == "approved".
- Create when no existing ServiceNow incident ID is present.
- Update when an existing ServiceNow incident ID is present.
- ServiceNow tools independently enforce approval as a second safety layer.
- Never execute remediation actions.
"""

import logging

from app.tools.servicenow_tools import (
    create_servicenow_incident,
    update_servicenow_incident,
)

logger = logging.getLogger(__name__)


def _severity_to_servicenow_fields(
    severity: str,
) -> tuple[str, str]:
    """
    Convert Copilot severity to ServiceNow impact/urgency.
    """

    mapping = {
        "P1": ("1", "1"),
        "P2": ("2", "2"),
        "P3": ("3", "3"),
    }

    normalized = severity.strip().upper()

    if normalized not in mapping:
        raise ValueError(
            f"Unsupported severity: {severity}"
        )

    return mapping[normalized]


def write_to_servicenow(state: dict) -> dict:
    """
    Create or update a ServiceNow incident after human approval.
    """

    approval_status = state.get("approval_status")

    # ---------------------------------------------------------
    # HARD APPROVAL BOUNDARY
    # ---------------------------------------------------------

    if approval_status != "approved":
        message = (
            "ServiceNow write blocked because human approval "
            f"was not approved. Current approval status: "
            f"{approval_status!r}"
        )

        logger.warning(message)

        return {
            "servicenow_status": "blocked",
            "servicenow_operation": "none",
            "servicenow_error_code": "APPROVAL_REQUIRED",
            "servicenow_error_message": message,
            "final_outcome": (
                "ServiceNow write blocked: "
                "human approval required."
            ),
        }

    incident = state.get("incident")
    remediation_plan = state.get("remediation_plan")

    if incident is None:
        message = (
            "Cannot write to ServiceNow because "
            "incident state is missing."
        )

        logger.error(message)

        return {
            "servicenow_status": "failed",
            "servicenow_operation": "none",
            "servicenow_error_code": "MISSING_INCIDENT",
            "servicenow_error_message": message,
            "errors": list(state.get("errors", [])) + [message],
            "final_outcome": (
                "ServiceNow write failed: "
                "incident state is missing."
            ),
        }

    if remediation_plan is None:
        message = (
            "Cannot write to ServiceNow because "
            "remediation plan is missing."
        )

        logger.error(message)

        return {
            "servicenow_status": "failed",
            "servicenow_operation": "none",
            "servicenow_error_code": "MISSING_REMEDIATION_PLAN",
            "servicenow_error_message": message,
            "errors": list(state.get("errors", [])) + [message],
            "final_outcome": (
                "ServiceNow write failed: "
                "remediation plan is missing."
            ),
        }

    # ---------------------------------------------------------
    # Severity mapping
    # ---------------------------------------------------------

    try:
        impact, urgency = _severity_to_servicenow_fields(
            incident.severity
        )

    except ValueError as exc:
        message = str(exc)

        logger.error(message)

        return {
            "servicenow_status": "failed",
            "servicenow_operation": "none",
            "servicenow_error_code": "INVALID_SEVERITY",
            "servicenow_error_message": message,
            "errors": list(state.get("errors", [])) + [message],
            "final_outcome": (
                "ServiceNow write failed: invalid severity."
            ),
        }

    servicenow_update = (
        remediation_plan.servicenow_update
    )

    existing_incident_id = (
        state.get("servicenow_incident_id")
    )

    # ---------------------------------------------------------
    # CREATE
    # ---------------------------------------------------------

    if not existing_incident_id:
        logger.info(
            "Creating ServiceNow incident after "
            "approved human decision."
        )

        idempotency_key = (
            f"ai-copilot-{incident.incident_id}"
        )

        result = create_servicenow_incident(
            title=servicenow_update.short_description,
            description=incident.description,
            severity=incident.severity,
            work_notes=servicenow_update.work_notes,
            idempotency_key=idempotency_key,
            approval_status=approval_status,
        )

        if not result.success:
            message = (
                result.error_message
                or "ServiceNow create failed."
            )

            logger.error(
                "ServiceNow create failed: "
                "code=%s message=%s",
                result.error_code,
                message,
            )

            return {
                "servicenow_status": "failed",
                "servicenow_operation": "create",
                "servicenow_error_code": result.error_code,
                "servicenow_error_message": message,
                "errors": list(
                    state.get("errors", [])
                ) + [message],
                "final_outcome": (
                    "ServiceNow incident creation failed."
                ),
            }

        incident_record = result.incident

        if incident_record is None:
            message = (
                "ServiceNow create reported success but "
                "returned no incident record."
            )

            return {
                "servicenow_status": "failed",
                "servicenow_operation": "create",
                "servicenow_error_code": (
                    "INVALID_CREATE_RESPONSE"
                ),
                "servicenow_error_message": message,
                "errors": list(
                    state.get("errors", [])
                ) + [message],
                "final_outcome": (
                    "ServiceNow incident creation failed: "
                    "invalid response."
                ),
            }

        logger.info(
            "ServiceNow incident created: "
            "number=%s sys_id=%s impact=%s urgency=%s",
            incident_record.number,
            incident_record.sys_id,
            incident_record.impact,
            incident_record.urgency,
        )

        return {
            "servicenow_incident_id": (
                incident_record.sys_id
            ),
            "servicenow_number": (
                incident_record.number
            ),
            "servicenow_status": "created",
            "servicenow_operation": "create",
            "servicenow_error_code": None,
            "servicenow_error_message": None,
            "final_outcome": (
                f"ServiceNow incident "
                f"{incident_record.number} "
                f"created successfully."
            ),
        }

    # ---------------------------------------------------------
    # UPDATE
    # ---------------------------------------------------------

    logger.info(
        "Updating existing ServiceNow incident: %s",
        existing_incident_id,
    )

    result = update_servicenow_incident(
        incident_id=existing_incident_id,
        state="2",
        work_notes=servicenow_update.work_notes,
        approval_status=approval_status,
        impact=impact,
        urgency=urgency,
    )

    if not result.success:
        message = (
            result.error_message
            or "ServiceNow update failed."
        )

        logger.error(
            "ServiceNow update failed: "
            "code=%s message=%s",
            result.error_code,
            message,
        )

        return {
            "servicenow_status": "failed",
            "servicenow_operation": "update",
            "servicenow_error_code": result.error_code,
            "servicenow_error_message": message,
            "errors": list(
                state.get("errors", [])
            ) + [message],
            "final_outcome": (
                "ServiceNow incident update failed."
            ),
        }

    incident_record = result.incident

    number = (
        incident_record.number
        if incident_record is not None
        else existing_incident_id
    )

    logger.info(
        "ServiceNow incident updated successfully: "
        "%s",
        number,
    )

    return {
        "servicenow_incident_id": (
            existing_incident_id
        ),
        "servicenow_number": number,
        "servicenow_status": "updated",
        "servicenow_operation": "update",
        "servicenow_error_code": None,
        "servicenow_error_message": None,
        "final_outcome": (
            f"ServiceNow incident {number} "
            f"updated successfully."
        ),
    }