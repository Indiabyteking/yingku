from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from app.clients.http_client import ExternalServiceError
from app.controllers import get_services

import_bp = Blueprint("media_import", __name__)


@import_bp.get("/import")
def import_page():
    presets = get_services().library_service.get_import_presets()
    return render_template(
        "import.html",
        presets=presets,
        nav_active="import",
        page_title="添加影视",
    )


@import_bp.get("/api/import/browse")
def browse_alist():
    path = (request.args.get("path") or "/").strip() or "/"
    refresh = (request.args.get("refresh") or "").lower() in ("1", "true", "yes")
    try:
        data = get_services().library_service.browse_alist(path=path, refresh=refresh)
        return jsonify({"ok": True, "data": data})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@import_bp.post("/api/import/scan")
def start_scan():
    payload = request.get_json(silent=True) or {}
    paths = payload.get("paths") or []
    if not isinstance(paths, list) or not paths:
        return jsonify({"ok": False, "message": "请至少勾选一个网盘文件或文件夹"}), 400

    overrides_raw = payload.get("filename_overrides")
    overrides = overrides_raw if isinstance(overrides_raw, dict) else None

    task_id = get_services().library_service.start_scan_task(
        [str(p) for p in paths if p],
        filename_overrides=overrides,
    )
    return jsonify({"ok": True, "task_id": task_id})


@import_bp.get("/api/tasks/<task_id>")
def poll_task(task_id: str):
    task = get_services().library_service.get_task_status(task_id)
    if not task:
        return jsonify({"ok": False, "message": "未找到对应的后台任务"}), 404
    return jsonify({"ok": True, "task": task})


@import_bp.get("/api/import/tmdb-search")
def search_tmdb():
    query = (request.args.get("q") or "").strip()
    media_type = (request.args.get("type") or "").strip()
    year_raw = (request.args.get("year") or "").strip()
    if not query:
        return jsonify({"ok": False, "message": "请输入要检索的片名关键词"}), 400

    year = int(year_raw) if year_raw.isdigit() else None
    mtype = media_type if media_type in ("movie", "tv") else None

    try:
        items = get_services().library_service.search_tmdb_manual(query=query, media_type=mtype, year=year)
        return jsonify({"ok": True, "items": items})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@import_bp.post("/api/import/confirm")
def confirm_import():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "message": "没有选择可入库的条目"}), 400

    valid_items = [it for it in items if isinstance(it, dict) and it.get("alist_path") and it.get("tmdb_id")]
    if not valid_items:
        return jsonify({"ok": False, "message": "所选条目尚未指定对应的 TMDB 作品"}), 400

    task_id = get_services().library_service.start_import_task(valid_items)
    return jsonify({"ok": True, "task_id": task_id})


@import_bp.post("/api/import/recognize-sample")
def recognize_sample():
    payload = request.get_json(silent=True) or {}
    filename = str(payload.get("filename") or "").strip()
    parent_path = str(payload.get("parent_path") or "/").strip() or "/"
    use_cache = bool(payload.get("use_cache", True))

    if not filename:
        return jsonify({"ok": False, "message": "请输入要测试识别的网盘文件名"}), 400

    try:
        rec = get_services().recognition_service.recognize_file(
            filename=filename,
            parent_path=parent_path,
            alist_path=f"{parent_path.rstrip('/')}/{filename}",
            use_cache=use_cache,
        )
        return jsonify({"ok": True, "result": rec})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400
