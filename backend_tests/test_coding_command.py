from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from jaza_sentinel import create_app
from jaza_sentinel.codex_runtime import (
    EXECUTION_STATES,
    CodexHandoffService,
    CodexRuntimeError,
    CodexUsageService,
)
from jaza_sentinel.codecrawler import CodeCrawlerError, CodeCrawlerService
from jaza_sentinel.integrations.jira import JiraCodingService, JiraIntegrationError
from jaza_sentinel.integrations.jira.artifacts import JiraArtifactService
from jaza_sentinel.integrations.jira.service import adf_to_markdown, adf_to_text, text_to_adf
from jaza_sentinel.storage import JsonStateRepository


class FakeJiraClient:
    project_key = "SCRUM"

    def __init__(self) -> None:
        self.created = 0
        self.attachment_bytes: dict[str, bytes] = {}
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
                "attachment": [],
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

    def download_attachment(self, attachment_id: str, content_reference: str, *, max_bytes: int) -> bytes:
        assert content_reference.endswith(f"/attachment/content/{attachment_id}")
        payload = self.attachment_bytes[attachment_id]
        assert len(payload) <= max_bytes
        return payload

    def upload_attachment(self, issue_key: str, filename: str, content_type: str, payload: bytes):
        attachment_id = str(1000 + len(self.attachment_bytes))
        self.attachment_bytes[attachment_id] = payload
        self.issues[issue_key]["fields"]["attachment"].append({
            "id": attachment_id, "filename": filename, "mimeType": content_type,
            "size": len(payload), "content": f"https://jira.example/rest/api/3/attachment/content/{attachment_id}",
        })
        return [self.issues[issue_key]["fields"]["attachment"][-1]]

    def add_attachment(self, issue_key: str, attachment_id: str, filename: str, payload: bytes, mime_type="text/plain"):
        self.attachment_bytes[attachment_id] = payload
        self.issues[issue_key]["fields"]["attachment"].append({
            "id": attachment_id, "filename": filename, "mimeType": mime_type, "size": len(payload),
            "created": "2026-09-10T12:00:00.000+0000", "author": {"displayName": "King Trizzen"},
            "content": f"https://jira.example/rest/api/3/attachment/content/{attachment_id}",
        })


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


def test_attachment_metadata_uses_jira_ids_and_requires_selection_above_five(jira):
    service, client = jira
    for number in range(6):
        client.add_attachment("SCRUM-1", str(100 + number), "same-name.md", f"row-{number}".encode())
    story = service.issue("SCRUM-1")
    assert story["attachments"]["count"] == 6
    assert story["attachments"]["requires_selection"] is True
    assert {item["attachment_id"] for item in story["attachments"]["attachments"]} == {str(100 + number) for number in range(6)}
    selected = service.select_attachments("SCRUM-1", ["100", "101"])
    assert selected["attachments"]["selected_count"] == 2
    with pytest.raises(JiraIntegrationError) as rejected:
        service.select_attachments("SCRUM-1", ["999"])
    assert rejected.value.code == "attachment_not_on_issue"


def test_artifacts_are_ticket_scoped_hashed_and_never_reused_by_filename(jira, repository):
    service, client = jira
    client.add_attachment("SCRUM-1", "101", "../../architecture.md", b"first")
    client.add_attachment("SCRUM-1", "102", "architecture.md", b"second")
    artifacts = JiraArtifactService(client, repository)
    result = artifacts.materialize("SCRUM-1", service.attachment_sources("SCRUM-1"))
    assert result["ready"] is True
    first, second = result["attachments"]
    assert first["local_path"] != second["local_path"]
    assert Path(first["local_path"]).parent.name == "SCRUM-1"
    assert Path(first["local_path"]).read_bytes() == b"first"
    assert first["sha256"] == __import__("hashlib").sha256(b"first").hexdigest()
    assert ".." not in Path(first["local_path"]).name
    client.issues["SCRUM-1"]["fields"]["attachment"] = [client.issues["SCRUM-1"]["fields"]["attachment"][1]]
    fresh = artifacts.materialize("SCRUM-1", service.attachment_sources("SCRUM-1"))
    assert fresh["attachments"][0]["attachment_id"] == "102"
    assert Path(fresh["attachments"][0]["local_path"]).read_bytes() == b"second"
    cross_ticket = artifacts.materialize("SCRUM-2", service.attachment_sources("SCRUM-1"))
    assert cross_ticket["ready"] is False
    assert cross_ticket["attachments"][0]["error"] == "attachment_not_on_issue"
    assert not (artifacts.root / "SCRUM-2" / "102--architecture.md").exists()


