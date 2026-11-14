from __future__ import annotations

from pathlib import Path
from typing import Any

from app import create_app
from app.config import ConfigManager
from app.models.state_model import LocalStateRepository
from app.services.recognition_service import RecognitionService


class StubTMDBClient:
    def __init__(self, image_cache_dir: Path) -> None:
        self.image_cache_dir = image_cache_dir
        self.search_queries: list[str] = []

    def check_connection(self, token: str | None = None):
        if not token or token == "to_do":
            return False, "TMDB 令牌无效", {}
        return True, "TMDB 连接正常", {}

    def search_candidates(self, query: str, media_type: str | None = None, year: int | None = None) -> list[dict[str, Any]]:
        self.search_queries.append(query)
        catalog = [
            {
                "tmdb_id": 10997,
                "media_type": "movie",
                "title": "霸王别姬",
                "original_title": "霸王別姬",
                "year": 1993,
                "release_date": "1993-01-01",
                "overview": "程蝶衣与段小楼的一生",
                "tmdb_rating": 8.7,
                "tmdb_votes": 1800,
                "popularity": 45.0,
                "poster_remote": "/bwbj.jpg",
                "backdrop_remote": "/bwbj_bg.jpg",
            },
            {
                "tmdb_id": 4613,
                "media_type": "tv",
                "title": "兄弟连",
                "original_title": "Band of Brothers",
                "year": 2001,
                "release_date": "2001-09-09",
                "overview": "二战美军101空降师E连纪实剧集",
                "tmdb_rating": 8.6,
                "tmdb_votes": 3500,
                "popularity": 80.0,
                "poster_remote": "/bob.jpg",
                "backdrop_remote": "/bob_bg.jpg",
            },
            {
                "tmdb_id": 278,
                "media_type": "movie",
                "title": "肖申克的救赎",
                "original_title": "The Shawshank Redemption",
                "year": 1994,
                "release_date": "1994-09-23",
                "overview": "希望让人自由",
                "tmdb_rating": 8.7,
                "tmdb_votes": 26000,
                "popularity": 120.0,
                "poster_remote": "/shawshank.jpg",
                "backdrop_remote": "/shawshank_bg.jpg",
            },
        ]
        q_low = query.lower()
        return [
            item
            for item in catalog
            if q_low in item["title"].lower()
            or q_low in item["original_title"].lower()
            or item["title"].startswith(query)
        ]

    def fetch_work_detail(self, media_type: str, tmdb_id: int) -> dict[str, Any]:
        if media_type == "tv" and int(tmdb_id) == 4613:
            return {
                "media_type": "tv",
                "tmdb_id": 4613,
                "imdb_id": "tt0185906",
                "title": "兄弟连",
                "original_title": "Band of Brothers",
                "year": 2001,
                "release_date": "2001-09-09",
                "runtime": 60,
                "overview": "二战E连故事",
                "genres": ["剧情", "战争"],
                "tmdb_rating": 8.6,
                "tmdb_votes": 3500,
                "poster_remote": "/bob.jpg",
                "backdrop_remote": "/bob_bg.jpg",
                "logo_remote": "/bob_logo.png",
                "cast": [{"name": "达米安·刘易斯", "character": "Richard Winters", "profile_remote": "/winters.jpg"}],
                "seasons": [
                    {
                        "season_number": 1,
                        "name": "第 1 季",
                        "overview": "全十集",
                        "air_date": "2001-09-09",
                        "episode_count": 2,
                        "poster_remote": "/bob_s1.jpg",
                    }
                ],
            }
        return {
            "media_type": "movie",
            "tmdb_id": int(tmdb_id),
            "imdb_id": "tt0111161",
            "title": "肖申克的救赎" if int(tmdb_id) == 278 else "霸王别姬",
            "original_title": "The Shawshank Redemption" if int(tmdb_id) == 278 else "Farewell My Concubine",
            "year": 1994 if int(tmdb_id) == 278 else 1993,
            "release_date": "1994-09-23",
            "runtime": 142,
            "overview": "经典高分电影简介",
            "genres": ["剧情", "犯罪"],
            "tmdb_rating": 8.7,
            "tmdb_votes": 26000,
            "poster_remote": "/shawshank.jpg",
            "backdrop_remote": "/shawshank_bg.jpg",
            "logo_remote": "/shawshank_logo.png",
            "cast": [{"name": "蒂姆·罗宾斯", "character": "Andy Dufresne", "profile_remote": "/andy.jpg"}],
            "seasons": [],
        }

    def fetch_season_episodes(self, tmdb_id: int, season_number: int) -> list[dict[str, Any]]:
        return [
            {
                "season_number": season_number,
                "episode_number": 1,
                "title": "新兵训练",
                "overview": "第一集简介",
                "air_date": "2001-09-09",
                "runtime": 70,
                "still_remote": "/ep1.jpg",
                "tmdb_rating": 8.4,
            },
            {
                "season_number": season_number,
                "episode_number": 2,
                "title": "诺曼底登陆日",
                "overview": "第二集简介",
                "air_date": "2001-09-09",
                "runtime": 52,
                "still_remote": "/ep2.jpg",
                "tmdb_rating": 8.8,
            },
        ]

    def fetch_candidate_images(self, media_type: str, tmdb_id: int) -> dict[str, list[dict[str, Any]]]:
        return {
            "logos": [{"file_path": "/alt_logo.png", "lang": "中文", "width": 500, "height": 200, "vote_average": 6.0}],
            "posters": [{"file_path": "/alt_poster.jpg", "lang": "中文", "width": 1000, "height": 1500, "vote_average": 6.0}],
            "backdrops": [{"file_path": "/alt_bg.jpg", "lang": "无字/通用", "width": 1920, "height": 1080, "vote_average": 6.0}],
        }

    def cache_image(self, remote_file_path: str, size: str = "w780", category: str = "posters") -> str:
        if not remote_file_path:
            return ""
        rel = f"{category}/{size}_{remote_file_path.lstrip('/')}"
        target = self.image_cache_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x89PNG\r\n\x1a\ncached")
        return rel


