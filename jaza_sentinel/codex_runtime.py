"""Supported, allowlisted Codex CLI handoff and structured 5-hour usage reads."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from .storage import JsonStateRepository
from .repositories import known_repositories
from .begin_diagnostics import log_begin


BUNDLED_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")


def resolve_codex_executable() -> str:
    # Use the current app's CLI before a stale standalone installation on PATH.
    if BUNDLED_CODEX.is_file() and os.access(BUNDLED_CODEX, os.X_OK):
        return str(BUNDLED_CODEX)
    return shutil.which("codex") or ""


class CodexRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CodexUsageService:
    """Read official App Server rate-limit state; never infer usage."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or resolve_codex_executable()

    def current(self) -> dict[str, Any]:
        unavailable = {
            "available": False,
            "window_minutes": 300,
            "used_percent": None,
            "remaining_percent": None,
            "resets_at": None,
            "message": "5h usage unavailable",
            "source": "codex_app_server",
        }
        if not self.executable:
            return unavailable
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                [self.executable, "app-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            assert process.stdin is not None
            self._send(
                process,
                {
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "clientInfo": {"name": "jaza_sentinel", "title": "Jaza Sentinel", "version": "0.3"}
                    },
                },
            )
            self._read_response(process, 1)
            self._send(process, {"method": "initialized", "params": {}})
            self._send(process, {"method": "account/rateLimits/read", "id": 2, "params": {}})
            payload = self._read_response(process, 2)
            return self.parse_rate_limits(payload)
        except (OSError, ValueError, TimeoutError, KeyError, TypeError):
            return unavailable
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()

    @staticmethod
    def parse_rate_limits(payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result") or payload
        candidates: list[dict[str, Any]] = []
        by_id = result.get("rateLimitsByLimitId") or {}
        preferred = by_id.get("codex") if isinstance(by_id, dict) else None
        if isinstance(preferred, dict):
            candidates.extend([preferred.get("primary") or {}, preferred.get("secondary") or {}])
        legacy = result.get("rateLimits") or {}
        if isinstance(legacy, dict):
            candidates.extend([legacy.get("primary") or {}, legacy.get("secondary") or {}])
        window = next(
            (item for item in candidates if int(item.get("windowDurationMins") or 0) == 300),
            None,
        )
        if not window or not isinstance(window.get("usedPercent"), (int, float)):
            raise ValueError("No exact five-hour window")
        used = max(0.0, min(100.0, float(window["usedPercent"])))
        reset = window.get("resetsAt")
        reset_iso = datetime.fromtimestamp(float(reset), UTC).isoformat() if reset else None
        return {
            "available": True,
            "window_minutes": 300,
            "used_percent": used,
            "remaining_percent": 100.0 - used,
            "resets_at": reset_iso,
            "message": None,
            "source": "codex_app_server",
        }

    @staticmethod
    def _send(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    @staticmethod
    def _read_response(process: subprocess.Popen[str], request_id: int) -> dict[str, Any]:
        assert process.stdout is not None
        deadline = datetime.now().timestamp() + 8
        while datetime.now().timestamp() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 0.5)
            if not ready:
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                break
            payload = json.loads(line)
            if payload.get("id") == request_id:
                if payload.get("error"):
                    raise ValueError("App Server returned an error")
                return payload
        raise TimeoutError("Codex App Server response timed out")


class CodexHandoffService:
    """Launch exactly `codex exec --json` or its supported resume form."""

    def __init__(
        self,
        repository: JsonStateRepository,
        *,
        executable: str | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.local = repository
        self.executable = executable or resolve_codex_executable()
        self.log_dir = log_dir or Path(__file__).resolve().parents[1] / ".runtime" / "codex-handoffs"

    def begin(self, story: dict[str, Any], repository_path: str) -> dict[str, Any]:
        key = str(story["jira_key"])
        resolved = Path(repository_path).expanduser().resolve()
        allowed = {Path(item["repository_path"]) for item in known_repositories(self.local)}
        valid = resolved in allowed and resolved.is_dir()
        log_begin(
            key, local_project_id=story.get("local_project_id"),
            repository_path=str(resolved),
            repository_validation="passed" if valid else "failed",
            codex_executable=self.executable or "unavailable",
        )
        if not valid:
            log_begin(key, launch="failed", error_code="repository_not_allowlisted")
            raise CodexRuntimeError(
                "repository_not_allowlisted",
                "Choose one of Jaza's known Paladin repositories.",
                status_code=400,
            )
        if not self.executable:
            log_begin(key, launch="failed", error_code="codex_unavailable")
            raise CodexRuntimeError("codex_unavailable", "The supported Codex CLI is unavailable.")
        association = self.local.coding_association(key)
        thread_id = association.get("codex_thread_id")
        prompt = self._prompt(story)
        command = self._command(resolved, str(thread_id) if thread_id else None)
        resumed = bool(thread_id)
        log_path = self.log_dir / f"{key.lower()}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        log_begin(key, launch="attempted")
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=resolved,
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.close()
        except OSError as exc:
            self.local.update_coding_association(key, {"execution_state": "failed"})
            log_begin(key, launch="failed", error_code="codex_launch_failed")
            raise CodexRuntimeError("codex_launch_failed", "Codex could not be launched.") from exc
        launch_thread_id = thread_id
        launch_error: str | None = None
        confirmed = False
        deadline = monotonic() + 10
        while monotonic() < deadline:
            try:
                lines = log_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            for line in lines:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "thread.started":
                    launch_thread_id = event.get("thread_id") or event.get("threadId") or thread_id
                    confirmed = True
                    break
                if event.get("type") in {"error", "turn.failed"}:
                    launch_error = "Codex reported a launch failure."
                    break
            if confirmed or launch_error:
                break
            if process.poll() is not None:
                launch_error = "Codex exited before confirming the handoff."
                break
            sleep(0.1)
        if launch_error:
            log_begin(key, launch="failed", error_code="codex_launch_failed")
            self.local.update_coding_association(key, {"execution_state": "failed"})
            raise CodexRuntimeError("codex_launch_failed", launch_error)
        if not confirmed or not launch_thread_id:
            log_begin(key, launch="failed", error_code="codex_launch_unconfirmed")
            process.terminate()
            self.local.update_coding_association(key, {"execution_state": "failed"})
            raise CodexRuntimeError("codex_launch_unconfirmed", "Codex did not confirm the handoff.")
        thread_id = launch_thread_id
        self.local.update_coding_association(
            key,
            {
                "codex_thread_id": thread_id,
                "execution_state": "running",
                "last_handoff_at": datetime.now(UTC).isoformat(),
                "repository_path": str(resolved),
            },
        )
        log_begin(key, launch="confirmed", thread_id=thread_id)
        return {
            "jira_key": key,
            "execution_state": "running",
            "codex_thread_id": thread_id,
            "resumed": resumed,
        }

    @staticmethod
    def _prompt(story: dict[str, Any]) -> str:
        return (
            f'JIRA WORK ITEM: {story["jira_key"]}\n'
            f'TITLE: {story["summary"]}\n\n'
            "Execute the approved specification below exactly.\n"
            "Preserve all stated constraints and acceptance criteria.\n\n"
            "--- APPROVED SPECIFICATION ---\n"
            f'{story["description"]}'
        )

    def _command(self, repository_path: Path, thread_id: str | None) -> list[str]:
        # Paladin also contains project containers (for example gtkportal2).
        # begin() authorizes the directory before this narrowly scoped CLI opt-in.
        git_options = [] if (repository_path / ".git").exists() else ["--skip-git-repo-check"]
        if thread_id:
            return [self.executable, "exec", "resume", "--json", *git_options, thread_id, "-"]
        return [
            self.executable,
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(repository_path),
            *git_options,
            "-",
        ]
