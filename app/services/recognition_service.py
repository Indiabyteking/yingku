from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any

import zhconv

from app.clients.deepseek_client import DeepSeekClient
from app.clients.http_client import ExternalServiceError
from app.clients.tmdb_client import TMDBClient
from app.config import ConfigManager
from app.models.state_model import LocalStateRepository
from app.services.name_parser import (
    ParsedMediaName,
    parse_media_filename,
    to_initials_key,
    to_pinyin_key,
)

PARSER_CACHE_VERSION = "v2"


class RecognitionService:
    """
    影视资源名称识别与 TMDB 校验服务：
    1. 规则清洗 + 本地防和谐还原；
    2. TMDB 多路候选搜索 + 标题/拼音同音/年份/季集综合打分；
    3. 规则置信度不足且配置了 DeepSeek 时，调用大模型推断并强制回查 TMDB 校验；
    4. 结果写入本地 SQLite 识别缓存，同一文件不重复请求大模型。
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        state_repo: LocalStateRepository,
        tmdb_client: TMDBClient,
        deepseek_client: DeepSeekClient,
    ) -> None:
        self._cfg = config_manager
        self._state = state_repo
        self._tmdb = tmdb_client
        self._llm = deepseek_client

    def _make_cache_key(self, alist_path: str, filename: str) -> str:
        llm_flag = "llm1" if self._cfg.settings.llm_ready else "llm0"
        raw = f"{PARSER_CACHE_VERSION}|{llm_flag}|{alist_path}|{filename}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def recognize_file(
        self,
        *,
        filename: str,
        parent_path: str = "/",
        alist_path: str = "",
        file_size: int = 0,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        effective_path = alist_path or f"{parent_path.rstrip('/')}/{filename}"
        cache_key = self._make_cache_key(effective_path, filename)

        if use_cache:
            cached = self._state.get_recognition_cache(cache_key)
            if cached:
                cached["file_size"] = file_size or cached.get("file_size", 0)
                return cached

        parsed = parse_media_filename(filename, parent_path=parent_path)
        candidates = self._gather_tmdb_candidates(parsed)
        best_cand, best_score, match_detail = self._rank_candidates(parsed, candidates)

        source = "rule"
        ai_used = False
        ai_note = ""
        final_inferred_title = parsed.inferred_title

        # 若疑似混杂拼音但规则词典未完全覆盖，且命中同音 TMDB 候选，则把推测片名更新为同音还原后的标准名
        if best_cand and parsed.is_obfuscated and match_detail.get("phonetic_exact"):
            final_inferred_title = best_cand["title"]

        # 规则无法确定时，尝试交给 DeepSeek 推断并用 TMDB 二次校验
        should_call_ai = (best_score < 0.80 or parsed.is_non_media_likely is False and best_cand is None)
        if should_call_ai and not parsed.is_non_media_likely:
            if self._cfg.settings.llm_ready:
                try:
                    ai_guess = self._llm.infer_media_info(
                        filename=filename,
                        parent_path=parent_path,
                        cleaned_name=parsed.cleaned_name,
                        candidates=candidates,
                    )
                    if ai_guess and ai_guess.get("inferred_title"):
                        ai_used = True
                        verified_cands = self._verify_ai_guess_with_tmdb(ai_guess)
                        if verified_cands:
                            # 合并候选并以 AI 推断的标题做评分校验，绝不直接采信未校验 ID
                            ai_parsed = ParsedMediaName(
                                raw_name=parsed.raw_name,
                                parent_path=parsed.parent_path,
                                cleaned_name=parsed.cleaned_name,
                                inferred_title=ai_guess["inferred_title"],
                                secondary_title=ai_guess.get("english_title") or "",
                                year=ai_guess.get("year") or parsed.year,
                                season_number=ai_guess.get("season") or parsed.season_number,
                                episode_number=ai_guess.get("episode") or parsed.episode_number,
                                media_type_hint=ai_guess.get("media_type") or parsed.media_type_hint,
                                version_label=parsed.version_label,
                                is_obfuscated=parsed.is_obfuscated,
                            )
                            ai_best, ai_score, ai_detail = self._rank_candidates(ai_parsed, verified_cands)
                            if ai_best and ai_score >= best_score:
                                best_cand = ai_best
                                best_score = min(0.96, max(ai_score, 0.84))
                                match_detail = ai_detail
                                final_inferred_title = ai_guess["inferred_title"]
                                if ai_guess.get("season") and parsed.season_number is None:
                                    parsed.season_number = ai_guess["season"]
                                if ai_guess.get("episode") and parsed.episode_number is None:
                                    parsed.episode_number = ai_guess["episode"]
                                source = "ai"
                                ai_note = f"DeepSeek 推断为《{final_inferred_title}》（{ai_guess.get('reasoning') or '综合路径与文件名'}），并经 TMDB 检索校验通过。"
                                candidates = self._merge_unique_candidates(verified_cands, candidates)
                except ExternalServiceError as exc:
                    ai_note = f"DeepSeek 辅助识别调用失败（{exc.message}），已自动降级为本地规则识别结果。"
            else:
                if best_score < 0.80:
                    ai_note = "当前未配置有效的 DeepSeek API Key，仅使用本地规则与拼音/字形还原引擎识别。"

        # 缓存候选预览海报到本地（避免页面直接引用 TMDB 外链）
        hydrated_candidates = [self._attach_local_preview(c) for c in candidates[:6]]
        matched_work = self._attach_local_preview(best_cand) if best_cand else None

        # 计算分桶：可确认 / 待核对 / 未识别
        if parsed.is_non_media_likely and best_score < 0.90:
            bucket = "unrecognized" if matched_work is None else "needs_review"
            best_score = min(best_score, 0.48)
        elif matched_work and best_score >= 0.80:
            bucket = "confirmable"
        elif matched_work and best_score >= 0.45:
            bucket = "needs_review"
        else:
            bucket = "unrecognized"
            matched_work = None

        reasoning = self._compose_reasoning(
            parsed=parsed,
            final_inferred=final_inferred_title,
            matched_work=matched_work,
            score=best_score,
            match_detail=match_detail,
            ai_used=ai_used,
            ai_note=ai_note,
        )

        result: dict[str, Any] = {
            "alist_path": effective_path,
            "filename": filename,
            "parent_path": parent_path,
            "file_size": int(file_size or 0),
            "raw_name": parsed.raw_name,
            "cleaned_name": parsed.cleaned_name,
            "inferred_title": final_inferred_title,
            "secondary_title": parsed.secondary_title,
            "year": parsed.year,
            "season_number": parsed.season_number,
            "episode_number": parsed.episode_number,
            "version_label": parsed.version_label,
            "media_type": matched_work["media_type"] if matched_work else (parsed.media_type_hint or "movie"),
            "matched_work": matched_work,
            "candidates": hydrated_candidates,
            "confidence": round(best_score, 2),
            "bucket": bucket,
            "bucket_label": {"confirmable": "可确认", "needs_review": "待核对", "unrecognized": "未识别"}[bucket],
            "source": source,
            "source_label": "DeepSeek + TMDB 校验" if source == "ai" else "规则清洗 + TMDB 匹配",
            "is_obfuscated": parsed.is_obfuscated,
            "applied_rules": parsed.applied_rules,
            "reasoning": reasoning,
            "from_cache": False,
        }

        if use_cache:
            self._state.save_recognition_cache(cache_key, result)
        return result

    def _gather_tmdb_candidates(self, parsed: ParsedMediaName) -> list[dict[str, Any]]:
        queries: list[tuple[str, str | None, int | None]] = []
        mtype = parsed.media_type_hint if parsed.media_type_hint in ("movie", "tv") else None

        if parsed.inferred_title:
            queries.append((parsed.inferred_title, mtype, parsed.year))
            if parsed.year:
                queries.append((parsed.inferred_title, None, None))

        if parsed.secondary_title and parsed.secondary_title.lower() != parsed.inferred_title.lower():
            queries.append((parsed.secondary_title, mtype, parsed.year))

        if parsed.cleaned_name and parsed.cleaned_name not in (parsed.inferred_title, parsed.secondary_title):
            # 若 cleaned_name 含有汉字+拼音混写（如 周chu除三hai），提取连续汉字片段作为锚点检索候选！
            cjk_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", parsed.inferred_title)
            for chunk in sorted(cjk_chunks, key=len, reverse=True)[:2]:
                if chunk != parsed.inferred_title:
                    queries.append((chunk, mtype, parsed.year))
                    if parsed.year:
                        queries.append((chunk, None, None))

        collected: list[dict[str, Any]] = []
        seen_queries: set[tuple[str, str | None, int | None]] = set()
        for q, mt, yr in queries:
            q_clean = q.strip()
            if not q_clean or (q_clean, mt, yr) in seen_queries:
                continue
            seen_queries.add((q_clean, mt, yr))
            try:
                res = self._tmdb.search_candidates(q_clean, media_type=mt, year=yr)
                collected = self._merge_unique_candidates(collected, res)
                if len(collected) >= 12:
                    break
            except ExternalServiceError:
                continue
        return collected

    def _verify_ai_guess_with_tmdb(self, ai_guess: dict[str, Any]) -> list[dict[str, Any]]:
        cands: list[dict[str, Any]] = []
        mtype = ai_guess.get("media_type") if ai_guess.get("media_type") in ("movie", "tv") else None
        year = ai_guess.get("year")
        for title_key in ("inferred_title", "english_title"):
            q = (ai_guess.get(title_key) or "").strip()
            if not q:
                continue
            try:
                res = self._tmdb.search_candidates(q, media_type=mtype, year=year)
                cands = self._merge_unique_candidates(cands, res)
                if not res and year:
                    res_no_yr = self._tmdb.search_candidates(q, media_type=None, year=None)
                    cands = self._merge_unique_candidates(cands, res_no_yr)
            except ExternalServiceError:
                continue
        return cands

    @staticmethod
    def _merge_unique_candidates(
        primary: list[dict[str, Any]],
        extra: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen = {(c["media_type"], int(c["tmdb_id"])) for c in primary}
        merged = list(primary)
        for item in extra:
            key = (item["media_type"], int(item["tmdb_id"]))
            if key not in seen:
                seen.add(key)
                merged.append(item)
        return merged

    @staticmethod
    def _rank_candidates(
        parsed: ParsedMediaName,
        candidates: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, float, dict[str, Any]]:
        if not candidates:
            return None, 0.0, {}

        target_cn = zhconv.convert(parsed.inferred_title, "zh-cn").lower().strip()
        target_en = parsed.secondary_title.lower().strip()
        target_py = to_pinyin_key(parsed.inferred_title)
        target_init = to_initials_key(parsed.inferred_title)

        best_item: dict[str, Any] | None = None
        best_score = -1.0
        best_detail: dict[str, Any] = {}

        for cand in candidates:
            c_title = zhconv.convert(cand.get("title") or "", "zh-cn").lower().strip()
            c_orig = zhconv.convert(cand.get("original_title") or "", "zh-cn").lower().strip()
            c_py = to_pinyin_key(cand.get("title") or "")

            sim_cn = SequenceMatcher(None, target_cn, c_title).ratio() if (target_cn and c_title) else 0.0
            sim_orig = SequenceMatcher(None, target_cn, c_orig).ratio() if (target_cn and c_orig) else 0.0
            sim_en = 0.0
            if target_en:
                sim_en = max(
                    SequenceMatcher(None, target_en, c_orig).ratio() if c_orig else 0.0,
                    SequenceMatcher(None, target_en, c_title).ratio() if c_title else 0.0,
                )

            exact_title = target_cn in (c_title, c_orig) or (bool(target_en) and target_en in (c_orig, c_title))
            phonetic_exact = bool(target_py and len(target_py) >= 4 and target_py == c_py)
            phonetic_sim = SequenceMatcher(None, target_py, c_py).ratio() if (target_py and c_py) else 0.0

            base = max(sim_cn, sim_orig, sim_en)
            if exact_title:
                base = max(base, 0.90)
            elif phonetic_exact:
                base = max(base, 0.86)
            elif phonetic_sim >= 0.88 and len(target_py) >= 5:
                base = max(base, 0.76)

            # 年份加减分
            year_bonus = 0.0
            if parsed.year and cand.get("year"):
                diff = abs(int(parsed.year) - int(cand["year"]))
                if diff == 0:
                    year_bonus = 0.08
                elif diff == 1:
                    year_bonus = 0.03
                else:
                    year_bonus = -0.12

            # 剧集/电影类型吻合度加减分
            type_bonus = 0.0
            if parsed.media_type_hint:
                if cand.get("media_type") == parsed.media_type_hint:
                    type_bonus = 0.06
                else:
                    type_bonus = -0.14

            # 中英双语双重命中加成
            bilingual_bonus = 0.05 if (sim_cn >= 0.85 and sim_en >= 0.85) else 0.0

            total = max(0.0, min(0.99, base + year_bonus + type_bonus + bilingual_bonus))
            if total > best_score:
                best_score = total
                best_item = cand
                best_detail = {
                    "exact_title": exact_title,
                    "phonetic_exact": phonetic_exact,
                    "bilingual_verified": bilingual_bonus > 0,
                    "year_matched": year_bonus > 0,
                    "target_init": target_init,
                }

        return best_item, best_score, best_detail

    def _attach_local_preview(self, cand: dict[str, Any] | None) -> dict[str, Any] | None:
        if not cand:
            return None
        copied = dict(cand)
        poster_remote = copied.get("poster_remote") or ""
        if poster_remote:
            local_rel = self._tmdb.cache_image(poster_remote, size="w342", category="thumbs")
            copied["poster_local"] = local_rel
        else:
            copied["poster_local"] = ""
        return copied

    @staticmethod
    def _compose_reasoning(
        *,
        parsed: ParsedMediaName,
        final_inferred: str,
        matched_work: dict[str, Any] | None,
        score: float,
        match_detail: dict[str, Any],
        ai_used: bool,
        ai_note: str,
    ) -> str:
        steps: list[str] = []
        if parsed.applied_rules:
            steps.append("规则处理：" + "、".join(parsed.applied_rules) + "。")
        else:
            steps.append(f"规则提取片名「{parsed.cleaned_name}」。")

        if parsed.is_non_media_likely and score < 0.85:
            steps.append("文件名或目录包含教程/课程特征词，疑似非标准影视资源，请人工核对或手动指定。")

        if matched_work:
            m_type_cn = "剧集" if matched_work["media_type"] == "tv" else "电影"
            yr_str = f" ({matched_work['year']})" if matched_work.get("year") else ""
            evidence: list[str] = []
            if match_detail.get("bilingual_verified"):
                evidence.append("中英双语片名双重吻合")
            elif match_detail.get("exact_title"):
                evidence.append("标准译名/原名精确命中")
            elif match_detail.get("phonetic_exact"):
                evidence.append(f"全拼声韵与《{matched_work['title']}》完全一致（还原谐音/拼音防和谐改写）")
            if match_detail.get("year_matched"):
                evidence.append("发行年份一致")
            if parsed.season_number is not None and parsed.episode_number is not None:
                evidence.append(f"对应 S{parsed.season_number:02d}E{parsed.episode_number:02d}")
            ev_text = "，".join(evidence) if evidence else f"综合匹配度 {int(round(score * 100))}%"
            steps.append(f"TMDB 匹配到{m_type_cn}《{matched_work['title']}》{yr_str}（{ev_text}）。")
        else:
            steps.append(f"以「{final_inferred}」检索 TMDB 未找到高可信度条目，可在右侧手动搜索并指定作品。")

        if ai_note:
            steps.append(ai_note)
        elif not ai_used and parsed.is_obfuscated:
            steps.append("（未使用 AI，由本地防和谐规则与拼音声韵引擎完成还原并经 TMDB 校验）")

        return " ".join(steps)
