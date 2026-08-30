"""Prompt-building utilities for MiniMax Music 3 workflows.

The Music 3 encoder accepts two independent text inputs: ``caption`` controls
the sound and arrangement, while ``lyrics`` controls the words and section
structure. These nodes keep that boundary intact while allowing one language
model call to design both parts coherently.
"""

from __future__ import annotations

import json
import re


LYRICS_LANGUAGE_OPTIONS = (
    "自动｜默认中文，明确要求英文才英文",
    "中文",
    "English",
)
VOCAL_MODE_OPTIONS = (
    "自动｜默认有歌词",
    "有歌词",
    "纯音乐",
)
DURATION_PRESET_OPTIONS = (
    "自定义｜使用下方秒数",
    "15 秒｜灵感片段",
    "30 秒｜片段/短歌",
    "45 秒｜短歌",
    "60 秒｜完整短歌",
    "90 秒｜标准单曲",
    "120 秒｜完整单曲",
    "150 秒｜完整单曲",
    "180 秒｜长篇歌曲",
    "240 秒｜长篇叙事",
    "300 秒｜长篇叙事",
    "360 秒｜Music3 上限",
)
REFERENCE_MODE_OPTIONS = (
    "自动｜有音频参考曲风+词风，无音频纯文本",
    "参考曲风+词风",
    "只参考曲风",
    "只参考词风",
    "纯文本｜不参考音频",
)

_ENGLISH_REQUEST_PATTERNS = (
    r"英文(?:歌|歌曲|歌词|演唱|唱词)",
    r"(?:歌词|演唱|唱词)(?:使用|用|为|写成)?\s*英文",
    r"用英文(?:写|唱|创作|作词)",
    r"english\s+(?:lyrics?|vocals?|language)",
    r"lyrics?\s+in\s+english",
    r"sing(?:ing)?\s+in\s+english",
)
_INSTRUMENTAL_REQUEST_PATTERNS = (
    r"纯音乐",
    r"无人声",
    r"不要(?:人声|演唱|歌词)",
    r"无歌词",
    r"instrumental",
    r"no\s+(?:vocals?|lyrics?)",
)

_REFERENCE_MARKER = "<<<REFERENCE_ANALYSIS>>>"
_CAPTION_MARKER = "<<<MUSIC3_CAPTION>>>"
_LYRICS_MARKER = "<<<MUSIC3_LYRICS>>>"
_END_MARKER = "<<<END>>>"
_CAPTION_HEADINGS = (
    "### Global Metadata",
    "### Vocal Details",
    "### Arrangement",
)
_SUPPORTED_LYRIC_TAGS = {
    "intro": "Intro",
    "verse": "Verse",
    "pre-chorus": "Pre-Chorus",
    "chorus": "Chorus",
    "post-chorus": "Post-Chorus",
    "bridge": "Bridge",
    "instrumental": "Instrumental",
    "solo": "Solo",
    "outro": "Outro",
}


