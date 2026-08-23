"""Flask API for the local Jaza Sentinel command center."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from .codex_pet import CodexPetConfigError, CodexPetController
from .reporting import ReportingService
from .reporting.service import ReportingInputError
from .storage import JsonStateRepository
from .validation import (
    RequestValidationError,
    validate_context_entry,
    validate_project_patch,
    validate_usage_entry,
    validate_work_item,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_app(
    *,
    data_dir: Path | None = None,
    codex_config_path: Path | None = None,
    reporting_service: ReportingService | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["JAZA_DATA_DIR"] = str(data_dir or PROJECT_ROOT / "data" / "runtime")
    app.config["JAZA_CODEX_CONFIG_PATH"] = str(
        codex_config_path
        or Path(os.environ.get("JAZA_CODEX_CONFIG_PATH", Path.home() / ".codex" / "config.toml"))
    )
    repository = JsonStateRepository(
        Path(app.config["JAZA_DATA_DIR"]), PROJECT_ROOT / "data" / "defaults"
    )
    pet_controller = CodexPetController(Path(app.config["JAZA_CODEX_CONFIG_PATH"]))
    reports = reporting_service or ReportingService(repository)
    app.extensions["jaza_repository"] = repository
    app.extensions["jaza_pet_controller"] = pet_controller
    app.extensions["jaza_reporting_service"] = reports

    @app.errorhandler(RequestValidationError)
    def handle_validation_error(error: RequestValidationError):
        return jsonify({"error": "validation_error", "fields": error.errors}), 400

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "jaza-sentinel", "version": "0.2.0"})

    @app.get("/api/sentinel/dashboard")
    def dashboard():
        return jsonify(_dashboard(repository))

    @app.get("/api/sentinel/pet-presence")
    def pet_presence():
        try:
            return jsonify(pet_controller.current())
        except CodexPetConfigError as error:
            return jsonify(
                {
                    "available": False,
                    "selected_pet": None,
                    "selected_avatar_id": None,
                    "display_name": None,
                    "message": error.message,
                }
            )

    @app.post("/api/sentinel/pet-presence")
    def select_pet_presence():
        payload = request.get_json(silent=True)
        pet = payload.get("pet") if isinstance(payload, dict) else None
        if pet not in {"jaza", "star"}:
            return jsonify(
                {
                    "error": "validation_error",
                    "fields": {"pet": "must be either 'jaza' or 'star'"},
                }
            ), 400
        try:
            return jsonify(pet_controller.select(pet))
        except CodexPetConfigError as error:
            return jsonify({"error": error.code, "message": error.message}), 503

    @app.get("/api/programs")
    def programs():
        return jsonify({"items": repository.programs()})

    @app.get("/api/projects")
    def projects():
        return jsonify({"items": repository.projects()})

    @app.patch("/api/projects/<project_id>")
    def patch_project(project_id: str):
        existing = next((item for item in repository.projects() if item["id"] == project_id), None)
        if existing is None:
            return jsonify({"error": "not_found", "message": "Project not found"}), 404
        updated = validate_project_patch(request.get_json(silent=True), existing)
        repository.update_project(project_id, updated)
        return jsonify({"item": updated})

    @app.get("/api/work-items")
    def work_items():
        items = repository.work_items()
        for field in ("target_type", "target_id", "status"):
            value = request.args.get(field)
            if value:
                items = [item for item in items if item.get(field) == value]
        return jsonify({"items": items})

    @app.post("/api/work-items")
    def create_work_item():
        item = validate_work_item(request.get_json(silent=True))
        target_error = _validate_target(repository, item)
        if target_error:
            return target_error
        return jsonify({"item": repository.create_work_item(item)}), 201

    @app.patch("/api/work-items/<item_id>")
    def patch_work_item(item_id: str):
        existing = next((item for item in repository.work_items() if item["id"] == item_id), None)
        if existing is None:
            return jsonify({"error": "not_found", "message": "Work item not found"}), 404
        item = validate_work_item(request.get_json(silent=True), existing=existing)
        target_error = _validate_target(repository, item)
        if target_error:
            return target_error
        repository.update_work_item(item_id, item)
        return jsonify({"item": item})

    @app.post("/api/notes")
    def create_note():
        note = validate_context_entry(request.get_json(silent=True), kind="note")
        target_error = _validate_target(repository, note)
        if target_error:
            return target_error
        return jsonify({"item": repository.append_note(note)}), 201

    @app.post("/api/check-ins")
    def create_check_in():
        check_in = validate_context_entry(request.get_json(silent=True), kind="check_in")
        target_error = _validate_target(repository, check_in)
        if target_error:
            return target_error
        return jsonify({"item": repository.append_check_in(check_in)}), 201

    @app.get("/api/usage-entries")
    def usage_entries():
        return jsonify({"items": repository.usage_entries()})

    @app.post("/api/usage-entries")
    def create_usage_entry():
        entry = validate_usage_entry(request.get_json(silent=True))
        return jsonify({"item": repository.append_usage_entry(entry)}), 201

    @app.get("/api/reporting/overview")
    def reporting_overview():
        return jsonify(reports.overview())

    @app.get("/api/reporting/domains/<domain>")
    def domain_report(domain: str):
        try:
            return jsonify(reports.get_report(domain, request.args.get("window", "week")))
        except ReportingInputError as error:
            return jsonify({"error": "validation_error", "message": str(error)}), 400

    @app.post("/api/reporting/domains/<domain>/insight")
    def domain_insight(domain: str):
        payload = request.get_json(silent=True)
        payload = payload if isinstance(payload, dict) else {}
        # Deliberately accepted fields exclude GTK user_id.
        if set(payload) - {"window", "refresh"}:
            return jsonify(
                {"error": "validation_error", "message": "Only window and refresh are accepted."}
            ), 400
        try:
            return jsonify(
                reports.generate_insight(
                    domain,
                    str(payload.get("window") or "week"),
                    refresh=payload.get("refresh") is True,
                )
            )
        except ReportingInputError as error:
            return jsonify({"error": "validation_error", "message": str(error)}), 400

    @app.post("/api/reporting/feedback")
    def reporting_feedback():
        try:
            return jsonify({"item": reports.record_feedback(request.get_json(silent=True))}), 201
        except ReportingInputError as error:
            return jsonify({"error": "validation_error", "message": str(error)}), 400

    return app


def _validate_target(repository: JsonStateRepository, item: dict[str, Any]):
    if repository.target_exists(item["target_type"], item["target_id"]):
        return None
    return (
        jsonify(
            {
                "error": "validation_error",
                "fields": {"target_id": "does not match an existing program or project"},
            }
        ),
        400,
    )


def _dashboard(repository: JsonStateRepository) -> dict[str, Any]:
    items = repository.work_items()
    projects = repository.projects()
    check_ins = repository.check_ins()
    today = datetime.now(UTC).date()

    needs_attention = [
        item
        for item in items
        if item.get("status") != "completed"
        and item.get("human_check_in_status") in {"requested", "awaiting_direction"}
    ]
    attention_projects = [
        project
        for project in projects
        if project.get("status") != "completed" and project.get("human_check_in_required") is True
    ]
    attention_check_ins = [
        check_in
        for check_in in check_ins
        if check_in.get("status") in {"requested", "awaiting_direction"}
    ]
    upcoming = sorted(
        [
            {**item, "attention_at": item.get("scheduled_for") or item.get("review_after")}
            for item in items
            if item.get("status") != "completed"
            and (item.get("scheduled_for") or item.get("review_after"))
        ],
        key=lambda item: item["attention_at"],
    )[:8]

    return {
        "identity": {
            "name": "Jaza Soulminder",
            "role": "Sentinel",
            "message": "Jaza manages the bigger picture.",
        },
        "metrics": {
            "needs_my_attention": len(needs_attention)
            + len(attention_projects)
            + len(attention_check_ins),
            "active_work": sum(item.get("status") == "active" for item in items),
            "ready": sum(item.get("status") == "ready" for item in items),
            "waiting": sum(item.get("status") == "waiting" for item in items),
            "completed_today": sum(
                item.get("status") == "completed" and _date_of(item.get("updated_at")) == today
                for item in items
            ),
            "prepared_for_star": sum(
                item.get("execution_status") == "prepared_for_star" for item in items
            ),
        },
        "needs_attention": needs_attention[:8],
        "attention_projects": attention_projects[:8],
        "attention_check_ins": attention_check_ins[:8],
        "upcoming": upcoming,
        "recent_notes": sorted(
            repository.notes(), key=lambda note: note.get("created_at", ""), reverse=True
        )[:6],
        "recent_check_ins": sorted(
            check_ins,
            key=lambda check_in: check_in.get("created_at", ""),
            reverse=True,
        )[:6],
    }


def _date_of(timestamp: str | None):
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    except ValueError:
        return None
