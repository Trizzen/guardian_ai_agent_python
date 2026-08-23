"""Jaza-specific structured Luna reporting using MenuShield's proven gateway pattern."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field


PROMPT_VERSION = "jaza-reporting-v1"
REPORT_VERSION = "jaza-report-v1"
ALLOWED_DOMAINS = {
    "daily-command",
    "coding-command",
    "fitness-program",
    "nutrition-program",
    "gardening-program",
    "financial-program",
    "budget-program",
    "unclassified",
}


class LunaUnavailableError(RuntimeError):
    def __init__(self, message: str, code: str = "LUNA_UNAVAILABLE") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class LunaClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(max_length=120)
    domain: Literal[
        "daily-command",
        "coding-command",
        "fitness-program",
        "nutrition-program",
        "gardening-program",
        "financial-program",
        "budget-program",
        "unclassified",
    ]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=240)


class LunaStructuredReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=900)
    wins: list[str] = Field(max_length=5)
    patterns: list[str] = Field(max_length=5)
    risks_or_attention: list[str] = Field(max_length=5)
    recommended_next_focus: str = Field(max_length=500)
    questions_for_king_trizzen: list[str] = Field(max_length=4)
    evidence_insufficient: bool
    classification_decisions: list[LunaClassification] = Field(max_length=24)


SYSTEM_PROMPT = """You are Luna, the bounded inference engine inside Jaza Soulminder.

Interpret only the supplied normalized GuardThisKingdom facts, deterministic statistics, transparent attention rules, and explicitly labeled Jaza local planning state. Never invent a goal, completion, failure, minute total, trend, project state, plant condition, or source record. Python has already performed the arithmetic; do not recalculate or contradict it. Distinguish known facts from cautious inference. State when evidence is insufficient. Never imply GuardThisKingdom was modified. Stay within the requested Jaza domain. Do not provide medical diagnosis, investment instructions, account assumptions, or psychological judgments.

You may classify only the supplied ambiguous_facts. Choose only one allowed Jaza domain or unclassified, give a concise evidence-based reason, and use low confidence when the text is not decisive. Classification does not alter source data. Prefer concise, operationally useful reporting. Return only the strict structured object."""


def _shared_values() -> dict[str, str | None]:
    raw = str(os.environ.get("JAZA_SHARED_OPENAI_ENV_FILE", "") or "").strip()
    if not raw:
        return {}
    path = Path(raw).expanduser()
    if path.is_symlink() or not path.is_file():
        return {}
    values = dotenv_values(path)
    return {"OPENAI_API_KEY": values.get("OPENAI_API_KEY"), "OPENAI_MODEL": values.get("OPENAI_MODEL")}


class LunaReportingProvider:
    provider_name = "openai"
    endpoint_name = "responses"

    def __init__(self, *, client_factory=None) -> None:
        shared = _shared_values()
        self._api_key = str(os.environ.get("OPENAI_API_KEY") or shared.get("OPENAI_API_KEY") or "").strip()
        self.model = str(
            os.environ.get("JAZA_LUNA_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or shared.get("OPENAI_MODEL")
            or "gpt-5.6-luna"
        ).strip()
        self.timeout_seconds = max(5, min(300, int(os.environ.get("JAZA_LUNA_TIMEOUT_SECONDS", "90"))))
        self.reasoning_effort = str(os.environ.get("JAZA_LUNA_REASONING_EFFORT", "low")).lower()
        if self.reasoning_effort not in {"none", "low", "medium", "high"}:
            self.reasoning_effort = "low"
        self._client_factory = client_factory

    def status(self) -> dict[str, Any]:
        sdk_available = True
        try:
            import openai  # noqa: F401
        except Exception:
            sdk_available = False
        return {
            "ready": bool(self._api_key and self.model and sdk_available),
            "provider": self.provider_name,
            "model": self.model,
            "message": None if self._api_key and sdk_available else "Luna configuration is unavailable.",
        }

    def _client(self):
        if not self.status()["ready"]:
            raise LunaUnavailableError("Luna is not configured for this local Jaza process.")
        if self._client_factory:
            return self._client_factory(
                api_key=self._api_key,
                timeout=self.timeout_seconds,
                max_retries=0,
            )
        from openai import OpenAI

        return OpenAI(api_key=self._api_key, timeout=self.timeout_seconds, max_retries=0)

    @staticmethod
    def _usage(response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        return {
            name: value
            for name in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance((value := getattr(usage, name, None)), int)
        }

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        started = datetime.now(UTC)
        try:
            response = self._client().responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=True)},
                ],
                text_format=LunaStructuredReport,
                reasoning={"effort": self.reasoning_effort},
                max_output_tokens=4096,
                store=False,
            )
        except LunaUnavailableError:
            raise
        except Exception as exc:
            raise LunaUnavailableError(
                "Luna could not complete this report. Deterministic facts remain available.",
                "LUNA_REQUEST_FAILED",
            ) from exc
        if str(getattr(response, "status", "completed") or "completed") != "completed":
            raise LunaUnavailableError(
                "Luna returned an incomplete report. Deterministic facts remain available.",
                "LUNA_RESPONSE_INCOMPLETE",
            )
        payload = getattr(response, "output_parsed", None)
        if not isinstance(payload, LunaStructuredReport):
            try:
                payload = LunaStructuredReport.model_validate(payload)
            except Exception as exc:
                raise LunaUnavailableError(
                    "Luna returned an invalid report shape. Deterministic facts remain available.",
                    "LUNA_SCHEMA_INVALID",
                ) from exc
        supplied_ids = {str(item.get("source_id")) for item in context.get("ambiguous_facts", [])}
        decisions = [
            item.model_dump()
            for item in payload.classification_decisions
            if item.source_id in supplied_ids and item.domain in ALLOWED_DOMAINS
        ]
        finished = datetime.now(UTC)
        return {
            "report_id": f"report_{uuid4().hex[:16]}",
            "report_version": REPORT_VERSION,
            "prompt_version": PROMPT_VERSION,
            "summary": payload.summary,
            "wins": payload.wins,
            "patterns": payload.patterns,
            "risks_or_attention": payload.risks_or_attention,
            "recommended_next_focus": payload.recommended_next_focus,
            "questions_for_king_trizzen": payload.questions_for_king_trizzen,
            "evidence_insufficient": payload.evidence_insufficient,
            "classification_decisions": decisions,
            "generated_at": finished.isoformat(),
            "provider": self.provider_name,
            "model": str(getattr(response, "model", "") or self.model),
            "grounded": True,
            "source_modified": False,
            "usage": self._usage(response),
            "latency_ms": int((finished - started).total_seconds() * 1000),
        }
