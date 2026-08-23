"""Narrow SELECT-only queries for GTK reporting evidence."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .connection import GtkReadOnlyConnection


GTK_USER_ID = 1002

_GOAL_COLUMNS = """
    goalUniqueID, goalName, goalNumber, goalStart, goalFinish,
    goalNotes, goalMeasure, goalActualComplete, goalType, team_sharing
"""


class GuardThisKingdomRepository:
    """Read API whose target user cannot be selected by callers."""

    target_user_id = GTK_USER_ID

    def __init__(self, connection: GtkReadOnlyConnection | None = None) -> None:
        self.connection = connection or GtkReadOnlyConnection()

    def health(self) -> dict[str, Any]:
        row = self.connection.fetch_one("SELECT 1 AS healthy")
        return {"connected": bool(row and row.get("healthy") == 1)}

    def user_profile(self) -> dict[str, Any]:
        return self.connection.fetch_one(
            """
            SELECT TOP (1) id, timezone
            FROM dbo.[user]
            WHERE id = :gtk_user_id
            """,
            {"gtk_user_id": GTK_USER_ID},
        ) or {"id": GTK_USER_ID, "timezone": "UTC"}

    def week_start_day(self) -> str:
        row = self.connection.fetch_one(
            """
            SELECT TOP (1) goal_settings
            FROM dbo.scorecard_settings
            WHERE user_id = :gtk_user_id
            """,
            {"gtk_user_id": GTK_USER_ID},
        )
        try:
            settings = json.loads(str((row or {}).get("goal_settings") or "{}"))
        except (TypeError, ValueError):
            settings = {}
        value = str(settings.get("dayOfWeek", "monday") or "monday").lower()
        return value if value in {
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
        } else "monday"

    def earliest_goal_start(self) -> datetime | None:
        row = self.connection.fetch_one(
            """
            SELECT MIN(goalStart) AS earliest_start
            FROM (
                SELECT goalStart FROM dbo.completed_goals WHERE UserID = :gtk_user_id
                UNION ALL
                SELECT goalStart FROM dbo.failed_goals WHERE UserID = :gtk_user_id
            ) AS combined_goals
            """,
            {"gtk_user_id": GTK_USER_ID},
        )
        return (row or {}).get("earliest_start")

    def goal_rows(self, start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]:
        params = {"gtk_user_id": GTK_USER_ID, "start": start, "end": end}
        rows: dict[str, list[dict[str, Any]]] = {}
        rows["live"] = self.connection.fetch_all(
            f"""
            SELECT {_GOAL_COLUMNS}
            FROM dbo.live_goals
            WHERE UserID = :gtk_user_id
              AND goalStart >= :start
              AND goalStart < :end
            ORDER BY goalStart DESC, goalUniqueID DESC
            """,
            params,
        )
        for status, table_name in (
            ("completed", "completed_goals"),
            ("failed", "failed_goals"),
        ):
            rows[status] = self.connection.fetch_all(
                f"""
                SELECT {_GOAL_COLUMNS}
                FROM dbo.{table_name}
                WHERE UserID = :gtk_user_id
                  AND goalStart >= :start
                  AND goalStart < :end
                ORDER BY goalStart DESC, goalUniqueID DESC
                """,
                params,
            )
        return rows

    def overdue_live_rows(self, before: datetime) -> list[dict[str, Any]]:
        return self.connection.fetch_all(
            f"""
            SELECT {_GOAL_COLUMNS}
            FROM dbo.live_goals
            WHERE UserID = :gtk_user_id
              AND goalStart < :before
            ORDER BY goalStart ASC, goalUniqueID ASC
            """,
            {"gtk_user_id": GTK_USER_ID, "before": before},
        )

    def global_stats(
        self, start: datetime, end: datetime, *, include_live_in_rate: bool
    ) -> dict[str, Any]:
        row = self.connection.fetch_one(
            """
            SELECT
              (SELECT COUNT(1) FROM dbo.completed_goals
               WHERE UserID = :gtk_user_id AND goalStart >= :start AND goalStart < :end) AS completed_count,
              (SELECT COUNT(1) FROM dbo.failed_goals
               WHERE UserID = :gtk_user_id AND goalStart >= :start AND goalStart < :end) AS failed_count,
              (SELECT COUNT(1) FROM dbo.live_goals
               WHERE UserID = :gtk_user_id AND goalStart >= :start AND goalStart < :end) AS live_count
            """,
            {"gtk_user_id": GTK_USER_ID, "start": start, "end": end},
        ) or {}
        minute_rows = self.connection.fetch_all(
            """
            SELECT goalType AS goal_type, COALESCE(SUM(goalNumber), 0) AS total_minutes
            FROM dbo.completed_goals
            WHERE UserID = :gtk_user_id
              AND goalStart >= :start
              AND goalStart < :end
              AND goalType IN ('Spirit', 'Soul', 'Body', 'Garden')
            GROUP BY goalType
            """,
            {"gtk_user_id": GTK_USER_ID, "start": start, "end": end},
        )
        minutes = {"Spirit": 0, "Soul": 0, "Body": 0, "Garden": 0}
        for minute_row in minute_rows:
            key = str(minute_row.get("goal_type") or "")
            if key in minutes:
                minutes[key] = int(minute_row.get("total_minutes") or 0)
        completed = int(row.get("completed_count") or 0)
        failed = int(row.get("failed_count") or 0)
        live = int(row.get("live_count") or 0)
        denominator = completed + failed + (live if include_live_in_rate else 0)
        return {
            "completed_goals_count": completed,
            "failed_goals_count": failed,
            "live_goals_count": live,
            "completed_percentage": round(completed / denominator * 100, 2) if denominator else 0,
            "spirit_minutes": minutes["Spirit"],
            "soul_minutes": minutes["Soul"],
            "body_minutes": minutes["Body"],
            "garden_minutes": minutes["Garden"],
        }

    def garden_plant_rows(self) -> list[dict[str, Any]]:
        return self.connection.fetch_all(
            """
            SELECT id, plant_id, plant_name, plant_type, plant_date,
                   target_harvest_date, next_harvest, maintenance_notes, is_active
            FROM dbo.gardening_pro
            WHERE user_id = :gtk_user_id
            ORDER BY is_active DESC, next_harvest ASC, plant_name ASC
            """,
            {"gtk_user_id": GTK_USER_ID},
        )

    def garden_history_rows(
        self, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        return self.connection.fetch_all(
            """
            SELECT id, plant_id, history_type, event_at, ph_level,
                   soil_tidbits, note_text
            FROM dbo.gardening_pro_history
            WHERE user_id = :gtk_user_id
              AND event_at >= :start
              AND event_at < :end
            ORDER BY event_at DESC, id DESC
            """,
            {"gtk_user_id": GTK_USER_ID, "start": start, "end": end},
        )

