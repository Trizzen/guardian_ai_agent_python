from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaza_sentinel.app import create_app
from jaza_sentinel.integrations.guard_this_kingdom.connection import (
    GtkReadOnlyConnection,
    GtkUnavailableError,
    assert_select_only,
)
from jaza_sentinel.integrations.guard_this_kingdom.mapper import goal_row_to_fact
from jaza_sentinel.integrations.guard_this_kingdom.repository import (
    GTK_USER_ID,
    GuardThisKingdomRepository,
)
from jaza_sentinel.reporting.classifier import classify
from jaza_sentinel.reporting.luna import (
    LunaReportingProvider,
    LunaStructuredReport,
    LunaUnavailableError,
)
from jaza_sentinel.reporting.service import ReportingService
from jaza_sentinel.reporting.statistics import calculate_stats
from jaza_sentinel.storage import JsonStateRepository


def goal_row(
    goal_id: int,
    title: str,
    *,
    goal_type: str = "Body",
    minutes: int = 15,
    measure: str = "standard",
    start: datetime | None = None,
) -> dict:
    occurred = start or datetime(2026, 8, 8, 9, 0)
    return {
        "goalUniqueID": goal_id,
        "goalName": title,
        "goalNumber": minutes,
        "goalStart": occurred,
        "goalFinish": occurred + timedelta(hours=2),
        "goalNotes": "",
        "goalMeasure": measure,
        "goalActualComplete": occurred + timedelta(minutes=minutes),
        "goalType": goal_type,
        "team_sharing": None,
    }


class CapturingConnection:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def fetch_all(self, statement, parameters=None):
        self.calls.append((statement, dict(parameters or {})))
        return []

    def fetch_one(self, statement, parameters=None):
        self.calls.append((statement, dict(parameters or {})))
        if "healthy" in statement:
            return {"healthy": 1}
        return None


class FakeGtkRepository:
    target_user_id = GTK_USER_ID

    def __init__(self, unavailable: bool = False):
        self.unavailable = unavailable
        self.goal_calls: list[tuple[datetime, datetime]] = []
        current = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        self.rows = {
            "live": [goal_row(1, "Morning workout", start=current)],
            "completed": [goal_row(2, "Protein meal prep", start=current)],
            "failed": [goal_row(3, "Debug GuardThisKingdom API", goal_type="Soul", start=current)],
        }

    def health(self):
        if self.unavailable:
            raise GtkUnavailableError("offline")
        return {"connected": True}

    def user_profile(self):
        if self.unavailable:
            raise GtkUnavailableError("offline")
        return {"id": GTK_USER_ID, "timezone": "UTC"}

    def week_start_day(self):
        return "monday"

    def earliest_goal_start(self):
        return datetime(2026, 1, 1)

    def goal_rows(self, start, end):
        self.goal_calls.append((start, end))
        return self.rows

    def overdue_live_rows(self, _before):
        return []

    def global_stats(self, _start, _end, *, include_live_in_rate):
        return {
            "completed_goals_count": 1,
            "failed_goals_count": 1,
            "live_goals_count": 1,
            "completed_percentage": 33.33 if include_live_in_rate else 50.0,
            "spirit_minutes": 0,
            "soul_minutes": 0,
            "body_minutes": 15,
            "garden_minutes": 0,
        }

    def garden_plant_rows(self):
        return [
            {
                "id": 9,
                "plant_id": "tomato-1",
                "plant_name": "Tomato",
                "plant_type": "vegetable",
                "plant_date": datetime(2026, 5, 1),
                "target_harvest_date": datetime(2026, 8, 20),
                "next_harvest": datetime(2026, 8, 20),
                "maintenance_notes": "Check soil",
                "is_active": True,
            }
        ]

    def garden_history_rows(self, _start, _end):
        return [
            {
                "id": 10,
                "plant_id": "tomato-1",
                "history_type": "watered",
                "event_at": datetime(2026, 8, 8),
                "ph_level": None,
                "soil_tidbits": "",
                "note_text": "Watered deeply",
            }
        ]