def test_failed_attachment_blocks_begin_without_transition_or_codex(repository, jira, paladin, tmp_path):
    service, client = jira
    client.add_attachment("SCRUM-1", "101", "unsafe.zip", b"zip")
    app = create_app(
        data_dir=tmp_path / "app-state", jira_service=service, codex_usage_service=FakeUsage(),
        codex_handoff_service=FakeVisibleHandoff(), jira_artifact_service=JiraArtifactService(client, repository),
    )
    app.config["TESTING"] = True
    response = app.test_client().post("/api/coding/jira/issues/SCRUM-1/begin", json={"local_project_id": "gtkportal2", "surface": "APP"})
    assert response.status_code == 409
    assert response.get_json()["error"] == "artifact_not_ready"
    assert client.issues["SCRUM-1"]["fields"]["status"]["name"] == "In Progress"


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
    assert service.issue("SCRUM-1")["codecrawler"]["state"] == "not_run"
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


def test_codex_prompt_preserves_markdown_and_trusted_artifact_manifest():
    prompt = CodexHandoffService._prompt({
        "jira_key": "SCRUM-7", "summary": "Precise work", "description": "flat", "markdown_description": "## Exact\n\n- `diagram.png`",
        "attachment_manifest": "## Jira Attachments\n\n- `diagram.png` — local artifact: `/runtime/SCRUM-7/101--diagram.png` — SHA-256: `abc`",
    })
    assert "## Exact\n\n- `diagram.png`" in prompt
    assert "Jira Attachments" in prompt
    assert "/runtime/SCRUM-7/101--diagram.png" in prompt


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


def fake_codecrawler_run(monkeypatch, expected_command: list[str], repository_path: Path, *, exit_code: int = 0):
    """Fake only the approved crawler process; no tool, shell, or model runs."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert command == expected_command
        assert kwargs["shell"] is False
        output = repository_path / "_codecrawler"
        output.mkdir(exist_ok=True)
        for name in ("CODECRAWLER_TREE.md", "CODECRAWLER_SOURCE.md"):
            (output / name).write_text(name, encoding="utf-8")
        (output / "CODECRAWLER_MANIFEST.json").write_text(
            json.dumps({"file_count": 7}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, exit_code)

    monkeypatch.setattr("jaza_sentinel.codecrawler.subprocess.run", run)
    return calls


class FakeVisibleHandoff:
    """Route fake: prove Begin validation without opening an app or CLI."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str, str]] = []

    def validate_surface(self, surface: object) -> str:
        return CodexHandoffService.validate_surface(surface)

    def begin(self, story: dict[str, Any], repository_path: str, surface: str) -> dict[str, Any]:
        self.calls.append((story, repository_path, surface))
        return {"execution_state": "prepared", "execution_surface": surface, "codex_thread_id": None}


def test_routes_reject_arbitrary_commands_and_preserve_full_description(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "runtime",
        codex_config_path=tmp_path / "missing.toml",
        jira_service=FakeCodingRouteService(),
        codex_usage_service=FakeUsage(),
    )
    app.config["TESTING"] = True
    client = app.test_client()
    for unsafe in ({"command": "rm -rf /"}, {"repository_path": "/tmp"}, {"pid": 42}):
        rejected = client.post("/api/coding/jira/issues/SCRUM-1/begin", json=unsafe)
        assert rejected.status_code == 400
    invalid_surface = client.post("/api/coding/jira/issues/SCRUM-1/begin", json={"surface": "BACKGROUND"})
    assert invalid_surface.status_code == 400
    full = "Alpha\n\nBeta"
    created = client.post("/api/coding/jira/issues", json={"title": "T", "description": full})
    assert created.status_code == 201
    assert created.get_json()["item"]["description"] == full


def test_codecrawler_route_runs_only_the_approved_tool_for_the_allowlisted_repository(
    repository, jira, paladin, tmp_path, monkeypatch
):
    service, client = jira
    client.issues["SCRUM-2"] = client._issue(
        "SCRUM-2", "Reconnaissance", "To Do", "Full Jira specification", True
    )
    executable = tmp_path / "codecrawler.py"
    executable.write_text("# fixed test executable\n", encoding="utf-8")
    target = paladin / "gtkportal2"
    crawler = CodeCrawlerService(repository, executable=executable)
    calls = fake_codecrawler_run(
        monkeypatch, [sys.executable, str(executable), str(target)], target
    )
    app = create_app(
        data_dir=tmp_path / "app-state",
        jira_service=service,
        codex_usage_service=FakeUsage(),
        codecrawler_service=crawler,
    )
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/api/coding/jira/issues/SCRUM-2/codecrawler", json={"local_project_id": "gtkportal2"}
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert calls and payload["crawl"]["state"] == "completed"
    assert payload["crawl"]["file_count"] == 7
    assert payload["item"]["codecrawler"]["state"] == "completed"
    assert payload["item"]["codecrawler"]["output_paths"] == [
        str(target / "_codecrawler" / name)
        for name in ("CODECRAWLER_TREE.md", "CODECRAWLER_SOURCE.md", "CODECRAWLER_MANIFEST.json")
    ]


