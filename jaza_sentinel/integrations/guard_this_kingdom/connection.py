"""Fail-closed SQL connection boundary for GuardThisKingdom reads."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


_READ_PREFIX = re.compile(r"^\s*(?:--[^\n]*\n\s*)*(SELECT|WITH)\b", re.IGNORECASE)
_WRITE_TOKEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|EXEC(?:UTE)?|ALTER|CREATE|DROP|TRUNCATE|GRANT|REVOKE|DENY|DBCC)\b",
    re.IGNORECASE,
)


class GtkUnavailableError(RuntimeError):
    """Safe, user-displayable GTK availability failure."""

    def __init__(self, message: str, code: str = "GTK_UNAVAILABLE") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _value_from_pointer(pointer_name: str, keys: tuple[str, ...]) -> str:
    raw_path = str(os.environ.get(pointer_name, "") or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path).expanduser()
    if path.is_symlink() or not path.is_file():
        return ""
    values = dotenv_values(path)
    for key in keys:
        value = str(values.get(key, "") or "").strip()
        if value:
            return value
    return ""


def configured_database_uri() -> str:
    """Resolve GTK's URI without logging or copying its credential value."""

    for name in ("JAZA_GTK_DATABASE_URI", "SQLALCHEMY_DATABASE_URI", "params"):
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return _value_from_pointer(
        "JAZA_GTK_ENV_FILE", ("params", "SQLALCHEMY_DATABASE_URI")
    )


def assert_select_only(statement: str) -> None:
    normalized = str(statement or "")
    if not _READ_PREFIX.search(normalized) or _WRITE_TOKEN.search(normalized):
        raise GtkUnavailableError(
            "Jaza blocked a non-read GuardThisKingdom statement.",
            "GTK_SELECT_ONLY_VIOLATION",
        )


class GtkReadOnlyConnection:
    """SQLAlchemy Core engine with two independent SELECT-only guards."""

    def __init__(self, database_uri: str | None = None) -> None:
        self.database_uri = str(database_uri or configured_database_uri()).strip()
        self._engine: Any | None = None

    @property
    def configured(self) -> bool:
        return bool(self.database_uri)

    def _get_engine(self):
        if not self.database_uri:
            raise GtkUnavailableError(
                "GuardThisKingdom database configuration is unavailable.",
                "GTK_DATABASE_NOT_CONFIGURED",
            )
        if self._engine is not None:
            return self._engine
        try:
            from sqlalchemy import create_engine, event

            engine = create_engine(
                self.database_uri,
                future=True,
                pool_pre_ping=True,
                pool_recycle=900,
            )

            @event.listens_for(engine, "before_cursor_execute")
            def _select_guard(_conn, _cursor, statement, _parameters, _context, _many):
                assert_select_only(statement)

            self._engine = engine
            return engine
        except GtkUnavailableError:
            raise
        except Exception as exc:
            raise GtkUnavailableError(
                "GuardThisKingdom read support could not be initialized.",
                "GTK_DRIVER_UNAVAILABLE",
            ) from exc

    def fetch_all(
        self, statement: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        assert_select_only(statement)
        try:
            from sqlalchemy import text

            with self._get_engine().connect() as connection:
                result = connection.execute(text(statement), parameters or {})
                return [dict(row) for row in result.mappings().all()]
        except GtkUnavailableError:
            raise
        except Exception as exc:
            raise GtkUnavailableError(
                "GuardThisKingdom data is temporarily unavailable.",
                "GTK_QUERY_UNAVAILABLE",
            ) from exc

    def fetch_one(
        self, statement: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        rows = self.fetch_all(statement, parameters)
        return rows[0] if rows else None

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

