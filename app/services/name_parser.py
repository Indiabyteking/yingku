from __future__ import annotations

import posixpath
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from pypinyin import Style, lazy_pinyin
import zhconv

VIDEO_EXT_RE = re.compile(
    r"\.(mp4|mkv|avi|mov|flv|ts|m2ts|m4v|webm|wmv|rmvb|mpg|mpeg|iso)$",
    re.IGNORECASE,
)

# 常见网盘广告、引流、防和谐提示前后缀
AD_BRACKET_PATTERNS = [
    re.compile(
        r"[\[【（(][^\]】）)]*(?:"
        r"公众号|关注|转存|河蟹|和谐|防删|秒删|免费分享|严禁商用|请勿|加微|微信|QQ群|"
        r"首发|独家|压制|出品|电影天堂|飘花|阳光电影|BT之家|迅雷|夸克|百度网盘|"
        r"密码|解压|必看|说明|更新|合集|珍藏|收藏|高清影视|高清资源|无水印|"
        r"www\.|\.com|\.net|\.cc|\.org|\.fun|\.tv"
        r")[^\]】）)]*[\]】）)]",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:赠送|附赠|福利|必看)[：:]\s*"),
    re.compile(r"^(?:来自[：:]\s*分享)\s*"),
]

# 分辨率、编码、音源、片源、字幕组等技术噪声标签
RESOLUTION_RE = re.compile(r"\b(4K|8K|2160p|1440p|1080p|1080i|720p|576p|480p|UHD|FHD|HD)\b", re.IGNORECASE)
HDR_RE = re.compile(r"\b(HDR10\+?|HDR|Dolby[\s._-]?Vision|DoVi|DV|SDR|10bit|8bit|12bit)\b", re.IGNORECASE)
CODEC_RE = re.compile(r"\b(H\.?265|H\.?264|HEVC|AVC|x265|x264|AV1|VP9|MPEG-?2|XviD|DivX)\b", re.IGNORECASE)
SOURCE_RE = re.compile(
    r"\b(Blu-?Ray|BluRay|BDRip|BDMux|REMUX|WEB-?DL|WEBRip|HDTV|DVDRip|NF|AMZN|DSNP|ATVP|HMAX|Baha|CR)\b",
    re.IGNORECASE,
)
AUDIO_RE = re.compile(
    r"\b(TrueHD|Atmos|DTS-?HD(?:\.?MA)?|DTS-?X|DTS|DDP\s*5\.1|DD\+?5\.1|EAC3|AC3|AAC(?:2\.0|5\.1)?|FLAC|LPCM|2Audio|3Audio)\b",
    re.IGNORECASE,
)
SUB_LANG_RE = re.compile(
    r"(?:中英双字|中英字幕|中文字幕|双语字幕|特效字幕|简繁中字|简繁字幕|内封字幕|内嵌中字|国粤双语|国英双语|粤语中字|国语配音|台配国语|"
    r"[A-Za-z0-9\u4e00-\u9fff]{1,10}(?:字幕组|压制组|影视组|译制组)|CHS[-_.]?CHT|CHS|CHT)",
    re.IGNORECASE,
)

# 季集识别正则
SXXEXX_RE = re.compile(r"(?:^|[\s._\-\[\(【])S(\d{1,2})[\s._\-]*E(\d{1,3})(?:$|[\s._\-\]\)】vV])", re.IGNORECASE)
CN_SEASON_EP_RE = re.compile(r"第\s*([0-9一二三四五六七八九十]{1,3})\s*季[\s._\-]*第\s*([0-9一二三四五六七八九十百]{1,4})\s*[集话話期]")
CN_SEASON_ONLY_RE = re.compile(r"第\s*([0-9一二三四五六七八九十]{1,3})\s*季")
EN_SEASON_ONLY_RE = re.compile(r"\bSeason[\s._\-]*(\d{1,2})\b|\bS(\d{1,2})\b", re.IGNORECASE)
CN_EP_ONLY_RE = re.compile(r"第\s*([0-9一二三四五六七八九十百]{1,4})\s*[集话話期]")
EP_PREFIX_RE = re.compile(r"(?:^|[\s._\-\[\(])EP?(\d{1,3})(?:$|[\s._\-\]\)])", re.IGNORECASE)
BRACKET_EP_RE = re.compile(r"\[(\d{2,3})\](?!\s*[pP])")