def test_codecrawler_rejects_unknown_payloads_and_shared_authority_escapes(repository, jira, paladin, tmp_path):
    service, _ = jira
    executable = tmp_path / "codecrawler.py"
    executable.write_text("# fixed test executable\n", encoding="utf-8")
    crawler = CodeCrawlerService(repository, executable=executable)
    app = create_app(
        data_dir=tmp_path / "app-state",
        jira_service=service,
        codex_usage_service=FakeUsage(),
        codecrawler_service=crawler,
    )
    app.config["TESTING"] = True
    client = app.test_client()
    for unsafe in (
        {"command": "rm -rf /"},
        {"local_project_id": "gtkportal2", "repository_path": "/tmp"},
        {"local_project_id": "gtkportal2", "tool": "other"},
    ):
        assert client.post("/api/coding/jira/issues/SCRUM-1/codecrawler", json=unsafe).status_code == 400
    rejected = client.post(
        "/api/coding/jira/issues/SCRUM-1/codecrawler", json={"local_project_id": "escape"}
    )
    assert rejected.status_code == 400
    with pytest.raises(CodeCrawlerError) as error:
        crawler.run("ignored")
    assert error.value.code == "repository_not_allowlisted"


def test_codecrawler_serializes_duplicate_runs_and_records_bounded_failure(repository, paladin, tmp_path, monkeypatch):
    executable = tmp_path / "codecrawler.py"
    executable.write_text("# fixed test executable\n", encoding="utf-8")
    target = paladin / "gtkportal2"
    crawler = CodeCrawlerService(repository, executable=executable)
    lock = crawler._lock_for("gtkportal2")
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(CodeCrawlerError) as duplicate:
            crawler.run("gtkportal2")
        assert duplicate.value.code == "codecrawler_already_running"
    finally:
        lock.release()

    fake_codecrawler_run(monkeypatch, [sys.executable, str(executable), str(target)], target, exit_code=9)
    with pytest.raises(CodeCrawlerError) as failure:
        crawler.run("gtkportal2", jira_key="SCRUM-1")
    assert failure.value.code == "codecrawler_exit_nonzero"
    persisted = repository.codecrawler_run("gtkportal2")
    assert persisted["state"] == "failed"
    assert persisted["exit_code"] == 9
    assert persisted["error_category"] == "codecrawler_exit_nonzero"