class FakeLuna:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def status(self):
        return {"ready": not self.fail, "provider": "openai", "model": "gpt-5.6-luna", "message": None}

    def generate(self, context):
        self.calls += 1
        if self.fail:
            raise LunaUnavailableError("offline")
        return {
            "report_id": "report_test",
            "report_version": "jaza-report-v1",
            "prompt_version": "jaza-reporting-v1",
            "summary": f"Grounded {context['domain']} summary.",
            "wins": [],
            "patterns": [],
            "risks_or_attention": [],
            "recommended_next_focus": "Review the evidence.",
            "questions_for_king_trizzen": [],
            "evidence_insufficient": False,
            "classification_decisions": [],
            "generated_at": "2026-08-09T12:00:00+00:00",
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "grounded": True,
            "source_modified": False,
            "usage": {"total_tokens": 42},
            "latency_ms": 5,
        }


@pytest.fixture
def local_repository(tmp_path: Path) -> JsonStateRepository:
    defaults = Path(__file__).resolve().parents[1] / "data" / "defaults"
    return JsonStateRepository(tmp_path / "runtime", defaults)


def test_select_only_guard_allows_reads_and_blocks_mutations():
    assert_select_only("SELECT 1")
    assert_select_only("WITH rows AS (SELECT 1 AS value) SELECT value FROM rows")
    for statement in (
        "UPDATE dbo.live_goals SET goalName='x'",
        "INSERT INTO dbo.live_goals DEFAULT VALUES",
        "DELETE FROM dbo.live_goals",
        "MERGE dbo.live_goals AS target USING source ON 1=1 WHEN MATCHED THEN DELETE;",
        "EXEC dbo.proc_failed_goal 1",
    ):
        with pytest.raises(GtkUnavailableError) as error:
            assert_select_only(statement)
        assert error.value.code == "GTK_SELECT_ONLY_VIOLATION"


def test_read_only_repository_hard_scopes_every_query_to_1002():
    connection = CapturingConnection()
    repository = GuardThisKingdomRepository(connection)  # type: ignore[arg-type]
    start = datetime(2026, 8, 1)
    end = datetime(2026, 8, 9)
    repository.user_profile()
    repository.week_start_day()
    repository.goal_rows(start, end)
    repository.overdue_live_rows(end)
    repository.global_stats(start, end, include_live_in_rate=False)
    repository.garden_plant_rows()
    repository.garden_history_rows(start, end)

    scoped_calls = [params for _statement, params in connection.calls if params]
    assert scoped_calls
    assert all(params.get("gtk_user_id") == 1002 for params in scoped_calls)
    assert not hasattr(repository, "add")
    assert not hasattr(repository, "delete")
    assert not hasattr(repository, "commit")
    assert not hasattr(repository, "update")


def test_goal_mapping_preserves_taxonomy_status_minutes_and_slider_behavior():
    fact = goal_row_to_fact(
        goal_row(77, "Run", goal_type="Body", minutes=45, measure="slider"),
        "completed",
    )
    assert fact.source_id == "completed_goals:77"
    assert fact.category == "Body"
    assert fact.status == "completed"
    assert fact.minutes == 45
    assert fact.behavior == "sliding"
    assert fact.metadata["recurrence_storage"] == "materialized_occurrence"


