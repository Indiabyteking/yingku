from __future__ import annotations

from app.services.name_parser import (
    collapse_cjk_delimiters,
    parse_media_filename,
    to_initials_key,
    to_pinyin_key,
)


def test_bilingual_tv_episode_cleaning():
    parsed = parse_media_filename(
        "兄弟连.Band.of.Brothers.S01E01.1080p.H265-NEW字幕组.mp4",
        parent_path="/资源/来自：分享/兄弟连",
    )
    assert parsed.inferred_title == "兄弟连"
    assert parsed.secondary_title == "Band of Brothers"
    assert parsed.season_number == 1
    assert parsed.episode_number == 1
    assert parsed.media_type_hint == "tv"
    assert "1080p" in parsed.version_label
    assert "H265" in parsed.version_label


def test_obfuscated_mixed_pinyin_and_dots_restoration():
    parsed = parse_media_filename(
        "【先转存防和谐】周·chu·除·三·hai.2023.2160p.WEB-DL.H265.mp4",
        parent_path="/资源/电影分享",
    )
    assert parsed.cleaned_name == "周·chu·除·三·hai"
    assert parsed.inferred_title == "周处除三害"
    assert parsed.year == 2023
    assert parsed.is_obfuscated is True
    assert "4K" in parsed.version_label


def test_obfuscated_shawshank_pinyin_and_ad_prefix():
    parsed = parse_media_filename(
        "【夸克首发】肖·shen·克·的·jiu·赎.1994.4K.HDR.10bit-珍藏版.mkv",
        parent_path="/baidu/我的资源",
    )
    assert parsed.inferred_title == "肖申克的救赎"
    assert parsed.year == 1994
    assert parsed.is_obfuscated is True


def test_traditional_and_homophone_restoration():
    parsed = parse_media_filename(
        "[免费分享严禁商用]無·堅·道.Infernal.Affairs.2002.1080p.国粤双语.mkv",
        parent_path="/baidu/港片合集",
    )
    assert parsed.inferred_title == "无间道"
    assert parsed.secondary_title == "Infernal Affairs"
    assert parsed.year == 2002
    assert parsed.is_obfuscated is True


def test_initials_abbreviation_with_parent_folder():
    parsed = parse_media_filename(
        "【关注公众号防失联】XDL.S01E05.1080p.BluRay.x265.mp4",
        parent_path="/资源/来自：分享/兄弟连",
    )
    assert parsed.inferred_title == "兄弟连"
    assert parsed.season_number == 1
    assert parsed.episode_number == 5
    assert parsed.is_obfuscated is True


def test_chinese_season_episode_and_numeric_fallback():
    p1 = parse_media_filename("庆余年.第二季第十二集.4K.HDR.mp4", parent_path="/剧集")
    assert p1.inferred_title == "庆余年"
    assert p1.season_number == 2
    assert p1.episode_number == 12

    p2 = parse_media_filename("07.mkv", parent_path="/baidu/我的资源/兄弟连/Season 1")
    assert p2.inferred_title == "兄弟连"
    assert p2.season_number == 1
    assert p2.episode_number == 7


def test_numeric_movie_title_not_stripped_as_year():
    parsed = parse_media_filename("1917.2019.2160p.UHD.BluRay.x265.mkv", parent_path="/movies")
    assert parsed.inferred_title == "1917"
    assert parsed.year == 2019


def test_pinyin_and_delimiter_helpers():
    collapsed, changed = collapse_cjk_delimiters("让*子*弹*飞")
    assert changed is True
    assert collapsed == "让子弹飞"
    assert to_pinyin_key("霸王bie姬") == to_pinyin_key("霸王别姬")
    assert to_initials_key("肖申克的救赎") == "xskdjs"