YEAR_RE = re.compile(r"(?:(?<=^)|(?<=[\s._\(\[（【\-]))((?:19\d{2}|20[0-3]\d))(?=$|[\s._\)\]）】\-])")

# 非影视教程/课件特征词（用于降低误判置信度，归入待核对/未识别）
NON_MEDIA_KEYWORDS = (
    "教程",
    "课程",
    "网课",
    "实验",
    "操作题",
    "真题",
    "精听",
    "模考",
    "背单词",
    "导学",
    "题型",
    "数据库",
    "安装与使用说明",
    "使用流程",
    "教学录屏",
    "能干什么",
)

# 常见防和谐夹杂拼音、谐音字与形近字映射词典
OBFUSCATED_PHRASE_MAP: dict[str, str] = {
    # 夹杂拼音防和谐
    "肖shen克的jiu赎": "肖申克的救赎",
    "肖shen克de救shu": "肖申克的救赎",
    "肖申克的jiu赎": "肖申克的救赎",
    "绝ming毒shi": "绝命毒师",
    "绝mingdu师": "绝命毒师",
    "绝命du师": "绝命毒师",
    "周chu除三hai": "周处除三害",
    "周处除三hai": "周处除三害",
    "寄sheng虫": "寄生虫",
    "无jian道": "无间道",
    "让zi弹fei": "让子弹飞",
    "让子弹fei": "让子弹飞",
    "hei客帝国": "黑客帝国",
    "兄di连": "兄弟连",
    "狂biao": "狂飙",
    "这个sha手不太冷": "这个杀手不太冷",
    "sha手不太冷": "这个杀手不太冷",
    "si侍": "死侍",
    "du战": "毒战",
    "qiang火": "枪火",
    "se戒": "色戒",
    "fu山行": "釜山行",
    "奥ben海mo": "奥本海默",
    "星ji穿yue": "星际穿越",
    "盗meng空jian": "盗梦空间",
    "我不是yao神": "我不是药神",
    # 常见谐音字与形近字改写
    "消申克的救赎": "肖申克的救赎",
    "消深克的救赎": "肖申克的救赎",
    "尚申克的救赎": "肖申克的救赎",
    "肖申克的救熟": "肖申克的救赎",
    "绝命读师": "绝命毒师",
    "绝名毒师": "绝命毒师",
    "周楚除三害": "周处除三害",
    "寄牲虫": "寄生虫",
    "寄声虫": "寄生虫",
    "斧山行": "釜山行",
    "无坚道": "无间道",
    "让子蛋飞": "让子弹飞",
    "黑克帝国": "黑客帝国",
    "歹侍": "死侍",
    "刹破狼": "杀破狼",
    "狂飚": "狂飙",
    "甄环传": "甄嬛传",
    "我不是要神": "我不是药神",
    "权力的游侠": "权力的游戏",
    "权利的游戏": "权力的游戏",
}

# 高频网盘拼音首字母缩写词典
ABBREVIATION_TITLE_MAP: dict[str, str] = {
    "xskdjs": "肖申克的救赎",
    "jmds": "绝命毒师",
    "xdl": "兄弟连",
    "zccsh": "周处除三害",
    "wjd": "无间道",
    "rzdf": "让子弹飞",
    "bwbj": "霸王别姬",
    "hkdg": "黑客帝国",
    "xjcy": "星际穿越",
    "dmkj": "盗梦空间",
    "abhm": "奥本海默",
    "qyn": "庆余年",
    "jsc": "寄生虫",
    "fsx": "釜山行",
    "wbsys": "我不是药神",
    "lldq": "流浪地球",
    "zgsstbl": "这个杀手不太冷",
    "ygz": "阳光灿烂的日子",
    "qldyx": "权力的游戏",
    "kb": "狂飙",
    "sm": "三体",
}

CN_NUM_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def parse_cn_number(raw: str) -> int | None:
    s = raw.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        parts = s.split("十", 1)
        tens = CN_NUM_MAP.get(parts[0], 1) if parts[0] else 1
        ones = CN_NUM_MAP.get(parts[1], 0) if parts[1] else 0
        return tens * 10 + ones
    total = 0
    for ch in s:
        if ch not in CN_NUM_MAP:
            return None
        total = total * 10 + CN_NUM_MAP[ch]
    return total