MUSIC3_WRITER_SYSTEM_PROMPT = r"""你是 MiniMax Music 3 的歌曲创意导演、音乐参考分析师、原创作词人和结构化 Caption 作者。你要把用户要求以及可选参考音频反推成一套可以直接生成歌曲的“曲风说明 + 歌词”，但二者必须保持为两个独立文本块。

【输入优先级】
1. 用户明确要求、排除项、语言、人声、题材、情节、唱腔、乐器和时长。
2. 已有歌词中的内容与段落标签。
3. 用户描述强烈暗示的音乐方向。
4. 保守、连贯的音乐默认值。
不要静默改变用户指定的人声性别、语言、纯音乐要求、必需乐器或禁止项。校园、武侠、戏剧、节庆等首先是题材或文化语境，不要机械地把它们当成唯一曲风标签；要为它们选择真正可演唱、可编曲的主风格与必要融合。

【参考音频规则】
1. 任务会明确指定参考模式。只有请求中实际附带音频时才允许声称听到参考音频；没有音频时必须按纯文本完成，不得虚构分析。
2. “参考曲风+词风”同时提取风格、速度/律动、情绪弧线、人声、编曲、制作质感，以及歌词语言、叙事视角、句长、押韵密度、段落节奏和副歌钩子机制。
3. “只参考曲风”不得借用参考音频中的歌词主题、人物、意象、叙事或原句；只迁移高层音乐特征。
4. “只参考词风”不得沿用参考音频的旋律、节拍、乐器、音色或制作；只迁移抽象的语言与结构特征。
5. 参考音频永远只是可迁移特征来源。不得识别、猜测或输出歌名和歌手，不得复现原歌词或模仿在世艺人的独特表达。用户提示与排除项优先于参考音频。

【先在内部建立 Music Brief】
提取主风格与子风格、文化与市场语境、情绪弧线、大致速度和律动、人声配置与音色、核心乐器、制作质感、段落结构、空间感和排除项。只在用户明确要求或音乐上确有必要时写精确 BPM、调性和音阶；否则使用速度范围或定性描述。曲风冲突时，以音乐连贯性做最小折中，不堆砌互相竞争的标签。

【歌词规则】
1. 严格使用任务中已经解析好的歌词语言，不根据用户输入本身是中文还是英文再次猜测。默认中文；只有用户明确要求英文时才写英文。
2. 写全新原创歌词，不续写、仿写或复现现有受版权保护歌词，也不模仿在世艺人的独特措辞。用户提到歌手或作品时，只提炼高层音乐特征。
3. 只允许以下段落标签，且标签必须独占一行：[Intro]、[Verse]、[Pre-Chorus]、[Chorus]、[Post-Chorus]、[Bridge]、[Instrumental]、[Solo]、[Outro]。不要写 [Verse 1]、[Hook]、括号标签或把演奏说明写在标签同行。
4. 乐器、速度、强弱、混响、转调和演唱控制写入 Arrangement，不混进歌词正文。歌词正文只保留可唱文字；可用简短自然的拟声、和声或念白，但不要写制作指令。
5. 歌词要围绕用户要求建立清楚视角、具体意象、推进和可记忆副歌钩子。中文歌词优先自然口语与可唱句长，不为押韵牺牲语义。校园题材避免只有名词清单；武侠题材要有人物选择与江湖关系；戏剧唱腔要把表演方式放入 Vocal Details，并让歌词使用适合舞台表达的句式，而不是堆砌“戏腔”标签。
6. 若为纯音乐，不写任何可唱词，只用 [Intro]、[Instrumental]、[Solo]、[Outro] 组织结构。

【Structured Caption 规则】
Caption 一律使用专业、自然、简洁的英文，供 MiniMax Music 3 直接读取。不要写逗号标签堆；要写成给音乐人和制作人的创意简报。Caption 必须且只能包含以下三个三级标题，并按此顺序：
### Global Metadata
写主风格/子风格、合理速度、情绪与能量进程、适用场景、整体音色和制作轮廓。
### Vocal Details
有人声时写主唱配置、音域、音色、咬字、分段演唱变化、和声与克制的人声效果；纯音乐时明确 Instrumental, no vocals，并说明由什么乐器或纹理承担主旋律。
### Arrangement
按实际歌词段落建立时间线，具体说明各段进入、退出、增强或留白的主次乐器、鼓组与低频、转场、装饰和空间效果。曲风说明要与最终歌词的情绪和段落一致，但不要引用、改写或概括歌词句子。

【输出契约】
只输出下列四个标记和其中内容，不要解释，不要 Markdown 代码块，不要歌名、ID、推理过程或寒暄。参考分析只写实际采用的可迁移特征；纯文本模式写“Pure-text mode; no reference audio used.”：
<<<REFERENCE_ANALYSIS>>>
...
<<<MUSIC3_CAPTION>>>
### Global Metadata
...
### Vocal Details
...
### Arrangement
...
<<<MUSIC3_LYRICS>>>
[Intro]
...
<<<END>>>
"""


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def resolve_lyrics_language(user_request: str, selection: str) -> str:
    """Resolve language conservatively: auto means Chinese unless explicit."""

    chosen = str(selection or LYRICS_LANGUAGE_OPTIONS[0])
    if chosen == "English":
        return "English"
    if chosen == "中文":
        return "中文"
    return "English" if _contains_any(str(user_request or ""), _ENGLISH_REQUEST_PATTERNS) else "中文"


def resolve_vocal_mode(user_request: str, selection: str) -> str:
    chosen = str(selection or VOCAL_MODE_OPTIONS[0])
    if chosen == "纯音乐":
        return "纯音乐"
    if chosen == "有歌词":
        return "有歌词"
    return "纯音乐" if _contains_any(str(user_request or ""), _INSTRUMENTAL_REQUEST_PATTERNS) else "有歌词"


