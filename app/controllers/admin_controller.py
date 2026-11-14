from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from app.clients.http_client import ExternalServiceError
from app.controllers import get_services

admin_bp = Blueprint("admin", __name__)


@admin_bp.get("/admin")
def admin_page():
    search = (request.args.get("q") or "").strip()
    media_type = (request.args.get("type") or "").strip()
    sort = (request.args.get("sort") or "recent").strip()
    selected_id_raw = (request.args.get("work_id") or "").strip()

    lib = get_services().library_service
    vm = lib.build_admin_list(search=search, media_type=media_type, sort=sort)

    active_work_detail = None
    if selected_id_raw.isdigit():
        active_work_detail = lib.build_admin_work_detail(int(selected_id_raw))
    elif vm["works"]:
        active_work_detail = lib.build_admin_work_detail(int(vm["works"][0]["id"]))

    return render_template(
        "admin.html",
        vm=vm,
        active_detail=active_work_detail,
        nav_active="admin",
        page_title="后台管理",
    )


@admin_bp.get("/api/admin/works/<int:work_id>")
def get_work_admin_detail(work_id: int):
    detail = get_services().library_service.build_admin_work_detail(work_id)
    if not detail:
        return jsonify({"ok": False, "message": "未找到该影视条目"}), 404
    return jsonify({"ok": True, "data": detail})


@admin_bp.post("/api/admin/works/<int:work_id>/title")
def update_work_title(work_id: int):
    payload = request.get_json(silent=True) or {}
    custom_title = str(payload.get("custom_title") or "").strip()
    try:
        work = get_services().library_service.update_display_title(work_id, custom_title)
        return jsonify({"ok": True, "message": "显示标题已保存", "work": work})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.get("/api/admin/works/<int:work_id>/images")
def list_candidate_images(work_id: int):
    try:
        images = get_services().library_service.get_work_candidate_images(work_id)
        return jsonify({"ok": True, "images": images})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.post("/api/admin/works/<int:work_id>/select-image")
def select_candidate_image(work_id: int):
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind") or "").strip()
    file_path = str(payload.get("file_path") or "").strip()
    try:
        work = get_services().library_service.switch_work_image(work_id, kind=kind, remote_file_path=file_path)
        kind_cn = {"logo": "片名 Logo", "poster": "竖版海报", "backdrop": "横版背景图"}.get(kind, "图片")
        return jsonify({"ok": True, "message": f"已更换{kind_cn}并缓存到本地", "work": work})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.post("/api/admin/works/<int:work_id>/rematch")
def rematch_work(work_id: int):
    payload = request.get_json(silent=True) or {}
    media_type = str(payload.get("media_type") or "").strip()
    tmdb_id = payload.get("tmdb_id")
    if media_type not in ("movie", "tv") or not tmdb_id:
        return jsonify({"ok": False, "message": "请选择要重新匹配的目标 TMDB 作品"}), 400

    try:
        work = get_services().library_service.rematch_work(work_id, media_type, int(tmdb_id))
        return jsonify({"ok": True, "message": f"已重新匹配为《{work['display_title']}》并刷新全部资料", "work": work})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.post("/api/admin/works/<int:work_id>/refresh")
def refresh_work(work_id: int):
    try:
        work = get_services().library_service.refresh_work(work_id)
        return jsonify({"ok": True, "message": f"《{work['display_title']}》资料与多平台评分已重新获取", "work": work})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.post("/api/admin/works/<int:work_id>/map-episode")
def map_episode_file(work_id: int):
    payload = request.get_json(silent=True) or {}
    file_id = payload.get("file_id")
    if not file_id:
        return jsonify({"ok": False, "message": "缺少媒体文件 ID"}), 400

    s_raw = payload.get("season_number")
    e_raw = payload.get("episode_number")
    season_no = int(s_raw) if s_raw not in (None, "") else None
    episode_no = int(e_raw) if e_raw not in (None, "") else None

    try:
        detail = get_services().library_service.map_file_to_episode(
            work_id=work_id,
            file_id=int(file_id),
            season_number=season_no,
            episode_number=episode_no,
        )
        return jsonify({"ok": True, "message": "文件与季集对应关系已保存", "data": detail})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.post("/api/admin/works/<int:work_id>/file-version")
def update_file_version(work_id: int):
    payload = request.get_json(silent=True) or {}
    file_id = payload.get("file_id")
    version_label = str(payload.get("version_label") or "").strip()
    if not file_id:
        return jsonify({"ok": False, "message": "缺少媒体文件 ID"}), 400

    try:
        detail = get_services().library_service.update_file_version(
            work_id=work_id,
            file_id=int(file_id),
            version_label=version_label,
        )
        return jsonify({"ok": True, "message": "版本标签已更新", "data": detail})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.post("/api/admin/works/<int:work_id>/attach-file")
def attach_file(work_id: int):
    payload = request.get_json(silent=True) or {}
    alist_path = str(payload.get("alist_path") or "").strip()
    version_label = str(payload.get("version_label") or "").strip()
    s_raw = payload.get("season_number")
    e_raw = payload.get("episode_number")
    season_no = int(s_raw) if s_raw not in (None, "") else None
    episode_no = int(e_raw) if e_raw not in (None, "") else None

    if not alist_path:
        return jsonify({"ok": False, "message": "请填写或选择 AList 视频文件路径"}), 400

    try:
        detail = get_services().library_service.attach_alist_file_to_work(
            work_id=work_id,
            alist_path=alist_path,
            version_label=version_label,
            season_number=season_no,
            episode_number=episode_no,
        )
        return jsonify({"ok": True, "message": "已关联新的网盘媒体文件", "data": detail})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.delete("/api/admin/works/<int:work_id>/files/<int:file_id>")
def delete_attached_file(work_id: int, file_id: int):
    try:
        detail = get_services().library_service.remove_media_file(work_id=work_id, file_id=file_id)
        return jsonify({"ok": True, "message": "已移除关联的媒体文件", "data": detail})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@admin_bp.delete("/api/admin/works/<int:work_id>")
def delete_work(work_id: int):
    deleted = get_services().library_service.delete_work(work_id)
    if not deleted:
        return jsonify({"ok": False, "message": "未找到要删除的影视条目"}), 404
    return jsonify({"ok": True, "message": "该影视作品已从本地媒体库移除"})
