import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "data" / "portrait_generator_v12.json"


def _load_catalog():
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


PORTRAIT_CATALOG = _load_catalog()
PORTRAIT_FIELDS = [
    (section, field)
    for section in PORTRAIT_CATALOG.get("sections", [])
    for field in section.get("fields", [])
]
PORTRAIT_FIELD_BY_ID = {field["id"]: (section, field) for section, field in PORTRAIT_FIELDS}
DEFAULT_PORTRAIT_STATE = json.dumps(
    {
        "version": 4,
        "adult_content": False,
        "selected": {},
        "enabled": {},
        "overrides": {},
        "pinned": {},
        "locked": {},
        "section_locked": {},
        "section_enabled": {},
        "option_overrides": {},
    },
    ensure_ascii=False,
    separators=(",", ":"),
)


SECTION_PREFIXES = {
    "person": "人物",
    "hair": "发型",
    "makeup": "妆容",
    "expression": "神态",
    "cloth": "服装",
    "posture": "姿态",
    "action": "动作",
    "camera": "镜头",
    "light": "光影",
    "bg": "环境",
    "comp": "构图",
    "extra": "风格细节",
}
PROMPT_SECTION_ORDER = (
    "person",
    "hair",
    "makeup",
    "expression",
    "cloth",
    "posture",
    "action",
    "camera",
    "light",
    "bg",
    "comp",
    "extra",
)


def _legacy_movement_field(field_id, value):
    adult = field_id == "simPick"
    code = str(value or "").upper()
    prefix = "adultPosture" if adult else "posture"
    posture_names = {
        "A": "Supine",
        "B": "Prone",
        "C": "Side",
        "D": "Kneeling",
        "E": "Sitting",
        "F": "Standing",
        "G": "Squatting",
        "H": "Suspended",
        "J": "Special",
    }
    if code[:1] in posture_names:
        return prefix + posture_names[code[0]]
    if not code.startswith("I"):
        return ""
    try:
        number = int(code[1:])
    except ValueError:
        return ""
    if adult:
        if number <= 20 or number >= 81:
            return "adultActionTransition"
        if number <= 40:
            return "adultActionWalking"
        if number <= 60:
            return "adultActionJumping"
        return "adultActionSpinning"
    if number <= 10 or number >= 26:
        return "actionTransition"
    if number <= 18:
        return "actionWalking"
    if number <= 22:
        return "actionJumping"
    return "actionSpinning"


def _migrate_legacy_movement(state):
    for legacy_id in ("sfwSimPick", "simPick"):
        target_id = _legacy_movement_field(legacy_id, state["selected"].get(legacy_id))
        if target_id:
            state["selected"].setdefault(target_id, state["selected"][legacy_id])
            if state["overrides"].get(legacy_id):
                state["overrides"].setdefault(target_id, state["overrides"][legacy_id])
            if state["pinned"].get(legacy_id):
                state["pinned"][target_id] = True
            if state["locked"].get(legacy_id):
                state["locked"][target_id] = True
            if state["enabled"].get(legacy_id) is False:
                state["enabled"][target_id] = False
        legacy_prefix = f"{legacy_id}::"
        for key, text in list(state["option_overrides"].items()):
            if not key.startswith(legacy_prefix):
                continue
            value = key[len(legacy_prefix):]
            option_target = _legacy_movement_field(legacy_id, value)
            if option_target:
                state["option_overrides"].setdefault(f"{option_target}::{value}", text)
            del state["option_overrides"][key]
        for name in ("selected", "overrides", "pinned", "locked", "enabled"):
            state[name].pop(legacy_id, None)
    for legacy_id in (
        "sfwSimMode", "sfwSimCoreCat", "sfwSimCat",
        "simMode", "simCoreCat", "simCat",
    ):
        for name in ("selected", "overrides", "pinned", "locked", "enabled"):
            state[name].pop(legacy_id, None)
    if "pose" in state["section_locked"]:
        value = state["section_locked"].pop("pose")
        state["section_locked"].setdefault("posture", value)
        state["section_locked"].setdefault("action", value)
    if "pose" in state["section_enabled"]:
        value = state["section_enabled"].pop("pose")
        state["section_enabled"].setdefault("posture", value)
        state["section_enabled"].setdefault("action", value)
    state["version"] = 4
    return state


