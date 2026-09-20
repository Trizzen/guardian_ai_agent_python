"""Deterministic Jira synchronization for the Coding Command Sprint 0 board."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from ...storage import JsonStateRepository
from ...repositories import known_repositories, resolve_known_repository
from .client import JiraClient, JiraIntegrationError
from .artifacts import MAX_HANDOFF_ATTACHMENTS


STATUS_MAP = {
    "to do": "to_do",
    "in progress": "in_progress",
    "in review": "in_review",
    "done": "done",
}
STATUS_LABELS = {value: key.title() for key, value in STATUS_MAP.items()}


class JiraCodingService:
    def __init__(self, client: JiraClient, repository: JsonStateRepository) -> None:
        self.client = client
        self.local = repository
        self._context: dict[str, Any] | None = None

    def refresh(self, *, bootstrap: bool = True) -> dict[str, Any]:
        migrated = self.bootstrap_local_items() if bootstrap else []
        board = self.board()
        board["bootstrapped"] = migrated
        return board

    def board(self) -> dict[str, Any]:
        context = self._jira_context()
        sprint = context["sprint"]
        result = self.client.get(
            "/rest/api/3/search/jql",
            params={
                "jql": f'project = {context["project_key"]} AND sprint = {int(sprint["id"])} ORDER BY rank ASC',
                "fields": f'summary,description,status,assignee,priority,issuetype,attachment,{context["sprint_field_id"]}',
                "maxResults": 100,
            },
        )
        stories = [self._story(issue, sprint) for issue in result.get("issues", [])]
        return {
            "available": True,
            "project": {"key": context["project_key"], "name": context["project_name"]},
            "sprint": sprint,
            "statuses": [
                {"id": state, "label": STATUS_LABELS[state]}
                for state in ("to_do", "in_progress", "in_review", "done")
            ],
            "stories": stories,
            "repositories": self.known_repositories(),
            "refreshed_at": datetime.now(UTC).isoformat(),
        }

    def issue(self, key: str) -> dict[str, Any]:
        self._validate_key(key)
        context = self._jira_context()
        issue = self.client.get(
            f"/rest/api/3/issue/{key}",
            params={
                "fields": f'summary,description,status,assignee,priority,issuetype,attachment,{context["sprint_field_id"]}'
            },
        )
        story = self._story(issue, context["sprint"])
        if story["sprint"] != context["sprint"]["name"]:
            raise JiraIntegrationError("outside_sprint", "That issue is not in Sprint 0.", status_code=409)
        return story

    def create_issue(
        self,
        summary: str,
        description: str,
        *,
        local_work_item_id: str | None = None,
        local_project_id: str | None = None,
    ) -> dict[str, Any]:
        summary = str(summary).strip()
        if not summary:
            raise JiraIntegrationError("validation_error", "Title is required.", status_code=400)
        if len(summary) > 255:
            raise JiraIntegrationError("validation_error", "Title must be 255 characters or fewer.", status_code=400)
        if not isinstance(description, str) or not description.strip():
            raise JiraIntegrationError("validation_error", "Description is required.", status_code=400)
        context = self._jira_context()
        fields: dict[str, Any] = {
            "project": {"key": context["project_key"]},
            "summary": summary,
            "description": text_to_adf(description),
            "issuetype": {"id": context["story_type_id"]},
            "assignee": {"accountId": context["account_id"]},
            context["sprint_field_id"]: int(context["sprint"]["id"]),
        }
        if local_work_item_id:
            fields["labels"] = [self._bootstrap_label(local_work_item_id)]
        created = self.client.post("/rest/api/3/issue", json={"fields": fields})
        key = str(created.get("key") or "")
        if not key:
            raise JiraIntegrationError("jira_invalid_response", "Jira did not return an issue key.")
        association: dict[str, Any] = {}
        if local_work_item_id:
            association["local_work_item_id"] = local_work_item_id
        if local_project_id:
            self._validated_project(local_project_id)
            association["local_project_id"] = local_project_id
        if association:
            self.local.update_coding_association(key, association)
        story = self.issue(key)
        if story["status"] != "to_do":
            raise JiraIntegrationError(
                "jira_unexpected_status",
                f"Jira created {key}, but it did not begin in To Do.",
                status_code=409,
            )
        return story

    def transition_to_in_progress(self, key: str) -> dict[str, Any]:
        story = self.issue(key)
        if story["status"] == "in_progress":
            return story
        if story["status"] != "to_do":
            raise JiraIntegrationError(
                "begin_not_allowed",
                "Begin is available only for To Do or In Progress stories.",
                status_code=409,
            )
        transitions = self.client.get(f"/rest/api/3/issue/{key}/transitions")
        transition = next(
            (
                item
                for item in transitions.get("transitions", [])
                if str((item.get("to") or {}).get("name", "")).casefold() == "in progress"
            ),
            None,
        )
        if not transition:
            raise JiraIntegrationError(
                "jira_transition_unavailable", "Jira does not offer an In Progress transition.", status_code=409
            )
        self.client.post(
            f"/rest/api/3/issue/{key}/transitions",
            json={"transition": {"id": str(transition["id"])}},
        )
        return self.issue(key)

    def bootstrap_local_items(self) -> list[dict[str, str]]:
        migrated: list[dict[str, str]] = []
        for item in self.local.work_items():
            if item.get("target_type") != "project" or item.get("status") == "completed":
                continue
            existing_key = item.get("jira_key")
            if existing_key:
                continue
            recovered = self._find_bootstrap_issue(str(item["id"]))
            if recovered:
                key = recovered
            else:
                description = self._local_description(item)
                story = self.create_issue(
                    str(item.get("title") or "Untitled Jaza work item"),
                    description,
                    local_work_item_id=str(item["id"]),
                    local_project_id=str(item.get("target_id")) if item.get("target_id") else None,
                )
                key = story["jira_key"]
            self.local.link_work_item_to_jira(str(item["id"]), key)
            self.local.update_coding_association(
                key,
                {
                    "local_work_item_id": str(item["id"]),
                    "local_project_id": str(item.get("target_id") or ""),
                },
            )
            migrated.append({"local_work_item_id": str(item["id"]), "jira_key": key})
        return migrated

    def set_repository(self, key: str, local_project_id: str) -> dict[str, Any]:
        self._validate_key(key)
        project = self._validated_project(local_project_id)
        return self.local.update_coding_association(
            key,
            {"local_project_id": project["id"], "repository_path": project["repository_path"]},
        )

    def select_attachments(self, key: str, attachment_ids: object) -> dict[str, Any]:
        self._validate_key(key)
        if not isinstance(attachment_ids, list) or any(not isinstance(item, str) or not item.isdigit() for item in attachment_ids):
            raise JiraIntegrationError("validation_error", "Attachment selection must contain Jira attachment IDs only.", status_code=400)
        if len(attachment_ids) > MAX_HANDOFF_ATTACHMENTS or len(set(attachment_ids)) != len(attachment_ids):
            raise JiraIntegrationError("validation_error", "Choose between zero and five distinct Jira attachments.", status_code=400)
        known = {item["attachment_id"] for item in self.attachment_sources(key)}
        if not set(attachment_ids) <= known:
            raise JiraIntegrationError("attachment_not_on_issue", "Choose attachments belonging to this Jira issue only.", status_code=409)
        self.local.update_coding_association(key, {"selected_attachment_ids": list(attachment_ids), "attachment_handoff": {"attachments": [], "ready": False, "message": None}})
        return self.issue(key)

    def attachment_sources(self, key: str) -> list[dict[str, Any]]:
        self._validate_key(key)
        context = self._jira_context()
        issue = self.client.get(f"/rest/api/3/issue/{key}", params={"fields": "attachment"})
        return self._attachment_sources(issue, key)

    def upload_attachment(self, key: str, filename: str, content_type: str, payload: bytes) -> dict[str, Any]:
        self._validate_key(key)
        # Read the issue first: this proves sprint membership and prevents an upload to an arbitrary key.
        self.issue(key)
        sources = self.attachment_sources(key)
        if len(sources) >= MAX_HANDOFF_ATTACHMENTS:
            raise JiraIntegrationError("attachment_limit_reached", "This Jira issue already has Sentinel's maximum of five attachments.", status_code=409)
        candidate = {"attachment_id": "1", "filename": filename, "size": len(payload), "mime_type": content_type, "content_reference": "https://invalid/rest/api/3/attachment/content/1"}
        from .artifacts import JiraArtifactService
        JiraArtifactService._validate_source(candidate)
        self.client.upload_attachment(key, filename, content_type, payload)
        self.local.update_coding_association(key, {"attachment_handoff": {"attachments": [], "ready": False, "message": None}})
        return self.issue(key)

    def known_repositories(self) -> list[dict[str, str]]:
        return known_repositories(self.local)

    def _jira_context(self) -> dict[str, Any]:
        if self._context is not None:
            return self._context
        project_key = self.client.project_key
        project = self.client.get(f"/rest/api/3/project/{project_key}")
        boards = self.client.get(
            "/rest/agile/1.0/board", params={"projectKeyOrId": project_key, "maxResults": 50}
        ).get("values", [])
        sprint_candidates: list[dict[str, Any]] = []
        for board in boards:
            response = self.client.get(
                f'/rest/agile/1.0/board/{int(board["id"])}/sprint',
                params={"state": "active,future,closed", "maxResults": 100},
            )
            for sprint in response.get("values", []):
                name = str(sprint.get("name") or "")
                if name.casefold() == "sprint 0" or name.casefold().endswith(" sprint 0"):
                    sprint_candidates.append(sprint)
        if not sprint_candidates:
            raise JiraIntegrationError("sprint_not_found", "Jira Sprint 0 could not be resolved.")
        state_order = {"active": 0, "future": 1, "closed": 2}
        sprint = sorted(sprint_candidates, key=lambda item: state_order.get(str(item.get("state")), 9))[0]
        fields = self.client.get("/rest/api/3/field")
        field_values = fields.get("value", []) if "value" in fields else fields
        if isinstance(field_values, dict):
            field_values = field_values.get("values", [])
        sprint_field = next((item for item in field_values if item.get("name") == "Sprint"), None)
        if not sprint_field:
            raise JiraIntegrationError("sprint_field_not_found", "Jira Sprint field could not be resolved.")
        myself = self.client.get("/rest/api/3/myself")
        types_response = self.client.get(
            "/rest/api/3/issuetype/project", params={"projectId": str(project["id"]), "level": 0}
        )
        types = types_response.get("value", types_response.get("issueTypes", []))
        story_type = next((item for item in types if str(item.get("name", "")).casefold() == "story"), None)
        if not story_type:
            raise JiraIntegrationError("story_type_not_found", "The Jira project has no Story issue type.")
        self._context = {
            "project_key": project_key,
            "project_name": project.get("name"),
            "sprint": {
                "id": int(sprint["id"]),
                "name": sprint["name"],
                "state": sprint["state"],
                "field_id": sprint_field["id"],
            },
            "sprint_field_id": sprint_field["id"],
            "account_id": myself["accountId"],
            "story_type_id": story_type["id"],
        }
        return self._context

    def _story(self, issue: dict[str, Any], expected_sprint: dict[str, Any]) -> dict[str, Any]:
        fields = issue.get("fields") or {}
        raw_status = str((fields.get("status") or {}).get("name") or "")
        status = STATUS_MAP.get(raw_status.casefold())
        if status is None:
            raise JiraIntegrationError(
                "unsupported_jira_status", f"Jira status '{raw_status}' is outside Coding Command."
            )
        sprint_values = fields.get(expected_sprint["field_id"]) or []
        sprint = next(
            (item for item in sprint_values if int(item.get("id", -1)) == int(expected_sprint["id"])),
            None,
        )
        key = str(issue.get("key") or "")
        association = self.local.coding_association(key)
        attachments = self._attachment_sources(issue, key)
        selected_ids = association.get("selected_attachment_ids")
        if not isinstance(selected_ids, list) or not all(isinstance(item, str) for item in selected_ids):
            selected_ids = [item["attachment_id"] for item in attachments] if len(attachments) <= MAX_HANDOFF_ATTACHMENTS else []
        # A Jira refresh can remove an attachment; do not retain a stale selection by filename or ID.
        selected_ids = [item for item in selected_ids if item in {source["attachment_id"] for source in attachments}]
        project = next(
            (item for item in self.local.projects() if item.get("id") == association.get("local_project_id")),
            None,
        )
        repository_path = association.get("repository_path") or (project or {}).get("repository_path")
        local_project_id = association.get("local_project_id")
        crawl = self.local.codecrawler_run(str(local_project_id or "")) if local_project_id else {}
        if not crawl:
            crawl = {
                "local_project_id": local_project_id,
                "repository_name": (project or {}).get("name"),
                "repository_path": repository_path,
                "tool_name": "CodeCrawler",
                "jira_key": None,
                "state": "not_run",
                "started_at": None,
                "completed_at": None,
                "exit_code": None,
                "error_category": None,
                "file_count": None,
                "output_paths": [],
            }
        return {
            "jira_key": key,
            "summary": str(fields.get("summary") or ""),
            "description": adf_to_text(fields.get("description")),
            "markdown_description": adf_to_markdown(fields.get("description")),
            "status": status,
            "assignee": (fields.get("assignee") or {}).get("displayName"),
            "priority": (fields.get("priority") or {}).get("name"),
            "sprint": sprint.get("name") if sprint else None,
            "issue_type": (fields.get("issuetype") or {}).get("name"),
            "local_project_id": local_project_id,
            "local_repository_path": repository_path,
            "codex_thread_id": association.get("codex_thread_id"),
            "execution_state": association.get("execution_state", "not_started"),
            "execution_surface": association.get("execution_surface"),
            "execution_profile": association.get("execution_profile"),
            "execution_prepared_at": association.get("execution_prepared_at"),
            "execution_last_activity": association.get("execution_last_activity"),
            "execution_last_activity_at": association.get("execution_last_activity_at"),
            "codecrawler": crawl if local_project_id else None,
            "attachments": self._attachment_summary(key, selected_ids, attachments),
        }

    def _attachment_sources(self, issue: dict[str, Any], issue_key: str) -> list[dict[str, Any]]:
        raw = (issue.get("fields") or {}).get("attachment") or []
        if not isinstance(raw, list):
            return []
        output: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("id") or not item.get("filename"):
                continue
            output.append({
                "issue_key": issue_key, "attachment_id": str(item["id"]), "filename": str(item["filename"]),
                "mime_type": item.get("mimeType"), "size": item.get("size"), "created": item.get("created"),
                "author": (item.get("author") or {}).get("displayName"), "content_reference": str(item.get("content") or ""),
            })
        return output

    def _attachment_summary(self, key: str, selected_ids: list[str], sources: list[dict[str, Any]]) -> dict[str, Any]:
        stored = self.local.coding_association(key).get("attachment_handoff", {})
        saved = {str(item.get("attachment_id")): item for item in stored.get("attachments", []) if isinstance(item, dict)} if isinstance(stored, dict) else {}
        rows = []
        for source in sources:
            prior = saved.get(source["attachment_id"], {})
            rows.append({"attachment_id": source["attachment_id"], "filename": source["filename"], "mime_type": source.get("mime_type"), "size": source.get("size"), "author": source.get("author"), "created": source.get("created"), "selected": source["attachment_id"] in selected_ids, "status": prior.get("status", "not_materialized"), "sha256": prior.get("sha256"), "error": prior.get("error")})
        required_selection = len(sources) > MAX_HANDOFF_ATTACHMENTS and not selected_ids
        return {"count": len(sources), "selected_count": len(selected_ids), "limit": MAX_HANDOFF_ATTACHMENTS, "requires_selection": required_selection, "ready": bool(stored.get("ready")) and not required_selection if isinstance(stored, dict) else False, "message": (stored.get("message") if isinstance(stored, dict) else None) or ("Choose up to five attachments before beginning." if required_selection else None), "attachments": rows}

    def _find_bootstrap_issue(self, item_id: str) -> str | None:
        context = self._jira_context()
        label = self._bootstrap_label(item_id)
        result = self.client.get(
            "/rest/api/3/search/jql",
            params={
                "jql": f'project = {context["project_key"]} AND labels = "{label}"',
                "fields": "key",
                "maxResults": 2,
            },
        )
        issues = result.get("issues", [])
        return str(issues[0]["key"]) if issues else None

    def _validated_project(self, project_id: str) -> dict[str, Any]:
        project = resolve_known_repository(self.local, project_id)
        if not project:
            raise JiraIntegrationError(
                "repository_not_allowlisted",
                "Choose one of Jaza's known Paladin repositories.",
                status_code=400,
            )
        return project

    @staticmethod
    def _validate_key(key: str) -> None:
        if not key.startswith("SCRUM-") or not key[6:].isdigit():
            raise JiraIntegrationError("invalid_jira_key", "A valid SCRUM Jira key is required.", status_code=400)

    @staticmethod
    def _bootstrap_label(item_id: str) -> str:
        return f"jaza-bootstrap-{item_id}"[:255]

    @staticmethod
    def _local_description(item: dict[str, Any]) -> str:
        sections = [str(item.get("description") or "").strip()]
        if item.get("next_action"):
            sections.append(f'Next action:\n{str(item["next_action"]).strip()}')
        if item.get("notes"):
            sections.append(f'Notes:\n{str(item["notes"]).strip()}')
        return "\n\n".join(section for section in sections if section) or "Migrated from Jaza Planning State."


def text_to_adf(value: str) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    lines = value.split("\n")
    for index, line in enumerate(lines):
        if index:
            content.append({"type": "hardBreak"})
        if line:
            content.append({"type": "text", "text": line})
    return {"version": 1, "type": "doc", "content": [{"type": "paragraph", "content": content}]}


def adf_to_text(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "")
    node_type = value.get("type")
    if node_type == "text":
        return str(value.get("text") or "")
    if node_type == "hardBreak":
        return "\n"
    children = [adf_to_text(item) for item in value.get("content", []) if isinstance(item, dict)]
    separator = "\n" if node_type in {"doc", "bulletList", "orderedList", "listItem"} else ""
    return separator.join(part for part in children if part != "").strip() if node_type == "doc" else separator.join(children)


def adf_to_markdown(value: Any) -> str:
    """Convert the Jira ADF structures used by Sentinel stories to Markdown.

    This is intentionally deterministic and presentation-preserving: it does
    not call a model, summarize, or attempt to interpret the specification.
    """
    if not isinstance(value, dict):
        return str(value or "")
    if value.get("type") == "doc":
        return "\n\n".join(
            block for block in (_adf_markdown_block(node) for node in value.get("content", [])) if block
        )
    return _adf_markdown_block(value)


def _adf_markdown_block(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "paragraph":
        return _adf_markdown_inline(node.get("content", []))
    if node_type == "heading":
        level = int((node.get("attrs") or {}).get("level") or 1)
        return f"{'#' * max(1, min(level, 6))} {_adf_markdown_inline(node.get('content', []))}"
    if node_type == "codeBlock":
        language = str((node.get("attrs") or {}).get("language") or "")
        return f"```{language}\n{_adf_plain_text(node.get('content', [])).rstrip()}\n```"
    if node_type == "blockquote":
        content = "\n\n".join(
            block for block in (_adf_markdown_block(child) for child in node.get("content", [])) if block
        )
        return "\n".join(f"> {line}" if line else ">" for line in content.splitlines())
    if node_type == "rule":
        return "---"
    if node_type == "bulletList":
        return _adf_markdown_list(node, ordered=False)
    if node_type == "orderedList":
        return _adf_markdown_list(node, ordered=True)
    if node_type == "taskList":
        return _adf_markdown_list(node, task=True)
    return "\n\n".join(
        block for block in (_adf_markdown_block(child) for child in node.get("content", [])) if block
    )


def _adf_markdown_list(node: dict[str, Any], *, ordered: bool = False, task: bool = False, depth: int = 0) -> str:
    rows: list[str] = []
    for index, item in enumerate(node.get("content", []), start=1):
        if not isinstance(item, dict):
            continue
        children = [child for child in item.get("content", []) if isinstance(child, dict)]
        first = children.pop(0) if children else None
        text = _adf_markdown_block(first) if first else ""
        marker = f"{index}." if ordered else "-"
        if task:
            state = str((item.get("attrs") or {}).get("state") or "").casefold()
            marker = "- [x]" if state in {"done", "complete", "completed"} else "- [ ]"
        prefix = "  " * depth + marker
        rows.append(f"{prefix} {text}".rstrip())
        for child in children:
            child_type = child.get("type")
            if child_type == "bulletList":
                rows.append(_adf_markdown_list(child, depth=depth + 1))
            elif child_type == "orderedList":
                rows.append(_adf_markdown_list(child, ordered=True, depth=depth + 1))
            elif child_type == "taskList":
                rows.append(_adf_markdown_list(child, task=True, depth=depth + 1))
            else:
                detail = _adf_markdown_block(child)
                if detail:
                    rows.append("  " * (depth + 1) + detail.replace("\n", "\n" + "  " * (depth + 1)))
    return "\n".join(row for row in rows if row)


def _adf_markdown_inline(nodes: Any) -> str:
    if not isinstance(nodes, list):
        return ""
    output: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if node_type == "hardBreak":
            output.append("\n")
            continue
        if node_type == "text":
            text = str(node.get("text") or "")
            for mark in node.get("marks", []):
                if not isinstance(mark, dict):
                    continue
                mark_type = mark.get("type")
                if mark_type == "strong":
                    text = f"**{text}**"
                elif mark_type == "em":
                    text = f"_{text}_"
                elif mark_type == "strike":
                    text = f"~~{text}~~"
                elif mark_type == "code":
                    text = f"`{text}`"
                elif mark_type == "link":
                    href = str((mark.get("attrs") or {}).get("href") or "")
                    text = f"[{text}]({href})" if href else text
            output.append(text)
            continue
        if node_type == "mention":
            output.append(str((node.get("attrs") or {}).get("text") or ""))
            continue
        output.append(_adf_markdown_inline(node.get("content", [])))
    return "".join(output)


def _adf_plain_text(nodes: Any) -> str:
    if not isinstance(nodes, list):
        return ""
    return "".join(
        str(node.get("text") or "") if isinstance(node, dict) and node.get("type") == "text"
        else "\n" if isinstance(node, dict) and node.get("type") == "hardBreak"
        else _adf_plain_text(node.get("content", [])) if isinstance(node, dict)
        else ""
        for node in nodes
    )
