"""Explicit request validation for the local Sentinel API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


STATUSES = ("backlog", "ready", "active", "waiting", "completed")
PRIORITIES = ("low", "normal", "high", "critical")
CHECK_IN_STATUSES = ("none", "requested", "awaiting_direction")
ASSIGNEES = ("king_trizzen", "jaza", "star_reborn")
EXECUTION_STATUSES = ("not_delegated", "prepared_for_star")
TARGET_TYPES = ("program", "project")


class RequestValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("Request validation failed")
        self.errors = errors


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def validate_work_item(
    payload: Any,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = _require_object(payload)
    allowed = {
        "title",
        "description",
        "target_type",
        "target_id",
        "domain_program",
        "priority",
        "status",
        "next_action",
        "notes",
        "human_check_in_required",
        "human_check_in_status",
        "execution_assignee",
        "execution_status",
        "scheduled_for",
        "review_after",
    }
    errors = _unknown_fields(data, allowed)
    merged = dict(existing or {})
    merged.update(data)

    title = _string(merged.get("title"), "title", errors, required=True, max_length=160)
    target_type = _choice(merged.get("target_type"), "target_type", TARGET_TYPES, errors)
    target_id = _string(merged.get("target_id"), "target_id", errors, required=True, max_length=100)
    priority = _choice(merged.get("priority", "normal"), "priority", PRIORITIES, errors)
    status = _choice(merged.get("status", "backlog"), "status", STATUSES, errors)
    assignee = _choice(
        merged.get("execution_assignee", "king_trizzen"),
        "execution_assignee",
        ASSIGNEES,
        errors,
    )

    check_in_value = merged.get("human_check_in_status")
    if check_in_value is None and merged.get("human_check_in_required") is True:
        check_in_value = "requested"
    check_in_status = _choice(
        check_in_value or "none",
        "human_check_in_status",
        CHECK_IN_STATUSES,
        errors,
    )

    scheduled_for = _timestamp(merged.get("scheduled_for"), "scheduled_for", errors)
    review_after = _timestamp(merged.get("review_after"), "review_after", errors)
    if errors:
        raise RequestValidationError(errors)

    now = utc_now()
    return {
        "id": (existing or {}).get("id", new_id("work")),
        "title": title,
        "description": _optional_string(merged.get("description"), 2000),
        "target_type": target_type,
        "target_id": target_id,
        "domain_program": target_id if target_type == "program" else None,
        "priority": priority,
        "status": status,
        "next_action": _optional_string(merged.get("next_action"), 1000),
        "notes": _optional_string(merged.get("notes"), 4000),
        "created_at": (existing or {}).get("created_at", now),
        "updated_at": now,
        "human_check_in_required": check_in_status != "none",
        "human_check_in_status": check_in_status,
        "execution_assignee": assignee,
        "execution_status": "prepared_for_star" if assignee == "star_reborn" else "not_delegated",
        "scheduled_for": scheduled_for,
        "review_after": review_after,
        "jira_key": (existing or {}).get("jira_key"),
    }


def validate_project_patch(payload: Any, existing: dict[str, Any]) -> dict[str, Any]:
    data = _require_object(payload)
    allowed = {
        "description",
        "status",
        "priority",
        "current_focus",
        "next_action",
        "notes",
        "human_check_in_required",
    }
    errors = _unknown_fields(data, allowed)
    merged = dict(existing)
    merged.update(data)
    status = _choice(merged.get("status"), "status", STATUSES, errors)
    priority = _choice(merged.get("priority"), "priority", PRIORITIES, errors)
    human_required = merged.get("human_check_in_required", False)
    if not isinstance(human_required, bool):
        errors["human_check_in_required"] = "must be true or false"
    if errors:
        raise RequestValidationError(errors)
    merged.update(
        {
            "description": _optional_string(merged.get("description"), 2000),
            "status": status,
            "priority": priority,
            "current_focus": _optional_string(merged.get("current_focus"), 1000),
            "next_action": _optional_string(merged.get("next_action"), 1000),
            "notes": _optional_string(merged.get("notes"), 4000),
            "human_check_in_required": human_required,
            "updated_at": utc_now(),
        }
    )
    return merged


def validate_context_entry(payload: Any, *, kind: str) -> dict[str, Any]:
    data = _require_object(payload)
    allowed = {"target_type", "target_id", "body", "check_in_status"}
    errors = _unknown_fields(data, allowed)
    target_type = _choice(data.get("target_type"), "target_type", TARGET_TYPES, errors)
    target_id = _string(data.get("target_id"), "target_id", errors, required=True, max_length=100)
    body = _string(data.get("body"), "body", errors, required=True, max_length=4000)
    entry: dict[str, Any] = {
        "id": new_id("note" if kind == "note" else "checkin"),
        "target_type": target_type,
        "target_id": target_id,
        "body": body,
        "created_at": utc_now(),
    }
    if kind == "check_in":
        entry["status"] = _choice(
            data.get("check_in_status", "requested"),
            "check_in_status",
            CHECK_IN_STATUSES,
            errors,
        )
    if errors:
        raise RequestValidationError(errors)
    return entry


def validate_usage_entry(payload: Any) -> dict[str, Any]:
    data = _require_object(payload)
    allowed = {"provider_tool", "token_estimate", "cost_estimate", "notes"}
    errors = _unknown_fields(data, allowed)
    provider_tool = _string(
        data.get("provider_tool"), "provider_tool", errors, required=True, max_length=120
    )
    token_estimate = data.get("token_estimate")
    if token_estimate is not None and (not isinstance(token_estimate, int) or token_estimate < 0):
        errors["token_estimate"] = "must be a non-negative integer or null"
    cost_estimate = data.get("cost_estimate")
    if cost_estimate is not None and (
        isinstance(cost_estimate, bool)
        or not isinstance(cost_estimate, (int, float))
        or cost_estimate < 0
    ):
        errors["cost_estimate"] = "must be a non-negative number or null"
    if errors:
        raise RequestValidationError(errors)
    return {
        "id": new_id("usage"),
        "provider_tool": provider_tool,
        "token_estimate": token_estimate,
        "cost_estimate": float(cost_estimate) if cost_estimate is not None else None,
        "notes": _optional_string(data.get("notes"), 1000),
        "timestamp": utc_now(),
    }


def _require_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RequestValidationError({"body": "must be a JSON object"})
    return payload


def _unknown_fields(data: dict[str, Any], allowed: set[str]) -> dict[str, str]:
    unknown = sorted(set(data) - allowed)
    return {field: "is not accepted" for field in unknown}


def _choice(
    value: Any,
    field: str,
    choices: tuple[str, ...],
    errors: dict[str, str],
) -> str:
    if value not in choices:
        errors[field] = f"must be one of: {', '.join(choices)}"
        return choices[0]
    return value


def _string(
    value: Any,
    field: str,
    errors: dict[str, str],
    *,
    required: bool,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        errors[field] = "must be a string"
        return ""
    value = value.strip()
    if required and not value:
        errors[field] = "is required"
    elif len(value) > max_length:
        errors[field] = f"must be {max_length} characters or fewer"
    return value


def _optional_string(value: Any, max_length: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def _timestamp(value: Any, field: str, errors: dict[str, str]) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        errors[field] = "must be an ISO 8601 timestamp or null"
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors[field] = "must be an ISO 8601 timestamp or null"
        return None
    return value