def to_pinyin_key(text: str) -> str:
    """生成用于同音/夹杂拼音比对的连续无声调拼音串。"""
    normalized = zhconv.convert(unicodedata.normalize("NFKC", text or ""), "zh-cn")
    tokens = lazy_pinyin(normalized, style=Style.NORMAL, errors="default")
    joined = "".join(tokens).lower()
    return re.sub(r"[^a-z0-9]", "", joined)


def to_initials_key(text: str) -> str:
    """提取中文文本的拼音首字母缩写。"""
    normalized = zhconv.convert(unicodedata.normalize("NFKC", text or ""), "zh-cn")
    cjk_only = "".join(ch for ch in normalized if "\u4e00" <= ch <= "\u9fff")
    if not cjk_only:
        return ""
    return "".join(lazy_pinyin(cjk_only, style=Style.FIRST_LETTER)).lower()


def collapse_cjk_delimiters(text: str) -> tuple[str, bool]:
    """还原汉字之间插入的点号、下划线、星号、斜杠、空格等防和谐分隔符。"""
    prev = text
    # 连续匹配“单字 + 分隔符 + 单字”
    pattern = re.compile(r"(?<=[\u4e00-\u9fff])\s*[·•._\-*/|~\\+\s]\s*(?=[\u4e00-\u9fff])")
    collapsed = pattern.sub("", prev)
    # 处理如“周·chu·除·三·hai”中汉字与短拼音之间的间隔符
    mixed_sep = re.compile(
        r"(?<=[\u4e00-\u9fff])\s*[·•_*|~/\\]\s*(?=[a-zA-Z]{1,6}(?:$|[\s·•_*|~/\\\u4e00-\u9fff]))|"
        r"(?<=[a-zA-Z])\s*[·•_*|~/\\]\s*(?=[\u4e00-\u9fff])"
    )
    collapsed = mixed_sep.sub("", collapsed)
    return collapsed, collapsed != prev


@dataclass
class ParsedMediaName:
    raw_name: str
    parent_path: str
    cleaned_name: str
    inferred_title: str
    secondary_title: str = ""
    year: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    media_type_hint: str = ""  # "movie", "tv", or ""
    version_label: str = ""
    is_obfuscated: bool = False
    is_non_media_likely: bool = False
    applied_rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_name": self.raw_name,
            "parent_path": self.parent_path,
            "cleaned_name": self.cleaned_name,
            "inferred_title": self.inferred_title,
            "secondary_title": self.secondary_title,
            "year": self.year,
            "season_number": self.season_number,
            "episode_number": self.episode_number,
            "media_type_hint": self.media_type_hint,
            "version_label": self.version_label,
            "is_obfuscated": self.is_obfuscated,
            "is_non_media_likely": self.is_non_media_likely,
            "applied_rules": list(self.applied_rules),
        }