class StubDeepSeekClient:
    def __init__(self) -> None:
        self.call_count = 0

    def check_connection(self, **_kwargs):
        return False, "LLM_API_KEY 当前为占位值（to_do）", {}

    def infer_media_info(self, **_kwargs) -> dict[str, Any] | None:
        self.call_count += 1
        # 故意假设模型只给出推断片名（甚至哪怕模型编造 ID，服务层也只用推断片名去 TMDB 检索校验）
        return {
            "inferred_title": "肖申克的救赎",
            "english_title": "The Shawshank Redemption",
            "year": 1994,
            "media_type": "movie",
            "season": None,
            "episode": None,
            "fake_hallucinated_tmdb_id": 999999999,
            "reasoning": "隐晦暗号『瑞德与安迪的高墙越狱』指向《肖申克的救赎》",
        }


class StubAListClient:
    def check_connection(self, **_kwargs):
        return True, "连接成功", {"mounts": ["/资源"]}

    def list_dir(self, path: str = "/", refresh: bool = False):
        return [{"name": "兄弟连.S01E01.mp4", "path": "/资源/兄弟连.S01E01.mp4", "parent_path": "/资源", "is_dir": False, "is_video": True, "size": 1024, "size_human": "1 KB", "modified": "", "sign": ""}]

    def collect_video_files(self, selected_paths: list[str], max_depth: int = 4):
        return [{"alist_path": p, "filename": p.split("/")[-1], "parent_path": "/资源", "size": 104857600} for p in selected_paths]

    def get_item_meta(self, path: str):
        return {"name": path.split("/")[-1], "is_dir": False, "size": 209715200}

    def build_stream_url(self, alist_path: str):
        return {"stream_url": f"http://127.0.0.1:5244/p{alist_path}", "direct_url": "", "raw_url": "", "provider": "Quark", "filename": alist_path.split("/")[-1]}


class StubMDBListClient:
    def check_connection(self, **_kwargs):
        return True, "MDBList 正常", {}

    def fetch_ratings(self, media_type: str, tmdb_id: int):
        return [
            {"source": "imdb", "label": "IMDb", "display": "9.3", "raw_value": 9.3, "score": 93, "votes": 1000},
            {"source": "tomatoes", "label": "烂番茄", "display": "91%", "raw_value": 91, "score": 91, "votes": 200},
        ]


