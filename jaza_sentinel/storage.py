"""Small, recovery-safe JSON persistence for Jaza Sentinel."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any


STATE_FILES = ("programs.json", "projects.json", "sentinel.json")


class JsonStateRepository:
    """Owns the three local JSON documents used by the v0.1 control plane."""

    def __init__(self, runtime_dir: Path, defaults_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.defaults_dir = Path(defaults_dir)
        self._lock = RLock()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        for filename in STATE_FILES:
            self._load_document(filename)

    def programs(self) -> list[dict[str, Any]]:
        return self._collection("programs.json", "programs")

    def projects(self) -> list[dict[str, Any]]:
        return self._collection("projects.json", "projects")

    def work_items(self) -> list[dict[str, Any]]:
        return self._collection("sentinel.json", "work_items")

    def notes(self) -> list[dict[str, Any]]:
        return self._collection("sentinel.json", "notes")

    def check_ins(self) -> list[dict[str, Any]]:
        return self._collection("sentinel.json", "check_ins")

    def usage_entries(self) -> list[dict[str, Any]]:
        return self._collection("sentinel.json", "usage_entries")

    def report_feedback(self) -> list[dict[str, Any]]:
        return self._optional_collection("sentinel.json", "report_feedback")

    def coding_associations(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            document = self._load_document("sentinel.json")
            value = document.get("coding_associations", {})
            return deepcopy(value) if isinstance(value, dict) else {}

    def coding_association(self, jira_key: str) -> dict[str, Any]:
        return self.coding_associations().get(jira_key, {})

    def update_coding_association(
        self, jira_key: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            document = self._load_document("sentinel.json")
            associations = document.setdefault("coding_associations", {})
            current = associations.get(jira_key, {})
            current.update(deepcopy(values))
            current["jira_key"] = jira_key
            associations[jira_key] = current
            self._write_document("sentinel.json", document)
            return deepcopy(current)

    def codecrawler_runs(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            document = self._load_document("sentinel.json")
            value = document.get("codecrawler_runs", {})
            return deepcopy(value) if isinstance(value, dict) else {}

    def codecrawler_run(self, local_project_id: str) -> dict[str, Any]:
        return self.codecrawler_runs().get(local_project_id, {})

    def update_codecrawler_run(
        self, local_project_id: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            document = self._load_document("sentinel.json")
            runs = document.setdefault("codecrawler_runs", {})
            current = runs.get(local_project_id, {})
            current.update(deepcopy(values))
            current["local_project_id"] = local_project_id
            runs[local_project_id] = current
            self._write_document("sentinel.json", document)
            return deepcopy(current)

    def link_work_item_to_jira(self, item_id: str, jira_key: str) -> dict[str, Any] | None:
        with self._lock:
            document = self._load_document("sentinel.json")
            for item in document["work_items"]:
                if item.get("id") == item_id:
                    item["jira_key"] = jira_key
                    item["updated_at"] = datetime.now(UTC).isoformat()
                    self._write_document("sentinel.json", document)
                    return deepcopy(item)
        return None

    def create_work_item(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            document = self._load_document("sentinel.json")
            document["work_items"].append(deepcopy(item))
            self._write_document("sentinel.json", document)
        return deepcopy(item)

    def update_work_item(self, item_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            document = self._load_document("sentinel.json")
            for index, current in enumerate(document["work_items"]):
                if current.get("id") == item_id:
                    document["work_items"][index] = deepcopy(item)
                    self._write_document("sentinel.json", document)
                    return deepcopy(item)
        return None

    def update_project(self, project_id: str, project: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            document = self._load_document("projects.json")
            for index, current in enumerate(document["projects"]):
                if current.get("id") == project_id:
                    document["projects"][index] = deepcopy(project)
                    self._write_document("projects.json", document)
                    return deepcopy(project)
        return None

    def append_note(self, note: dict[str, Any]) -> dict[str, Any]:
        return self._append("notes", note)

    def append_check_in(self, check_in: dict[str, Any]) -> dict[str, Any]:
        return self._append("check_ins", check_in)

    def append_usage_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        return self._append("usage_entries", entry)

    def append_report_feedback(self, entry: dict[str, Any]) -> dict[str, Any]:
        return self._append("report_feedback", entry)

    def target_exists(self, target_type: str, target_id: str) -> bool:
        collection = self.programs() if target_type == "program" else self.projects()
        return any(item.get("id") == target_id for item in collection)

    def _append(self, collection_name: str, item: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            document = self._load_document("sentinel.json")
            document.setdefault(collection_name, [])
            document[collection_name].append(deepcopy(item))
            self._write_document("sentinel.json", document)
        return deepcopy(item)

    def _collection(self, filename: str, key: str) -> list[dict[str, Any]]:
        with self._lock:
            document = self._load_document(filename)
            return deepcopy(document[key])

    def _optional_collection(self, filename: str, key: str) -> list[dict[str, Any]]:
        with self._lock:
            document = self._load_document(filename)
            return deepcopy(document.get(key, []))

    def _load_document(self, filename: str) -> dict[str, Any]:
        runtime_path = self.runtime_dir / filename
        try:
            with runtime_path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                raise ValueError("root value must be a JSON object")
            self._validate_document_shape(filename, value)
            return value
        except FileNotFoundError:
            return self._restore_default(filename)
        except (json.JSONDecodeError, OSError, TypeError, ValueError, KeyError):
            self._preserve_corrupt_file(runtime_path)
            return self._restore_default(filename)

    def _restore_default(self, filename: str) -> dict[str, Any]:
        default_path = self.defaults_dir / filename
        with default_path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        self._validate_document_shape(filename, value)
        self._write_document(filename, value)
        return deepcopy(value)

    @staticmethod
    def _validate_document_shape(filename: str, document: dict[str, Any]) -> None:
        expected = {
            "programs.json": ("programs",),
            "projects.json": ("projects",),
            "sentinel.json": ("work_items", "notes", "check_ins", "usage_entries"),
        }[filename]
        for key in expected:
            if not isinstance(document[key], list):
                raise ValueError(f"{filename}.{key} must be a list")

    def _write_document(self, filename: str, document: dict[str, Any]) -> None:
        destination = self.runtime_dir / filename
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.runtime_dir,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, destination)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _preserve_corrupt_file(path: Path) -> None:
        if not path.exists():
            return
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(f"{path.name}.corrupt-{timestamp}")
        try:
            shutil.move(path, backup)
        except OSError:
            pass
