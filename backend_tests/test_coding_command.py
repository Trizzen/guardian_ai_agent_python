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


def test_existing_codex_thread_uses_supported_resume_command(repository):
    service = CodexHandoffService(repository, executable="/known/codex")
    assert service._command(Path("/allowlisted"), "thread-123") == [
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
    monkeypatch.setattr("shutil.which", lambda _: None)
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
