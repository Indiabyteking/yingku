from __future__ import annotations

import json
import re
from typing import Any

from app.clients.http_client import ExternalServiceError, RateLimitedHttpClient
from app.config import ConfigManager, is_effective_value, is_placeholder_only

SYSTEM_PROMPT = (
    "你是专业的影视资源命名还原助手。夸克、百度网盘资源常使用谐音字、形近字、拼音或首字母缩写、"
    "插入分隔符、繁简混用、广告前后缀等方式规避审查。请结合文件名、上级目录路径以及提供的 TMDB 候选列表，"
    "推断该资源的真实原始影视片名（优先中文常用译名，同时给出英文或原名）及季集号。\n"
    "请严格只输出一个 JSON 对象，格式如下：\n"
    '{"inferred_title": "真实中文片名", "english_title": "英文或原名(未知填空)", '
    '"media_type": "movie或tv", "year": 2023或null, "season": 1或null, "episode": 1或null, '
    '"reasoning": "简明中文判断理由（说明还原了哪些谐音/缩写/噪声）"}'
)


class DeepSeekClient:
    """DeepSeek（OpenAI 兼容接口）封装，支持 responses 与 chat_completions 两种调用协议。"""

    def __init__(
        self,
        config_manager: ConfigManager,
        http_client: RateLimitedHttpClient | None = None,
    ) -> None:
        self._cfg = config_manager
        self._http = http_client or RateLimitedHttpClient("DeepSeek", min_interval=0.3, max_retries=2, timeout=25.0)

    @staticmethod
    def build_endpoint(base_url: str, api_mode: str) -> str:
        clean_base = base_url.rstrip("/")
        suffix = "/responses" if api_mode == "responses" else "/chat/completions"
        if clean_base.endswith("/v1"):
            return f"{clean_base}{suffix}"
        return f"{clean_base}/v1{suffix}"

    def check_connection(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        api_mode: str | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        s = self._cfg.settings
        b_url = (base_url if base_url is not None else s.llm_base_url).strip().rstrip("/")
        key = (api_key if api_key is not None else s.llm_api_key).strip()
        mdl = (model if model is not None else s.llm_model).strip() or "deepseek-chat"
        mode = (api_mode if api_mode is not None else s.llm_api).strip().lower() or "chat_completions"

        if mode not in ("responses", "chat_completions"):
            return False, f"不支持的 LLM_API 调用方式：{mode}（仅支持 responses 或 chat_completions）", {}
        if not is_effective_value(b_url):
            return False, "请填写有效的 LLM_BASE_URL（如 https://api.deepseek.com）", {}
        if not is_effective_value(key):
            if is_placeholder_only(key):
                return (
                    False,
                    f"检测到 LLM_API_KEY 为占位值（{key}），无法调用大模型接口；请填写真实密钥，或跳过此步仅使用规则识别",
                    {"placeholder": True},
                )
            return False, "未填写 LLM_API_KEY（可跳过此步，跳过后自动使用本地规则识别）", {}

        try:
            text = self._invoke_raw(
                base_url=b_url,
                api_key=key,
                model=mdl,
                api_mode=mode,
                system_prompt="You are a helpful assistant.",
                user_prompt="Reply with OK.",
                max_tokens=12,
            )
            preview = (text or "OK").strip()[:30]
            return True, f"连接成功（{mode} / {mdl}，响应：{preview}）", {"mode": mode, "model": mdl}
        except ExternalServiceError as exc:
            return False, exc.message, {}
        except Exception as exc:
            return False, f"DeepSeek 检测失败：{exc}", {}

    def infer_media_info(
        self,
        *,
        filename: str,
        parent_path: str,
        cleaned_name: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        s = self._cfg.settings
        if not s.llm_ready:
            return None

        cand_lines = []
        for c in candidates[:6]:
            cand_lines.append(
                f"- [{c.get('media_type')}] {c.get('title')} / {c.get('original_title')} ({c.get('year') or '未知年份'})"
            )
        user_prompt = (
            f"原始文件名: {filename}\n"
            f"所在网盘目录: {parent_path}\n"
            f"规则初步清洗名: {cleaned_name}\n"
            f"初步检索候选:\n" + ("\n".join(cand_lines) if cand_lines else "（暂无直接命中候选）")
        )

        raw_text = self._invoke_raw(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            model=s.llm_model,
            api_mode=s.llm_api,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=320,
        )
        return self.parse_llm_json(raw_text)

    def _invoke_raw(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        api_mode: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 256,
    ) -> str:
        endpoint = self.build_endpoint(base_url, api_mode)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        if api_mode == "responses":
            body: dict[str, Any] = {
                "model": model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_output_tokens": max_tokens,
            }
        else:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }

        resp = self._http.request("POST", endpoint, headers=headers, json_body=body)
        if resp.status_code == 401:
            detail = self._extract_error_detail(resp)
            raise ExternalServiceError("DeepSeek", f"API Key 认证失败 (HTTP 401){detail}", status_code=401)
        if resp.status_code == 404:
            detail = self._extract_error_detail(resp)
            raise ExternalServiceError(
                "DeepSeek",
                f"接口路径或模型不存在 (HTTP 404，当前协议 {api_mode} / 模型 {model}){detail}",
                status_code=404,
            )
        if resp.status_code >= 400:
            detail = self._extract_error_detail(resp)
            raise ExternalServiceError("DeepSeek", f"大模型调用失败 (HTTP {resp.status_code}){detail}", status_code=resp.status_code)

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ExternalServiceError("DeepSeek", "大模型返回了非 JSON 响应") from exc

        return self.extract_response_text(payload)

    @staticmethod
    def extract_response_text(payload: dict[str, Any]) -> str:
        # 1. OpenAI Responses API 标准字段
        if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
            return payload["output_text"].strip()

        output_items = payload.get("output")
        if isinstance(output_items, list):
            chunks: list[str] = []
            for item in output_items:
                if not isinstance(item, dict):
                    continue
                for content_part in item.get("content") or []:
                    if isinstance(content_part, dict) and isinstance(content_part.get("text"), str):
                        chunks.append(content_part["text"])
            if chunks:
                return "\n".join(chunks).strip()

        # 2. OpenAI Chat Completions 标准字段
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") or {}
            if isinstance(msg.get("content"), str):
                return msg["content"].strip()

        raise ExternalServiceError("DeepSeek", "未能从大模型响应中提取出有效文本内容")

    @staticmethod
    def parse_llm_json(raw_text: str) -> dict[str, Any] | None:
        if not raw_text:
            return None
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.IGNORECASE | re.MULTILINE)
        match = re.search(r"\{[\s\S]*\}", cleaned)
        candidate = match.group(0) if match else cleaned
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None

        inferred = str(obj.get("inferred_title") or "").strip()
        if not inferred:
            return None

        mtype = str(obj.get("media_type") or "").lower().strip()
        if mtype not in ("movie", "tv"):
            mtype = ""

        def to_int(val: Any) -> int | None:
            if val is None or val == "":
                return None
            try:
                return int(val)
            except (TypeError, ValueError):
                return None

        return {
            "inferred_title": inferred,
            "english_title": str(obj.get("english_title") or "").strip(),
            "media_type": mtype,
            "year": to_int(obj.get("year")),
            "season": to_int(obj.get("season")),
            "episode": to_int(obj.get("episode")),
            "reasoning": str(obj.get("reasoning") or "由 DeepSeek 模型结合路径与候选推断").strip(),
        }

    @staticmethod
    def _extract_error_detail(resp: Any) -> str:
        try:
            data = resp.json()
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                return f"：{err['message']}"
            if isinstance(err, str) and err:
                return f"：{err}"
        except Exception:
            pass
        return ""
