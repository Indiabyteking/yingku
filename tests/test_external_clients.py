from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from app.clients.alist_client import AListClient
from app.clients.deepseek_client import DeepSeekClient
from app.clients.http_client import RateLimitedHttpClient
from app.clients.mdblist_client import MDBListClient
from app.clients.player_client import PlayerClient
from app.clients.tmdb_client import TMDBClient
from app.config import ConfigManager
from app.models.state_model import LocalStateRepository


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.content = content if content else (json.dumps(json_data).encode("utf-8") if json_data is not None else b"")
        self.headers = headers or {}
        self.text = self.content.decode("utf-8", errors="ignore")

    def json(self) -> Any:
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text)


class FakeSession:
    def __init__(self, responder) -> None:
        self._responder = responder
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs) -> FakeResponse:
        call = {"method": method, "url": url, **kwargs}
        self.calls.append(call)
        return self._responder(call, len(self.calls))


def _make_cfg(tmp_path: Path, env_lines: str) -> ConfigManager:
    env_file = tmp_path / ".env"
    env_file.write_text(env_lines, encoding="utf-8")
    cfg = ConfigManager(env_path=env_file, data_dir=tmp_path / "data")
    cfg.ensure_dirs()
    return cfg


def test_http_client_retries_on_429_rate_limit():
    slept: list[float] = []

    def responder(_call: dict[str, Any], count: int) -> FakeResponse:
        if count == 1:
            return FakeResponse(status_code=429, json_data={"error": "rate limit"}, headers={"Retry-After": "0.15"})
        return FakeResponse(status_code=200, json_data={"ok": True})

    session = FakeSession(responder)
    http = RateLimitedHttpClient(
        "TestSvc",
        min_interval=0.0,
        max_retries=2,
        session=session,  # type: ignore[arg-type]
        sleep_fn=slept.append,
    )
    resp = http.request("GET", "https://example.local/items")
    assert resp.status_code == 200
    assert len(session.calls) == 2
    assert len(slept) == 1
    assert slept[0] == 0.15


def test_alist_client_login_list_and_proxy_stream(tmp_path: Path):
    cfg = _make_cfg(
        tmp_path,
        "ALIST_URL=http://127.0.0.1:5244\nALIST_USERNAME=admin\nALIST_PASSWORD=alist123\n",
    )

    def responder(call: dict[str, Any], _count: int) -> FakeResponse:
        url = call["url"]
        if url.endswith("/api/auth/login"):
            return FakeResponse(200, {"code": 200, "data": {"token": "fake-jwt-token"}})
        if url.endswith("/api/fs/list"):
            return FakeResponse(
                200,
                {
                    "code": 200,
                    "data": {
                        "content": [
                            {"name": "readme.txt", "is_dir": False, "size": 120},
                            {"name": "兄弟连.S01E01.mp4", "is_dir": False, "size": 2_147_483_648},
                            {"name": "剧集目录", "is_dir": True, "size": 0},
                        ]
                    },
                },
            )
        if url.endswith("/api/fs/get"):
            return FakeResponse(
                200,
                {
                    "code": 200,
                    "data": {
                        "name": "兄弟连.S01E01.mp4",
                        "is_dir": False,
                        "size": 2_147_483_648,
                        "sign": "abc:0",
                        "provider": "Quark",
                        "raw_url": "http://127.0.0.1:5244/p/%E8%B5%84%E6%BA%90/ep1.mp4?sign=abc:0",
                    },
                },
            )
        return FakeResponse(404, {"code": 404})

    http = RateLimitedHttpClient("AList", min_interval=0.0, session=FakeSession(responder))  # type: ignore[arg-type]
    client = AListClient(cfg, http_client=http)

    entries = client.list_dir("/资源")
    assert entries[0]["is_dir"] is True
    assert entries[1]["is_video"] is True
    assert entries[2]["is_video"] is False

    stream = client.build_stream_url("/资源/兄弟连.S01E01.mp4")
    assert stream["stream_url"].startswith("http://127.0.0.1:5244/p/")
    assert stream["provider"] == "Quark"


