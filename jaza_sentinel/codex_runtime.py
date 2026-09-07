"""Supported Codex launch surfaces and structured 5-hour usage reads."""

from __future__ import annotations

import json
import os
import select
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage import JsonStateRepository
from .repositories import known_repositories
from .begin_diagnostics import log_begin


BUNDLED_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
EXECUTION_SURFACES = ("APP", "TERMINAL")
EXECUTION_STATES = (
    "prepared",
    "running",
    "completed",
    "failed",
    "stopped",
    "awaiting_human_review",
)
# The bundled Codex CLI exposes --model and config overrides.  This identifier is
# deliberately specified on every Sentinel launch instead of inheriting a prior
# Desktop/CLI selection.
DEFAULT_EXECUTION_PROFILE = {"model": "gpt-5.6-terra", "reasoning_effort": "high"}


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
    """Prepare only visible, human-controlled Codex launch surfaces.

    This service deliberately never starts ``codex exec``.  APP opens a
    workspace and puts the exact prompt on the clipboard; TERMINAL asks macOS
    Terminal to run an interactive, inline Codex session.  Neither launcher is
    evidence that an agent has started, so both begin as ``prepared``.
    """

    def __init__(
        self,
        repository: JsonStateRepository,
        *,
        executable: str | None = None,
    ) -> None:
        self.local = repository
        self.executable = executable or resolve_codex_executable()

    @staticmethod
    def validate_surface(surface: object) -> str:
        if surface not in EXECUTION_SURFACES:
            raise CodexRuntimeError(
                "invalid_execution_surface",
                "Choose APP (Codex Desktop) or TERMINAL (visible Codex CLI).",
                status_code=400,
            )
        return str(surface)

    @staticmethod
    def execution_profile() -> dict[str, str]:
        return dict(DEFAULT_EXECUTION_PROFILE)

    def begin(self, story: dict[str, Any], repository_path: str, surface: object) -> dict[str, Any]:
        key = str(story["jira_key"])
        selected_surface = self.validate_surface(surface)
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
        prompt = self._prompt(story)
        profile = self.execution_profile()
        timestamp = datetime.now(UTC).isoformat()
        log_begin(
            key,
            surface=selected_surface,
            model=profile["model"],
            reasoning_effort=profile["reasoning_effort"],
            launch="attempted",
        )
        try:
            if selected_surface == "APP":
                self._copy_prompt(prompt)
                self._open_app(resolved)
                activity = "Workspace opened and exact Jira specification prepared for human submission."
            else:
                self._open_terminal(self._terminal_command(resolved, prompt))
                activity = "Visible Terminal launch requested; Codex session identity is not yet known."
        except (OSError, subprocess.CalledProcessError) as exc:
            self.local.update_coding_association(
                key,
                {
                    "execution_surface": selected_surface,
                    "execution_profile": profile,
                    "execution_state": "failed",
                    "execution_last_activity": "Visible launch failed.",
                    "execution_prepared_at": timestamp,
                },
            )
            log_begin(key, launch="failed", error_code="codex_launch_failed")
            raise CodexRuntimeError("codex_launch_failed", "Codex could not be launched.") from exc
        association = self.local.update_coding_association(
            key,
            {
                # Never resume or invent a thread from an earlier model/session.
                "codex_thread_id": None,
                "execution_surface": selected_surface,
                "execution_profile": profile,
                "execution_state": "prepared",
                "execution_prepared_at": timestamp,
                "execution_last_activity": activity,
                "repository_path": str(resolved),
            },
        )
        log_begin(key, surface=selected_surface, state="prepared", launch="prepared")
        return {
            "jira_key": key,
            "execution_surface": selected_surface,
            "execution_profile": profile,
            "execution_state": association["execution_state"],
            "codex_thread_id": None,
            "prepared_at": timestamp,
            "last_activity": activity,
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

    def _terminal_command(self, repository_path: Path, prompt: str) -> list[str]:
        """Build an interactive CLI command; its final argument is the full prompt."""
        return [
            self.executable,
            "--model",
            DEFAULT_EXECUTION_PROFILE["model"],
            "--config",
            'model_reasoning_effort="high"',
            "--no-alt-screen",
            "--cd",
            str(repository_path),
            prompt,
        ]

    def _open_app(self, repository_path: Path) -> None:
        profile = self.execution_profile()
        subprocess.run(
            [
                self.executable,
                "app",
                "--config",
                f'model="{profile["model"]}"',
                "--config",
                f'model_reasoning_effort="{profile["reasoning_effort"]}"',
                str(repository_path),
            ],
            check=True,
        )

    @staticmethod
    def _copy_prompt(prompt: str) -> None:
        subprocess.run(["pbcopy"], input=prompt, text=True, check=True)

    @staticmethod
    def _open_terminal(command: list[str]) -> None:
        # The shell command is quoted as data and passed as an argument to
        # osascript, never interpolated into AppleScript or a shell expression.
        script = shlex.join(command)
        subprocess.run(
            [
                "osascript",
                "-e", "on run argv",
                "-e", 'tell application "Terminal" to activate',
                "-e", 'tell application "Terminal" to do script item 1 of argv',
                "-e", "end run",
                script,
            ],
            check=True,
        )

    def record_execution_status(
        self, jira_key: str, state: str, *, thread_id: str | None = None, activity: str | None = None
    ) -> dict[str, Any]:
        """Persist only a known execution state; completion always awaits review."""
        if state not in EXECUTION_STATES:
            raise ValueError("Unknown execution state")
        recorded_state = "awaiting_human_review" if state == "completed" else state
        values: dict[str, Any] = {
            "execution_state": recorded_state,
            "execution_last_activity": activity or (
                "Agent completion reported; human review is required."
                if state == "completed" else f"Execution state reported as {recorded_state}."
            ),
            "execution_last_activity_at": datetime.now(UTC).isoformat(),
        }
        if thread_id:
            values["codex_thread_id"] = thread_id
        association = self.local.update_coding_association(jira_key, values)
        log_begin(jira_key, state=recorded_state, thread_id=thread_id or "unknown")
        return association

    def record_agent_completed(self, jira_key: str, *, thread_id: str | None = None) -> dict[str, Any]:
        """Record real completion evidence without bypassing required human review."""
        return self.record_execution_status(jira_key, "completed", thread_id=thread_id)