def resolve_duration_seconds(target_duration: object, duration_preset: str) -> int:
    match = re.match(r"\s*(\d+)\s*秒", str(duration_preset or ""))
    if match:
        return max(10, min(360, int(match.group(1))))
    return max(10, min(360, int(float(target_duration))))


def _reference_instruction(reference_mode: str) -> str:
    mode = str(reference_mode or REFERENCE_MODE_OPTIONS[0])
    if mode == "参考曲风+词风":
        return "若请求附带参考音频，分析并迁移其高层曲风与词风；若没有音频，明确按纯文本完成。"
    if mode == "只参考曲风":
        return "若请求附带参考音频，只迁移曲风、律动、人声、编曲和制作特征，严禁迁移歌词主题、意象、句子或叙事。"
    if mode == "只参考词风":
        return "若请求附带参考音频，只迁移歌词语言与结构特征，严禁迁移旋律、节拍、乐器、音色或制作。"
    if mode == "纯文本｜不参考音频":
        return "忽略请求中可能附带的音频，只根据用户提示、已有歌词和文字参考完成。"
    return "请求附带音频时同时参考高层曲风与词风；没有音频时自动按纯文本完成，绝不虚构听觉分析。"


def _duration_structure(seconds: int, instrumental: bool) -> str:
    if instrumental:
        return "使用 Intro → Instrumental → Solo（按需）→ Outro，段落数量与目标时长相称。"
    if seconds <= 75:
        return "使用紧凑结构：Intro → Verse → Chorus → Outro；副歌可以回归一次，但不要塞入过多歌词。"
    if seconds <= 150:
        return "使用完整但克制的结构：Intro → Verse → Pre-Chorus（按需）→ Chorus → Verse → Chorus → Bridge（按需）→ Final Chorus → Outro。"
    return "使用完整长歌结构并保留器乐呼吸：Intro → Verse → Pre-Chorus（按需）→ Chorus → Verse → Chorus → Instrumental/Solo（按需）→ Bridge → Final Chorus → Outro。"


def _clean_block(text: object) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json|text|markdown)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