def parse_media_filename(filename: str, parent_path: str = "/") -> ParsedMediaName:
    """
    第一阶段：基于规则清洗网盘文件名、提取季集与画质版本，并还原常见防和谐改写。
    """
    rules: list[str] = []
    raw_name = (filename or "").strip()
    norm = unicodedata.normalize("NFKC", raw_name)

    # 1. 去扩展名
    stem = VIDEO_EXT_RE.sub("", norm).strip()

    # 检测是否疑似非影视教程/课件
    combined_context = f"{parent_path}/{stem}"
    is_non_media = any(kw in combined_context for kw in NON_MEDIA_KEYWORDS)

    # 2. 提取画质/编码信息用于多版本展示（如 "4K · HDR · H265"）
    version_parts: list[str] = []
    res_m = RESOLUTION_RE.search(stem)
    if res_m:
        tag = res_m.group(1).upper().replace("2160P", "4K").replace("1080P", "1080p").replace("720P", "720p")
        version_parts.append(tag)
    hdr_m = HDR_RE.search(stem)
    if hdr_m:
        h_val = hdr_m.group(1).upper()
        version_parts.append("Dolby Vision" if "VISION" in h_val or h_val in ("DOVI", "DV") else h_val)
    src_m = SOURCE_RE.search(stem)
    if src_m:
        version_parts.append(src_m.group(1))
    codec_m = CODEC_RE.search(stem)
    if codec_m:
        version_parts.append(codec_m.group(1).upper().replace("H.265", "H265").replace("H.264", "H264"))

    # 3. 清除广告/引流括号前后缀
    working = stem
    for pat in AD_BRACKET_PATTERNS:
        updated = pat.sub(" ", working)
        if updated != working:
            if "去除广告/防和谐前后缀" not in rules:
                rules.append("去除广告/防和谐前后缀")
            working = updated

    # 4. 解析季号与集号（同时截断季集号之后的噪声后缀）
    season_no: int | None = None
    episode_no: int | None = None
    cut_pos: int | None = None

    m_se = SXXEXX_RE.search(working)
    if m_se:
        season_no = int(m_se.group(1))
        episode_no = int(m_se.group(2))
        cut_pos = m_se.start()
        rules.append(f"解析季集标签 S{season_no:02d}E{episode_no:02d}")
    else:
        m_cn_se = CN_SEASON_EP_RE.search(working)
        if m_cn_se:
            season_no = parse_cn_number(m_cn_se.group(1))
            episode_no = parse_cn_number(m_cn_se.group(2))
            cut_pos = m_cn_se.start()
            rules.append(f"解析中文季集 第{season_no}季第{episode_no}集")
        else:
            m_cn_ep = CN_EP_ONLY_RE.search(working)
            if m_cn_ep:
                episode_no = parse_cn_number(m_cn_ep.group(1))
                cut_pos = m_cn_ep.start()
                rules.append(f"解析集号 第{episode_no}集")
            else:
                m_ep = EP_PREFIX_RE.search(working)
                if m_ep:
                    episode_no = int(m_ep.group(1))
                    cut_pos = m_ep.start()
                    rules.append(f"解析集号 E{episode_no:02d}")
                else:
                    m_br = BRACKET_EP_RE.search(working)
                    if m_br:
                        episode_no = int(m_br.group(1))
                        cut_pos = m_br.start()
                        rules.append(f"解析方括号集号 [{episode_no:02d}]")

    # 从目录路径补充季号（如 /兄弟连/Season 1/01.mp4）
    parent_clean = unicodedata.normalize("NFKC", parent_path or "")
    if season_no is None:
        m_ps_cn = CN_SEASON_ONLY_RE.search(parent_clean)
        if m_ps_cn:
            season_no = parse_cn_number(m_ps_cn.group(1))
        else:
            m_ps_en = EN_SEASON_ONLY_RE.search(parent_clean)
            if m_ps_en:
                season_no = int(m_ps_en.group(1) or m_ps_en.group(2))

    # 纯数字集号文件名（如 /兄弟连/03.mp4）
    if episode_no is None and re.fullmatch(r"0*(\d{1,3})", working.strip()):
        num_val = int(working.strip())
        if 1 <= num_val <= 300:
            episode_no = num_val
            working = ""
            rules.append(f"纯数字文件名识别为第 {episode_no} 集")

    if episode_no is not None and season_no is None:
        season_no = 1

    if cut_pos is not None and cut_pos > 0:
        working = working[:cut_pos]
    elif cut_pos == 0:
        # 季集号在最开头（如 S01E01.Band.of.Brothers...），去掉季集片段继续清洗
        working = SXXEXX_RE.sub(" ", working, count=1)
        working = CN_SEASON_EP_RE.sub(" ", working, count=1)
        working = CN_EP_ONLY_RE.sub(" ", working, count=1)
        working = EP_PREFIX_RE.sub(" ", working, count=1)

    # 5. 解析发行年份（截断年份后的画质后缀）
    year: int | None = None
    year_matches = list(YEAR_RE.finditer(working))
    if year_matches:
        ym = year_matches[-1]
        cand_year = int(ym.group(1))
        # 若年份不在最开头（避免电影《1917》《2012》《2046》片名本身被截空）
        prefix_before_year = working[: ym.start()].strip(" ._-([（【")
        if prefix_before_year:
            year = cand_year
            working = prefix_before_year
            rules.append(f"提取年份 {year}")
        else:
            # 片名本身即为年份（如 1917.2019.1080p 中第一次匹配或单独 1917）
            pass

    # 若文件名里没解析出年份，看上级文件夹是否带年份
    if year is None:
        folder_name = posixpath.basename(parent_clean.rstrip("/"))
        f_ym = YEAR_RE.search(folder_name)
        if f_ym and folder_name[: f_ym.start()].strip(" ._-([（【"):
            year = int(f_ym.group(1))

    # 6. 剔除分辨率、编码、片源、音轨与字幕组噪声
    before_tech = working
    for regex in (RESOLUTION_RE, HDR_RE, CODEC_RE, SOURCE_RE, AUDIO_RE, SUB_LANG_RE):
        working = regex.sub(" ", working)
    if working != before_tech:
        rules.append("清洗分辨率/编码/字幕组标签")

    # 清理残余括号及首尾分隔符
    working = re.sub(r"[\[\]【】()（）《》「」『』]", " ", working)
    working = re.sub(r"[-_.]+", " ", working)
    working = re.sub(r"\s+", " ", working).strip()

    # 如果文件名本身只剩集号/空白，从上级目录提取片名！
    if not working or len(working) <= 1 and not ("\u4e00" <= working <= "\u9fff"):
        parent_folder = _pick_meaningful_parent_folder(parent_clean)
        if parent_folder:
            working = parent_folder
            rules.append(f"文件名无片名，回退取上级目录名「{parent_folder}」")

    cleaned_name = working

    # 7. 防和谐改写还原流水线
    restored, secondary_en, obf_flag, obf_rules = restore_obfuscated_title(cleaned_name, parent_clean)
    rules.extend(obf_rules)

    media_type_hint = "tv" if (season_no is not None or episode_no is not None) else ""
    version_label = " · ".join(dict.fromkeys(version_parts)) if version_parts else "标准版"

    return ParsedMediaName(
        raw_name=raw_name,
        parent_path=parent_path,
        cleaned_name=cleaned_name or raw_name,
        inferred_title=restored or cleaned_name or raw_name,
        secondary_title=secondary_en,
        year=year,
        season_number=season_no,
        episode_number=episode_no,
        media_type_hint=media_type_hint,
        version_label=version_label,
        is_obfuscated=obf_flag,
        is_non_media_likely=is_non_media,
        applied_rules=rules,
    )


