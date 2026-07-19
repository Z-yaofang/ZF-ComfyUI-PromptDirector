import json
import math
import random
import re
import sys
import threading
from pathlib import Path

from comfy_execution.graph import ExecutionBlocker


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


def _load_json(name):
    with (DATA_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


PURPOSES = _load_json("purposes.json")
VISUAL_METHODS = _load_json("visual_methods.json")
DEFAULT_COMBINATIONS = _load_json("default_combinations.json")
WRITING_GRAMMAR = _load_json("writing_grammar.json")
PURPOSE_BY_ID = {item["id"]: item for item in PURPOSES}
VISUAL_BY_ID = {item["id"]: item for item in VISUAL_METHODS}
DEFAULT_SELECTION_JSON = json.dumps(DEFAULT_COMBINATIONS, ensure_ascii=False, separators=(",", ":"))

REFERENCE_SCOPES = (
    "综合提取（元素、创意、构图）",
    "主体与元素",
    "构图与镜头",
    "材质、色彩与光线",
    "文字、版式与信息层级",
    "创意概念与可迁移关系",
    "只参考结构，不复制内容",
)

MODEL_LEVELS = (
    "1｜核心清晰（轻量成图模型）",
    "2｜完整表达（主流成图模型）",
    "3｜精密制作（强语义成图模型）",
)
REFERENCE_MODES = (
    "创意迁移",
    "参考图创意提取测试",
)
DEFAULT_MODEL_LEVEL = MODEL_LEVELS[1]
MODEL_LEVEL_SPECS = {
    "1": {
        "name": MODEL_LEVELS[0],
        "length_factor": 0.62,
        "instruction": "使用直接主谓宾、清楚动作和少量强相关细节，主体事件占据主要描述篇幅。",
    },
    "2": {
        "name": MODEL_LEVELS[1],
        "length_factor": 1.0,
        "instruction": "完整表达核心事件、主题素材、用途结构和一个主视觉方法，细节围绕同一观看重点。",
    },
    "3": {
        "name": MODEL_LEVELS[2],
        "length_factor": 1.45,
        "instruction": "使用制作级视觉说明，展开人物、空间、版式、材料、光线与关系，同时保持一个清楚的语义中心。",
    },
}


DIRECTOR_SYSTEM_PROMPT = """你是视觉创意导演，也是中文图像正向提示词作者。每次只为一张图写一条可直接交给图像生成模型的成品提示词。

【创作秩序】
1. 用户提示非空时，先把其中明确的主体、数量、身份、年龄、地点、动作、关系、关键物、文字和画面目标建立为本图核心。这个核心作为提示词开头的完整内容块。
2. 用途决定作品要完成的专业任务，并据此从取材主题中选择相关人物、环境、服装、道具、建筑、文化、材料与情绪证据。主题也允许提供符合其规则的知识联想和原创补充。
3. 视觉方法决定这些内容的空间结构、观看方式和主要视觉看点。用途与视觉方法共同服务已经建立的用户核心。
4. 用户提示与所选用途、视觉方法天然匹配时，充分执行三者。适配空间较小时，完整呈现用户核心，再采用与它相容的用途能力和视觉语言。

【空提示创作】
用户提示为空时，用途先确定作品类型和取材范围，视觉方法确定画面结构，再从取材主题中选择一个明确主体、一个主要事件和一组相互支持的素材。每个任务形成一张独立、完整、自洽的图。

【故事分镜图】
任务标记为故事分镜图时，创作对象是一张包含全部分镜的复合宫格图。输入数量表示有效分镜格数。先建立统一的角色辨识、服装道具、地点结构、时间进程、色彩媒介和运动方向，再按从左到右、从上到下写清每格唯一的事件时刻。相邻格保持动作承接、视线承接、空间轴线和因果连续。用户提示非空时，它是故事中段必须准确出现的关键瞬间；前格建立成立的起因，后格呈现直接反应、转折、余波和结局。尾部空位统一成为纯黑矩形色块。

【视觉写作】
先写核心主体与事件，再写直接相关的主题素材，最后写用途、构图、镜头、画风、光线、色彩和材质。动作在一个连续内容块中写清支撑、方向、接触对象和事件时刻。每个属性选定一个具体值。群像中的主要成员各自拥有明确位置、动作、视线、关系职责和辨识特征。抽象气质转译为可见的姿态、距离、空间、颜色、光线与材料。

【文字与内部标签纪律】
内部的创意概念、用途名称、世界观名称、节点字段和参考图分析标签只用于组织画面。除非用户明确要求，否则不得把它们自动写成标题、招牌、Logo、字幕、屏幕大字或其它可读文字。无法辨认的文字只描述为不可读的装饰性文字纹理，不使用“可能、似乎、疑似、像是、或A或B、不确定”等推测表达。

最终以正向、确定、自然的中文描述为主。输入中明确的保留要求和关键边界可以使用一句简短约束。最终只输出成品提示词正文。"""


REFERENCE_ANALYSIS_SYSTEM_PROMPT = """你是专业的视觉参考图分析师。你的工作是把参考图拆解成可以迁移到新图像中的视觉关系，而不是复述图片或复制图片中的人物身份、品牌和原文案。

请只输出严格有效的 JSON，不要使用 Markdown 代码块，不要添加解释。所有字段都使用中文。分析应区分“图中看见的事实”和“可以迁移的创意”，不要凭空补充无法确认的内容。

JSON 结构必须包含：
{
  "image_overview": "一句话概括画面",
  "subjects": ["主体、人物或核心对象"],
  "elements": [{"name": "元素名称", "role": "作用", "position": "画面位置", "visual_features": "外观特征"}],
  "composition": {"layout": "布局结构", "framing": "景别和裁切", "camera_angle": "视角和机位", "perspective": "透视关系", "depth": "前中后景", "negative_space": "留白和视觉重心"},
  "actions_and_relationships": ["主体之间的动作、连接或因果关系"],
  "style_and_creative_concept": "创意概念、叙事机制或视觉隐喻",
  "materials_and_colors": "材质、纹理、主色和配色关系",
  "lighting_and_atmosphere": "光线方向、明暗、氛围和时间感",
  "typography_and_layout": "文字内容、字体、版式和信息层级；没有文字就写无；无法辨认时只描述为不可读的装饰性文字纹理，不猜测语言或具体字词",
  "transferable_design": ["适合迁移到新作品的视觉关系或创意规则"],
  "avoid_copying": ["必须避免直接复制的身份、商标、原文案或独特细节"]
}

保持 JSON 精炼完整：image_overview 和各说明字段各用一至三句短句；elements 最多 12 项；actions_and_relationships、transferable_design、avoid_copying 各最多 6 项。优先保证所有字段闭合，不为追求篇幅堆叠同义细节。
"""


def _reference_analysis_request(scope, reference_strength, extract_text, protect_identity, custom_focus):
    scope_text = str(scope or REFERENCE_SCOPES[0]).strip()
    extra = str(custom_focus or "").strip()
    options = [
        f"本次重点：{scope_text}。",
        f"参考强度为 {float(reference_strength):.2f}（只迁移视觉关系，不照搬内容）。",
        "请优先提取主体、元素清单、构图方式、镜头视角、姿态动作、材质色彩、光线氛围和创意概念。",
    ]
    if extract_text:
        options.append("请识别图中文字，并记录原文、位置、字体风格和层级；无法辨认时只描述可见形态和位置，写成不可读的装饰性文字纹理，不猜测语言或具体字词。")
    else:
        options.append("忽略图中文字，不要把文字内容作为迁移目标。")
    if protect_identity:
        options.append("不要复制人物身份、脸部特征、品牌 Logo、商标或原图独有的可识别信息；将它们写入 avoid_copying。")
    else:
        options.append("如图中有身份或品牌信息，只描述其视觉作用，并提醒下游按需替换。")
    if extra:
        options.append(f"用户补充关注点：{extra}")
    return "\n".join(options) + "\n\n请严格按照系统消息中的 JSON 结构输出。"


def _find_vlm_node_class():
    """Find the already-loaded llama-cpp VLM node without hard-importing its hyphenated package."""
    # Do not probe arbitrary module attributes with getattr/hasattr here.  In
    # particular, ``torch.classes`` implements dynamic attribute lookup and
    # treats an attribute named ``llama_cpp_instruct_adv`` as a Torch custom
    # class namespace.  Asking that namespace whether ``process`` exists then
    # raises a RuntimeError when the class is not registered, instead of
    # simply returning False.
    preferred = (
        "custom_nodes.ComfyUI-llama-cpp_vlm.nodes",
        "custom_nodes.ComfyUI-llama-cpp_vllm.nodes",
        "ComfyUI-llama-cpp_vlm.nodes",
        "ComfyUI-llama-cpp_vllm.nodes",
    )
    for module_name in preferred:
        module = sys.modules.get(module_name)
        module_dict = getattr(module, "__dict__", None) if module is not None else None
        if not isinstance(module_dict, dict):
            continue
        candidate = module_dict.get("llama_cpp_instruct_adv")
        if isinstance(candidate, type) and callable(getattr(candidate, "process", None)):
            return candidate

    for module in list(sys.modules.values()):
        module_dict = getattr(module, "__dict__", None)
        if not isinstance(module_dict, dict):
            continue
        candidate = module_dict.get("llama_cpp_instruct_adv")
        if isinstance(candidate, type) and callable(getattr(candidate, "process", None)):
            return candidate
    return None


def _run_reference_vlm(llama_model, prompt, image, parameters, seed, max_size, unique_id):
    vlm_class = _find_vlm_node_class()
    if vlm_class is None:
        raise RuntimeError(
            "未找到已加载的 llama-cpp VLM 节点。请先启用 ComfyUI-llama-cpp_vlm，或把已有多模态输出接入 analysis_result。"
        )
    # Reference analysis is a structured-JSON task.  Keep sampling bounded
    # even when an encrypted/upstream parameter node exposes a more creative
    # temperature, while leaving all downstream image-generation settings
    # untouched.
    vlm_parameters = dict(parameters or {})
    try:
        configured_temperature = float(vlm_parameters.get("temperature", 0.2))
    except (TypeError, ValueError):
        configured_temperature = 0.2
    vlm_parameters["temperature"] = max(0.0, min(0.2, configured_temperature))
    vlm = vlm_class()
    result = vlm.process(
        llama_model=llama_model,
        preset_prompt="Empty - Nothing",
        custom_prompt=prompt,
        system_prompt=REFERENCE_ANALYSIS_SYSTEM_PROMPT,
        inference_mode="images",
        max_frames=4,
        max_size=max(128, int(max_size)),
        seed=int(seed),
        force_offload=False,
        save_states=False,
        unique_id=str(unique_id or "zf_reference_analyzer"),
        parameters=vlm_parameters,
        images=image,
        queue_handler=None,
    )
    return str(result[0] if isinstance(result, tuple) else result).strip()


REFERENCE_JSON_FIELDS = (
    "image_overview",
    "subjects",
    "elements",
    "composition",
    "actions_and_relationships",
    "style_and_creative_concept",
    "materials_and_colors",
    "lighting_and_atmosphere",
    "typography_and_layout",
    "transferable_design",
    "avoid_copying",
)


def _salvage_reference_json(text):
    """Recover individually completed fields from a truncated JSON object.

    Small local VLMs sometimes stop after the token limit before writing the
    final closing braces.  Completed values near the beginning are still
    valid JSON, so decode them one by one instead of demoting the entire
    analysis to an opaque raw string.
    """
    source = str(text or "")
    decoder = json.JSONDecoder()
    recovered = {}
    for key in REFERENCE_JSON_FIELDS:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*', source)
        if not match:
            continue
        remainder = source[match.end():].lstrip()
        try:
            value, _ = decoder.raw_decode(remainder)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if value not in (None, "", [], {}):
            recovered[key] = value
    return recovered


def _parse_reference_json(raw):
    text = str(raw or "").strip()
    if not text:
        return {}, ""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}, text
    except Exception:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else {}, text
            except Exception:
                pass
    recovered = _salvage_reference_json(cleaned)
    if recovered:
        return recovered, text
    return {}, text


