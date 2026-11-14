from __future__ import annotations

from flask import Blueprint, abort, render_template, request, send_from_directory

from app.controllers import get_services

home_bp = Blueprint("home", __name__)


@home_bp.get("/")
def index():
    search = (request.args.get("q") or "").strip()
    genre = (request.args.get("genre") or "").strip()
    year_raw = (request.args.get("year") or "").strip()
    min_rating_raw = (request.args.get("min_rating") or "").strip()
    media_type = (request.args.get("type") or "").strip()

    vm = get_services().playback_service.build_home_data(
        search=search,
        genre=genre,
        year_raw=year_raw,
        min_rating_raw=min_rating_raw,
        media_type=media_type,
    )
    return render_template("home.html", vm=vm, nav_active="home", page_title="首页")


@home_bp.get("/media-cache/<path:rel_path>")
def serve_cached_image(rel_path: str):
    cache_dir = get_services().config.image_cache_dir
    clean = rel_path.replace("\\", "/").lstrip("/")
    if ".." in clean.split("/"):
        abort(404)
    return send_from_directory(cache_dir, clean, max_age=86400)