def _pick_meaningful_parent_folder(parent_path: str) -> str:
    parts = [p.strip() for p in parent_path.replace("\\", "/").split("/") if p.strip()]
    ignore_names = {"baidu", "资源", "我的资源", "来自：分享", "我的备份", "video", "movies", "tv"}
    for folder in reversed(parts):
        if folder.lower() in ignore_names:
            continue
        if re.fullmatch(r"(?:Season\s*\d+|S\d{1,2}|第[0-9一二三四五六七八九十]+季)", folder, flags=re.IGNORECASE):
            continue
        cleaned_folder = YEAR_RE.sub(" ", folder)
        cleaned_folder = RESOLUTION_RE.sub(" ", cleaned_folder)
        cleaned_folder = re.sub(r"[\[【（(][^\]】）)]*[\]】）)]", " ", cleaned_folder)
        cleaned_folder = re.sub(r"\s+", " ", cleaned_folder).strip(" ._-")
        if cleaned_folder:
            return cleaned_folder
    return ""


def restore_obfuscated_title(
    cleaned_name: str,
    parent_path: str = "",
) -> tuple[str, str, bool, list[str]]:
    """
    针对网盘常见的防和谐手段做本地还原：
    1. 合并汉字间插入的分隔符/空格（如 肖·申·克·的·救·赎）
    2. 繁体转简体统一（如 無間道 -> 无间道）
    3. 分离中英双语片名（如 兄弟连 Band of Brothers）
    4. 还原夹杂拼音、谐音字、形近字与首字母缩写（如 肖shen克的jiu赎、XDL）
    """
    rules: list[str] = []
    is_obfuscated = False
    text = cleaned_name.strip()
    if not text:
        return "", "", False, rules

    # Step A: 还原原始文件名中可能残留的点/星号/竖线/空格等防和谐分隔符
    delim_collapsed, did_delim = collapse_cjk_delimiters(text)
    spaced_collapsed, did_space = _collapse_spaced_single_cjk(delim_collapsed)
    if did_delim or did_space:
        text = spaced_collapsed
        is_obfuscated = True
        rules.append("合并插入在片名文字间的分隔符/空格")

    # Step B: 繁简混用归一
    simplified = zhconv.convert(text, "zh-cn")
    if simplified != text:
        text = simplified
        is_obfuscated = True
        rules.append("繁体字转为简体中文")

    # Step C: 检查是否命中防和谐夹杂拼音/谐音词典（忽略大小写与词内空格后匹配，同时保留英文副标题空格）
    compact_lower = text.replace(" ", "").lower()
    for obf_key, canonical in OBFUSCATED_PHRASE_MAP.items():
        if obf_key.lower() in compact_lower:
            spaced_pat = r"\s*".join(re.escape(ch) for ch in obf_key)
            text = re.sub(spaced_pat, canonical, text, flags=re.IGNORECASE)
            is_obfuscated = True
            rules.append(f"还原防和谐谐音/拼音改写「{obf_key} → {canonical}」")
            break

    # Step D: 处理纯字母首字母缩写（优先结合父目录中文名首字母，其次查高频缩写词典）
    alpha_only = text.replace(" ", "").lower()
    if re.fullmatch(r"[a-z]{2,10}", alpha_only):
        parent_folder = _pick_meaningful_parent_folder(parent_path)
        if parent_folder:
            parent_simp = zhconv.convert(parent_folder, "zh-cn")
            if to_initials_key(parent_simp) == alpha_only or to_pinyin_key(parent_simp) == alpha_only:
                is_obfuscated = True
                rules.append(f"结合上级目录还原首字母/拼音缩写「{text} → {parent_simp}」")
                return parent_simp, "", is_obfuscated, rules

        if alpha_only in ABBREVIATION_TITLE_MAP:
            mapped = ABBREVIATION_TITLE_MAP[alpha_only]
            is_obfuscated = True
            rules.append(f"还原常见片名拼音首字母缩写「{text} → {mapped}」")
            return mapped, "", is_obfuscated, rules

    # Step E: 中英双语片名切分（如 "兄弟连 Band of Brothers"）
    # 注意：只有英文部分包含多个单词或长度 >= 4 且不是嵌入中文内部的拼音时才切分
    bilingual_match = re.match(
        r"^([\u4e00-\u9fff0-9：:·《》—\-]{2,25})\s+([A-Za-z][A-Za-z0-9\s'&:\-]{3,})$",
        text,
    )
    if bilingual_match:
        cn_part = bilingual_match.group(1).strip()
        en_part = bilingual_match.group(2).strip()
        rules.append(f"分离中英双语标题「{cn_part} / {en_part}」")
        return cn_part, en_part, is_obfuscated, rules

    # 检测是否仍含有“汉字中夹杂小写拼音”的防和谐形态（后续将通过 TMDB 候选拼音比对进一步还原）
    if re.search(r"[\u4e00-\u9fff]+[a-zA-Z]{1,6}[\u4e00-\u9fff]*|[a-zA-Z]{2,6}[\u4e00-\u9fff]{2,}", text.replace(" ", "")):
        is_obfuscated = True
        text = text.replace(" ", "")
        if not any("防和谐" in r for r in rules):
            rules.append("检测到中英/拼音混写防和谐特征，启用声韵校验匹配")

    return text.strip(), "", is_obfuscated, rules