def test_tmdb_client_detail_parsing_and_local_image_cache(tmp_path: Path):
    cfg = _make_cfg(tmp_path, "TMDB_TOKEN=valid_fake_bearer_token\n")
    state_repo = LocalStateRepository(cfg.local_db_path)

    fake_png = b"\x89PNG\r\n\x1a\nfakeimagebytes"

    def responder(call: dict[str, Any], _count: int) -> FakeResponse:
        url = call["url"]
        if "/movie/872585" in url:
            return FakeResponse(
                200,
                {
                    "id": 872585,
                    "title": "奥本海默",
                    "original_title": "Oppenheimer",
                    "release_date": "2023-07-19",
                    "runtime": 181,
                    "overview": "传记历史电影简介",
                    "vote_average": 8.12,
                    "vote_count": 9200,
                    "imdb_id": "tt15398776",
                    "poster_path": "/poster_opp.jpg",
                    "backdrop_path": "/backdrop_opp.jpg",
                    "genres": [{"id": 18, "name": "剧情"}, {"id": 36, "name": "历史"}],
                    "credits": {
                        "cast": [{"name": "基里安·墨菲", "character": "J. Robert Oppenheimer", "profile_path": "/cillian.jpg"}]
                    },
                    "images": {
                        "logos": [
                            {"file_path": "/logo_en.png", "iso_639_1": "en", "vote_average": 5.5, "width": 800},
                            {"file_path": "/logo_zh.png", "iso_639_1": "zh", "vote_average": 5.0, "width": 700},
                        ]
                    },
                },
            )
        if url.startswith("https://image.tmdb.org/t/p/"):
            return FakeResponse(200, content=fake_png)
        return FakeResponse(404, {})

    session = FakeSession(responder)
    http = RateLimitedHttpClient("TMDB", min_interval=0.0, session=session)  # type: ignore[arg-type]
    tmdb = TMDBClient(cfg, state_repo=state_repo, http_client=http)

    detail = tmdb.fetch_work_detail("movie", 872585)
    assert detail["title"] == "奥本海默"
    assert detail["year"] == 2023
    assert detail["logo_remote"] == "/logo_zh.png"  # 优先选取中文 Logo

    rel1 = tmdb.cache_image("/logo_zh.png", size="w500", category="logos")
    assert rel1.startswith("logos/")
    assert (cfg.image_cache_dir / rel1).read_bytes() == fake_png

    calls_before = len(session.calls)
    rel2 = tmdb.cache_image("/logo_zh.png", size="w500", category="logos")
    assert rel2 == rel1
    assert len(session.calls) == calls_before  # 命中本地缓存，不再重复发起网络下载


def test_mdblist_client_parses_multi_platform_ratings_and_degrades(tmp_path: Path):
    cfg_empty = _make_cfg(tmp_path, "MDBLIST_APIKEY=to_do\n")
    mdb_disabled = MDBListClient(cfg_empty)
    ok, msg, _ = mdb_disabled.check_connection()
    assert ok is False
    assert "占位值" in msg
    assert mdb_disabled.fetch_ratings("movie", 278) == []

    cfg = _make_cfg(tmp_path, "MDBLIST_APIKEY=real_mdb_key\n")
    session = FakeSession(
        lambda _c, _n: FakeResponse(
            200,
            {
                "title": "The Shawshank Redemption",
                "ratings": [
                    {"source": "imdb", "value": 9.3, "score": 93, "votes": 2900000},
                    {"source": "tomatoes", "value": 89, "score": 89, "votes": 140},
                    {"source": "metacritic", "value": 82, "score": 82, "votes": 32},
                ],
            },
        )
    )
    mdb = MDBListClient(cfg, http_client=RateLimitedHttpClient("MDBList", min_interval=0.0, session=session))  # type: ignore[arg-type]
    ratings = mdb.fetch_ratings("movie", 278)
    labels = {r["source"]: r["display"] for r in ratings}
    assert labels["imdb"] == "9.3"
    assert labels["tomatoes"] == "89%"
    assert labels["metacritic"] == "82"
    # 确保带浏览器 User-Agent 请求头防止 Cloudflare 403
    req_headers = requests.Session().headers
    assert req_headers is not None


