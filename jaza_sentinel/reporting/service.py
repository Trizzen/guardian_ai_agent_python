"""Orchestrate GTK evidence, deterministic reporting, Luna, cache, and feedback."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, time, timedelta
from threading import RLock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..integrations.guard_this_kingdom import (
    GTK_USER_ID,
    GtkUnavailableError,
    GuardThisKingdomRepository,
)
from ..integrations.guard_this_kingdom.mapper import (
    garden_history_row_to_fact,
    goal_row_to_fact,
    plant_row_to_fact,
)
from ..storage import JsonStateRepository
from .classifier import DOMAIN_IDS, classify_all
from .luna import LunaReportingProvider, LunaUnavailableError, PROMPT_VERSION, REPORT_VERSION
from .models import ActivityFact
from .statistics import attention_signals, calculate_stats, is_overdue, trend


LOGGER = logging.getLogger(__name__)
WINDOWS = ("today", "week", "month", "ytd", "all")
DOMAIN_LABELS = {
    "daily-command": "Daily Command",
    "coding-command": "Coding Projects",
    "fitness-program": "Fitness",
    "nutrition-program": "Nutrition",
    "gardening-program": "Gardening",
    "financial-program": "Financial Planning",
    "budget-program": "Budgeting",
}


class ReportingInputError(ValueError):
    pass


class ReportingService:
    def __init__(
        self,
        local_repository: JsonStateRepository,
        *,
        gtk_repository: GuardThisKingdomRepository | None = None,
        luna_provider: LunaReportingProvider | None = None,
    ) -> None:
        self.local = local_repository
        self.gtk = gtk_repository or GuardThisKingdomRepository()
        self.luna = luna_provider or LunaReportingProvider()
        self.ttl_seconds = max(60, int(os.environ.get("JAZA_REPORT_CACHE_TTL_SECONDS", "3600")))
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._lock = RLock()

    def overview(self) -> dict[str, Any]:
        try:
            gtk_status = self.gtk.health()
            gtk_payload = {"connected": bool(gtk_status.get("connected")), "message": None}
        except GtkUnavailableError as exc:
            gtk_payload = {"connected": False, "message": exc.message}
        return {
            "guard_this_kingdom": gtk_payload,
            "luna": self.luna.status(),
            "target_user_scope": GTK_USER_ID,
            "windows": list(WINDOWS),
            "domains": [
                {"id": domain, "label": DOMAIN_LABELS[domain]} for domain in DOMAIN_IDS
            ],
            "source_policy": "GuardThisKingdom is read-only evidence; Jaza JSON remains planning state.",
        }

    def get_report(self, domain: str, window_name: str) -> dict[str, Any]:
        self._validate(domain, window_name)
        started = monotonic()
        try:
            report = self._build_report(domain, window_name)
            with self._lock:
                cached = self._cache.get((domain, window_name))
                if cached and monotonic() - cached[0] <= self.ttl_seconds:
                    report["insight"] = cached[1]
                    report["insight_cache"] = {"status": "hit", "ttl_seconds": self.ttl_seconds}
                else:
                    report["insight"] = None
                    report["insight_cache"] = {"status": "empty", "ttl_seconds": self.ttl_seconds}
            LOGGER.info(
                "report_ready domain=%s window=%s row_count=%s classified=%s unclassified=%s latency_ms=%s",
                domain,
                window_name,
                report["provenance"]["record_count"],
                report["classification"]["classified_count"],
                report["classification"]["unclassified_count"],
                int((monotonic() - started) * 1000),
            )
            return report
        except GtkUnavailableError as exc:
            LOGGER.warning("gtk_report_unavailable domain=%s window=%s code=%s", domain, window_name, exc.code)
            return self._unavailable_report(domain, window_name, exc)

    def generate_insight(
        self, domain: str, window_name: str, *, refresh: bool = False
    ) -> dict[str, Any]:
        self._validate(domain, window_name)
        cache_key = (domain, window_name)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and not refresh and monotonic() - cached[0] <= self.ttl_seconds:
                report = self.get_report(domain, window_name)
                report["insight_cache"]["status"] = "hit"
                return report
        report = self.get_report(domain, window_name)
        if not report.get("available"):
            return report
        context = self._luna_context(report)
        LOGGER.info("luna_invocation domain=%s window=%s cache=miss", domain, window_name)
        try:
            insight = self.luna.generate(context)
        except LunaUnavailableError as exc:
            LOGGER.warning("luna_failure domain=%s window=%s code=%s", domain, window_name, exc.code)
            report["insight_error"] = {"code": exc.code, "message": exc.message}
            report["insight"] = None
            return report
        with self._lock:
            self._cache[cache_key] = (monotonic(), insight)
        report["insight"] = insight
        report["insight_cache"] = {"status": "miss", "ttl_seconds": self.ttl_seconds}
        LOGGER.info(
            "luna_success domain=%s window=%s latency_ms=%s total_tokens=%s",
            domain,
            window_name,
            insight.get("latency_ms"),
            insight.get("usage", {}).get("total_tokens"),
        )
        return report

    def record_feedback(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ReportingInputError("Feedback must be a JSON object.")
        report_id = str(payload.get("report_id") or "").strip()
        domain = str(payload.get("domain") or "").strip()
        useful = payload.get("useful")
        note = str(payload.get("note") or "").strip()[:1000]
        if not report_id or domain not in DOMAIN_IDS or not isinstance(useful, bool):
            raise ReportingInputError("report_id, a valid domain, and useful boolean are required.")
        item = {
            "report_id": report_id[:120],
            "report_version": REPORT_VERSION,
            "prompt_version": PROMPT_VERSION,
            "domain": domain,
            "generated_at": str(payload.get("generated_at") or "")[:80],
            "useful": useful,
            "correction": note,
            "follow_up_notes": "",
            "recorded_at": datetime.now().astimezone().isoformat(),
        }
        return self.local.append_report_feedback(item)

    def _build_report(self, domain: str, window_name: str) -> dict[str, Any]:
        profile = self.gtk.user_profile()
        timezone_name = str(profile.get("timezone") or "UTC")
        try:
            tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
            timezone_name = "UTC"
        now_local = datetime.now(tz).replace(tzinfo=None)
        week_start = self.gtk.week_start_day()
        start, end = self._window_bounds(window_name, now_local, week_start)
        if window_name == "all":
            start = self.gtk.earliest_goal_start() or now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = self.gtk.goal_rows(start, end)
        facts = [
            goal_row_to_fact(row, status)
            for status, status_rows in rows.items()
            for row in status_rows
        ]
        if domain in {"gardening-program", "daily-command"}:
            facts.extend(plant_row_to_fact(row) for row in self.gtk.garden_plant_rows())
            facts.extend(garden_history_row_to_fact(row) for row in self.gtk.garden_history_rows(start, end))
        classify_all(facts)
        unclassified = [fact for fact in facts if fact.classification.domain == "unclassified"]
        relevant = facts if domain == "daily-command" else [
            fact for fact in facts if fact.classification.domain == domain
        ]
        prior_stats = None
        if window_name != "all":
            span = end - start
            prior_rows = self.gtk.goal_rows(start - span, start)
            prior_facts = classify_all([
                goal_row_to_fact(row, status)
                for status, status_rows in prior_rows.items()
                for row in status_rows
            ])
            if domain != "daily-command":
                prior_facts = [fact for fact in prior_facts if fact.classification.domain == domain]
            prior_stats = calculate_stats(prior_facts)
        stats = calculate_stats(relevant)
        all_overdue = classify_all([
            goal_row_to_fact(row, "live")
            for row in self.gtk.overdue_live_rows(now_local)
        ])
        start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        overdue = [
            fact for fact in all_overdue
            if (domain == "daily-command" or fact.classification.domain == domain)
            and is_overdue(fact, now_local, start_of_today)
        ]
        planning = self._planning_context(domain)
        signals = attention_signals(domain, stats, prior_stats, overdue, planning)
        used_ids = sorted(fact.source_id for fact in relevant)
        fingerprint = hashlib.sha256("\n".join(used_ids).encode("utf-8")).hexdigest()
        global_stats = self.gtk.global_stats(start, end, include_live_in_rate=window_name == "today")
        activity = sorted(
            relevant,
            key=lambda fact: fact.occurred_at or fact.due_at or "",
            reverse=True,
        )[:20]
        return {
            "available": True,
            "domain": domain,
            "domain_label": DOMAIN_LABELS[domain],
            "window": window_name,
            "window_label": {"today": "Today", "week": "This Week", "month": "This Month", "ytd": "Year-to-Date", "all": "All Time"}[window_name],
            "window_bounds": {"start": start.isoformat(), "end_exclusive": end.isoformat(), "timezone": timezone_name, "gtk_week_start": week_start},
            "source": {"guard_this_kingdom": True, "mode": "read_only", "target_user_id": GTK_USER_ID, "jaza_local_state": bool(planning)},
            "stats": stats,
            "prior_window_stats": prior_stats,
            "trend": trend(stats, prior_stats),
            "gtk_parity_stats": global_stats,
            "activity": [fact.public_dict() for fact in activity],
            "overdue_activity": [fact.public_dict() for fact in overdue[:12]],
            "attention_signals": signals,
            "planning_context": planning,
            "classification": {
                "classified_count": len(facts) - len(unclassified),
                "unclassified_count": len(unclassified),
                "ambiguous_for_luna": [fact.public_dict() for fact in unclassified[:24]],
                "rules_version": "jaza-domain-rules-v1",
                "statistics_scope": "deterministically_classified_facts_only" if domain != "daily-command" else "all_source_facts",
            },
            "provenance": {
                "record_count": len(relevant),
                "record_id_fingerprint_sha256": fingerprint,
                "record_ids_preview": used_ids[:30],
                "generated_at": datetime.now().astimezone().isoformat(),
                "report_version": REPORT_VERSION,
                "prompt_version": PROMPT_VERSION,
            },
        }

    def _planning_context(self, domain: str) -> dict[str, Any]:
        if domain == "coding-command":
            projects = self.local.projects()
            return {
                "source": "jaza_local_json",
                "source_role": "planning_state_not_gtk_evidence",
                "active_projects": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "status": item.get("status"),
                        "current_focus": item.get("current_focus"),
                        "next_action": item.get("next_action"),
                    }
                    for item in projects
                    if item.get("status") in {"active", "ready", "waiting"}
                ],
                "work_items": [
                    {"id": item.get("id"), "title": item.get("title"), "status": item.get("status"), "next_action": item.get("next_action")}
                    for item in self.local.work_items()
                    if item.get("target_type") == "project" and item.get("status") != "completed"
                ][:12],
            }
        items = [
            item for item in self.local.work_items()
            if item.get("target_type") == "program" and item.get("target_id") == domain
        ]
        return {
            "source": "jaza_local_json",
            "source_role": "planning_state_not_gtk_evidence",
            "work_items": [
                {"id": item.get("id"), "title": item.get("title"), "status": item.get("status"), "next_action": item.get("next_action")}
                for item in items[:12]
            ],
        }

    @staticmethod
    def _luna_context(report: dict[str, Any]) -> dict[str, Any]:
        return {
            "task": "Interpret the grounded Jaza domain report and classify only supplied ambiguous facts.",
            "domain": report["domain"],
            "window": report["window"],
            "window_bounds": report["window_bounds"],
            "deterministic_stats": report["stats"],
            "prior_window_stats": report["prior_window_stats"],
            "deterministic_trend": report["trend"],
            "attention_signals": report["attention_signals"],
            "recent_activity": report["activity"][:12],
            "ambiguous_facts": report["classification"]["ambiguous_for_luna"],
            "jaza_planning_context": report["planning_context"],
            "provenance": report["provenance"],
            "source_policy": "GTK is read-only evidence. Jaza JSON is separate planning state.",
        }

    @staticmethod
    def _window_bounds(window_name: str, now_local: datetime, week_start: str) -> tuple[datetime, datetime]:
        start_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        if window_name == "today":
            return start_today, start_today + timedelta(days=1)
        if window_name == "week":
            days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
            start = start_today - timedelta(days=(start_today.weekday() - days.index(week_start)) % 7)
            return start, start + timedelta(days=7)
        if window_name == "month":
            start = start_today.replace(day=1)
            next_month = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
            # GTK's get_mtd_goals_stats passes the final calendar date to the
            # shared `< end_date` helper. Preserve that compatibility edge.
            return start, next_month - timedelta(days=1)
        if window_name == "ytd":
            # GTK's existing YTD helper uses today's midnight as an exclusive end.
            return start_today.replace(month=1, day=1), start_today
        return datetime(1970, 1, 1), start_today + timedelta(days=1)

    @staticmethod
    def _validate(domain: str, window_name: str) -> None:
        if domain not in DOMAIN_IDS:
            raise ReportingInputError("Unknown Jaza reporting domain.")
        if window_name not in WINDOWS:
            raise ReportingInputError("Unknown reporting window.")

    def _unavailable_report(self, domain: str, window_name: str, error: GtkUnavailableError) -> dict[str, Any]:
        return {
            "available": False,
            "domain": domain,
            "domain_label": DOMAIN_LABELS[domain],
            "window": window_name,
            "source": {"guard_this_kingdom": False, "mode": "read_only", "target_user_id": GTK_USER_ID},
            "stats": calculate_stats([]),
            "activity": [],
            "overdue_activity": [],
            "attention_signals": [],
            "planning_context": self._planning_context(domain),
            "classification": {"classified_count": 0, "unclassified_count": 0, "ambiguous_for_luna": []},
            "provenance": {"record_count": 0, "generated_at": datetime.now().astimezone().isoformat(), "report_version": REPORT_VERSION},
            "insight": None,
            "error": {"code": error.code, "message": error.message},
        }
