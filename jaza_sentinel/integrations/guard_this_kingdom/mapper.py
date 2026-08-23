"""Map GTK rows into deliberately small, Jaza-owned activity facts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from ...reporting.models import ActivityFact


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value not in (None, "") else None


def _text(value: Any, limit: int = 700) -> str:
    return " ".join(str(value or "").split())[:limit]


def goal_row_to_fact(row: dict[str, Any], status: str) -> ActivityFact:
    measure = _text(row.get("goalMeasure"), 25).lower()
    source_table = {
        "live": "live_goals",
        "completed": "completed_goals",
        "failed": "failed_goals",
    }[status]
    return ActivityFact(
        source="guard_this_kingdom",
        source_kind="goal",
        source_id=f"{source_table}:{int(row.get('goalUniqueID') or 0)}",
        occurred_at=_iso(row.get("goalStart")),
        due_at=_iso(row.get("goalFinish")),
        title=_text(row.get("goalName"), 256),
        note=_text(row.get("goalNotes")),
        category=_text(row.get("goalType"), 25),
        minutes=max(0, int(row.get("goalNumber") or 0)),
        status=status,
        behavior="sliding" if measure == "slider" else "standard",
        metadata={
            "goal_measure": measure,
            "actual_completion_at": _iso(row.get("goalActualComplete")),
            "has_team_association": bool(_text(row.get("team_sharing"), 120)),
            "recurrence_storage": "materialized_occurrence",
        },
    )


def plant_row_to_fact(row: dict[str, Any]) -> ActivityFact:
    active = bool(row.get("is_active"))
    return ActivityFact(
        source="guard_this_kingdom",
        source_kind="garden_plant",
        source_id=f"gardening_pro:{int(row.get('id') or 0)}",
        occurred_at=_iso(row.get("plant_date")),
        due_at=_iso(row.get("next_harvest") or row.get("target_harvest_date")),
        title=_text(row.get("plant_name"), 120),
        note=_text(row.get("maintenance_notes")),
        category="Garden",
        minutes=None,
        status="active" if active else "inactive",
        behavior="garden_record",
        metadata={
            "plant_type": _text(row.get("plant_type"), 20),
            "target_harvest_date": _iso(row.get("target_harvest_date")),
            "next_harvest": _iso(row.get("next_harvest")),
        },
    )


def garden_history_row_to_fact(row: dict[str, Any]) -> ActivityFact:
    ph_value = row.get("ph_level")
    if isinstance(ph_value, Decimal):
        ph_value = float(ph_value)
    return ActivityFact(
        source="guard_this_kingdom",
        source_kind="garden_history",
        source_id=f"gardening_pro_history:{int(row.get('id') or 0)}",
        occurred_at=_iso(row.get("event_at")),
        due_at=None,
        title=_text(row.get("history_type"), 32) or "Garden observation",
        note=_text(row.get("note_text") or row.get("soil_tidbits")),
        category="Garden",
        minutes=None,
        status="observed",
        behavior="garden_event",
        metadata={
            "plant_id": _text(row.get("plant_id"), 64),
            "history_type": _text(row.get("history_type"), 32),
            "ph_level": ph_value,
        },
    )

