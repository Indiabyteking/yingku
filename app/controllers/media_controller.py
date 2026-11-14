from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request

from app.clients.http_client import ExternalServiceError
from app.controllers import get_services

media_bp = Blueprint("media", __name__)


@media_bp.get("/movies/<int:work_id>")
def movie_detail(work_id: int):
    vm = get_services().playback_service.build_movie_detail(work_id)
    if not vm:
        abort(404, description="未找到该电影条目")
    return render_template(
        "movie_detail.html",
        vm=vm,
        nav_active="movies",
        page_title=vm["work"]["display_title"],
    )


@media_bp.get("/tv/<int:work_id>")
def tv_detail(work_id: int):
    svcs = get_services()
    season_raw = (request.args.get("season") or "").strip()
    selected_season = int(season_raw) if season_raw.isdigit() else None

    if selected_season is not None:
        svcs.library_service.ensure_season_loaded(work_id, selected_season)

    vm = svcs.playback_service.build_tv_detail(work_id, selected_season=selected_season)
    if not vm:
        abort(404, description="未找到该剧集条目")
    return render_template(
        "tv_detail.html",
        vm=vm,
        nav_active="tv",
        page_title=vm["work"]["display_title"],
    )


@media_bp.post("/api/play")
def trigger_playback():
    payload = request.get_json(silent=True) or {}
    work_id = payload.get("work_id")
    if not work_id:
        return jsonify({"ok": False, "message": "缺少作品 ID 参数"}), 400

    episode_id = payload.get("episode_id")
    file_id = payload.get("file_id")

    try:
        result = get_services().playback_service.launch_playback(
            work_id=int(work_id),
            episode_id=int(episode_id) if episode_id not in (None, "") else None,
            file_id=int(file_id) if file_id not in (None, "") else None,
        )
        return jsonify({"ok": True, "message": f"已调用 {result['player_name']} 开始播放", "data": result})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400


@media_bp.post("/api/progress")
def update_progress():
    payload = request.get_json(silent=True) or {}
    work_id = payload.get("work_id")
    if not work_id:
        return jsonify({"ok": False, "message": "缺少作品 ID 参数"}), 400

    episode_id = payload.get("episode_id")
    watched = payload.get("watched")
    if watched is not None:
        watched = bool(watched)

    progress_percent = payload.get("progress_percent")
    if progress_percent is not None and progress_percent != "":
        progress_percent = float(progress_percent)
    else:
        progress_percent = None

    position_seconds = payload.get("position_seconds")
    if position_seconds is not None and position_seconds != "":
        position_seconds = int(position_seconds)
    else:
        position_seconds = None

    try:
        updated = get_services().playback_service.update_progress_manual(
            work_id=int(work_id),
            episode_id=int(episode_id) if episode_id not in (None, "") else None,
            watched=watched,
            progress_percent=progress_percent,
            position_seconds=position_seconds,
        )
        return jsonify({"ok": True, "message": "观看进度已更新", "progress": updated})
    except ExternalServiceError as exc:
        return jsonify({"ok": False, "message": exc.message}), 400