def _as_text(value):
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("label") or "元素").strip()
                details = [
                    str(item.get(key)).strip()
                    for key in ("position", "role", "visual_features")
                    if str(item.get(key) or "").strip()
                ]
                parts.append(f"{name}（{'；'.join(details)}）" if details else name)
            elif str(item).strip():
                parts.append(str(item).strip())
        return "、".join(parts)
    if isinstance(value, dict):
        return "；".join(f"{key}：{val}" for key, val in value.items() if str(val).strip())
    return str(value or "").strip()


def _positive_visual_text(value):
    """Normalize uncertain OCR/VLM wording before it reaches the image writer."""
    text = _as_text(value)
    if not text:
        return ""
    text = re.sub(
        r"(?:可能为|可能是)(?:日文|中文)(?:或(?:日文|中文))?",
        "不可读的装饰性文字纹理",
        text,
    )
    replacements = (
        ("似日文或中文", "不可读的装饰性文字纹理"),
        ("可能为日文或中文", "不可读的装饰性文字纹理"),
        ("可能是日文或中文", "不可读的装饰性文字纹理"),
        ("字体风格不确定", "字体仅作为不可读的低对比装饰纹理"),
        ("无法确认的文字", "不可读的装饰性文字纹理"),
        ("不确定的文字", "不可读的装饰性文字纹理"),
        ("可能是", "呈"),
        ("可能为", "为"),
        ("可能有", "有"),
        ("可能存在", "存在"),
        ("似乎是", "呈"),
        ("疑似", ""),
        ("无法确认", "不可读"),
        ("不确定", "不可读"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    text = re.sub(r"（[^）]*(?:可能|似乎|疑似|不确定|无法确认)[^）]*）", "（不可读的装饰性文字纹理）", text)
    text = re.sub(r"\([^)]*(?:可能|似乎|疑似|不确定|无法确认)[^)]*\)", "（不可读的装饰性文字纹理）", text)
    return text


def _format_reference_instruction(data, raw, scope, reference_strength, extract_text, protect_identity):
    if not data:
        fallback = _positive_visual_text(raw)
        if not fallback:
            return ""
        return (
            f"【参考图像分析（{scope}，强度 {float(reference_strength):.2f}）】\n"
            f"请把以下多模态分析作为视觉关系参考：{fallback}\n"
            "只迁移可复用的主体关系、构图、材质、光线和创意机制；不要复制人物身份、品牌、Logo 或原图文字。"
        )

    creative_only = str(scope or "").strip() == REFERENCE_SCOPES[5]
    lines = [f"【参考图像分析（{scope}，强度 {float(reference_strength):.2f}）】"]
    if creative_only:
        # This scope is intentionally abstract. Do not pass the concrete
        # subject/object inventory to the downstream director, otherwise a
        # creative-reference test still recreates the source image's props.
        field_labels = (
            ("composition", "空间与构图关系"),
            ("style_and_creative_concept", "创意机制"),
            ("materials_and_colors", "材质与色彩语言"),
            ("lighting_and_atmosphere", "光线与氛围语言"),
            ("transferable_design", "可迁移规则"),
            ("avoid_copying", "明确排除的原图内容"),
        )
    else:
        field_labels = (
            ("image_overview", "画面概览"),
            ("subjects", "主体"),
            ("elements", "元素与位置"),
            ("composition", "构图与镜头"),
            ("actions_and_relationships", "动作与关系"),
            ("style_and_creative_concept", "创意概念"),
            ("materials_and_colors", "材质与色彩"),
            ("lighting_and_atmosphere", "光线与氛围"),
            ("typography_and_layout", "文字与版式"),
            ("transferable_design", "可迁移规则"),
            ("avoid_copying", "避免复制"),
        )
    for key, label in field_labels:
        if key == "typography_and_layout" and not extract_text:
            continue
        value = _positive_visual_text(data.get(key))
        if value:
            lines.append(f"{label}：{value}")
    if protect_identity:
        lines.append("身份保护：人物脸部、姓名、品牌 Logo、商标和原图独有文字只作为不可复制信息处理。")
    if creative_only:
        lines.append("抽象迁移规则：只保留创意机制、空间组织、材质语言和视觉关系；原图的具体人物、花卉、茶具、色卡、服装、道具和文字不得成为新图的必需内容。")
    else:
        lines.append("迁移规则：保留参考图的视觉关系、空间组织和创意机制，替换为用户指定的主体、世界观与用途；不要复刻原图内容或做逐像素临摹。")
    return "\n".join(lines)


def _reference_summary(data, raw):
    if not data:
        return str(raw or "").strip()[:600]
    overview = _as_text(data.get("image_overview"))
    subjects = _as_text(data.get("subjects"))
    composition = _as_text(data.get("composition"))
    concept = _as_text(data.get("style_and_creative_concept"))
    parts = [item for item in (overview, f"主体：{subjects}" if subjects else "", f"构图：{composition}" if composition else "", f"创意：{concept}" if concept else "") if item]
    return "；".join(parts)[:1000]


def _reference_creative_profile(data, raw, reference_strength=0.75):
    """Convert image analysis into a first-class, temporary purpose/visual combo.

    Concrete elements remain available as a material pool.  The director is
    told which relationships are the creative anchors and how a world/theme
    may expand them, so image content is not mistaken for a pixel-copy lock.
    """
    if not isinstance(data, dict) or not data:
        text = _positive_visual_text(raw)
        return {
            "purpose": {
                "name": "参考图临时用途：创意机制迁移",
                "prompt": "提取参考图的创意机制和元素素材，在新的主体与世界观中生成同类创意。",
            },
            "visual": {
                "name": "参考图临时视觉方法",
                "prompt": "保留参考图的构图关系、空间组织、材质语言和光线氛围，允许替换具体内容。",
            },
            "creative_concept": text[:1600],
            "anchor_elements": [],
            "expandable_elements": [],
            "composition": "",
            "material_language": "",
            "lighting": "",
            "typography": "",
            "world_expansion": "世界观为空时，从参考图元素素材继续联想；世界观存在时，将其角色、物件、植物和媒介替换或扩展到同一创意机制中。",
            "avoid_copying": [],
            "reference_strength": float(reference_strength),
        }

    elements = data.get("elements") if isinstance(data.get("elements"), list) else []
    element_text = []
    for item in elements[:24]:
        if isinstance(item, dict):
            name = _positive_visual_text(item.get("name") or "元素")
            role = _positive_visual_text(item.get("role"))
            position = _positive_visual_text(item.get("position"))
            features = _positive_visual_text(item.get("visual_features"))
            detail = "；".join(part for part in (role, position, features) if part)
            element_text.append(f"{name}（{detail}）" if detail else name)
        elif str(item).strip():
            element_text.append(_positive_visual_text(item))

    subjects = _positive_visual_text(data.get("subjects"))
    composition = _positive_visual_text(data.get("composition"))
    concept = _positive_visual_text(data.get("style_and_creative_concept"))
    materials = _positive_visual_text(data.get("materials_and_colors"))
    lighting = _positive_visual_text(data.get("lighting_and_atmosphere"))
    typography_raw = _positive_visual_text(data.get("typography_and_layout"))
    if typography_raw and typography_raw not in {"无", "无文字", "没有文字"}:
        typography = "原图文字只参考位置、密度、笔触和版式层级，不迁移具体字词；除非用户核心明确要求文字，否则写成不可读的装饰性文字纹理。"
    else:
        typography = "不迁移原图文字；如需保留版式，仅使用不可读的装饰性文字纹理。"
    relationships = _positive_visual_text(data.get("actions_and_relationships"))
    transferable = _positive_visual_text(data.get("transferable_design"))
    avoid_copying_raw = data.get("avoid_copying") if isinstance(data.get("avoid_copying"), list) else []
    avoid_copying = [_positive_visual_text(item) for item in avoid_copying_raw if _positive_visual_text(item)]
    if typography_raw and typography_raw not in {"无", "无文字", "没有文字"}:
        avoid_copying = [
            item
            for item in avoid_copying
            if not re.search(r"文字|字词|文案|字体|书法|标题|Logo|商标|calligraphy|typography|text|word|font|title|content", item, flags=re.I)
        ]
        avoid_copying.append("原图可读文字、商标、Logo和具体文案不直接复制")

    anchor_text = "；".join(part for part in (concept, relationships, subjects) if part)
    expansion_text = "；".join(part for part in ("；".join(element_text), transferable) if part)
    return {
        "purpose": {
            "name": "参考图临时用途：创意机制迁移",
            "prompt": "把参考图的创意机制、元素素材和叙事关系迁移到新的主体与世界观中，生成同类但非复刻的作品。",
        },
        "visual": {
            "name": "参考图临时视觉方法",
            "prompt": "优先沿用参考图的空间组织、构图关系、材质语言、光线氛围和视觉重叠方式；具体主体、物件和媒介允许被世界观扩展。",
        },
        "creative_concept": concept,
        "anchor_elements": [anchor_text] if anchor_text else [],
        "expandable_elements": [expansion_text] if expansion_text else [],
        "composition": composition,
        "material_language": materials,
        "lighting": lighting,
        "typography": typography,
        "world_expansion": "世界观为空时，从参考图元素素材继续联想并生成同类变体；世界观存在时，用世界观中的角色、植物、器物、媒介和场景替换或扩展参考图元素，同时保持参考图的核心创意机制。",
        "relationships": relationships,
        "avoid_copying": avoid_copying,
        "reference_strength": float(reference_strength),
    }


def _reference_creative_block(profile):
    if not isinstance(profile, dict):
        return ""
    purpose = profile.get("purpose") or {}
    visual = profile.get("visual") or {}
    lines = [
        "【参考图临时用途与创意（动态素材库）】",
        f"临时用途：{purpose.get('name', '创意机制迁移')}",
        f"用途目标：{purpose.get('prompt', '')}",
        f"临时视觉方法：{visual.get('name', '参考图临时视觉方法')}",
        f"视觉落实：{visual.get('prompt', '')}",
    ]
    fields = (
        ("creative_concept", "核心创意机制"),
        ("anchor_elements", "创意锚点与关系"),
        ("expandable_elements", "元素素材库"),
        ("composition", "构图与空间关系"),
        ("material_language", "材质与色彩语言"),
        ("lighting", "光线与氛围"),
        ("typography", "文字与版式语言"),
        ("relationships", "动作与叙事关系"),
        ("world_expansion", "世界观扩展规则"),
        ("avoid_copying", "身份与不可复制信息"),
    )
    for key, label in fields:
        value = _positive_visual_text(profile.get(key))
        if value:
            lines.append(f"{label}：{value}")
    lines.append(
        "优先级规则：用户明确要求决定最终主体与硬约束；参考图临时用途与创意提供核心机制和元素素材；"
        "世界观负责扩展或替换素材；静态用途与视觉方法只作为后置表达修饰。不要逐像素复刻，但不要无故删除参考图中的关键创意元素。内部概念标签、用途名和世界观名只作语义指导，不得自动变成画面文字；无法辨认的文字统一写成不可读的装饰性文字纹理。"
    )
    return "\n".join(lines)


def _safe_selection(selection_json, allow_default=True):
    try:
        raw = json.loads(selection_json) if selection_json else []
    except Exception:
        raw = []
    if isinstance(raw, dict):
        raw = raw.get("combinations", raw.get("selection", []))
    if not isinstance(raw, list):
        raw = []

    selected = []
    for item in raw:
        if not isinstance(item, dict) or item.get("enabled", True) is False:
            continue
        purpose = PURPOSE_BY_ID.get(str(item.get("purpose", "")))
        visual = VISUAL_BY_ID.get(str(item.get("visual", "")))
        if not purpose or not visual:
            continue
        selected.append(
            {
                "purpose": purpose,
                "visual": visual,
                "strength": max(0.0, min(2.0, float(item.get("strength", 1.0)))),
            }
        )

    if not selected and allow_default:
        selected = [
            {
                "purpose": PURPOSE_BY_ID["character_scene_photo"],
                "visual": VISUAL_BY_ID["direct_expression"],
                "strength": 1.0,
            }
        ]
    return selected


def _model_level_key(value):
    match = re.match(r"\s*([123])", str(value or ""))
    return match.group(1) if match else "2"


def _model_level_name(value):
    return MODEL_LEVEL_SPECS[_model_level_key(value)]["name"]


def _clean_theme(theme):
    text = str(theme or "").strip()
    return re.sub(r"(?:\s*【用户提示词】\s*)+$", "", text).strip()


def _aspect_description(width, height):
    width = max(1, int(width))
    height = max(1, int(height))
    ratio = width / height
    divisor = math.gcd(width, height)
    exact = f"{width // divisor}:{height // divisor}"
    if 0.92 <= ratio <= 1.08:
        profile = "近方形画幅，主体与环境采用集中、均衡的空间组织"
    elif ratio >= 2.0:
        profile = "超宽横幅，适合连续空间、横向运动与多组关系"
    elif ratio > 1.08:
        profile = "横向画幅，适合左右关系、环境范围与叙事展开"
    elif ratio <= 0.5:
        profile = "超高竖幅，适合巨大垂直尺度、上下层级与纵深通道"
    else:
        profile = "竖向画幅，适合人物高度、上下关系与垂直空间"
    return f"{width}×{height}，比例{exact}；{profile}"


def _length_target(selection, model_level):
    if selection:
        primary = selection[0]["purpose"]
        configured = primary.get("length_range", [600, 1100])
    else:
        # Reference-only diagnostics intentionally have no purpose/visual
        # combination. Keep a useful prompt budget without silently falling
        # back to the default portrait purpose.
        configured = [520, 980]
    minimum, maximum = int(configured[0]), int(configured[1])
    if len(selection) > 1:
        minimum += min(240, (len(selection) - 1) * 70)
        maximum += min(520, (len(selection) - 1) * 150)
    factor = MODEL_LEVEL_SPECS[_model_level_key(model_level)]["length_factor"]
    minimum = max(260, round(minimum * factor))
    maximum = max(minimum + 220, round(maximum * factor))
    maximum = min(maximum, {"1": 1300, "2": 3600, "3": 7000}[_model_level_key(model_level)])
    return minimum, maximum


def _selection_summary(selection):
    return " + ".join(f"{item['purpose']['name']} / {item['visual']['name']}" for item in selection) or "（未应用用途与创意）"


def _prompt_reference_block(reference_instruction):
    text = _positive_visual_text(reference_instruction)
    if not text:
        return ""
    return (
        "【参考图像提取】\n"
        f"{text}\n"
        "下游成图时只迁移参考图中明确可复用的元素关系、创意机制、构图和材质语言；"
        "参考强度服从上文，用户明确内容、世界观和用途优先。不要复制人物身份、品牌、Logo、原图文字或逐像素细节。"
    )


def _is_storyboard(selection):
    # Storyboard is a structural mode.  It must win even when the UI stores
    # another selected purpose/visual combination before it in the list.
    return any(
        item.get("purpose", {}).get("id") == "storyboard_sequence"
        for item in (selection or [])
        if isinstance(item, dict)
    )


def _promote_storyboard(selection):
    """Keep the storyboard combination primary when it is combined with extras."""
    items = list(selection or [])
    for index, item in enumerate(items):
        if item.get("purpose", {}).get("id") == "storyboard_sequence":
            return [item, *items[:index], *items[index + 1 :]]
    return items


def _storyboard_layout(panel_count):
    panel_count = max(1, int(panel_count))
    columns = int(math.ceil(math.sqrt(panel_count)))
    rows = int(math.ceil(panel_count / columns))
    blanks = columns * rows - panel_count
    return columns, rows, blanks


def _storyboard_beats(panel_count, has_user_prompt):
    panel_count = max(1, int(panel_count))
    if panel_count == 1:
        return ["用户指定关键瞬间" if has_user_prompt else "故事核心瞬间"]

    if has_user_prompt:
        anchor = min(panel_count, max(1, int(math.ceil(panel_count * 0.55))))
        before_pool = ["世界与人物建立", "起因显现", "目标形成", "事件触发", "逼近关键地点", "阻碍升级", "临界准备"]
        after_pool = ["即时反应", "局势转折", "后果扩散", "代价显现", "余波", "关系变化", "结局与下一步"]
        before_count = anchor - 1
        before = before_pool[-before_count:] if before_count <= len(before_pool) else [
            f"前情推进{index + 1}" for index in range(before_count - len(before_pool))
        ] + before_pool
        after_count = panel_count - anchor
        after = after_pool[:after_count]
        if after_count > len(after_pool):
            after += [f"后续进程{index + 1}" for index in range(after_count - len(after_pool))]
        return before + ["用户指定关键瞬间"] + after

    templates = {
        2: ["事件触发", "直接结果"],
        3: ["人物与处境建立", "关键事件", "结果与余波"],
        4: ["世界建立", "事件触发", "高潮选择", "结局余波"],
        5: ["世界建立", "目标形成", "阻碍升级", "高潮选择", "结果"],
        6: ["世界建立", "事件触发", "行动推进", "意外转折", "高潮选择", "余波"],
        7: ["日常建立", "异常出现", "目标形成", "行动受阻", "真相转折", "高潮行动", "结局"],
        8: ["世界建立", "人物日常", "触发事件", "追索推进", "阻碍升级", "关系转折", "高潮行动", "余波结局"],
    }
    if panel_count in templates:
        return templates[panel_count]
    phases = ["建立", "触发", "发展", "阻碍", "转折", "高潮", "后果", "收束"]
    return [f"{phases[min(len(phases) - 1, int(index * len(phases) / panel_count))]}阶段{index + 1}" for index in range(panel_count)]


def _storyboard_task_prompt(
    panel_count,
    theme,
    user_prompt,
    selection,
    width,
    height,
    model_level,
    minimum,
    maximum,
    additional_preset,
    reference_instruction,
    reference_creative=None,
):
    columns, rows, blanks = _storyboard_layout(panel_count)
    beats = _storyboard_beats(panel_count, bool(user_prompt))
    beat_text = "\n".join(f"第{index}格：{beat}" for index, beat in enumerate(beats, 1))
    blank_text = (
        f"有效分镜之后的{blanks}个尾部空位统一绘制为完整纯黑矩形色块。"
        if blanks
        else "全部宫格均为有效分镜。"
    )
    if user_prompt:
        mode_text = "用户提示构成故事铁案，准确进入标记为“用户指定关键瞬间”的格子；其余格只推演能够自然到达和离开这个瞬间的情节。"
        user_text = user_prompt
    else:
        mode_text = "从世界观中选择一个稳定主角、一个核心目标、一个阻碍和一个结果，建立完整短故事。"
        user_text = "（空；由世界观、故事分镜用途和视觉方法建立故事）"

    if theme:
        theme_text = theme
    elif reference_creative:
        theme_text = "（空；从参考图临时创意的元素素材库扩展故事世界）"
    else:
        theme_text = "（空；依据故事用途与视觉方法建立自洽世界、角色和事件链）"
    preset = str(additional_preset or "").strip()
    preset_block = f"\n\n【本次附加设定】\n{preset}" if preset else ""
    reference_block = "" if reference_creative else _prompt_reference_block(reference_instruction)
    creative_block = _reference_creative_block(reference_creative)
    return (
        f"【单张宫格分镜任务】\n本次只生成一张复合图；有效分镜{panel_count}格。{mode_text}\n\n"
        f"【画幅与宫格】\n整张图：{_aspect_description(width, height)}\n"
        f"宫格结构：{columns}列×{rows}行，阅读方向从左到右、从上到下，格框边界清楚，格间距统一。{blank_text}\n\n"
        f"【用户核心】\n{user_text}\n\n"
        f"【取材世界观】\n{theme_text}\n\n"
        f"{creative_block + chr(10) if creative_block else ''}"
        f"{reference_block + chr(10) if reference_block else ''}"
        f"【用途与创意】\n{_combination_block(selection)}\n\n"
        f"【故事节拍】\n{beat_text}\n\n"
        "【连续性资产】\n先在成品提示词中一次确定主角与重要配角的年龄、脸型、发型、体态、服装整套配色、关键道具；一次确定主要地点的方位、入口、层级、材质和光源。随后逐格沿用这些锚点。人物从上一格离开的方向与下一格进入方向衔接，动作结果、道具状态、衣物痕迹、天气与时间持续演变。\n\n"
        "【逐格成文】\n成品提示词先写整张宫格的统一画风、角色锚点、世界规则、布局和连续性，再按格序逐一写主体位置、唯一动作阶段、作用对象、表情反应、景别机位、场景证据和与前后格的承接。建立格交代空间，推进格强化行动，高潮格使用最强视觉重心，收束格呈现明确后果。\n\n"
        f"【成文密度】\n目标成图模型等级：{MODEL_LEVEL_SPECS[_model_level_key(model_level)]['name']}。"
        f"{MODEL_LEVEL_SPECS[_model_level_key(model_level)]['instruction']}建议约{minimum}至{maximum}个中文字符。\n\n"
        "【文字限制】除非用户核心明确要求出现文字，内部创意概念、用途名称和世界观名称不得变成标题、招牌、Logo、字幕或屏幕大字；无法辨认的文字只写成不可读的装饰性纹理。\n\n"
        "【输出】\n只输出一条用于生成整张宫格分镜图的中文正向提示词正文。"
        f"{preset_block}"
    )


def _purpose_block(purpose, rank):
    role = "主导用途" if rank == 1 else f"补充用途{rank - 1}"
    focus = "、".join(purpose.get("material_focus", []))
    return (
        f"{role}：{purpose['name']}\n"
        f"作品目标：{purpose['prompt']}\n"
        f"主题取材焦点：{focus}\n"
        f"展开维度：{purpose.get('detail_prompt', '')}"
    )


def _visual_block(visual, rank):
    role = "主视觉方法" if rank == 1 else f"补充视觉方法{rank - 1}"
    return (
        f"{role}：{visual['name']}\n"
        f"空间与观看结构：{visual['prompt']}\n"
        f"落实方式：{visual.get('application', visual['description'])}"
    )


def _combination_block(selection):
    blocks = []
    for index, item in enumerate(selection, 1):
        blocks.append(_purpose_block(item["purpose"], index))
        blocks.append(_visual_block(item["visual"], index))
    if len(selection) > 1:
        blocks.append("组合关系：第一组建立作品类型与主结构，后续组合提供能够融入同一画面的补充能力。")
    return "\n\n".join(blocks)


def _variation_lenses(count):
    lenses = list(WRITING_GRAMMAR.get("variation_lenses", []))
    if not lenses:
        lenses = [{"name": "核心画面", "instruction": "选择本轮最有表现力的一种完整方案。"}]
    environment_rules = [
        "采用干燥晴朗的日间环境；不出现降雨、积水、湿地面、滴水雨伞或无来源水花。",
        "采用干燥的室内自然光环境；室内地面和家具保持正常干燥，不撑伞，不出现飘雨。",
        "采用多云但无降水的环境，使用柔和漫射光，不用湿地反光制造氛围。",
        "采用清晨干燥环境，以低角度阳光、长影和清晰空气建立时间感。",
        "采用午后干燥环境，以正常日照、材料本色和人物活动建立生活感。",
        "采用傍晚干燥环境，以暖冷交界和逐渐延长的影子建立变化。",
        "采用干燥夜间环境，以功能照明、窗口光和真实阴影建立空间，不使用雨夜作为默认气氛。",
        "采用有风但无降水的环境，用衣物、树叶、窗帘或纸张的方向表现风。",
        "采用寒冷、清晰且无降水的环境，用服装层次、呼吸和冷色自然光表现温度。",
        "采用温暖、干燥的环境，用人物动作、空气感和材料触感表现季节。",
        "天气保持中性，不把天气当成主要看点；优先从任务、关系、道具和空间痕迹建立事件。",
        "本任务可以选择一次有明确因果的降水或雨后状态，但只能发生在室外、门廊或确有漏水原因的位置；室内不得无因飘雨或撑伞。",
    ]
    rng = random.SystemRandom()
    rng.shuffle(lenses)
    rng.shuffle(environment_rules)
    result = []
    for index in range(count):
        item = dict(lenses[index % len(lenses)])
        item["environment_rule"] = environment_rules[index % len(environment_rules)]
        result.append(item)
    return result


def _task_prompt(
    index,
    count,
    mode,
    theme,
    user_prompt,
    selection,
    width,
    height,
    model_level,
    minimum,
    maximum,
    lens,
    additional_preset,
    reference_instruction,
    reference_only=False,
    reference_creative=None,
):
    if reference_only:
        mode_text = (
            "本次是参考图创意提取测试。以参考图生成的动态临时用途与创意为主要依据，"
            "保留其元素素材和核心机制，允许在同一机制内进行新主体、新物件和新媒介的想象扩展；"
            "不把参考图像素结构直接搬迁。"
        )
        user_text = user_prompt or "（空；依据参考图提取结果生成同类创意的新图）"
    elif mode == "用户执行":
        mode_text = (
            "用户提示给出本图核心。先完整写清用户明确内容，再从主题中选择能够支持该核心的素材，"
            "最后使用用途与视觉方法完成专业表达。"
        )
        user_text = user_prompt
    else:
        mode_text = (
            "本图由用途与视觉方法主导。用途决定从主题中取什么，视觉方法决定怎样表现，"
            "共同建立一个具体主体和一个可被单张图像捕捉的事件。"
        )
        user_text = "（空；本图采用主题创作模式）"

    if theme:
        theme_text = theme
    elif reference_creative:
        theme_text = "（空；从参考图临时创意的元素素材库继续扩展）"
    else:
        theme_text = "（空；依据用途与视觉方法建立自洽题材和画面素材）"
    preset = str(additional_preset or "").strip()
    preset_block = f"\n\n【本次附加设定】\n{preset}" if preset else ""
    environment_rule = str(lens.get("environment_rule", "")).strip()
    if user_prompt:
        environment_block = (
            "【环境因果纪律】\n天气、水迹、雨伞和室内外状态服从用户明确内容与真实空间因果。"
            "除非用户、参考图创意或世界观事件明确要求，不自动添加降雨、积水、湿地反光或撑伞。\n\n"
        )
    else:
        environment_block = (
            "【空提示环境状态】\n"
            f"{environment_rule}\n"
            "参考图或世界观明确指定天气时可以服从该设定；否则本条状态优先。"
            "室内降雨、室内撑伞、无来源积水和无因湿身均视为不成立。\n\n"
        )
    reference_block = "" if reference_creative else _prompt_reference_block(reference_instruction)
    creative_block = _reference_creative_block(reference_creative)
    combination_block = (
        "本次测试已旁路静态用途与视觉方法；参考图临时用途与创意保持启用。"
        if reference_only
        else (_combination_block(selection) if selection else "本次没有额外静态用途与视觉方法；仅使用参考图临时用途与创意。")
    )
    return (
        f"【单图任务】\n第{index}张，共{count}张；创作模式：{mode}\n{mode_text}\n\n"
        f"【画幅】\n{_aspect_description(width, height)}\n\n"
        f"【用户核心】\n{user_text}\n\n"
        f"【取材主题】\n{theme_text}\n\n"
        f"{creative_block + chr(10) if creative_block else ''}"
        f"{reference_block + chr(10) if reference_block else ''}"
        f"【用途与创意】\n{combination_block}\n\n"
        f"【本图变化方向】\n{lens.get('name', '核心画面')}：{lens.get('instruction', '')}\n"
        "这个方向只作用于用户尚未指定的内容，并在本图中选择一个确定方案。\n\n"
        f"{environment_block}"
        f"【成文密度】\n目标成图模型等级：{MODEL_LEVEL_SPECS[_model_level_key(model_level)]['name']}。"
        f"{MODEL_LEVEL_SPECS[_model_level_key(model_level)]['instruction']}建议约{minimum}至{maximum}个中文字符，"
        "长度服务当前用途的真实复杂度。\n\n"
        "【文字限制】除非用户核心明确要求出现文字，内部创意概念、用途名称和世界观名称不得变成标题、招牌、Logo、字幕或屏幕大字；无法辨认的文字只写成不可读的装饰性纹理。\n\n"
        "【输出】\n按照“核心画面—主题素材—用途与创意”的顺序写成一条连续、具体、可直接出图的中文正向提示词。"
        f"{preset_block}"
    )


class ZFImageReferenceAnalyzer:
    """Analyze a reference image with the already installed llama-cpp VLM and format it for the director."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "旁路"}),
                "image": ("IMAGE",),
                "reference_scope": (REFERENCE_SCOPES, {"default": REFERENCE_SCOPES[0]}),
                "reference_strength": ("FLOAT", {"default": 0.75, "min": 0.0, "max": 1.0, "step": 0.05}),
                "extract_text": ("BOOLEAN", {"default": True, "label_on": "提取文字", "label_off": "忽略文字"}),
                "protect_identity": ("BOOLEAN", {"default": True, "label_on": "保护身份", "label_off": "允许描述身份"}),
                "max_size": ("INT", {"default": 768, "min": 128, "max": 4096, "step": 64}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF, "step": 1}),
            },
            "optional": {
                "llama_model": ("LLAMACPPMODEL",),
                "parameters": ("LLAMACPPARAMS",),
                "analysis_result": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "custom_focus": ("STRING", {"default": "", "multiline": True}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("reference_instruction", "analysis_json", "reference_summary", "reference_image")
    FUNCTION = "analyze"
    CATEGORY = "ZF/参考图像"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if not bool(kwargs.get("enabled", True)):
            return False
        # The image tensor is intentionally not hashed here; NaN makes ComfyUI
        # re-run the multimodal analysis whenever the node is queued.
        return float("NaN")

    def analyze(
        self,
        enabled,
        image,
        reference_scope,
        reference_strength,
        extract_text,
        protect_identity,
        max_size,
        seed,
        llama_model=None,
        parameters=None,
        analysis_result="",
        custom_focus="",
        unique_id=None,
    ):
        if not enabled:
            return ("", "", "参考图节点已旁路", image)

        request = _reference_analysis_request(
            reference_scope,
            reference_strength,
            extract_text,
            protect_identity,
            custom_focus,
        )
        raw = str(analysis_result or "").strip()
        if not raw and llama_model is not None:
            raw = _run_reference_vlm(llama_model, request, image, parameters, seed, max_size, unique_id)
        if not raw:
            pending = (
                "尚未得到多模态分析结果。请连接 llama_model，或把现有 VLM 节点的输出接到 analysis_result。"
                f"\n\n本节点生成的分析任务：\n{request}"
            )
            return (pending, "", "等待多模态模型分析", image)

        data, original = _parse_reference_json(raw)
        instruction = _format_reference_instruction(
            data,
            original,
            reference_scope,
            reference_strength,
            extract_text,
            protect_identity,
        )
        summary = _reference_summary(data, original)
        normalized_json = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data else original
        return (instruction, normalized_json, summary, image)


class ZFTextMemory:
    """Keep a named string in the current ComfyUI process for quick A/B tests."""

    MODES = ("更新缓存", "使用缓存", "清空缓存")
    _lock = threading.RLock()
    _cache = {}
    _revision = 0

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (cls.MODES, {"default": cls.MODES[0]}),
                "cache_key": ("STRING", {"default": "参考图API分析"}),
            },
            "optional": {
                "text": ("STRING", {"forceInput": True, "lazy": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "status")
    FUNCTION = "remember"
    CATEGORY = "ZF/工具"

    @classmethod
    def IS_CHANGED(cls, mode=None, **kwargs):
        # Updating or clearing is an explicit user action.  Do not let
        # ComfyUI reuse the previous node result when the upstream API text
        # changed but the cache widget values did not.
        if mode in ("更新缓存", "清空缓存"):
            return float("NaN")
        with cls._lock:
            return float(cls._revision)

    def check_lazy_status(self, mode, cache_key, text=None):
        if mode == "更新缓存" and text is None:
            return ["text"]
        return []

    def remember(self, mode, cache_key, text=None):
        key = str(cache_key or "参考图API分析").strip() or "参考图API分析"
        with self._lock:
            if mode == "清空缓存":
                self._cache.pop(key, None)
                self.__class__._revision += 1
                return ("", f"已清空临时文本缓存：{key}")

            if mode == "更新缓存":
                value = str(text or "").strip()
                self._cache[key] = value
                self.__class__._revision += 1
                return (value, f"已更新临时文本缓存：{key}（{len(value)} 字符）")

            value = self._cache.get(key, "")
            if value:
                return (value, f"正在使用临时文本缓存：{key}（{len(value)} 字符）")
            return ("", f"临时文本缓存为空：{key}；先切换为“更新缓存”运行一次")


class ZFTextListMemory:
    """Keep a whole STRING list, such as the director's multi-task result."""

    MODES = ("更新缓存", "使用缓存", "清空缓存")
    INPUT_IS_LIST = True
    OUTPUT_IS_LIST = (True, False)
    _lock = threading.RLock()
    _cache = {}
    _revision = 0

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (cls.MODES, {"default": cls.MODES[0]}),
                "cache_key": ("STRING", {"default": "最终提示词列表"}),
            },
            "optional": {
                "text": ("STRING", {"forceInput": True, "lazy": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text_list", "status")
    FUNCTION = "remember"
    CATEGORY = "ZF/工具"

    @staticmethod
    def _first(value, default=""):
        if isinstance(value, (list, tuple)):
            return value[0] if value else default
        return value if value is not None else default

    @classmethod
    def IS_CHANGED(cls, mode=None, **kwargs):
        if cls._first(mode) in ("更新缓存", "清空缓存"):
            return float("NaN")
        with cls._lock:
            return float(cls._revision)

    @staticmethod
    def _missing(value):
        if value is None:
            return True
        if isinstance(value, (list, tuple)):
            return not value or all(item is None for item in value)
        return False

    def check_lazy_status(self, mode, cache_key, text=None):
        if self._first(mode) == "更新缓存" and self._missing(text):
            return ["text"]
        return []

    def remember(self, mode, cache_key, text=None):
        mode = self._first(mode)
        key = str(self._first(cache_key, "最终提示词列表")).strip() or "最终提示词列表"
        if text is None:
            values = []
        elif isinstance(text, (list, tuple)):
            values = [str(item or "").strip() for item in text]
        else:
            values = [str(text or "").strip()]

        with self._lock:
            if mode == "清空缓存":
                self._cache.pop(key, None)
                self.__class__._revision += 1
                return (
                    ExecutionBlocker(f"已清空最终文本列表缓存：{key}；本次停止下游执行"),
                    f"已清空最终文本列表缓存：{key}",
                )
            if mode == "更新缓存":
                self._cache[key] = values
                self.__class__._revision += 1
                return (values, f"已更新最终文本列表缓存：{key}（{len(values)} 条）")

            cached = list(self._cache.get(key, []))
            if cached:
                return (cached, f"正在使用最终文本列表缓存：{key}（{len(cached)} 条）")
            return (
                ExecutionBlocker(f"最终文本列表缓存为空：{key}；先切换为“更新缓存”运行一次"),
                f"最终文本列表缓存为空：{key}；先切换为“更新缓存”运行一次",
            )


class ZFReferenceAnalysisPromptBuilder:
    """Build the two prompts used by an external vision API for reference analysis."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "旁路"}),
                "reference_scope": (REFERENCE_SCOPES, {"default": REFERENCE_SCOPES[0]}),
                "reference_strength": ("FLOAT", {"default": 0.75, "min": 0.0, "max": 1.0, "step": 0.05}),
                "extract_text": ("BOOLEAN", {"default": True, "label_on": "提取文字", "label_off": "忽略文字"}),
                "protect_identity": ("BOOLEAN", {"default": True, "label_on": "保护身份", "label_off": "允许描述身份"}),
            },
            "optional": {
                "custom_focus": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("system_prompt", "analysis_prompt")
    FUNCTION = "build"
    CATEGORY = "ZF/参考图像/API"

    def build(
        self,
        enabled,
        reference_scope,
        reference_strength,
        extract_text,
        protect_identity,
        custom_focus="",
    ):
        if not enabled:
            return ("", "")
        return (
            REFERENCE_ANALYSIS_SYSTEM_PROMPT,
            _reference_analysis_request(
                reference_scope,
                reference_strength,
                extract_text,
                protect_identity,
                custom_focus,
            ),
        )


class ZFReferenceCreativeAdapter:
    """Turn analyzer JSON into a temporary purpose/visual combination."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "analysis_json": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "reference_instruction": ("STRING", {"default": "", "forceInput": True}),
                "reference_strength": ("FLOAT", {"default": 0.75, "min": 0.0, "max": 1.0, "step": 0.05}),
                "enabled": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "旁路"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("reference_creative_json", "reference_creative_summary")
    FUNCTION = "adapt"
    CATEGORY = "ZF/参考图像"

    def adapt(self, analysis_json, reference_instruction="", reference_strength=0.75, enabled=True):
        if not enabled:
            return ("", "参考图临时用途与创意已旁路")
        data, original = _parse_reference_json(analysis_json)
        if not original:
            original = str(reference_instruction or "").strip()
        profile = _reference_creative_profile(data, original, reference_strength)
        encoded = json.dumps(profile, ensure_ascii=False, separators=(",", ":"))
        summary = _reference_creative_block(profile)
        return (encoded, summary)


class ZFPromptDirector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": True, "label_on": "启用", "label_off": "旁路"}),
                "user_prompt": ("STRING", {"forceInput": True}),
                "theme": ("STRING", {"forceInput": True}),
                "width": ("INT", {"forceInput": True, "min": 64, "max": 16384}),
                "height": ("INT", {"forceInput": True, "min": 64, "max": 16384}),
                "count": ("INT", {"forceInput": True, "min": 1, "max": 100}),
                "selection_json": ("STRING", {"default": DEFAULT_SELECTION_JSON, "multiline": False}),
            },
            "optional": {
                "additional_preset": ("STRING", {"default": "", "multiline": True}),
                "reference_instruction": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "reference_creative_json": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "reference_image": ("IMAGE",),
                "image_model_level": (MODEL_LEVELS, {"default": DEFAULT_MODEL_LEVEL}),
                "reference_mode": (REFERENCE_MODES, {"default": REFERENCE_MODES[0]}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "BOOLEAN", "STRING", "STRING", "STRING", "INT", "INT", "IMAGE")
    RETURN_NAMES = (
        "writer_system_prompt",
        "writer_tasks",
        "original_prompt",
        "enabled",
        "selection_json",
        "selection_summary",
        "creation_mode",
        "min_chars",
        "max_chars",
        "reference_image",
    )
    OUTPUT_IS_LIST = (False, True, False, False, False, False, False, False, False, False)
    FUNCTION = "build"
    CATEGORY = "ZF/提示词创意导演"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN") if bool(kwargs.get("enabled", True)) else False

    def build(
        self,
        enabled,
        user_prompt,
        theme,
        width,
        height,
        count,
        selection_json,
        additional_preset="",
        reference_instruction="",
        reference_creative_json="",
        reference_image=None,
        image_model_level=DEFAULT_MODEL_LEVEL,
        reference_mode=REFERENCE_MODES[0],
    ):
        original = str(user_prompt or "").strip()
        theme_text = _clean_theme(theme)
        result_count = max(1, int(count))
        mode = "用户执行" if original else "主题创作"
        reference_only = str(reference_mode or REFERENCE_MODES[0]).strip() == REFERENCE_MODES[1]
        reference_creative = None
        if str(reference_creative_json or "").strip():
            try:
                parsed = json.loads(str(reference_creative_json))
                if isinstance(parsed, dict):
                    reference_creative = parsed
            except Exception:
                reference_creative = None
        selection = [] if reference_only else _safe_selection(selection_json, allow_default=not bool(reference_creative))
        if not reference_only:
            selection = _promote_storyboard(selection)
        minimum, maximum = _length_target(selection, image_model_level)
        storyboard = _is_storyboard(selection)
        if storyboard:
            level_factor = MODEL_LEVEL_SPECS[_model_level_key(image_model_level)]["length_factor"]
            minimum = max(minimum, round((650 + result_count * 145) * level_factor))
            maximum = max(maximum, round((1100 + result_count * 300) * level_factor))
            maximum = min(maximum, {"1": 2600, "2": 5200, "3": 7000}[_model_level_key(image_model_level)])
        normalized = {
            "version": 2,
            "image_model_level": _model_level_name(image_model_level),
            "storyboard": storyboard,
            "panel_count": result_count if storyboard else None,
            "combinations": [
                {
                    "purpose": item["purpose"]["id"],
                    "visual": item["visual"]["id"],
                    "strength": item["strength"],
                    "enabled": True,
                }
                for item in selection
            ],
        }
        normalized_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))

        if enabled and storyboard:
            tasks = [
                _storyboard_task_prompt(
                    panel_count=result_count,
                    theme=theme_text,
                    user_prompt=original,
                    selection=selection,
                    width=width,
                    height=height,
                    model_level=image_model_level,
                    minimum=minimum,
                    maximum=maximum,
                    additional_preset=additional_preset,
                    reference_instruction=reference_instruction,
                    reference_creative=reference_creative,
                )
            ]
        elif enabled:
            if reference_only:
                lenses = [
                    {
                        "name": "参考图创意机制",
                        "instruction": "保持参考图提取出的创意机制、构图关系、材质和氛围作为主依据，不追加其它风格方向。",
                    }
                    for _ in range(result_count)
                ]
            else:
                lenses = _variation_lenses(result_count)
            tasks = [
                _task_prompt(
                    index=index + 1,
                    count=result_count,
                    mode=mode,
                    theme=theme_text,
                    user_prompt=original,
                    selection=selection,
                    width=width,
                    height=height,
                    model_level=image_model_level,
                    minimum=minimum,
                    maximum=maximum,
                    lens=lenses[index],
                    additional_preset=additional_preset,
                    reference_instruction=reference_instruction,
                    reference_only=reference_only,
                    reference_creative=reference_creative,
                )
                for index in range(result_count)
            ]
        else:
            tasks = [original]

        creation_mode = (
            REFERENCE_MODES[1]
            if reference_only
            else (f"故事分镜（{'用户瞬间' if original else '主题创作'}）" if storyboard else mode)
        )
        dynamic_summary = "参考图临时用途与创意" if reference_creative else "无参考图临时创意"
        summary = f"{creation_mode}｜{_model_level_name(image_model_level)}｜{dynamic_summary}｜{_selection_summary(selection)}"
        return (
            DIRECTOR_SYSTEM_PROMPT,
            tasks,
            original,
            bool(enabled),
            normalized_json,
            summary,
            creation_mode,
            minimum,
            maximum,
            reference_image,
        )


class ZFBlueprintParser:
    """Legacy compatibility node. Version 2 no longer uses a model-authored blueprint list."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "planner_output": ("STRING", {"forceInput": True}),
                "expected_count": ("INT", {"forceInput": True, "min": 1, "max": 100}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN", "INT")
    RETURN_NAMES = ("blueprints", "report", "valid", "actual_count")
    OUTPUT_IS_LIST = (True, False, False, False)
    FUNCTION = "parse"
    CATEGORY = "ZF/提示词创意导演/旧版兼容"

    def parse(self, planner_output, expected_count):
        text = str(planner_output or "").strip()
        items = [text] if text else ["主题创作任务"]
        return (items, "旧版兼容节点；V2工作流无需连接此节点", bool(text), len(items))


class ZFSinglePromptTask:
    """Legacy compatibility node. Version 2 sends director tasks straight to the writer model."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"forceInput": True}),
                "blueprint": ("STRING", {"forceInput": True}),
                "theme": ("STRING", {"forceInput": True}),
                "user_prompt": ("STRING", {"forceInput": True}),
                "selection_json": ("STRING", {"forceInput": True}),
                "width": ("INT", {"forceInput": True}),
                "height": ("INT", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("writer_system_prompt", "writer_user_prompt", "min_chars", "max_chars")
    FUNCTION = "build"
    CATEGORY = "ZF/提示词创意导演/旧版兼容"

    def build(self, enabled, blueprint, theme, user_prompt, selection_json, width, height):
        selection = _safe_selection(selection_json)
        minimum, maximum = _length_target(selection, DEFAULT_MODEL_LEVEL)
        return (DIRECTOR_SYSTEM_PROMPT, str(blueprint or user_prompt or "主题创作任务"), minimum, maximum)


class ZFDecisiveLlamaParams:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"parameters": ("LLAMACPPARAMS",)}}

    RETURN_TYPES = ("LLAMACPPARAMS",)
    RETURN_NAMES = ("parameters",)
    FUNCTION = "apply"
    CATEGORY = "ZF/提示词创意导演/辅助"

    def apply(self, parameters):
        result = dict(parameters or {})
        result.pop("grammar", None)
        return (result,)


class ZFPromptValidator:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"forceInput": True}),
                "generated_prompt": ("STRING", {"forceInput": True}),
                "original_prompt": ("STRING", {"forceInput": True}),
                "min_chars": ("INT", {"forceInput": True}),
                "max_chars": ("INT", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING", "INT")
    RETURN_NAMES = ("prompt", "valid", "report", "char_count")
    FUNCTION = "validate"
    CATEGORY = "ZF/提示词创意导演"

    def validate(self, enabled, generated_prompt, original_prompt, min_chars, max_chars):
        if not enabled:
            prompt = str(original_prompt or "").strip()
            return (prompt, True, "总开关关闭：原始提示词旁路", len(prompt))

        prompt = str(generated_prompt or "").strip()
        prompt = re.sub(r"^```(?:text|markdown)?\s*", "", prompt, flags=re.I)
        prompt = re.sub(r"\s*```$", "", prompt)
        prompt = re.sub(r"^\s*(?:最终)?提示词\s*[:：]\s*", "", prompt)
        prompt = re.sub(r"\s*--preview\s*$", "", prompt, flags=re.I)
        prompt = re.sub(r"\s*[\r\n]+\s*", "，", prompt)
        prompt = re.sub(r"，{2,}", "，", prompt).strip("， ")
        count = len(prompt)

        notes = []
        if count < int(min_chars):
            notes.append(f"低于建议{int(min_chars)}")
        if count > int(max_chars):
            notes.append(f"高于建议{int(max_chars)}")
        valid = bool(prompt)
        if not prompt:
            report = "输出为空"
        elif notes:
            report = f"已输出｜{count}字符｜" + "；".join(notes)
        else:
            report = f"已输出｜{count}字符｜建议区间内"
        return (prompt, valid, report, count)


class ZFLazyPromptSwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"forceInput": True}),
                "original_prompt": ("STRING", {"forceInput": True, "lazy": True}),
                "enhanced_prompt": ("STRING", {"forceInput": True, "lazy": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "choose"
    CATEGORY = "ZF/提示词创意导演"

    def check_lazy_status(self, enabled, original_prompt=None, enhanced_prompt=None):
        needed = "enhanced_prompt" if enabled else "original_prompt"
        value = enhanced_prompt if enabled else original_prompt
        return [needed] if value is None else []

    def choose(self, enabled, original_prompt=None, enhanced_prompt=None):
        return (enhanced_prompt if enabled else original_prompt,)


NODE_CLASS_MAPPINGS = {
    "ZFImageReferenceAnalyzer": ZFImageReferenceAnalyzer,
    "ZFTextMemory": ZFTextMemory,
    "ZFTextListMemory": ZFTextListMemory,
    "ZFReferenceAnalysisPromptBuilder": ZFReferenceAnalysisPromptBuilder,
    "ZFReferenceCreativeAdapter": ZFReferenceCreativeAdapter,
    "ZFPromptDirector": ZFPromptDirector,
    "ZFBlueprintParser": ZFBlueprintParser,
    "ZFSinglePromptTask": ZFSinglePromptTask,
    "ZFDecisiveLlamaParams": ZFDecisiveLlamaParams,
    "ZFPromptValidator": ZFPromptValidator,
    "ZFLazyPromptSwitch": ZFLazyPromptSwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ZFImageReferenceAnalyzer": "ZF 参考图像分析器",
    "ZFTextMemory": "ZF 临时文本缓存（跨队列复用）",
    "ZFTextListMemory": "ZF 最终文本列表缓存（跨队列复用）",
    "ZFReferenceAnalysisPromptBuilder": "ZF 产品图/参考图分析生成器（API）",
    "ZFReferenceCreativeAdapter": "ZF 参考图临时用途与创意适配器",
    "ZFPromptDirector": "ZF 提示词创意导演 V2",
    "ZFBlueprintParser": "ZF 视觉蓝图解析器（旧版兼容）",
    "ZFSinglePromptTask": "ZF 单图写作任务（旧版兼容）",
    "ZFDecisiveLlamaParams": "ZF Llama参数透传",
    "ZFPromptValidator": "ZF 提示词整理与观察",
    "ZFLazyPromptSwitch": "ZF 提示词总开关",
}
