"""Deterministic report arithmetic; Luna never owns these calculations."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .models import ActivityFact


def calculate_stats(facts: list[ActivityFact]) -> dict[str, Any]:
    goal_facts = [fact for fact in facts if fact.source_kind == "goal"]
    completed = [fact for fact in goal_facts if fact.status == "completed"]
    failed = [fact for fact in goal_facts if fact.status == "failed"]
    live = [fact for fact in goal_facts if fact.status == "live"]
    outcomes = len(completed) + len(failed)
    completed_minutes = sum(fact.minutes or 0 for fact in completed)
    recorded_minutes = sum(fact.minutes or 0 for fact in goal_facts)
    type_minutes: Counter[str] = Counter()
    for fact in completed:
        type_minutes[fact.category or "Unspecified"] += fact.minutes or 0
    behavior_counts = Counter(fact.behavior for fact in goal_facts)
    return {
        "scheduled_goals": len(goal_facts),
        "completed_goals": len(completed),
        "failed_goals": len(failed),
        "live_goals": len(live),
        "completion_rate": round(len(completed) / outcomes * 100, 2) if outcomes else 0,
        "failure_rate": round(len(failed) / outcomes * 100, 2) if outcomes else 0,
        "recorded_minutes": recorded_minutes,
        "completed_minutes": completed_minutes,
        "average_completed_minutes": round(completed_minutes / len(completed), 2) if completed else 0,
        "goal_type_minutes": dict(sorted(type_minutes.items())),
        "behavior_distribution": {
            "standard": behavior_counts.get("standard", 0),
            "sliding": behavior_counts.get("sliding", 0),
        },
        "garden_records": sum(fact.source_kind == "garden_plant" for fact in facts),
        "garden_events": sum(fact.source_kind == "garden_history" for fact in facts),
    }


def trend(current: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any] | None:
    if prior is None:
        return None
    return {
        "completed_goals_change": current["completed_goals"] - prior["completed_goals"],
        "failed_goals_change": current["failed_goals"] - prior["failed_goals"],
        "completed_minutes_change": current["completed_minutes"] - prior["completed_minutes"],
        "completion_rate_point_change": round(
            current["completion_rate"] - prior["completion_rate"], 2
        ),
    }


def attention_signals(
    domain: str,
    stats: dict[str, Any],
    prior: dict[str, Any] | None,
    overdue: list[ActivityFact],
    planning_context: dict[str, Any],
) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    if stats["failed_goals"] >= 3:
        signals.append({
            "code": "recent_failures",
            "severity": "attention",
            "message": f"{stats['failed_goals']} relevant goals failed in this window.",
            "rule": "failed_goals >= 3",
        })
    if prior and stats["completed_goals"] + stats["failed_goals"] >= 3:
        drop = prior["completion_rate"] - stats["completion_rate"]
        if drop >= 15:
            signals.append({
                "code": "completion_rate_drop",
                "severity": "attention",
                "message": f"Completion rate is {round(drop, 2)} points below the prior comparable window.",
                "rule": "completion-rate drop >= 15 points",
            })
    if overdue:
        signals.append({
            "code": "overdue_live_goals",
            "severity": "attention",
            "message": f"{len(overdue)} relevant live goals appear overdue under GTK timing rules.",
            "rule": "standard before local midnight or slider past deadline",
        })
    if domain == "coding-command" and planning_context.get("active_projects") and not stats["scheduled_goals"]:
        signals.append({
            "code": "plan_evidence_gap",
            "severity": "watch",
            "message": "Jaza has active project planning, but this window contains no matching GTK coding evidence.",
            "rule": "active Jaza project and zero classified GTK goals",
        })
    return signals


def is_overdue(fact: ActivityFact, now_local: datetime, start_of_today: datetime) -> bool:
    if fact.status != "live" or not fact.occurred_at:
        return False
    try:
        start = datetime.fromisoformat(fact.occurred_at)
        due = datetime.fromisoformat(fact.due_at) if fact.due_at else None
    except ValueError:
        return False
    if fact.behavior == "sliding":
        return bool(due and now_local > due)
    return start < start_of_today

