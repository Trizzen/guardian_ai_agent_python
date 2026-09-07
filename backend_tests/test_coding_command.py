from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from jaza_sentinel import create_app
from jaza_sentinel.codex_runtime import CodexHandoffService, CodexRuntimeError, CodexUsageService
from jaza_sentinel.integrations.jira import JiraCodingService, JiraIntegrationError
from jaza_sentinel.integrations.jira.service import adf_to_text, text_to_adf
from jaza_sentinel.storage import JsonStateRepository


class FakeJiraClient:
    project_key = "SCRUM"

    def __init__(self) -> None:
        self.created = 0
        self.issues: dict[str, dict[str, Any]] = {
            "SCRUM-1": self._issue("SCRUM-1", "Existing sprint work", "In Progress", "Original full text", True),
            "SCRUM-9": self._issue("SCRUM-9", "Backlog only", "To Do", "Must not appear", False),
        }

    @staticmethod
    def _issue(key: str, summary: str, status: str, description: str, in_sprint: bool, labels=None):
        return {
            "key": key,
            "fields": {
                "summary": summary,
                "description": text_to_adf(description),
                "status": {"name": status},
                "assignee": {"displayName": "King Trizzen"},
                "priority": {"name": "Medium"},
                "issuetype": {"name": "Story"},
                "customfield_10020": [
                    {"id": 2, "name": "SCRUM Sprint 0", "state": "active"}
                ] if in_sprint else [],
                "labels": labels or [],
            },
        }

    def get(self, path: str, *, params=None):
        if path == "/rest/api/3/project/SCRUM":
            return {"id": "10000", "key": "SCRUM", "name": "King Trizzen's Command Center"}
        if path == "/rest/agile/1.0/board":
            return {"values": [{"id": 1, "name": "SCRUM board", "type": "simple"}]}
        if path == "/rest/agile/1.0/board/1/sprint":
            return {"values": [
                {"id": 3, "name": "SCRUM Sprint 1", "state": "future"},
                {"id": 2, "name": "SCRUM Sprint 0", "state": "active"},
            ]}
        if path == "/rest/api/3/field":
            return {"value": [{"id": "customfield_10020", "name": "Sprint"}]}
        if path == "/rest/api/3/myself":
            return {"accountId": "authenticated-account", "displayName": "King Trizzen"}
        if path == "/rest/api/3/issuetype/project":
            return {"value": [{"id": "10004", "name": "Story"}]}
        if path == "/rest/api/3/search/jql":
            jql = params["jql"]
            if "labels =" in jql:
                label = jql.split('labels = "', 1)[1].split('"', 1)[0]
                return {"issues": [deepcopy(issue) for issue in self.issues.values() if label in issue["fields"]["labels"]]}
            return {"issues": [deepcopy(issue) for issue in self.issues.values() if issue["fields"]["customfield_10020"]]}
        if path.endswith("/transitions"):
            return {"transitions": [
                {"id": "11", "to": {"name": "To Do"}},
                {"id": "21", "to": {"name": "In Progress"}},
            ]}
        if path.startswith("/rest/api/3/issue/"):
            return deepcopy(self.issues[path.rsplit("/", 1)[-1]])
        raise AssertionError((path, params))

    def post(self, path: str, *, json):
        if path == "/rest/api/3/issue":
            self.created += 1
            key = f"SCRUM-{20 + self.created}"
            fields = json["fields"]
            issue = self._issue(
                key,
                fields["summary"],
                "To Do",
                adf_to_text(fields["description"]),
                fields["customfield_10020"] == 2,
                fields.get("labels"),
            )
            issue["fields"]["assignee"] = {
                "displayName": "King Trizzen",
                "accountId": fields["assignee"]["accountId"],
            }
            self.issues[key] = issue
            return {"key": key}
        if path.endswith("/transitions"):
            key = path.split("/")[-2]
            self.issues[key]["fields"]["status"] = {"name": "In Progress"}
            return {}
        raise AssertionError((path, json))


@pytest.fixture
def repository(tmp_path: Path) -> JsonStateRepository:
    return JsonStateRepository(tmp_path / "runtime", Path("data/defaults"))


@pytest.fixture
def jira(repository: JsonStateRepository):
    client = FakeJiraClient()
    return JiraCodingService(client, repository), client


def test_sprint_zero_discovery_backlog_exclusion_and_current_status(jira):
    service, _ = jira
    board = service.board()
    assert board["sprint"] == {
        "id": 2, "name": "SCRUM Sprint 0", "state": "active", "field_id": "customfield_10020"
    }
    assert [story["jira_key"] for story in board["stories"]] == ["SCRUM-1"]
    assert board["stories"][0]["status"] == "in_progress"
    assert [status["id"] for status in board["statuses"]] == ["to_do", "in_progress", "in_review", "done"]