def test_jira_adf_markdown_preserves_structure_without_summarizing_or_truncating():
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Constraints"}]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Keep every detail"}]}]},
            ]},
            {"type": "taskList", "content": [
                {"type": "taskItem", "attrs": {"state": "DONE"}, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Verify output"}]}]},
            ]},
            {"type": "codeBlock", "attrs": {"language": "python"}, "content": [{"type": "text", "text": "print('exact')"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Final unabridged sentence."}]},
        ],
    }
    markdown = adf_to_markdown(adf)
    assert markdown == (
        "## Constraints\n\n- Keep every detail\n\n- [x] Verify output\n\n"
        "```python\nprint('exact')\n```\n\nFinal unabridged sentence."
    )


def test_begin_route_accepts_discovered_gtkportal2_for_app(repository, jira, paladin, tmp_path):
    """SCRUM-16 must validate the browser ID through SCRUM-14 shared authority."""
    service, jira_client = jira
    jira_client.issues["SCRUM-2"] = jira_client._issue(
        "SCRUM-2", "GTK Garden Pro Analysis", "To Do", "Exact full specification", True
    )
    handoff = FakeVisibleHandoff()
    app = create_app(
        data_dir=tmp_path / "app-state",
        jira_service=service,
        codex_handoff_service=handoff,  # type: ignore[arg-type]
        codex_usage_service=FakeUsage(),
    )
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/api/coding/jira/issues/SCRUM-2/begin",
        json={"local_project_id": "gtkportal2", "surface": "APP"},
    )

    assert response.status_code == 200
    assert response.get_json()["item"]["local_project_id"] == "gtkportal2"
    assert handoff.calls[0][1] == str(paladin / "gtkportal2")
    assert handoff.calls[0][2] == "APP"


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


def fake_visible_launch(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return None

    monkeypatch.setattr("jaza_sentinel.codex_runtime.subprocess.run", run)
    return calls


def test_terminal_is_visible_interactive_and_preserves_full_spec(repository, jira, paladin, monkeypatch, caplog):
    service, _ = jira
    assert service.set_repository("SCRUM-1", "gtkportal2")["repository_path"] == str(paladin / "gtkportal2")
    story = service.issue("SCRUM-1")
    calls = fake_visible_launch(monkeypatch)
    handoff = CodexHandoffService(repository, executable="/known/codex")
    result = handoff.begin(story, story["local_repository_path"], "TERMINAL")
    terminal_command = calls[0][0]
    assert terminal_command[:2] == ["osascript", "-e"]
    shell_command = terminal_command[-1]
    assert " exec" not in shell_command
    assert "--no-alt-screen" in shell_command
    assert "--model gpt-5.6-terra" in shell_command
    assert 'model_reasoning_effort="high"' in shell_command
    assert handoff._prompt(story) in shell_command
    assert result["execution_state"] == "prepared"
    assert result["codex_thread_id"] is None
    association = repository.coding_association("SCRUM-1")
    assert association["execution_surface"] == "TERMINAL"
    assert association["execution_profile"] == {"model": "gpt-5.6-terra", "reasoning_effort": "high"}
    assert association["execution_state"] == "prepared"
    assert 'repository_validation="passed"' in caplog.text
    assert 'surface="TERMINAL" state="prepared"' in caplog.text
    assert story["description"] not in caplog.text


def test_app_opens_workspace_prepares_clipboard_and_never_executes(repository, jira, paladin, monkeypatch):
    service, _ = jira
    service.set_repository("SCRUM-1", "gtkportal2")
    story = service.issue("SCRUM-1")
    calls = fake_visible_launch(monkeypatch)
    handoff = CodexHandoffService(repository, executable="/known/codex")
    result = handoff.begin(story, story["local_repository_path"], "APP")
    assert calls[0][0] == ["pbcopy"]
    assert calls[0][1]["input"] == handoff._prompt(story)
    assert calls[1][0] == [
        "/known/codex", "app", "--config", 'model="gpt-5.6-terra"', "--config",
        'model_reasoning_effort="high"', str(paladin / "gtkportal2"),
    ]
    assert all("exec" not in command for command, _ in calls)
    assert result["execution_state"] == "prepared"
    assert result["codex_thread_id"] is None


def test_previous_astra_association_cannot_change_new_terra_launch(repository, jira, paladin, monkeypatch):
    service, _ = jira
    service.set_repository("SCRUM-1", "gtkportal2")
    repository.update_coding_association("SCRUM-1", {
        "codex_thread_id": "astra-thread", "execution_profile": {"model": "gpt-6-astra", "reasoning_effort": "max"},
    })
    story = service.issue("SCRUM-1")
    calls = fake_visible_launch(monkeypatch)
    CodexHandoffService(repository, executable="/known/codex").begin(story, story["local_repository_path"], "TERMINAL")
    assert "astra-thread" not in calls[0][0][-1]
    assert "gpt-6-astra" not in calls[0][0][-1]
    association = repository.coding_association("SCRUM-1")
    assert association["codex_thread_id"] is None
    assert association["execution_profile"]["model"] == "gpt-5.6-terra"


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
        runtime.begin({"jira_key": "SCRUM-1"}, str(paladin / folder), "APP")
    assert error.value.code == "repository_not_allowlisted"
    assert 'repository_validation="failed"' in caplog.text
    assert 'launch="attempted"' not in caplog.text


def test_no_fake_running_or_completed_state_and_completion_requires_human_review(repository, jira, paladin, monkeypatch):
    assert {"prepared", "running", "completed", "failed", "stopped", "awaiting_human_review"} <= set(EXECUTION_STATES)
    service, _ = jira
    service.set_repository("SCRUM-1", "gtkportal2")
    story = service.issue("SCRUM-1")
    fake_visible_launch(monkeypatch)
    runtime = CodexHandoffService(repository, executable="/known/codex")
    result = runtime.begin(story, story["local_repository_path"], "TERMINAL")
    assert result["execution_state"] == "prepared"
    association = runtime.record_agent_completed("SCRUM-1", thread_id="real-observed-id")
    assert association["execution_state"] == "awaiting_human_review"
    assert association["codex_thread_id"] == "real-observed-id"


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