def test_reporting_windows_follow_gtk_local_boundary_semantics():
    now = datetime(2026, 8, 9, 11, 30)
    assert ReportingService._window_bounds("today", now, "monday") == (
        datetime(2026, 8, 9),
        datetime(2026, 8, 10),
    )
    assert ReportingService._window_bounds("week", now, "monday") == (
        datetime(2026, 8, 3),
        datetime(2026, 8, 10),
    )
    assert ReportingService._window_bounds("week", now, "sunday") == (
        datetime(2026, 8, 9),
        datetime(2026, 8, 16),
    )
    assert ReportingService._window_bounds("month", now, "monday") == (
        datetime(2026, 8, 1),
        datetime(2026, 8, 31),
    )
    assert ReportingService._window_bounds("ytd", now, "monday") == (
        datetime(2026, 1, 1),
        datetime(2026, 8, 9),
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bench press workout", "fitness-program"),
        ("Protein meal prep", "nutrition-program"),
        ("Debug Angular API", "coding-command"),
        ("Review retirement investments", "financial-program"),
        ("Set monthly budget and bills", "budget-program"),
        ("Water garden tomatoes", "gardening-program"),
        ("Read Old Testament", "unclassified"),
    ],
)
def test_contextual_domain_classification(title, expected):
    fact = goal_row_to_fact(goal_row(1, title, goal_type="Soul"), "completed")
    assert classify(fact).domain == expected


@pytest.mark.parametrize(
    ("title", "note"),
    [
        ("Pray in tongues", "Build spiritual strength."),
        ("Shamar Meditate Life Armor", "Walk in truth today."),
        ("Run the API locally", "Check the response."),
    ],
)
def test_ambiguous_spiritual_and_technical_language_is_not_forced_into_fitness(title, note):
    row = goal_row(1, title, goal_type="Spirit")
    row["goalNotes"] = note
    fact = goal_row_to_fact(row, "completed")
    assert classify(fact).domain != "fitness-program"


def test_deterministic_statistics_do_not_depend_on_luna():
    facts = [
        goal_row_to_fact(goal_row(1, "Run", minutes=30), "completed"),
        goal_row_to_fact(goal_row(2, "Run", minutes=20), "failed"),
        goal_row_to_fact(goal_row(3, "Run", minutes=15), "live"),
    ]
    stats = calculate_stats(facts)
    assert stats["completed_goals"] == 1
    assert stats["failed_goals"] == 1
    assert stats["live_goals"] == 1
    assert stats["completion_rate"] == 50.0
    assert stats["completed_minutes"] == 30
    assert stats["behavior_distribution"] == {"standard": 3, "sliding": 0}


def test_reporting_service_combines_separate_planning_and_gtk_evidence(local_repository):
    service = ReportingService(
        local_repository,
        gtk_repository=FakeGtkRepository(),  # type: ignore[arg-type]
        luna_provider=FakeLuna(),  # type: ignore[arg-type]
    )
    report = service.get_report("coding-command", "week")
    assert report["available"] is True
    assert report["stats"]["failed_goals"] == 1
    assert report["planning_context"]["source_role"] == "planning_state_not_gtk_evidence"
    assert report["planning_context"]["active_projects"]
    assert report["source"]["target_user_id"] == 1002


def test_gardening_report_reads_real_plant_and_history_shapes(local_repository):
    service = ReportingService(
        local_repository,
        gtk_repository=FakeGtkRepository(),  # type: ignore[arg-type]
        luna_provider=FakeLuna(),  # type: ignore[arg-type]
    )
    report = service.get_report("gardening-program", "week")
    assert report["stats"]["garden_records"] == 1
    assert report["stats"]["garden_events"] == 1
    assert {item["source_kind"] for item in report["activity"]} >= {"garden_plant", "garden_history"}
    assert all("latitude" not in item for item in report["activity"])


def test_luna_failure_leaves_deterministic_report_available(local_repository):
    service = ReportingService(
        local_repository,
        gtk_repository=FakeGtkRepository(),  # type: ignore[arg-type]
        luna_provider=FakeLuna(fail=True),  # type: ignore[arg-type]
    )
    report = service.generate_insight("fitness-program", "week")
    assert report["available"] is True
    assert report["stats"]["live_goals"] == 1
    assert report["insight"] is None
    assert report["insight_error"]["code"] == "LUNA_UNAVAILABLE"