class ZFMusic3PromptDirector:
    """Build one model-agnostic writing task for caption and lyrics."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_request": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "placeholder": "例如：校园民谣，毕业前最后一晚，女声；副歌要有一句容易记住的话",
                        "tooltip": "写题材、内容、人物、情绪、唱腔、乐器、结构和排除项；一句话也可以。",
                    },
                ),
                "lyrics_language": (
                    LYRICS_LANGUAGE_OPTIONS,
                    {"default": LYRICS_LANGUAGE_OPTIONS[0]},
                ),
                "vocal_mode": (
                    VOCAL_MODE_OPTIONS,
                    {"default": VOCAL_MODE_OPTIONS[0]},
                ),
                "target_duration": (
                    "INT",
                    {
                        "default": 120,
                        "min": 10,
                        "max": 360,
                        "step": 5,
                        "tooltip": "用于控制歌词密度和段落数量；请与 Music3 Text Encode 的 max_duration 大致一致。",
                    },
                ),
                "duration_preset": (
                    DURATION_PRESET_OPTIONS,
                    {
                        "default": DURATION_PRESET_OPTIONS[0],
                        "tooltip": "预设优先；选择自定义时使用上方 target_duration。输出秒数可直连 Music3 Text Encode.max_duration。",
                    },
                ),
                "reference_mode": (
                    REFERENCE_MODE_OPTIONS,
                    {
                        "default": REFERENCE_MODE_OPTIONS[0],
                        "tooltip": "配合 API 节点的可选 AUDIO 输入；无音频时自动退回纯文本反推。",
                    },
                ),
            },
            "optional": {
                "existing_lyrics": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "forceInput": True,
                        "tooltip": "可选：已有歌词或草稿。完整歌词默认保留原文，并据此反推曲风。",
                    },
                ),
                "style_reference": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "forceInput": True,
                        "tooltip": "可选：额外曲风、唱腔、乐器、制作或排除项；它是创作约束，不会直接拼接到最终 Caption。",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "FLOAT")
    RETURN_NAMES = ("writer_system_prompt", "writer_task", "resolved_language", "plan_summary", "duration_seconds")
    FUNCTION = "build"
    CATEGORY = "ZF/音乐/MiniMax Music3"
    DESCRIPTION = (
        "把自然语言歌曲要求反推为一次 LLM 写作任务；模型返回独立的 Music3 Structured Caption 与歌词块，"
        "再由“ZF Music3 结果拆分”连接到官方 Text Encode 的 caption / lyrics。"
    )
    SEARCH_ALIASES = [
        "music reverse prompt",
        "Music3 prompt director",
        "MiniMax Music3 lyrics",
        "音乐反推",
        "歌词反推",
        "曲风设计",
    ]

    def build(
        self,
        user_request,
        lyrics_language=LYRICS_LANGUAGE_OPTIONS[0],
        vocal_mode=VOCAL_MODE_OPTIONS[0],
        target_duration=120,
        duration_preset=DURATION_PRESET_OPTIONS[0],
        reference_mode=REFERENCE_MODE_OPTIONS[0],
        existing_lyrics="",
        style_reference="",
    ):
        request = str(user_request or "").strip() or "请创作一首主题明确、情绪连贯的原创歌曲。"
        language = resolve_lyrics_language(request, lyrics_language)
        mode = resolve_vocal_mode(request, vocal_mode)
        duration = resolve_duration_seconds(target_duration, duration_preset)
        instrumental = mode == "纯音乐"
        lyrics = str(existing_lyrics or "").strip()
        reference = str(style_reference or "").strip()

        blocks = [
            "【本次用户要求】\n" + request,
            f"【已解析硬约束】\n歌词语言：{language}。人声模式：{mode}。目标时长：约 {duration} 秒。",
            "【段落密度建议】\n" + _duration_structure(duration, instrumental),
            "【参考音频模式】\n" + _reference_instruction(reference_mode),
        ]
        if lyrics:
            blocks.append(
                "【已有歌词/草稿】\n"
                + lyrics
                + "\n若它已经完整，只规范官方段落标签并原样返回可唱文字；除非用户明确要求改写，否则不要擅自换词。"
            )
        if reference:
            blocks.append(
                "【附加曲风参考】\n"
                + reference
                + "\n把它作为约束和音乐线索进行消化，不要逐字复制或直接拼接到最终 Caption。"
            )
        blocks.append(
            "【执行】\n先完成或整理最终歌词，再根据该歌词的段落、叙事强度和用户要求反推一套连贯的英文 Structured Caption。"
            "Caption 建议约 250–450 个英文单词，信息密度服从音乐连贯性并控制在模型文本限制内。"
            f"最终严格使用 {_REFERENCE_MARKER}、{_CAPTION_MARKER}、{_LYRICS_MARKER}、{_END_MARKER} 输出。"
        )
        summary = f"{mode}｜歌词{language}｜{duration}秒｜{reference_mode}｜曲风与歌词分离输出"
        return (MUSIC3_WRITER_SYSTEM_PROMPT, "\n\n".join(blocks), language, summary, float(duration))


def _extract_json_blocks(text: str) -> tuple[str, str]:
    try:
        data = json.loads(text)
    except Exception:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    caption = data.get("caption") or data.get("structured_caption") or data.get("music_description") or ""
    lyrics = data.get("lyrics") or ""
    return _clean_block(caption), _clean_block(lyrics)


def _extract_marked_blocks(text: str) -> tuple[str, str]:
    caption_match = re.search(
        re.escape(_CAPTION_MARKER) + r"\s*(.*?)\s*" + re.escape(_LYRICS_MARKER),
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    lyrics_match = re.search(
        re.escape(_LYRICS_MARKER) + r"\s*(.*?)(?:\s*" + re.escape(_END_MARKER) + r"|\Z)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return (
        _clean_block(caption_match.group(1)) if caption_match else "",
        _clean_block(lyrics_match.group(1)) if lyrics_match else "",
    )


def _extract_heading_blocks(text: str) -> tuple[str, str]:
    """Accept a readable markdown fallback from less obedient writer models."""

    lyrics_heading = re.search(
        r"^#{1,3}\s*(?:Music3\s+Lyrics|Lyrics|歌词)\s*$",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    if not lyrics_heading:
        return "", ""
    caption = _clean_block(text[: lyrics_heading.start()])
    caption = re.sub(
        r"^#{1,3}\s*(?:Music3\s+Caption|Structured\s+Caption|曲风(?:说明|提示词)?)\s*$",
        "",
        caption,
        count=1,
        flags=re.MULTILINE | re.IGNORECASE,
    ).strip()
    lyrics = _clean_block(text[lyrics_heading.end() :])
    return caption, lyrics


def parse_music3_response(response: object) -> tuple[str, str]:
    text = _clean_block(response)
    if not text:
        return "", ""
    caption, lyrics = _extract_marked_blocks(text)
    if caption or lyrics:
        return caption, lyrics
    caption, lyrics = _extract_json_blocks(text)
    if caption or lyrics:
        return caption, lyrics
    return _extract_heading_blocks(text)


def parse_music3_response_with_analysis(response: object) -> tuple[str, str, str]:
    text = _clean_block(response)
    caption, lyrics = parse_music3_response(text)
    analysis_match = re.search(
        re.escape(_REFERENCE_MARKER) + r"\s*(.*?)\s*" + re.escape(_CAPTION_MARKER),
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    analysis = _clean_block(analysis_match.group(1)) if analysis_match else ""
    return caption, lyrics, analysis


def _lyric_tag_report(lyrics: str) -> tuple[list[str], list[str]]:
    supported = []
    unsupported = []
    for raw in re.findall(r"^\s*\[([^\]\r\n]+)\]\s*$", lyrics, flags=re.MULTILINE):
        normalized = raw.strip().lower().replace("_", "-")
        if normalized in _SUPPORTED_LYRIC_TAGS:
            supported.append(_SUPPORTED_LYRIC_TAGS[normalized])
        else:
            unsupported.append(raw.strip())
    return supported, unsupported


class ZFMusic3ResponseParser:
    """Split and validate a writer response for direct Music 3 connections."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_response": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "expected_language": (
                    "STRING",
                    {
                        "default": "",
                        "forceInput": True,
                        "tooltip": "可连接音乐反推导演的 resolved_language，用于检查默认中文/明确英文规则。",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("caption", "lyrics", "valid", "report", "reference_analysis")
    FUNCTION = "parse"
    CATEGORY = "ZF/音乐/MiniMax Music3"
    DESCRIPTION = "拆分 LLM 返回的曲风 Caption 与歌词，并检查官方三段 Caption 和歌词段落标签。"
    SEARCH_ALIASES = [
        "Music3 response parser",
        "MiniMax Music3 split",
        "音乐反推拆分",
        "曲风歌词拆分",
    ]

    def parse(self, model_response, expected_language=""):
        caption, lyrics, reference_analysis = parse_music3_response_with_analysis(model_response)
        errors = []
        notes = []

        if not caption:
            errors.append("未找到曲风 Caption")
        else:
            missing = [heading for heading in _CAPTION_HEADINGS if heading.lower() not in caption.lower()]
            if missing:
                errors.append("Caption 缺少：" + "、".join(missing))

        if not lyrics:
            errors.append("未找到歌词")
        else:
            supported, unsupported = _lyric_tag_report(lyrics)
            if not supported:
                errors.append("歌词没有官方段落标签")
            if unsupported:
                errors.append("存在非官方段落标签：" + "、".join(unsupported))
            if supported:
                notes.append("段落：" + "→".join(supported))

        language = str(expected_language or "").strip()
        lyric_body = re.sub(r"^\s*\[[^\]\r\n]+\]\s*$", "", lyrics, flags=re.MULTILINE)
        has_cjk = bool(re.search(r"[\u3400-\u9fff]", lyric_body))
        has_letters = bool(re.search(r"[A-Za-z]", lyric_body))
        if language == "中文" and lyrics and not has_cjk:
            errors.append("期望中文歌词，但正文未检测到中文")
        elif language == "English" and lyrics and has_cjk and not has_letters:
            errors.append("期望英文歌词，但正文主要为中文")

        if reference_analysis:
            notes.append("已返回参考分析")
        valid = not errors
        report_parts = ["可直接连接 Music3 Text Encode" if valid else "需要检查"]
        report_parts.extend(errors)
        report_parts.extend(notes)
        return (caption, lyrics, valid, "｜".join(report_parts), reference_analysis)


__all__ = [
    "LYRICS_LANGUAGE_OPTIONS",
    "VOCAL_MODE_OPTIONS",
    "DURATION_PRESET_OPTIONS",
    "REFERENCE_MODE_OPTIONS",
    "MUSIC3_WRITER_SYSTEM_PROMPT",
    "ZFMusic3PromptDirector",
    "ZFMusic3ResponseParser",
    "parse_music3_response",
    "parse_music3_response_with_analysis",
    "resolve_duration_seconds",
    "resolve_lyrics_language",
    "resolve_vocal_mode",
]