@pytest.mark.parametrize(
    ("jira_status", "normalized"),
    [("To Do", "to_do"), ("In Progress", "in_progress"), ("In Review", "in_review"), ("Done", "done")],
)
def test_exact_status_mapping(jira, jira_status, normalized):
    service, client = jira
    client.issues["SCRUM-1"]["fields"]["status"] = {"name": jira_status}
    assert service.board()["stories"][0]["status"] == normalized


def test_bootstrap_creates_each_visible_planning_item_once_and_links_locally(jira, repository):
    service, client = jira
    eligible = [
        item for item in repository.work_items()
        if item["target_type"] == "project" and item["status"] != "completed"
    ]
    first = service.bootstrap_local_items()
    assert len(first) == len(eligible)
    assert client.created == len(eligible)
    linked = {item["id"]: item.get("jira_key") for item in repository.work_items()}
    assert all(linked[item["local_work_item_id"]] == item["jira_key"] for item in first)
    assert service.bootstrap_local_items() == []
    assert client.created == len(eligible)


def test_bootstrap_preserves_description_next_action_notes_and_project_mapping(jira, repository):
    service, client = jira
    migrated = service.bootstrap_local_items()
    source = next(item for item in repository.work_items() if item["id"] == "work_star_boundary")
    key = next(item["jira_key"] for item in migrated if item["local_work_item_id"] == source["id"])
    description = adf_to_text(client.issues[key]["fields"]["description"])
    assert "Future work only" in description
    assert "Next action:\nWait until" in description
    assert "Notes:\nPrepared means" in description
    assert service.issue(key)["local_repository_path"].endswith("agentic-ai-agent")


def test_new_issue_preserves_full_description_assignee_sprint_and_todo(jira):
    service, client = jira
    full = "First line\n\nExact acceptance criteria:\n- one\n- two"
    story = service.create_issue("Full fidelity", full)
    raw = client.issues[story["jira_key"]]["fields"]
    assert story["description"] == full
    assert raw["assignee"]["accountId"] == "authenticated-account"
    assert raw["customfield_10020"] == [{"id": 2, "name": "SCRUM Sprint 0", "state": "active"}]
    assert story["status"] == "to_do"


def test_story_detail_returns_full_description(jira):
    service, _ = jira
    assert service.issue("SCRUM-1")["description"] == "Original full text"


def test_begin_transition_only_allows_todo_or_in_progress(jira):
    service, client = jira
    client.issues["SCRUM-1"]["fields"]["status"] = {"name": "To Do"}
    assert service.transition_to_in_progress("SCRUM-1")["status"] == "in_progress"
    client.issues["SCRUM-1"]["fields"]["status"] = {"name": "Done"}
    with pytest.raises(JiraIntegrationError, match="Begin is available"):
        service.transition_to_in_progress("SCRUM-1")


def test_repository_mapping_is_allowlisted(jira):
    service, _ = jira
    assert service.set_repository("SCRUM-1", "jaza-sentinel")["repository_path"].endswith("agentic-ai-agent")
    with pytest.raises(JiraIntegrationError) as error:
        service.set_repository("SCRUM-1", "made-up-project")
    assert error.value.code == "repository_not_allowlisted"


def test_codex_prompt_contains_key_summary_and_unmodified_full_description():
    description = "Complete prompt\nwith every line."
    prompt = CodexHandoffService._prompt(
        {"jira_key": "SCRUM-7", "summary": "Precise work", "description": description}
    )
    assert "JIRA WORK ITEM: SCRUM-7" in prompt
    assert "TITLE: Precise work" in prompt
    assert prompt.endswith(description)


def test_existing_codex_thread_uses_supported_resume_command(repository, tmp_path):
    (tmp_path / ".git").mkdir()
    service = CodexHandoffService(repository, executable="/known/codex")
    assert service._command(tmp_path, "thread-123") == [
        "/known/codex", "exec", "resume", "--json", "thread-123", "-"
    ]


def test_codex_invocation_failure_is_explicit(repository):
    service = CodexHandoffService(repository, executable="/definitely/missing/codex")
    project = next(item for item in repository.projects() if item["id"] == "jaza-sentinel")
    with pytest.raises(CodexRuntimeError) as error:
        service.begin(
            {"jira_key": "SCRUM-7", "summary": "Test", "description": "Full"},
            project["repository_path"],
        )
    assert error.value.code == "codex_launch_failed"