def _parse_state(value):
    try:
        state = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    for key in (
        "selected",
        "enabled",
        "overrides",
        "pinned",
        "locked",
        "section_locked",
        "section_enabled",
        "option_overrides",
    ):
        if not isinstance(state.get(key), dict):
            state[key] = {}
    return _migrate_legacy_movement(state)


def _clean_text(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ，,;；")
    if text in ("", "不启用"):
        return ""
    return text


def _option_text(field, selected_value, option_overrides=None):
    selected = str(selected_value or "")
    for option in field.get("options", []):
        if str(option.get("value", "")) == selected:
            key = f"{field['id']}::{selected}"
            customized = _clean_text((option_overrides or {}).get(key))
            return customized or _clean_text(option.get("text") or option.get("value")), bool(option.get("adult"))
    return "", False


def _minor_marker(text):
    source = str(text or "")
    if re.search(r"(?<!\d)(?:[0-9]|1[0-7])\s*(?:岁|周岁|years?\s*old)", source, flags=re.I):
        return True
    return bool(re.search(r"未成年|幼女|幼童|儿童|小学生|初中生|婴儿|孩童", source))


def _field_texts(state, adult_requested):
    selected = state["selected"]
    enabled = state["enabled"]
    overrides = state["overrides"]
    normal_text = []
    adult_text = []
    by_section = {section_id: [] for section_id in PROMPT_SECTION_ORDER}

    for section, field in PORTRAIT_FIELDS:
        if state["section_enabled"].get(section["id"], True) is False:
            continue
        field_id = field["id"]
        if enabled.get(field_id, True) is False:
            continue
        override = _clean_text(overrides.get(field_id))
        option_text, option_is_adult = _option_text(
            field,
            selected.get(field_id),
            state["option_overrides"],
        )
        text = override or option_text
        if not text:
            continue
        is_adult = bool(field.get("adult") or option_is_adult)
        if is_adult:
            adult_text.append((section["id"], text))
            if not adult_requested:
                continue
        else:
            normal_text.append(text)
        by_section.setdefault(section["id"], []).append(text)
    return normal_text, adult_text, by_section


def _normalize_reference(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        pieces = []
        for key in (
            "image_overview",
            "subjects",
            "composition",
            "materials_and_colors",
            "lighting_and_atmosphere",
            "style_and_creative_concept",
        ):
            value = parsed.get(key)
            if isinstance(value, list):
                pieces.extend(_clean_text(item) for item in value)
            elif isinstance(value, dict):
                pieces.extend(_clean_text(item) for item in value.values())
            else:
                pieces.append(_clean_text(value))
        text = "，".join(item for item in pieces if item)
    text = re.sub(r"```(?:json|text|markdown)?|```", "", text, flags=re.I)
    return _clean_text(text)[:3000]


def _join_sections(by_section, allowed=None):
    parts = []
    for section_id in PROMPT_SECTION_ORDER:
        if allowed is not None and section_id not in allowed:
            continue
        values = list(dict.fromkeys(item for item in by_section.get(section_id, []) if item))
        if values:
            parts.append(f"{SECTION_PREFIXES.get(section_id, section_id)}：{'，'.join(values)}")
    return "；".join(parts)


def _catalog_asset_sections(include_adult, option_overrides=None):
    normal_sections = []
    adult_sections = []
    normal_count = 0
    adult_count = 0

    for section in PORTRAIT_CATALOG.get("sections", []):
        normal_fields = []
        adult_fields = []
        for field in section.get("fields", []):
            normal_values = []
            adult_values = []
            for option in field.get("options", []):
                option_value = str(option.get("value", ""))
                key = f"{field['id']}::{option_value}"
                value = _clean_text(
                    (option_overrides or {}).get(key)
                    or option.get("text")
                    or option.get("value")
                )
                if not value:
                    continue
                target = adult_values if field.get("adult") or option.get("adult") else normal_values
                if value not in target:
                    target.append(value)
            if normal_values:
                normal_fields.append(f"{field.get('label', field['id'])}：{'、'.join(normal_values)}")
                normal_count += len(normal_values)
            if adult_values:
                adult_fields.append(f"{field.get('label', field['id'])}：{'、'.join(adult_values)}")
                adult_count += len(adult_values)
        if normal_fields:
            normal_sections.append(f"【{section.get('title', section['id'])}】\n" + "\n".join(normal_fields))
        if include_adult and adult_fields:
            adult_sections.append(f"【{section.get('title', section['id'])}】\n" + "\n".join(adult_fields))

    parts = ["【人物资产库｜常规】", "\n\n".join(normal_sections)]
    if include_adult and adult_sections:
        parts.extend(["【人物资产库｜成人扩展】", "\n\n".join(adult_sections)])
    return "\n\n".join(parts), normal_count, adult_count if include_adult else 0


class ZFPortraitPromptGenerator:
    """Front-end driven portrait asset generator with optional reference material."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state_json": (
                    "STRING",
                    {
                        "default": DEFAULT_PORTRAIT_STATE,
                        "multiline": True,
                        "tooltip": "由人像生成器界面维护的选择状态。",
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0x7FFFFFFF,
                        "tooltip": "点击随机按钮时自动更新。",
                    },
                ),
                "adult_content": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "高级内容选项，默认关闭。",
                    },
                ),
            },
            "optional": {
                "reference_analysis": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": "可选接入已有的图片反推或结构化视觉分析；随机功能不依赖此输入。",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("portrait_prompt", "world_asset", "selection_json", "status")
    FUNCTION = "generate"
    CATEGORY = "ZF/提示词创意导演/人物资产"
    DESCRIPTION = "从可编辑的人像素材目录直接组装提示词，也可把输出作为人物世界观资产接入导演台。"
    SEARCH_ALIASES = [
        "ZF portrait prompt generator",
        "portrait asset",
        "人物提示词生成器",
        "人像生成器",
        "人物资产库",
    ]

    def generate(self, state_json, seed=0, adult_content=False, reference_analysis=None):
        state = _parse_state(state_json)
        reference = _normalize_reference(reference_analysis)
        adult_requested = bool(adult_content)
        normal_text, adult_text, by_section = _field_texts(state, adult_requested)

        safety_source = " ".join(normal_text + [reference] + list(state["overrides"].values()))
        adult_blocked = adult_requested and _minor_marker(safety_source)
        if adult_blocked:
            adult_requested = False
            _, _, by_section = _field_texts(state, False)

        prompt_body = _join_sections(by_section)
        if adult_requested and adult_text:
            prompt_body = f"明确的成年人物，{prompt_body}" if prompt_body else "明确的成年人物"
        if reference:
            prompt_body = f"{prompt_body}；参考画面要点：{reference}" if prompt_body else f"参考画面要点：{reference}"
        portrait_prompt = prompt_body or "单人肖像创作，人物身份、外观、服装、动作与环境保持统一自然"

        world_asset, normal_asset_count, adult_asset_count = _catalog_asset_sections(
            adult_requested,
            state["option_overrides"],
        )
        if reference:
            world_asset += f"\n\n【外部参考素材】\n{reference}"
        if adult_requested:
            world_asset += "\n\n【成人扩展边界】\n只用于明确的成年人物。"

        normalized_state = {
            "version": 4,
            "seed": int(seed),
            "adult_content": adult_requested,
            "selected": state["selected"],
            "enabled": state["enabled"],
            "overrides": state["overrides"],
            "pinned": state["pinned"],
            "locked": state["locked"],
            "section_locked": state["section_locked"],
            "section_enabled": state["section_enabled"],
            "option_overrides": state["option_overrides"],
        }
        active_count = sum(len(values) for values in by_section.values())
        asset_count = normal_asset_count + adult_asset_count
        if adult_blocked:
            status = f"当前提示词 {active_count} 项；完整资产库 {asset_count} 项；检测到未成年描述，成人扩展未参与输出"
        else:
            status = f"当前提示词 {active_count} 项；完整资产库 {asset_count} 项；成人内容{'开启' if adult_requested else '关闭'}"
        return (
            portrait_prompt,
            world_asset,
            json.dumps(normalized_state, ensure_ascii=False, separators=(",", ":")),
            status,
        )
