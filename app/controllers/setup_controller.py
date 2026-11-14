from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from app.clients.http_client import ExternalServiceError
from app.controllers import get_services

setup_bp = Blueprint("setup", __name__)


@setup_bp.get("/setup")
def onboarding_page():
    vm = get_services().setup_service.build_config_view_model()
    return render_template("setup.html", vm=vm, page_title="首次使用引导")


@setup_bp.post("/api/setup/check")
def check_service():
    payload = request.get_json(silent=True) or {}
    service_id = str(payload.get("service") or "").strip()
    values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    result = get_services().setup_service.check_single_service(service_id, values)
    return jsonify(result), (200 if result.get("ok") else 400)


@setup_bp.post("/api/setup/save")
def save_onboarding():
    payload = request.get_json(silent=True) or {}
    values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    skipped = payload.get("skipped") if isinstance(payload.get("skipped"), dict) else {}
    complete = bool(payload.get("complete_onboarding", True))
    verify_req = bool(payload.get("verify_required", complete))

    try:
        ok, message = get_services().setup_service.save_settings(
            values,
            skipped_services=skipped,
            complete_onboarding=complete,
            verify_required=verify_req,
        )
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400

    if not ok:
        return jsonify({"ok": False, "message": message}), 400
    return jsonify({"ok": True, "message": message, "redirect": "/"})


@setup_bp.get("/settings")
def settings_page():
    vm = get_services().setup_service.build_config_view_model()
    return render_template("settings.html", vm=vm, nav_active="settings", page_title="系统设置")


@setup_bp.post("/api/settings/save")
def save_settings():
    payload = request.get_json(silent=True) or {}
    values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    skipped = payload.get("skipped") if isinstance(payload.get("skipped"), dict) else None
    verify_req = bool(payload.get("verify_required", False))

    try:
        ok, message = get_services().setup_service.save_settings(
            values,
            skipped_services=skipped,
            complete_onboarding=False,
            verify_required=verify_req,
        )
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400

    if not ok:
        return jsonify({"ok": False, "message": message}), 400

    vm = get_services().setup_service.build_config_view_model()
    return jsonify({"ok": True, "message": message, "statuses": vm["statuses"], "degraded_notices": vm["degraded_notices"]})


@setup_bp.post("/api/settings/check-all")
def check_all_services():
    results = get_services().setup_service.check_all_current_services()
    vm = get_services().setup_service.build_config_view_model()
    return jsonify({"ok": True, "results": results, "statuses": vm["statuses"]})