def test_five_hour_usage_parses_real_app_server_shape_and_missing_is_unavailable(monkeypatch):
    parsed = CodexUsageService.parse_rate_limits({
        "result": {"rateLimitsByLimitId": {"codex": {"primary": {
            "usedPercent": 62, "windowDurationMins": 300, "resetsAt": 1788726166
        }}}}
    })
    assert parsed["used_percent"] == 62
    assert parsed["remaining_percent"] == 38
    assert parsed["window_minutes"] == 300
    monkeypatch.setattr("jaza_sentinel.codex_runtime.resolve_codex_executable", lambda: "")
    assert CodexUsageService(executable="").current()["message"] == "5h usage unavailable"


class FakeCodingRouteService:
    def board(self):
        return {"stories": []}

    def refresh(self, bootstrap=True):
        return {"stories": [], "bootstrapped": []}

    def create_issue(self, summary, description):
        return {"jira_key": "SCRUM-30", "summary": summary, "description": description}

    def issue(self, key):
        return {"jira_key": key, "summary": "x", "description": "full", "status": "to_do", "local_repository_path": "/tmp"}

    def known_repositories(self):
        return []


class FakeUsage:
    def current(self):
        return {"available": False}


def test_routes_reject_arbitrary_commands_and_preserve_full_description(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "runtime",
        codex_config_path=tmp_path / "missing.toml",
        jira_service=FakeCodingRouteService(),
        codex_usage_service=FakeUsage(),
    )
    app.config["TESTING"] = True
    client = app.test_client()
    rejected = client.post("/api/coding/jira/issues/SCRUM-1/begin", json={"command": "rm -rf /"})
    assert rejected.status_code == 400
    full = "Alpha\n\nBeta"
    created = client.post("/api/coding/jira/issues", json={"title": "T", "description": full})
    assert created.status_code == 201
    assert created.get_json()["item"]["description"] == full


@pytest.fixture
def paladin(tmp_path, monkeypatch):
    root = tmp_path / "paladin"
    root.mkdir()
    (root / "gtkportal2").mkdir()
    (root / "ignored").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "ignored-alias").symlink_to(root / "ignored", target_is_directory=True)
    (root / "plain-file").touch()
    (root / "gtkportal2" / "nested").mkdir()
    ignore = tmp_path / "ignore.json"
    ignore.write_text('{"ignored_folders": ["ignored"]}')
    monkeypatch.setattr("jaza_sentinel.repositories.PALADIN_ROOT", root)
    monkeypatch.setattr("jaza_sentinel.repositories.REPOSITORY_IGNORE_FILE", ignore)
    return root


def fake_launch(monkeypatch, events, exit_code=None):
    import io
    import json
    calls = []

    class Prompt(io.StringIO):
        def close(self):
            self.sent = self.getvalue()
            super().close()

    class Process:
        stdin = Prompt()
        terminated = False

        def poll(self):
            return exit_code

        def terminate(self):
            self.terminated = True

    process = Process()

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        for event in events:
            kwargs["stdout"].write(json.dumps(event) + "\n")
        kwargs["stdout"].flush()
        return process

    monkeypatch.setattr("jaza_sentinel.codex_runtime.subprocess.Popen", popen)
    return calls, process


def test_discovered_repository_shared_by_jira_and_codex(repository, jira, paladin, monkeypatch, tmp_path, caplog):
    service, _ = jira
    assert service.set_repository("SCRUM-1", "gtkportal2")["repository_path"] == str(paladin / "gtkportal2")
    story = service.issue("SCRUM-1")
    calls, process = fake_launch(monkeypatch, [{"type": "thread.started", "thread_id": "real-event-id"}])
    handoff = CodexHandoffService(repository, executable="/known/codex", log_dir=tmp_path / "logs")
    result = handoff.begin(story, story["local_repository_path"])
    assert result["codex_thread_id"] == "real-event-id"
    assert repository.coding_association("SCRUM-1")["execution_state"] == "running"
    assert repository.coding_association("SCRUM-1")["codex_thread_id"] == "real-event-id"
    assert calls[0][0] == ["/known/codex", "exec", "--json", "--sandbox", "workspace-write", "--cd", str(paladin / "gtkportal2"), "--skip-git-repo-check", "-"]
    assert calls[0][1]["cwd"] == paladin / "gtkportal2"
    assert process.stdin.sent == handoff._prompt(story)
    assert 'repository_validation="passed"' in caplog.text
    assert 'launch="confirmed" thread_id="real-event-id"' in caplog.text
    assert story["description"] not in caplog.text
    calls, _ = fake_launch(monkeypatch, [{"type": "thread.started", "thread_id": "real-event-id"}])
    assert handoff.begin(story, story["local_repository_path"])["resumed"] is True
    assert calls[0][0] == ["/known/codex", "exec", "resume", "--json", "--skip-git-repo-check", "real-event-id", "-"]