def _collapse_spaced_single_cjk(text: str) -> tuple[str, bool]:
    tokens = text.split()
    if len(tokens) < 2:
        return text, False

    # 如果存在连续的单汉字 token（如 "肖 申 克 的 救 赎" 或 "兄 弟 连 Band of Brothers"），将其合并
    out: list[str] = []
    cjk_buf: list[str] = []
    merged_any = False

    def is_short_cjk_or_pinyin_piece(tok: str) -> bool:
        if len(tok) == 1 and "\u4e00" <= tok <= "\u9fff":
            return True
        return False

    for tok in tokens:
        if is_short_cjk_or_pinyin_piece(tok):
            cjk_buf.append(tok)
        else:
            if len(cjk_buf) >= 2:
                out.append("".join(cjk_buf))
                merged_any = True
            elif cjk_buf:
                out.extend(cjk_buf)
            cjk_buf = []
            out.append(tok)

    if len(cjk_buf) >= 2:
        out.append("".join(cjk_buf))
        merged_any = True
    elif cjk_buf:
        out.extend(cjk_buf)

    # 二次检查类似 "周 chu 除 三 hai" 这种单字与短拼音交替被空格拆开的情况
    result = " ".join(out)
    alt_pat = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
    collapsed2 = alt_pat.sub("", result)
    if collapsed2 != result:
        merged_any = True
        result = collapsed2

    return result, merged_any
