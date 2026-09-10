"""Narrow, fixed CodeCrawler invocation for Sentinel-managed repositories."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import sys
from threading import Lock
from typing import Any

from .repositories import resolve_known_repository
from .storage import JsonStateRepository


CODECRAWLER_EXECUTABLE = Path("/Users/triz/paladin/tools/codecrawler.py")
CODECRAWLER_OUTPUT_FILENAMES = (
    "CODECRAWLER_TREE.md",
    "CODECRAWLER_SOURCE.md",
    "CODECRAWLER_MANIFEST.json",
)
CODECRAWLER_TIMEOUT_SECONDS = 600

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())


class CodeCrawlerError(RuntimeError):
    """A bounded operational result that is safe to return to the browser."""

    def __init__(self, code: str, message: str, *, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CodeCrawlerService:
    """Run only the approved crawler against a shared-authority repository."""

    def __init__(
        self,
        repository: JsonStateRepository,
        *,
        executable: Path = CODECRAWLER_EXECUTABLE,
        python_executable: str = sys.executable,
        timeout_seconds: int = CODECRAWLER_TIMEOUT_SECONDS,
    ) -> None:
        self.local = repository
        self.executable = Path(executable)
        self.python_executable = python_executable
        self.timeout_seconds = timeout_seconds
        self._locks: dict[str, Lock] = {}
        self._locks_guard = Lock()

    def run(self, local_project_id: object, *, jira_key: str | None = None) -> dict[str, Any]:
        project = resolve_known_repository(self.local, local_project_id)
        if project is None:
            raise CodeCrawlerError(
                "repository_not_allowlisted",
                "Choose one of Jaza's known Paladin repositories.",
                status_code=400,
            )
        project_id = project["id"]
        lock = self._lock_for(project_id)
        if not lock.acquire(blocking=False):
            self._log(project_id, jira_key=jira_key, state="running", result="duplicate_rejected")
            raise CodeCrawlerError(
                "codecrawler_already_running",
                "CodeCrawler is already running for that repository.",
                status_code=409,
            )
        try:
            return self._run(project, jira_key=jira_key)
        finally:
            lock.release()

    def _run(self, project: dict[str, str], *, jira_key: str | None) -> dict[str, Any]:
        project_id = project["id"]
        repository_path = Path(project["repository_path"])
        output_paths = [str(repository_path / "_codecrawler" / name) for name in CODECRAWLER_OUTPUT_FILENAMES]
        started_at = datetime.now(UTC).isoformat()
        base = {
            "repository_name": project["name"],
            "repository_path": str(repository_path),
            "tool_name": "CodeCrawler",
            "jira_key": jira_key,
            "started_at": started_at,
            "completed_at": None,
            "exit_code": None,
            "error_category": None,
            "file_count": None,
            "output_paths": output_paths,
        }
        self.local.update_codecrawler_run(project_id, {**base, "state": "running"})
        self._log(project_id, jira_key=jira_key, repository_path=str(repository_path), state="running")
        if not self.executable.is_file():
            return self._fail(project_id, base, "codecrawler_unavailable", "The approved CodeCrawler executable is unavailable.")
        try:
            completed = subprocess.run(
                [self.python_executable, str(self.executable), str(repository_path)],
                check=False,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return self._fail(project_id, base, "codecrawler_timeout", "CodeCrawler timed out before completing.")
        except OSError:
            return self._fail(project_id, base, "codecrawler_invocation_failed", "CodeCrawler could not be started.")
        if completed.returncode != 0:
            return self._fail(
                project_id,
                base,
                "codecrawler_exit_nonzero",
                "CodeCrawler exited without producing a fresh snapshot.",
                exit_code=completed.returncode,
            )

        file_count = self._manifest_file_count(Path(output_paths[-1]))
        if file_count is None or not all(Path(path).is_file() for path in output_paths):
            return self._fail(
                project_id,
                base,
                "codecrawler_output_invalid",
                "CodeCrawler completed without its expected snapshot artifacts.",
                exit_code=completed.returncode,
            )
        result = self.local.update_codecrawler_run(
            project_id,
            {
                **base,
                "state": "completed",
                "completed_at": datetime.now(UTC).isoformat(),
                "exit_code": completed.returncode,
                "file_count": file_count,
            },
        )
        self._log(project_id, jira_key=jira_key, repository_path=str(repository_path), state="completed", exit_code=completed.returncode)
        return result

    def _fail(
        self,
        project_id: str,
        base: dict[str, Any],
        code: str,
        message: str,
        *,
        exit_code: int | None = None,
    ) -> dict[str, Any]:
        self.local.update_codecrawler_run(
            project_id,
            {
                **base,
                "state": "failed",
                "completed_at": datetime.now(UTC).isoformat(),
                "exit_code": exit_code,
                "error_category": code,
            },
        )
        self._log(
            project_id,
            jira_key=base.get("jira_key"),
            repository_path=base.get("repository_path"),
            state="failed",
            result=code,
            exit_code=exit_code,
        )
        raise CodeCrawlerError(code, message)

    @staticmethod
    def _manifest_file_count(manifest_path: Path) -> int | None:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            file_count = payload.get("file_count")
            return file_count if isinstance(file_count, int) and file_count >= 0 else None
        except (OSError, ValueError, TypeError):
            return None

    def _lock_for(self, local_project_id: str) -> Lock:
        with self._locks_guard:
            return self._locks.setdefault(local_project_id, Lock())

    @staticmethod
    def _log(local_project_id: str, **fields: object) -> None:
        logger.info(
            "CODECRAWLER %s %s",
            json.dumps(local_project_id),
            " ".join(f"{name}={json.dumps(value)}" for name, value in fields.items()),
        )
