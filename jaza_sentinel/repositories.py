"""Shared authority for configured and discovered direct-child Paladin repositories."""

from __future__ import annotations

import json
from pathlib import Path
import re

from .storage import JsonStateRepository

PALADIN_ROOT = Path("/Users/triz/paladin").resolve()
REPOSITORY_IGNORE_FILE = Path(__file__).resolve().parents[1] / "data" / "repository_ignore.json"


def _ignored_repository_folders() -> set[str]:
    try:
        payload = json.loads(REPOSITORY_IGNORE_FILE.read_text(encoding="utf-8"))
        values = payload.get("ignored_folders", [])
        if not isinstance(values, list):
            return set()
        return {str(value) for value in values if isinstance(value, str) and value}
    except (OSError, json.JSONDecodeError, AttributeError):
        return set()


def _repository_id(name: str) -> str:
    return re.sub(r"[ _]+", "-", name.strip().lower())


def known_repositories(repository: JsonStateRepository) -> list[dict[str, str]]:
    repositories: dict[Path, dict[str, str]] = {}
    ignored = _ignored_repository_folders()
    for item in repository.projects():
        repository_path = item.get("repository_path")
        if not repository_path:
            continue
        source = Path(str(repository_path)).expanduser()
        path = source.resolve()
        if path.is_dir() and path.parent == PALADIN_ROOT and source.name not in ignored and path.name not in ignored:
            repositories[path] = {
                "id": str(item["id"]),
                "name": str(item["name"]),
                "repository_path": str(path),
            }

    for child in PALADIN_ROOT.iterdir() if PALADIN_ROOT.is_dir() else ():
        path = child.resolve()
        if child.is_dir() and child.name not in ignored and path.name not in ignored and path.parent == PALADIN_ROOT and path not in repositories:
            repositories[path] = {
                "id": _repository_id(child.name),
                "name": child.name,
                "repository_path": str(path),
            }

    return sorted(repositories.values(), key=lambda item: item["name"].casefold())


def resolve_known_repository(
    repository: JsonStateRepository, local_project_id: object
) -> dict[str, str] | None:
    """Resolve only a Sentinel-owned project ID to its validated repository.

    Callers deliberately receive no path-taking variant of this helper.  The
    browser may name a known project, but it never selects a filesystem target.
    """
    if not isinstance(local_project_id, str) or not local_project_id:
        return None
    return next(
        (item for item in known_repositories(repository) if item["id"] == local_project_id),
        None,
    )
