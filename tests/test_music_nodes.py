import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "music_nodes.py"
SPEC = importlib.util.spec_from_file_location("zf_prompt_director_music_nodes", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_auto_language_defaults_to_chinese_and_requires_explicit_english():
    auto = MODULE.LYRICS_LANGUAGE_OPTIONS[0]

    assert MODULE.resolve_lyrics_language("English rock，校园毕业主题", auto) == "中文"
    assert MODULE.resolve_lyrics_language("校园毕业主题，使用英文歌词", auto) == "English"
    assert MODULE.resolve_lyrics_language("write English lyrics about graduation", auto) == "English"


def test_auto_vocal_mode_defaults_to_lyrics_but_honors_instrumental_request():
    auto = MODULE.VOCAL_MODE_OPTIONS[0]

    assert MODULE.resolve_vocal_mode("武侠风，戏剧唱腔", auto) == "有歌词"
    assert MODULE.resolve_vocal_mode("武侠风纯音乐，不要人声", auto) == "纯音乐"


def test_director_builds_separate_caption_and_lyrics_contract():
    node = MODULE.ZFMusic3PromptDirector()
    system, task, language, summary, seconds = node.build(
        user_request="校园民谣，毕业前最后一晚",
        lyrics_language=MODULE.LYRICS_LANGUAGE_OPTIONS[0],
        vocal_mode=MODULE.VOCAL_MODE_OPTIONS[0],
        target_duration=95,
    )

    assert "<<<MUSIC3_CAPTION>>>" in system
    assert "<<<MUSIC3_LYRICS>>>" in system
    assert "<<<REFERENCE_ANALYSIS>>>" in system
    assert "Caption 一律" in system
    assert "歌词语言：中文" in task
    assert "约 95 秒" in task
    assert language == "中文"
    assert "曲风与歌词分离输出" in summary
    assert seconds == 95.0


def test_duration_preset_overrides_custom_seconds_and_reference_mode_is_explicit():
    node = MODULE.ZFMusic3PromptDirector()
    _, task, _, summary, seconds = node.build(
        user_request="武侠摇滚，女声",
        target_duration=45,
        duration_preset="180 秒｜长篇歌曲",
        reference_mode="只参考曲风",
    )

    assert seconds == 180.0
    assert "目标时长：约 180 秒" in task
    assert "严禁迁移歌词主题" in task
    assert "只参考曲风" in summary


def test_parser_splits_marked_output_and_validates_official_structure():
    response = """<<<REFERENCE_ANALYSIS>>>
Warm acoustic palette and short conversational lyric lines; no source wording retained.
<<<MUSIC3_CAPTION>>>
### Global Metadata
A warm Chinese campus folk-pop song at a relaxed mid-tempo pace.
### Vocal Details
An intimate female lead with natural phrasing and light chorus harmonies.
### Arrangement
[Intro] begins with acoustic guitar; [Chorus] adds brushed drums and bass.
<<<MUSIC3_LYRICS>>>
[Intro]
晚风翻过旧操场
[Verse]
粉笔灰落在肩上
[Chorus]
把明天写进这一晚
[Outro]
铃声很远
<<<END>>>"""

    caption, lyrics, valid, report, analysis = MODULE.ZFMusic3ResponseParser().parse(response, "中文")

    assert caption.startswith("### Global Metadata")
    assert lyrics.startswith("[Intro]")
    assert valid is True
    assert "可直接连接" in report
    assert "已返回参考分析" in report
    assert analysis.startswith("Warm acoustic")


def test_parser_accepts_json_fallback_and_reports_unsupported_tags():
    response = (
        '{"caption":"### Global Metadata\\nFolk pop.\\n### Vocal Details\\nFemale lead.\\n'
        '### Arrangement\\nAcoustic build.","lyrics":"[Verse 1]\\n测试\\n[Chorus]\\n副歌"}'
    )

    caption, lyrics, valid, report, analysis = MODULE.ZFMusic3ResponseParser().parse(response, "中文")

    assert caption
    assert lyrics
    assert valid is False
    assert "Verse 1" in report
    assert analysis == ""
