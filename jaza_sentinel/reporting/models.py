"""Small domain-owned contracts for GTK evidence and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Classification:
    domain: str = "unclassified"
    confidence: float = 0.0
    reason: str = "No deterministic rule matched."
    rule: str = "unclassified"


@dataclass
class ActivityFact:
    source: str
    source_kind: str
    source_id: str
    occurred_at: str | None
    due_at: str | None
    title: str
    note: str
    category: str
    minutes: int | None
    status: str
    behavior: str
    metadata: dict[str, Any] = field(default_factory=dict)
    classification: Classification = field(default_factory=Classification)

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        # Team identities and raw source internals never leave the backend.
        value["metadata"] = {
            key: item
            for key, item in value["metadata"].items()
            if key not in {"team_sharing", "database_row"}
        }
        return value

