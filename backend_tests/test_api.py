from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from jaza_sentinel import create_app


@pytest.fixture
def runtime_dir(tmp_path: Path) -> Path:
    return tmp_path / "runtime"


@pytest.fixture
def codex_config_path(tmp_path: Path) -> Path:
    path = tmp_path / "codex" / "config.toml"
    path.parent.mkdir()
    path.write_text(
        'model = "gpt-5"\n\n'
        '[desktop]\n'
        'selected-avatar-id = "custom:jaza-soulminder"\n'
        'animations-enabled = true\n\n'
        '[features]\n'
        'example = true\n',
        encoding="utf-8",
    )
    path.chmod(0o640)
    return path


@pytest.fixture
def client(runtime_dir: Path, codex_config_path: Path):
    app = create_app(data_dir=runtime_dir, codex_config_path=codex_config_path)
    app.config.update(TESTING=True)
    return app.test_client()


def sample_work_item() -> dict:
    return {
        "title": "Prepare the next verified milestone",
        "description": "Keep the outcome narrow and reviewable.",
        "target_type": "project",
        "target_id": "jaza-sentinel",
        "priority": "high",
        "status": "ready",
        "next_action": "Ask King Trizzen for approval.",
        "human_check_in_status": "requested",
        "execution_assignee": "star_reborn",
        "scheduled_for": "2026-08-09T09:00:00-04:00",
    }


