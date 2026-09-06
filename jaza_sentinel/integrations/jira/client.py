"""Minimal authenticated Jira Cloud HTTP client with safe public errors."""

from __future__ import annotations

import os
from typing import Any

import httpx


class JiraIntegrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class JiraClient:
    def __init__(self) -> None:
        self.base_url = os.environ.get("JIRA_BASE_URL", "").strip().rstrip("/")
        self.email = os.environ.get("JIRA_EMAIL", "").strip()
        self.token = os.environ.get("JIRA_API_TOKEN", "").strip()
        self.project_key = os.environ.get("JIRA_PROJECT_KEY", "SCRUM").strip() or "SCRUM"

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.email and self.token)

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, json=json)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise JiraIntegrationError(
                "jira_not_configured",
                "Jira is not configured. Set the existing JIRA environment variables.",
            )
        try:
            with httpx.Client(
                base_url=self.base_url,
                auth=(self.email, self.token),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=30,
            ) as client:
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                if response.status_code == 204 or not response.content:
                    return {}
                value = response.json()
                return value if isinstance(value, dict) else {"value": value}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            message = "Jira rejected the request."
            try:
                body = exc.response.json()
                details = body.get("errorMessages") or list((body.get("errors") or {}).values())
                if details:
                    message = " ".join(str(item) for item in details)[:500]
            except (ValueError, AttributeError):
                pass
            raise JiraIntegrationError("jira_request_failed", message, status_code=status) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise JiraIntegrationError(
                "jira_unavailable", "Jira is currently unavailable."
            ) from exc