@pytest.mark.parametrize("folder", ["../outside", "ignored", "escape", "ignored-alias", "plain-file", "gtkportal2/nested", "missing"])
def test_shared_repository_boundary(repository, jira, paladin, monkeypatch, folder, caplog):
    # Even explicitly configured projects cannot bypass the boundary or ignore list.
    monkeypatch.setattr(repository, "projects", lambda: [{"id": "unsafe", "name": "Unsafe", "repository_path": str(paladin / folder)}])
    service, _ = jira
    with pytest.raises(JiraIntegrationError) as error:
        service.set_repository("SCRUM-1", "unsafe")
    assert error.value.code == "repository_not_allowlisted"
    runtime = CodexHandoffService(repository, executable="/known/codex")
    with pytest.raises(CodexRuntimeError) as error:
        runtime.begin({"jira_key": "SCRUM-1"}, str(paladin / folder))
    assert error.value.code == "repository_not_allowlisted"
    assert 'repository_validation="failed"' in caplog.text
    assert 'launch="attempted"' not in caplog.text


@pytest.mark.parametrize("events,exit_code,error_code", [
    ([{"type": "error", "message": "secret must not be logged"}], 1, "codex_launch_failed"),
    ([], 1, "codex_launch_failed"),
    ([], None, "codex_launch_unconfirmed"),
    ([{"type": "thread.started"}], None, "codex_launch_unconfirmed"),
])
def test_no_fake_running_state(repository, paladin, monkeypatch, tmp_path, events, exit_code, error_code, caplog):
    calls, process = fake_launch(monkeypatch, events, exit_code)
    ticks = iter([0, 1, 11])
    monkeypatch.setattr("jaza_sentinel.codex_runtime.monotonic", lambda: next(ticks))
    monkeypatch.setattr("jaza_sentinel.codex_runtime.sleep", lambda _: None)
    runtime = CodexHandoffService(repository, executable="/known/codex", log_dir=tmp_path / "logs")
    with pytest.raises(CodexRuntimeError) as error:
        runtime.begin({"jira_key": "SCRUM-1", "summary": "Test", "description": "Private spec"}, str(paladin / "gtkportal2"))
    assert error.value.code == error_code
    association = repository.coding_association("SCRUM-1")
    assert association["execution_state"] == "failed"
    assert not association.get("codex_thread_id")
    assert 'launch="confirmed"' not in caplog.text
    assert 'launch="failed"' in caplog.text
    assert "secret must not be logged" not in caplog.text
    if error_code == "codex_launch_unconfirmed":
        assert process.terminated


def test_begin_route_keeps_safe_json_error(repository, jira, paladin, tmp_path, caplog):
    service, _ = jira
    app = create_app(data_dir=tmp_path / "app-state", jira_service=service,
                     codex_handoff_service=CodexHandoffService(repository, executable="/missing/codex", log_dir=tmp_path / "logs"))
    response = app.test_client().post("/api/coding/jira/issues/SCRUM-1/begin", json={"local_project_id": "gtkportal2"})
    assert response.status_code == 503
    assert response.get_json() == {"error": "codex_launch_failed", "message": "Codex could not be launched."}
    assert repository.coding_association("SCRUM-1")["execution_state"] == "failed"
    assert 'error_code="codex_launch_failed"' in caplog.text


def test_fresh_git_repository_keeps_original_command(repository, tmp_path):
    (tmp_path / ".git").mkdir()
    runtime = CodexHandoffService(repository, executable="/known/codex")
    assert runtime._command(tmp_path, None) == [
        "/known/codex", "exec", "--json", "--sandbox", "workspace-write", "--cd", str(tmp_path), "-"
    ]


def test_codex_resolution_prefers_current_app_and_falls_back_to_path(monkeypatch, tmp_path):
    from jaza_sentinel.codex_runtime import resolve_codex_executable
    bundled = tmp_path / "codex"
    monkeypatch.setattr("jaza_sentinel.codex_runtime.BUNDLED_CODEX", bundled)
    monkeypatch.setattr("shutil.which", lambda _: "/path/codex")
    assert resolve_codex_executable() == "/path/codex"
    bundled.write_text("test executable")
    bundled.chmod(0o755)
    assert resolve_codex_executable() == str(bundled)
    bundled.chmod(0o644)
    assert resolve_codex_executable() == "/path/codex"
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert resolve_codex_executable() == ""