def test_health_dashboard_and_seed_collections(client):
    assert client.get("/api/health").get_json()["status"] == "ok"

    dashboard = client.get("/api/sentinel/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.get_json()["identity"]["name"] == "Jaza Soulminder"
    assert dashboard.get_json()["metrics"]["needs_my_attention"] == 5

    programs = client.get("/api/programs").get_json()["items"]
    projects = client.get("/api/projects").get_json()["items"]
    assert {item["id"] for item in programs} >= {"daily-command", "budget-program"}
    assert {item["id"] for item in projects} >= {"guard-this-kingdom", "automatrix"}


def test_work_item_create_update_and_restart_persistence(
    client, runtime_dir, codex_config_path
):
    created_response = client.post("/api/work-items", json=sample_work_item())
    assert created_response.status_code == 201
    created = created_response.get_json()["item"]
    assert created["execution_status"] == "prepared_for_star"
    assert created["human_check_in_required"] is True

    updated_response = client.patch(
        f"/api/work-items/{created['id']}",
        json={"status": "active", "priority": "critical"},
    )
    assert updated_response.status_code == 200
    assert updated_response.get_json()["item"]["status"] == "active"

    restarted_client = create_app(
        data_dir=runtime_dir, codex_config_path=codex_config_path
    ).test_client()
    persisted = restarted_client.get("/api/work-items").get_json()["items"]
    matching = next(item for item in persisted if item["id"] == created["id"])
    assert matching["priority"] == "critical"
    assert matching["status"] == "active"


def test_missing_and_malformed_state_recovers_without_crashing(client, runtime_dir):
    (runtime_dir / "programs.json").unlink()
    assert len(client.get("/api/programs").get_json()["items"]) == 7
    assert (runtime_dir / "programs.json").exists()

    (runtime_dir / "sentinel.json").write_text("{broken", encoding="utf-8")
    response = client.get("/api/sentinel/dashboard")
    assert response.status_code == 200
    assert response.get_json()["identity"]["role"] == "Sentinel"
    assert list(runtime_dir.glob("sentinel.json.corrupt-*"))


def test_validation_returns_useful_errors(client):
    response = client.post(
        "/api/work-items",
        json={"title": "", "target_type": "galaxy", "priority": "urgent"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "validation_error"
    assert set(body["fields"]) >= {"title", "target_type", "target_id", "priority"}

    unknown_target = sample_work_item()
    unknown_target["target_id"] = "not-real"
    response = client.post("/api/work-items", json=unknown_target)
    assert response.status_code == 400
    assert "target_id" in response.get_json()["fields"]


def test_notes_check_ins_usage_and_project_updates(client):
    note = client.post(
        "/api/notes",
        json={
            "target_type": "program",
            "target_id": "gardening-program",
            "body": "Tomatoes need another support check.",
        },
    )
    assert note.status_code == 201

    check_in = client.post(
        "/api/check-ins",
        json={
            "target_type": "project",
            "target_id": "safe-bite",
            "body": "Choose the next owner-reviewed source.",
            "check_in_status": "awaiting_direction",
        },
    )
    assert check_in.status_code == 201
    assert check_in.get_json()["item"]["status"] == "awaiting_direction"
    assert client.get("/api/sentinel/dashboard").get_json()["metrics"]["needs_my_attention"] == 6

    usage = client.post(
        "/api/usage-entries",
        json={"provider_tool": "Codex", "token_estimate": 1200, "cost_estimate": 0.42},
    )
    assert usage.status_code == 201
    assert client.get("/api/usage-entries").get_json()["items"][-1]["token_estimate"] == 1200

    project = client.patch(
        "/api/projects/guard-this-kingdom",
        json={"status": "ready", "priority": "high", "next_action": "Confirm scope."},
    )
    assert project.status_code == 200
    assert project.get_json()["item"]["status"] == "ready"


def test_default_and_runtime_json_contain_no_secret_material(client, runtime_dir):
    client.get("/api/sentinel/dashboard")
    roots = [Path("data/defaults"), runtime_dir]
    forbidden = ("API_KEY", "sk-proj-", "GEMINI_API_KEY")
    for root in roots:
        for path in root.glob("*.json"):
            content = path.read_text(encoding="utf-8")
            json.loads(content)
            assert not any(marker in content for marker in forbidden)


def test_pet_presence_switches_only_allowlisted_codex_key(client, codex_config_path):
    original_text = codex_config_path.read_text(encoding="utf-8")
    before_work = client.get("/api/work-items").get_json()["items"]

    current = client.get("/api/sentinel/pet-presence")
    assert current.status_code == 200
    assert current.get_json() == {
        "available": True,
        "selected_pet": "jaza",
        "selected_avatar_id": "custom:jaza-soulminder",
        "display_name": "Jaza Soulminder",
        "message": None,
    }

    handed = client.post("/api/sentinel/pet-presence", json={"pet": "star"})
    assert handed.status_code == 200
    assert handed.get_json()["selected_pet"] == "star"
    star_text = codex_config_path.read_text(encoding="utf-8")
    assert star_text == original_text.replace(
        'selected-avatar-id = "custom:jaza-soulminder"',
        'selected-avatar-id = "custom:star-reborn"',
    )
    assert stat.S_IMODE(codex_config_path.stat().st_mode) == 0o640
    assert client.get("/api/work-items").get_json()["items"] == before_work

    recalled = client.post("/api/sentinel/pet-presence", json={"pet": "jaza"})
    assert recalled.status_code == 200
    assert recalled.get_json()["selected_pet"] == "jaza"
    assert codex_config_path.read_text(encoding="utf-8") == original_text


def test_pet_presence_rejects_unknown_pet_without_writing(client, codex_config_path):
    original_text = codex_config_path.read_text(encoding="utf-8")
    response = client.post("/api/sentinel/pet-presence", json={"pet": "phoenix"})
    assert response.status_code == 400
    assert response.get_json()["fields"]["pet"] == "must be either 'jaza' or 'star'"
    assert codex_config_path.read_text(encoding="utf-8") == original_text


def test_missing_or_malformed_codex_config_degrades_safely(runtime_dir, tmp_path):
    config_path = tmp_path / "missing" / "config.toml"
    client = create_app(data_dir=runtime_dir, codex_config_path=config_path).test_client()
    unavailable = client.get("/api/sentinel/pet-presence")
    assert unavailable.status_code == 200
    assert unavailable.get_json()["available"] is False
    assert client.post(
        "/api/sentinel/pet-presence", json={"pet": "star"}
    ).status_code == 503
    assert not config_path.exists()

    config_path.parent.mkdir()
    config_path.write_text("[desktop\nbroken", encoding="utf-8")
    original_text = config_path.read_text(encoding="utf-8")
    malformed = client.get("/api/sentinel/pet-presence")
    assert malformed.status_code == 200
    assert malformed.get_json()["available"] is False
    assert client.post(
        "/api/sentinel/pet-presence", json={"pet": "jaza"}
    ).status_code == 503
    assert config_path.read_text(encoding="utf-8") == original_text


def test_pet_presence_inserts_key_when_desktop_table_has_none(runtime_dir, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[desktop]\nanimations-enabled = true\n\n[features]\nexample = true\n',
        encoding="utf-8",
    )
    client = create_app(data_dir=runtime_dir, codex_config_path=config_path).test_client()
    response = client.post("/api/sentinel/pet-presence", json={"pet": "star"})
    assert response.status_code == 200
    assert config_path.read_text(encoding="utf-8") == (
        '[desktop]\nselected-avatar-id = "custom:star-reborn"\n'
        'animations-enabled = true\n\n[features]\nexample = true\n'
    )
