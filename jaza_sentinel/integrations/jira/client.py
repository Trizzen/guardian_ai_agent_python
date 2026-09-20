"""Minimal authenticated Jira Cloud HTTP client with safe public errors."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

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

    def download_attachment(self, attachment_id: str, content_reference: str, *, max_bytes: int) -> bytes:
        """Download only the Jira-issued content URL for one attachment, bounded in memory."""
        expected_path = f"/rest/api/3/attachment/content/{attachment_id}"
        reference = urlsplit(content_reference)
        base = urlsplit(self.base_url)
        allowed_paths = {expected_path, f"/jira{expected_path}"}
        if (
            not attachment_id.isdigit()
            or reference.scheme != base.scheme
            or reference.netloc != base.netloc
            or reference.path.rstrip("/") not in allowed_paths
        ):
            raise JiraIntegrationError("jira_attachment_reference_invalid", "Jira attachment reference is invalid.", status_code=409)
        if not self.configured:
            raise JiraIntegrationError("jira_not_configured", "Jira is not configured. Set the existing JIRA environment variables.")
        try:
            with httpx.Client(base_url=self.base_url, auth=(self.email, self.token), timeout=30) as client:
                with client.stream(
                    "GET", reference.path, params={"redirect": "false"}, headers={"Accept": "application/octet-stream"}
                ) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        raise JiraIntegrationError("jira_attachment_too_large", "Attachment exceeds Sentinel's file-size limit.", status_code=409)
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > max_bytes:
                            raise JiraIntegrationError("jira_attachment_too_large", "Attachment exceeds Sentinel's file-size limit.", status_code=409)
                    return bytes(payload)
        except JiraIntegrationError:
            raise
        except httpx.HTTPStatusError as exc:
            raise JiraIntegrationError("jira_attachment_unavailable", "Jira attachment is missing or inaccessible.", status_code=exc.response.status_code) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise JiraIntegrationError("jira_attachment_unavailable", "Jira attachment is currently unavailable.") from exc

    def upload_attachment(self, issue_key: str, filename: str, content_type: str, payload: bytes) -> list[dict[str, Any]]:
        """Use Jira's documented multipart endpoint; browser paths never enter this boundary."""
        if not self.configured:
            raise JiraIntegrationError("jira_not_configured", "Jira is not configured. Set the existing JIRA environment variables.")
        try:
            with httpx.Client(base_url=self.base_url, auth=(self.email, self.token), timeout=30) as client:
                response = client.post(
                    f"/rest/api/3/issue/{issue_key}/attachments",
                    headers={"Accept": "application/json", "X-Atlassian-Token": "no-check"},
                    files={"file": (filename, payload, content_type or "application/octet-stream")},
                )
                response.raise_for_status()
                value = response.json()
                return value if isinstance(value, list) else []
        except httpx.HTTPStatusError as exc:
            raise JiraIntegrationError("jira_attachment_upload_failed", "Jira rejected the attachment upload.", status_code=exc.response.status_code) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise JiraIntegrationError("jira_attachment_upload_failed", "Jira attachment upload is currently unavailable.") from exc

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