class StubPlayerClient:
    def __init__(self) -> None:
        self.played_urls: list[str] = []

    def check_connection(self, **_kwargs):
        return True, "MPC-HC 就绪", {}

    def launch_stream(self, stream_url: str, start_seconds: int = 0, on_session_update=None):
        self.played_urls.append(stream_url)
        return {"pid": 1234, "player_name": "mpc-hc64.exe", "stream_url": stream_url, "start_seconds": start_seconds}


def test_phonetic_rule_recognition_without_ai(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("ALIST_URL=http://127.0.0.1:5244\nALIST_USERNAME=admin\nTMDB_TOKEN=tok\nLLM_API_KEY=to_do\n", encoding="utf-8")
    cfg = ConfigManager(env_path=env_file, data_dir=tmp_path / "data")
    cfg.ensure_dirs()
    state = LocalStateRepository(cfg.local_db_path)
    tmdb = StubTMDBClient(cfg.image_cache_dir)
    llm = StubDeepSeekClient()

    svc = RecognitionService(cfg, state, tmdb, llm)  # type: ignore[arg-type]
    # 词典里未硬编码 "霸王bie姬"，但通过连续汉字片段检索 + pypinyin 声韵同音校验即可还原！
    res = svc.recognize_file(filename="【防和谐】霸·王·bie·姬.1993.1080p.BluRay.mkv", parent_path="/movies")
    assert res["inferred_title"] == "霸王别姬"
    assert res["matched_work"]["tmdb_id"] == 10997
    assert res["bucket"] == "confirmable"
    assert llm.call_count == 0


def test_ai_fallback_reverified_by_tmdb_and_cached(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ALIST_URL=http://127.0.0.1:5244\nALIST_USERNAME=admin\nTMDB_TOKEN=tok\nLLM_BASE_URL=https://api.deepseek.com\nLLM_API_KEY=sk-real\n",
        encoding="utf-8",
    )
    cfg = ConfigManager(env_path=env_file, data_dir=tmp_path / "data")
    cfg.ensure_dirs()
    state = LocalStateRepository(cfg.local_db_path)
    tmdb = StubTMDBClient(cfg.image_cache_dir)
    llm = StubDeepSeekClient()

    svc = RecognitionService(cfg, state, tmdb, llm)  # type: ignore[arg-type]
    res1 = svc.recognize_file(filename="瑞德与安迪的高墙越狱_珍藏版.mp4", parent_path="/加密分享")
    assert llm.call_count == 1
    assert res1["source"] == "ai"
    # 关键验证：绝不采信模型编造的 999999999，而是经过 TMDB 校验后绑定真实 ID 278！
    assert res1["matched_work"]["tmdb_id"] == 278
    assert res1["from_cache"] is False

    # 第二次识别同一文件必须直接命中本地 SQLite 缓存，不重复请求 AI
    res2 = svc.recognize_file(filename="瑞德与安迪的高墙越狱_珍藏版.mp4", parent_path="/加密分享")
    assert res2["from_cache"] is True
    assert llm.call_count == 1


def test_end_to_end_flask_routes_onboarding_import_play_and_admin(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ALIST_URL=http://127.0.0.1:5244\nALIST_USERNAME=admin\nALIST_PASSWORD=alist123\n"
        "TMDB_TOKEN=valid_token\nMDBLIST_APIKEY=valid_mdb\nLLM_API_KEY=to_do\nPLAYER_PATH=C:/mpc-hc64.exe\n",
        encoding="utf-8",
    )
    cfg = ConfigManager(env_path=env_file, data_dir=tmp_path / "data")
    cfg.ensure_dirs()

    player_stub = StubPlayerClient()
    app = create_app(
        config_manager=cfg,
        alist_client=StubAListClient(),  # type: ignore[arg-type]
        tmdb_client=StubTMDBClient(cfg.image_cache_dir),  # type: ignore[arg-type]
        mdblist_client=StubMDBListClient(),  # type: ignore[arg-type]
        deepseek_client=StubDeepSeekClient(),  # type: ignore[arg-type]
        player_client=player_stub,  # type: ignore[arg-type]
    )
    client = app.test_client()

    # 1. 首次打开首页自动跳转到 /setup 引导页
    r_home_before = client.get("/")
    assert r_home_before.status_code == 302
    assert "/setup" in r_home_before.headers["Location"]

    # 2. DeepSeek 为占位符 to_do 时点检测返回明确失败原因
    r_ds_check = client.post("/api/setup/check", json={"service": "deepseek", "values": {"LLM_API_KEY": "to_do"}})
    assert r_ds_check.status_code == 400
    assert "to_do" in r_ds_check.get_json()["message"]

    # 3. 跳过 DeepSeek 并保存完成引导，写回 .env 并进入空状态首页
    r_save = client.post(
        "/api/setup/save",
        json={
            "values": cfg.settings.to_env_dict(),
            "skipped": {"deepseek": True},
            "complete_onboarding": True,
            "verify_required": True,
        },
    )
    assert r_save.status_code == 200
    assert cfg.media_db_path.exists()
    assert cfg.local_db_path.exists()

    r_empty = client.get("/")
    assert r_empty.status_code == 200
    assert "还没有添加影视" in r_empty.get_data(as_text=True)

    # 4. 同步入库一部多版本电影 + 一部剧集
    lib = app.extensions["services"].library_service
    imp_res = lib.import_items_sync(
        [
            {
                "alist_path": "/资源/肖申克的救赎.1080p.mp4",
                "filename": "肖申克的救赎.1080p.mp4",
                "file_size": 2_000_000_000,
                "media_type": "movie",
                "tmdb_id": 278,
                "version_label": "1080p",
            },
            {
                "alist_path": "/资源/肖申克的救赎.4K.mkv",
                "filename": "肖申克的救赎.4K.mkv",
                "file_size": 8_000_000_000,
                "media_type": "movie",
                "tmdb_id": 278,
                "version_label": "4K HDR",
            },
            {
                "alist_path": "/资源/兄弟连/S01E01.mp4",
                "filename": "S01E01.mp4",
                "file_size": 2_100_000_000,
                "media_type": "tv",
                "tmdb_id": 4613,
                "season_number": 1,
                "episode_number": 1,
            },
            {
                "alist_path": "/资源/兄弟连/S01E02.mp4",
                "filename": "S01E02.mp4",
                "file_size": 2_100_000_000,
                "media_type": "tv",
                "tmdb_id": 4613,
                "season_number": 1,
                "episode_number": 2,
            },
        ]
    )
    assert len(imp_res["imported"]) == 2

    # 5. 验证电影详情页（Logo、片名、双版本选择）与剧集详情页
    works = app.extensions["media_repo"].list_works()
    movie_work = next(w for w in works if w["media_type"] == "movie")
    tv_work = next(w for w in works if w["media_type"] == "tv")

    r_movie = client.get(f"/movies/{movie_work['id']}")
    movie_html = r_movie.get_data(as_text=True)
    assert r_movie.status_code == 200
    assert "肖申克的救赎" in movie_html
    assert "/media-cache/logos/" in movie_html
    assert "4K HDR" in movie_html and "1080p" in movie_html
    assert "image.tmdb.org" not in movie_html  # 页面绝不直接引用 TMDB 外链

    # 6. 播放剧集第一集 -> 拉起 MPC-HC 并在首页“继续观看”出现进度
    eps = app.extensions["media_repo"].get_episodes(tv_work["id"], season_number=1)
    r_play = client.post("/api/play", json={"work_id": tv_work["id"], "episode_id": eps[0]["id"]})
    assert r_play.status_code == 200
    assert len(player_stub.played_urls) == 1

    r_home_after = client.get("/")
    home_html = r_home_after.get_data(as_text=True)
    assert "继续观看" in home_html
    assert "新兵训练" in home_html

    # 7. 后台修改标题、切换候选 Logo 与重新匹配
    r_title = client.post(f"/api/admin/works/{movie_work['id']}/title", json={"custom_title": "肖申克的救赎（典藏版）"})
    assert r_title.status_code == 200
    assert "肖申克的救赎（典藏版）" in client.get(f"/movies/{movie_work['id']}").get_data(as_text=True)

    r_img = client.post(
        f"/api/admin/works/{movie_work['id']}/select-image",
        json={"kind": "logo", "file_path": "/alt_logo.png"},
    )
    assert r_img.status_code == 200

    r_rematch = client.post(
        f"/api/admin/works/{movie_work['id']}/rematch",
        json={"media_type": "movie", "tmdb_id": 10997},
    )
    assert r_rematch.status_code == 200
    assert r_rematch.get_json()["work"]["title"] == "霸王别姬"