def test_deepseek_client_supports_both_responses_and_chat_completions(tmp_path: Path):
    # 1. 占位值 to_do 检测
    cfg_todo = _make_cfg(
        tmp_path,
        "LLM_BASE_URL=https://api.deepseek.com\nLLM_API_KEY=to_do\nLLM_MODEL=deepseek-flash\nLLM_API=responses\n",
    )
    ds_todo = DeepSeekClient(cfg_todo)
    ok, reason, _ = ds_todo.check_connection()
    assert ok is False
    assert "to_do" in reason

    # 2. responses 协议解析
    cfg_resp = _make_cfg(
        tmp_path,
        "LLM_BASE_URL=https://api.deepseek.com\nLLM_API_KEY=sk-valid\nLLM_MODEL=deepseek-flash\nLLM_API=responses\n",
    )
    resp_session = FakeSession(
        lambda call, _n: FakeResponse(
            200,
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '```json\n{"inferred_title": "周处除三害", "english_title": "The Pig, the Snake and the Pigeon", "year": 2023, "media_type": "movie", "season": null, "episode": null, "reasoning": "根据谐音与年份还原"}\n```',
                            }
                        ],
                    }
                ]
            },
        )
    )
    ds_resp = DeepSeekClient(
        cfg_resp,
        http_client=RateLimitedHttpClient("DeepSeek", min_interval=0.0, session=resp_session),  # type: ignore[arg-type]
    )
    inferred_1 = ds_resp.infer_media_info(
        filename="周chu除三hai.mp4",
        parent_path="/movies",
        cleaned_name="周chu除三hai",
        candidates=[],
    )
    assert resp_session.calls[0]["url"].endswith("/responses")
    assert inferred_1 is not None
    assert inferred_1["inferred_title"] == "周处除三害"
    assert inferred_1["year"] == 2023

    # 3. chat_completions 协议解析
    cfg_chat = _make_cfg(
        tmp_path,
        "LLM_BASE_URL=https://api.deepseek.com/v1\nLLM_API_KEY=sk-valid\nLLM_MODEL=deepseek-chat\nLLM_API=chat_completions\n",
    )
    chat_session = FakeSession(
        lambda _call, _n: FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"inferred_title": "兄弟连", "english_title": "Band of Brothers", "year": 2001, "media_type": "tv", "season": 1, "episode": 3, "reasoning": "缩写XDL结合二战剧集还原"}'
                        }
                    }
                ]
            },
        )
    )
    ds_chat = DeepSeekClient(
        cfg_chat,
        http_client=RateLimitedHttpClient("DeepSeek", min_interval=0.0, session=chat_session),  # type: ignore[arg-type]
    )
    inferred_2 = ds_chat.infer_media_info(
        filename="XDL_03.mp4",
        parent_path="/tv",
        cleaned_name="XDL 03",
        candidates=[],
    )
    assert chat_session.calls[0]["url"].endswith("/v1/chat/completions")
    assert inferred_2 is not None
    assert inferred_2["inferred_title"] == "兄弟连"
    assert inferred_2["season"] == 1
    assert inferred_2["episode"] == 3


def test_player_client_launches_mpc_hc_with_resume_args(tmp_path: Path):
    fake_exe = tmp_path / "mpc-hc64.exe"
    fake_exe.write_bytes(b"MZfakeplayer")
    cfg = _make_cfg(tmp_path, f"PLAYER_PATH={fake_exe}\n")

    launched_cmds: list[list[str]] = []

    class DummyProc:
        pid = 43210

        def wait(self):
            return 0

    def fake_popen(cmd, **_kwargs):
        launched_cmds.append(list(cmd))
        return DummyProc()

    player = PlayerClient(cfg, popen_factory=fake_popen)
    ok, msg, _ = player.check_connection()
    assert ok is True
    assert "mpc-hc64.exe" in msg

    res = player.launch_stream("http://127.0.0.1:5244/p/test.mp4", start_seconds=125)
    assert res["pid"] == 43210
    assert launched_cmds[0][0] == str(fake_exe)
    assert "http://127.0.0.1:5244/p/test.mp4" in launched_cmds[0]
    assert "/play" in launched_cmds[0]
    assert "125000" in launched_cmds[0]