def test_insight_cache_prevents_repeat_provider_calls(local_repository):
    luna = FakeLuna()
    service = ReportingService(
        local_repository,
        gtk_repository=FakeGtkRepository(),  # type: ignore[arg-type]
        luna_provider=luna,  # type: ignore[arg-type]
    )
    first = service.generate_insight("fitness-program", "week")
    second = service.generate_insight("fitness-program", "week")
    assert first["insight"]["report_id"] == "report_test"
    assert second["insight_cache"]["status"] == "hit"
    assert luna.calls == 1


def test_gtk_outage_does_not_break_local_reporting(local_repository):
    service = ReportingService(
        local_repository,
        gtk_repository=FakeGtkRepository(unavailable=True),  # type: ignore[arg-type]
        luna_provider=FakeLuna(),  # type: ignore[arg-type]
    )
    report = service.get_report("fitness-program", "week")
    assert report["available"] is False
    assert report["stats"]["completed_goals"] == 0
    assert local_repository.programs()


def test_feedback_is_stored_only_in_jaza_json(local_repository):
    service = ReportingService(
        local_repository,
        gtk_repository=FakeGtkRepository(),  # type: ignore[arg-type]
        luna_provider=FakeLuna(),  # type: ignore[arg-type]
    )
    item = service.record_feedback(
        {"report_id": "report_1", "domain": "fitness-program", "useful": False, "note": "Wrong category"}
    )
    assert item["correction"] == "Wrong category"
    assert local_repository.report_feedback() == [item]


def test_reporting_api_never_accepts_a_gtk_user_id(local_repository):
    service = ReportingService(
        local_repository,
        gtk_repository=FakeGtkRepository(),  # type: ignore[arg-type]
        luna_provider=FakeLuna(),  # type: ignore[arg-type]
    )
    app = create_app(
        data_dir=local_repository.runtime_dir,
        codex_config_path=local_repository.runtime_dir / "missing.toml",
        reporting_service=service,
    )
    client = app.test_client()
    get_response = client.get("/api/reporting/domains/fitness-program?window=week&user_id=999")
    assert get_response.status_code == 200
    assert get_response.get_json()["source"]["target_user_id"] == 1002
    response = client.post(
        "/api/reporting/domains/fitness-program/insight",
        json={"window": "week", "user_id": 999},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_luna_provider_parses_strict_output_and_drops_unknown_source_decisions(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    parsed = LunaStructuredReport(
        summary="Grounded summary.",
        wins=[],
        patterns=[],
        risks_or_attention=[],
        recommended_next_focus="Review.",
        questions_for_king_trizzen=[],
        evidence_insufficient=False,
        classification_decisions=[
            {"source_id": "unknown:1", "domain": "fitness-program", "confidence": 0.8, "reason": "Workout"}
        ],
    )
    response = SimpleNamespace(
        status="completed",
        output_parsed=parsed,
        model="gpt-5.6-luna",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
    )
    calls = []
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(parse=lambda **kwargs: calls.append(kwargs) or response)
    )
    provider = LunaReportingProvider(client_factory=lambda **_kwargs: fake_client)
    result = provider.generate({"domain": "fitness-program", "ambiguous_facts": []})
    assert result["grounded"] is True
    assert result["source_modified"] is False
    assert result["classification_decisions"] == []
    assert result["usage"]["total_tokens"] == 15
    assert calls[0]["model"] == "gpt-5.6-luna"
    assert calls[0]["store"] is False
    assert isinstance(calls[0]["input"][1]["content"], str)


def test_luna_provider_rejects_malformed_structured_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    response = SimpleNamespace(status="completed", output_parsed={"summary": "missing fields"}, model="gpt-5.6-luna")
    fake_client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **_kwargs: response))
    provider = LunaReportingProvider(client_factory=lambda **_kwargs: fake_client)
    with pytest.raises(LunaUnavailableError) as error:
        provider.generate({"domain": "fitness-program", "ambiguous_facts": []})
    assert error.value.code == "LUNA_SCHEMA_INVALID"
