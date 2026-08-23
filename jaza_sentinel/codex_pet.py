"""Narrow, local adapter for selecting Jaza or Star in Codex Desktop."""

from __future__ import annotations

import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path
from threading import RLock
from typing import Literal, cast


PetName = Literal["jaza", "star"]

PET_AVATAR_IDS: dict[PetName, str] = {
    "jaza": "custom:jaza-soulminder",
    "star": "custom:star-reborn",
}
PET_DISPLAY_NAMES: dict[PetName, str] = {
    "jaza": "Jaza Soulminder",
    "star": "Star Reborn",
}

_DESKTOP_HEADER = re.compile(r"^\s*\[desktop\]\s*(?:#.*)?$")
_SECTION_HEADER = re.compile(r"^\s*\[\[?.+?\]\]?\s*(?:#.*)?$")
_AVATAR_KEY = re.compile(r"^\s*selected-avatar-id\s*=")


class CodexPetConfigError(RuntimeError):
    """Safe public error for an unavailable or invalid Codex configuration."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CodexPetController:
    """Read or atomically replace only ``desktop.selected-avatar-id``."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path.expanduser()
        self._lock = RLock()

    def current(self) -> dict[str, object]:
        with self._lock:
            if not self.config_path.exists():
                return self._presence(
                    None,
                    available=False,
                    message="Codex config.toml was not found; pet switching is unavailable.",
                )

            document = self._read_document()
            avatar_id = self._avatar_from_document(document)
            return self._presence(avatar_id, available=True)

    def select(self, pet: str) -> dict[str, object]:
        if pet not in PET_AVATAR_IDS:
            raise CodexPetConfigError(
                "invalid_pet",
                "Pet must be either 'jaza' or 'star'.",
            )

        selected_pet = cast(PetName, pet)
        desired_avatar_id = PET_AVATAR_IDS[selected_pet]

        with self._lock:
            self._require_writable_config()
            original_text = self._read_text()
            self._parse(original_text)
            updated_text = self._replace_avatar_key(original_text, desired_avatar_id)
            updated_document = self._parse(updated_text)
            if self._avatar_from_document(updated_document) != desired_avatar_id:
                raise CodexPetConfigError(
                    "invalid_codex_config",
                    "The Codex pet selection could not be verified before saving.",
                )
            self._atomic_write(updated_text)
            return self._presence(desired_avatar_id, available=True)

    def _read_document(self) -> dict[str, object]:
        return self._parse(self._read_text())

    @staticmethod
    def _avatar_from_document(document: dict[str, object]) -> str | None:
        desktop = document.get("desktop", {})
        if not isinstance(desktop, dict):
            raise CodexPetConfigError(
                "invalid_codex_config",
                "Codex desktop configuration must be a TOML table.",
            )
        avatar_id = desktop.get("selected-avatar-id")
        if avatar_id is not None and not isinstance(avatar_id, str):
            raise CodexPetConfigError(
                "invalid_codex_config",
                "Codex desktop.selected-avatar-id must be a string.",
            )
        return avatar_id

    def _read_text(self) -> str:
        try:
            return self.config_path.read_text(encoding="utf-8")
        except OSError as error:
            raise CodexPetConfigError(
                "codex_config_unavailable",
                "Codex config.toml could not be read.",
            ) from error

    def _parse(self, text: str) -> dict[str, object]:
        try:
            return tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError) as error:
            raise CodexPetConfigError(
                "invalid_codex_config",
                "Codex config.toml is not valid TOML; no changes were made.",
            ) from error

    def _require_writable_config(self) -> None:
        if not self.config_path.exists():
            raise CodexPetConfigError(
                "codex_config_unavailable",
                "Codex config.toml was not found; no changes were made.",
            )
        if not self.config_path.is_file() or self.config_path.is_symlink():
            raise CodexPetConfigError(
                "unsafe_codex_config",
                "Codex config.toml must be a regular, non-symlink file.",
            )
        if not os.access(self.config_path, os.W_OK):
            raise CodexPetConfigError(
                "codex_config_unavailable",
                "Codex config.toml is not writable; no changes were made.",
            )

    def _replace_avatar_key(self, text: str, avatar_id: str) -> str:
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines(keepends=True)
        desktop_start: int | None = None
        desktop_end = len(lines)

        for index, line in enumerate(lines):
            content = line.rstrip("\r\n")
            if _DESKTOP_HEADER.match(content):
                if desktop_start is not None:
                    raise CodexPetConfigError(
                        "invalid_codex_config",
                        "Codex config.toml contains more than one desktop section.",
                    )
                desktop_start = index
                continue
            if desktop_start is not None and _SECTION_HEADER.match(content):
                desktop_end = index
                break

        replacement = f'selected-avatar-id = "{avatar_id}"{newline}'
        if desktop_start is None:
            separator = "" if not text or text.endswith(("\n", "\r")) else newline
            return f"{text}{separator}[desktop]{newline}{replacement}"

        matches = [
            index
            for index in range(desktop_start + 1, desktop_end)
            if _AVATAR_KEY.match(lines[index].rstrip("\r\n"))
        ]
        if len(matches) > 1:
            raise CodexPetConfigError(
                "invalid_codex_config",
                "Codex config.toml contains more than one selected-avatar-id key.",
            )
        if matches:
            index = matches[0]
            indentation = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            line_ending = "\r\n" if lines[index].endswith("\r\n") else newline
            lines[index] = f'{indentation}selected-avatar-id = "{avatar_id}"{line_ending}'
        else:
            lines.insert(desktop_start + 1, replacement)
        return "".join(lines)

    def _atomic_write(self, text: str) -> None:
        mode = stat.S_IMODE(self.config_path.stat().st_mode)
        temp_path: Path | None = None
        try:
            file_descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{self.config_path.name}.",
                suffix=".tmp",
                dir=self.config_path.parent,
            )
            temp_path = Path(temp_name)
            with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, mode)
            os.replace(temp_path, self.config_path)
        except OSError as error:
            raise CodexPetConfigError(
                "codex_config_unavailable",
                "Codex config.toml could not be updated; no other configuration was changed.",
            ) from error
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _presence(
        avatar_id: str | None,
        *,
        available: bool,
        message: str | None = None,
    ) -> dict[str, object]:
        selected_pet = next(
            (pet for pet, configured_id in PET_AVATAR_IDS.items() if configured_id == avatar_id),
            None,
        )
        return {
            "available": available,
            "selected_pet": selected_pet,
            "selected_avatar_id": avatar_id,
            "display_name": PET_DISPLAY_NAMES[selected_pet] if selected_pet else None,
            "message": message,
        }
