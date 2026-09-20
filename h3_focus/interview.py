"""Collect, align and organize user input without generating model instructions.

The media desk owns files and time. This module preserves user text and explicit
reference roles; model interpretation and prompt presets live downstream.
"""

from __future__ import annotations

import copy
import json
import math
import re

from .reference_detection import compare_detection
from .reference_plan import planned_detection
from .routing import RULES, BANKS_BY_KIND, alignment_context, binding_for, mechanical_entries
from .references import LABEL_RE, entry_errors, sync_references


SCHEMA_VERSION = "zv-h3-interview-v2"
MAX_JSON_BYTES = 256 * 1024
MODES = ("auto", "T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA", "Hybrid")
FOCUSES = ("balanced", "dialogue", "action")

TEXT_FIELDS = (
    "intent",
    "style",
    "must_keep",
    "must_change",
    "ending",
    "forbidden",
    "performance",
    "camera",
    "dialogue",
    "visible_text",
    "soundscape",
    "music",
)

PICTURE_ROLES = (
    "subject_identity",
    "first_frame",
    "last_frame",
    "keyframe",
    "composition_reference",
    "style_reference",
    "storyboard",
)
VIDEO_ROLES = (
    "motion_reference",
    "camera_reference",
    "structure_reference",
    "video_edit",
    "video_continue",
    "subject_identity",
)
AUDIO_ROLES = (
    "speech_lipsync",
    "audio_reuse",
    "voice_reference",
    "music_reference",
    "sound_reference",
)
ROLES_BY_KIND = {
    "picture": PICTURE_ROLES,
    "video": VIDEO_ROLES,
    "audio": AUDIO_ROLES,
}

CALL_LABEL_KIND = {
    "picture": "Picture",
    "video": "Video",
    "audio": "Audio",
}

ROLE_LABELS = {
    "subject_identity": "主体身份/外观",
    "first_frame": "首帧",
    "last_frame": "尾帧",
    "keyframe": "关键帧",
    "composition_reference": "构图参考",
    "style_reference": "风格参考",
    "storyboard": "分镜参考",
    "motion_reference": "动作参考",
    "camera_reference": "运镜参考",
    "structure_reference": "节奏/结构参考",
    "video_edit": "原视频编辑",
    "video_continue": "视频续写",
    "speech_lipsync": "台词与口型",
    "audio_reuse": "直接复用音轨",
    "voice_reference": "音色/说话方式参考",
    "music_reference": "音乐参考",
    "sound_reference": "声音参考",
    "video_soundtrack": "视频原声",
}

FIELD_LABELS = {
    "intent": "创作要求",
    "style": "画面风格与质感",
    "must_keep": "必须保留",
    "must_change": "必须改变",
    "ending": "结尾必须到达",
    "forbidden": "不能出现或需要避免",
    "performance": "动作与表演",
    "camera": "镜头与运镜",
    "dialogue": "对白或歌词原文",
    "visible_text": "画面可见文字原文",
    "soundscape": "环境声与物理声音",
    "music": "仅供观众听到的配乐",
}
ROUTE_LABELS = {
    "first_frame": "首帧接口",
    "last_frame": "尾帧接口",
    "ref_images": "参考图片接口",
    "ref_videos": "参考视频接口",
    "ref_video_audios": "视频原声接口",
    "ref_audios": "参考音频接口",
    "drive_audio": "驱动音频接口",
}
MATERIAL_CONTEXT_VERSION = "zv-h3-material-context-v1"

class InterviewError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("Invalid H3 interview")


def issue(path, code, message):
    return {"path": path, "code": code, "message": message}


def empty_interview():
    state = {
        "schema_version": SCHEMA_VERSION,
        "mode": "auto",
        "director_focus": "balanced",
        "media_roles": {},
        "media_purposes": {},
        "bindings": {},
        "alignment": None,
        "reference_detection": None,
        "reference_texts": {},
        "preset_pending": [],
    }
    state.update({field: "" for field in TEXT_FIELDS})
    return state


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_interview(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise InterviewError([issue("", "json_size", "采访数据必须小于 256 KiB")])
    try:
        value = json.loads(text or "{}", object_pairs_hook=_pairs, parse_constant=lambda _x: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError):
        raise InterviewError([issue("", "invalid_json", "采访数据不是合法 JSON，或包含重复字段/非法数值")]) from None
    if not isinstance(value, dict):
        raise InterviewError([issue("", "type", "采访数据必须是对象")])
    return value


def normalize_interview(value):
    if not isinstance(value, dict):
        raise InterviewError([issue("", "type", "采访数据必须是对象")])
    try:
        state_size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, RecursionError):
        raise InterviewError([issue("", "invalid_json", "采访状态包含非法数值或结构")]) from None
    if state_size > MAX_JSON_BYTES:
        raise InterviewError([issue("", "json_size", "当前采访状态（含引用与快照）最多256 KiB")])
    value = {key: val for key, val in value.items() if key not in {"recipe", "migration"}}
    defaults = empty_interview()
    allowed = set(defaults)
    errors = [issue("/" + key, "unknown_field", "采访数据包含未知字段") for key in value if key not in allowed]
    state = copy.deepcopy(defaults)
    state.update({key: copy.deepcopy(val) for key, val in value.items() if key in allowed})
    if state["schema_version"] != SCHEMA_VERSION:
        errors.append(issue("/schema_version", "schema_version", "采访版本不受支持"))
    if state["mode"] not in MODES:
        errors.append(issue("/mode", "choice", "H3 模式不受支持"))
    if state["director_focus"] not in FOCUSES:
        errors.append(issue("/director_focus", "choice", "导演侧重不受支持"))
    for field in TEXT_FIELDS:
        value = state[field]
        if not isinstance(value, str):
            errors.append(issue("/" + field, "type", "采访文本必须是字符串"))
            state[field] = ""
        elif len(value) > (16000 if isinstance(state.get("reference_texts"), dict) and isinstance(state["reference_texts"].get(field), dict) and state["reference_texts"][field].get("rendered") == value else 12000):
            errors.append(issue("/" + field, "length", "单项采访文本最多 12000 字符"))
        else:
            state[field] = value
    roles = state["media_roles"]
    if not isinstance(roles, dict):
        errors.append(issue("/media_roles", "type", "素材用途必须是按稳定素材 ID 保存的对象"))
        roles = {}
    normalized_roles = {}
    for item_id, assigned in roles.items():
        if not isinstance(item_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", item_id):
            errors.append(issue("/media_roles", "item_id", "素材用途包含非法稳定 ID"))
            continue
        if isinstance(assigned, str):
            assigned = [assigned]
        if not isinstance(assigned, list) or any(not isinstance(role, str) for role in assigned):
            errors.append(issue(f"/media_roles/{item_id}", "type", "每个素材的用途必须是字符串列表"))
            continue
        deduped = []
        for role in assigned:
            if role and role not in deduped:
                deduped.append(role)
        if deduped:
            normalized_roles[item_id] = deduped
    state["media_roles"] = normalized_roles
    purposes = state["media_purposes"]
    if not isinstance(purposes, dict):
        errors.append(issue("/media_purposes", "type", "自由用途必须是按稳定 ID 保存的文本对象"))
    else:
        for item_id, purpose in purposes.items():
            entry = state.get("reference_texts", {}).get("purpose:" + item_id) if isinstance(item_id, str) and isinstance(state.get("reference_texts"), dict) else None
            limit = 16000 if isinstance(entry, dict) and entry.get("rendered") == purpose else 12000
            if not isinstance(item_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", item_id) or not isinstance(purpose, str) or len(purpose) > limit:
                errors.append(issue("/media_purposes", "purpose", "自由用途需要合法稳定 ID 和不超过 12000 字符的文本"))
    bindings = state["bindings"]
    if not isinstance(bindings, dict):
        errors.append(issue("/bindings", "type", "机械绑定必须是按稳定 ID 保存的对象"))
    else:
        for item_id, binding in bindings.items():
            path = f"/bindings/{item_id}"
            if not isinstance(item_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", item_id) or not isinstance(binding, dict):
                errors.append(issue(path, "binding", "机械绑定需要合法稳定 ID 和对象"))
                continue
            if set(binding) != {"item_id", "participates", "banks"} or binding.get("item_id") != item_id or type(binding.get("participates")) is not bool:
                errors.append(issue(path, "binding", "绑定须记录一致 item_id、参与布尔值和 banks"))
            banks = binding.get("banks")
            if not isinstance(banks, list) or not banks or any(not isinstance(bank, str) or bank not in RULES['banks'] for bank in banks) or len(set(banks)) != len(banks):
                errors.append(issue(path + "/banks", "bank", "物理接口须为非空且无重复的已知接口列表"))
    if state["alignment"] is not None and (not isinstance(state["alignment"], dict) or state["alignment"].get("version") != 1):
        errors.append(issue("/alignment", "alignment", "对齐上下文版本不受支持，请重新检测"))
    reference_texts = state["reference_texts"]
    if not isinstance(reference_texts, dict) or len(reference_texts) > 1536:
        errors.append(issue("/reference_texts", "reference_contract", "实时引用须为受限字段对象"))
    else:
        for key, entry in reference_texts.items():
            if key not in TEXT_FIELDS and not re.fullmatch(r"purpose:[A-Za-z0-9_-]{1,96}", key):
                errors.append(issue("/reference_texts", "reference_contract", "引用字段未知"))
            errors.extend(issue("/reference_texts/" + key, "reference_contract", message) for message in entry_errors(entry, runtime=True))
    from .presets import validate_pending, PresetError
    pending = state["preset_pending"]
    if not isinstance(pending, list) or len(pending) > 1536:
        errors.append(issue("/preset_pending", "preset_pending", "待绑定槽位列表无效"))
    else:
        pending_ids = set()
        for row in pending:
            try:
                validate_pending(row)
                identity = (row["slot"]["kind"], row["slot"]["slot"])
                if identity in pending_ids:
                    errors.append(issue("/preset_pending", "preset_pending", "待绑定槽位重复"))
                pending_ids.add(identity)
            except PresetError as error: errors.append(issue("/preset_pending", "preset_pending", error.message))
    detection = state["reference_detection"]
    if detection is not None:
        if not isinstance(detection, dict):
            errors.append(issue("/reference_detection", "type", "线路检测快照必须是对象或 null"))
            detection = {}
        allowed_detection = {"version", "pictures", "videos", "audios", "stage1", "conditioning_count"}
        for key in detection:
            if key not in allowed_detection:
                errors.append(issue(f"/reference_detection/{key}", "unknown_field", "线路检测快照包含未知字段"))
        if detection.get("version") != 1:
            errors.append(issue("/reference_detection/version", "version", "线路检测快照版本必须为 1"))
        normalized_detection = {"version": 1}
        for plural in ("pictures", "videos", "audios"):
            entries = detection.get(plural, [])
            if not isinstance(entries, list):
                errors.append(issue(f"/reference_detection/{plural}", "type", "线路检测结果必须是按实际端口顺序排列的对象列表"))
                entries = []
            normalized_entries = []
            for index, entry in enumerate(entries):
                path = f"/reference_detection/{plural}/{index}"
                if not isinstance(entry, dict):
                    errors.append(issue(path, "type", "线路检测项必须是对象"))
                    continue
                item_id = entry.get("item_id")
                if not isinstance(item_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", item_id):
                    errors.append(issue(path + "/item_id", "item_id", "线路检测项必须包含合法稳定 ID"))
                    continue
                source_kind = entry.get("source_kind")
                source_port = entry.get("source_port")
                if not isinstance(source_kind, str) or not source_kind:
                    errors.append(issue(path + "/source_kind", "source_kind", "线路检测项缺少来源节点类型"))
                if not isinstance(source_port, (str, int)) or isinstance(source_port, bool):
                    errors.append(issue(path + "/source_port", "source_port", "线路检测项缺少来源端口"))
                normalized_entry = {"item_id": item_id, "source_kind": source_kind, "source_port": source_port}
                allowed_origins = {
                    "pictures": {"first_frame", "last_frame", "reference"},
                    "videos": {"reference"},
                    "audios": {"standalone", "video_soundtrack", "drive_audio"},
                }[plural]
                default_origin = "standalone" if plural == "audios" else "reference"
                origin = entry.get("origin", default_origin)
                if origin not in allowed_origins:
                    errors.append(issue(path + "/origin", "origin", f"{plural} 线路来源不受支持"))
                    origin = default_origin
                normalized_entry["origin"] = origin
                normalized_entries.append(normalized_entry)
            normalized_detection[plural] = normalized_entries
        stage1 = detection.get("stage1", {})
        if not isinstance(stage1, dict):
            errors.append(issue("/reference_detection/stage1", "type", "Stage①线路检测必须是对象"))
            stage1 = {}
        normalized_stage1 = {}
        for plural in ("pictures", "videos"):
            item_ids = stage1.get(plural, [])
            if not isinstance(item_ids, list) or any(not isinstance(item_id, str) for item_id in item_ids):
                errors.append(issue(f"/reference_detection/stage1/{plural}", "type", "Stage①线路顺序必须是稳定 ID 列表"))
                item_ids = []
            # One stable image may intentionally occupy first_frame,
            # last_frame and/or a ref_image socket. Preserve that semantic
            # multiplicity so Stage① numbering matches the actual H3 order.
            normalized_stage1[plural] = list(item_ids)
        normalized_detection["stage1"] = normalized_stage1
        count = detection.get("conditioning_count", 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(issue("/reference_detection/conditioning_count", "type", "H3 Conditioning 数量必须是非负整数"))
            count = 0
        normalized_detection["conditioning_count"] = count
        state["reference_detection"] = normalized_detection
    if errors:
        raise InterviewError(errors)
    return state


def media_inventory(project):
    assets = {asset["asset_id"]: asset for asset in project.get("assets", [])}
    labels = {row["item_id"]: row for row in project.get("label_map", [])}
    window = project.get("processing_window", {})
    start, end = float(window.get("start_seconds", 0)), float(window.get("end_seconds", 0))
    rows = []
    for kind, track_name in (("picture", "picture_track"), ("video", "video_track"), ("audio", "audio_track")):
        for item in sorted(project.get(track_name, []), key=lambda item: (
            item.get("order", 0) if kind == "picture" else item.get("timeline_in_seconds", 0),
            item.get("item_id", item.get("clip_id", "")),
        )):
            item_id = item.get("item_id", item.get("clip_id"))
            label_row = labels.get(item_id, {})
            asset = assets.get(item.get("asset_id"), {})
            timeline_in = item.get("timeline_in_seconds")
            timeline_out = item.get("timeline_out_seconds")
            in_window = True if kind == "picture" else bool(
                isinstance(timeline_in, (int, float))
                and isinstance(timeline_out, (int, float))
                and timeline_out > start + 1e-9
                and timeline_in < end - 1e-9
            )
            rows.append({
                "kind": kind,
                "item_id": item_id,
                "asset_id": item.get("asset_id"),
                "display_label": label_row.get("label", "未编号"),
                "display_ordinal": label_row.get("ordinal"),
                "call_label": "",
                "call_ordinal": None,
                "name": asset.get("name", "素材不存在"),
                "in_window": in_window,
                "enabled": item.get("enabled", True),
                "linked_video_clip_id": item.get("linked_video_clip_id"),
                "source_audio_enabled": item.get("source_audio_enabled", False),
                "audio_link_id": item.get("audio_link_id"),
                "timeline_in_seconds": timeline_in,
                "timeline_out_seconds": timeline_out,
                "source_in_seconds": item.get("source_in_seconds"),
                "source_out_seconds": item.get("source_out_seconds"),
            })
    return rows


def _active(state, inventory):
    return [(row, state["media_roles"].get(row["item_id"], [])) for row in inventory if binding_for(state, row)["participates"]]


def _call_references(state, inventory):
    """Physical slots assign labels. Semantics only annotate the resulting calls."""
    detection = state["reference_detection"]
    fixed = detection is None or all(
        entry.get("source_kind") == "ZVH3ReferenceOutlet"
        for plural in ("pictures", "videos", "audios") for entry in detection[plural]
    )
    entries_by_kind = mechanical_entries(state, inventory) if fixed else detection
    by_kind_id = {(row["kind"], row["item_id"]): row for row in inventory}
    calls = []
    for kind, label_kind in CALL_LABEL_KIND.items():
        for ordinal, entry in enumerate(entries_by_kind[kind + "s"], 1):
            item_id = entry["item_id"]
            soundtrack = kind == "audio" and entry.get("origin") == "video_soundtrack"
            row = by_kind_id.get(("video" if soundtrack else kind, item_id))
            semantic_id = row["audio_link_id"] if soundtrack and row else item_id
            calls.append({
                "kind": kind, "item_id": item_id,
                "origin": entry.get("origin", "standalone" if kind == "audio" else "reference"),
                "display_label": (row["display_label"] + (" 原声" if soundtrack else "")) if row else "素材不存在",
                "call_label": f"<{label_kind} {ordinal}>", "call_ordinal": ordinal,
                "name": row["name"] if row else "素材不存在",
                "timeline_in_seconds": row.get("timeline_in_seconds") if row else None,
                "timeline_out_seconds": row.get("timeline_out_seconds") if row else None,
                "source_in_seconds": row.get("source_in_seconds") if row else None,
                "source_out_seconds": row.get("source_out_seconds") if row else None,
                "roles": (["video_soundtrack"] if soundtrack else []) + list(state["media_roles"].get(semantic_id, [])),
                "purpose": state["media_purposes"].get(semantic_id, ""),
                "purpose_item_id": semantic_id,
                "soundtrack": soundtrack, "resolved": row is not None,
            })
    return calls


def infer_mode(state, inventory):
    detection = state["reference_detection"]
    entries = detection if detection is not None and any(entry.get("source_kind") != "ZVH3ReferenceOutlet" for plural in ("pictures", "videos", "audios") for entry in detection[plural]) else mechanical_entries(state, inventory)
    anchors = {row["origin"] for row in entries["pictures"] if row["origin"] != "reference"}
    refs = bool(entries["videos"] or entries["audios"] or any(row["origin"] == "reference" for row in entries["pictures"]))
    if refs:
        return "Hybrid" if anchors else "Ref2VA"
    if anchors == {"first_frame", "last_frame"}:
        return "FL2VA"
    if anchors == {"first_frame"}:
        return "I2VA"
    if anchors == {"last_frame"}:
        return "L2VA"
    return "T2VA"


def validate_interview(state, project, inventory, call_references=None):
    errors, warnings = [], []
    calls = _call_references(state, inventory) if call_references is None else call_references
    if not state["intent"].strip():
        warnings.append(issue("/intent", "semantic_empty", "生成目标可留空；建议写明剧情和素材关系"))
    for problem in project.get("validation", {}).get("errors", []):
        errors.append(issue("/media_project" + problem.get("path", ""), "media_project", problem.get("message", "素材工程无效")))
    window = project.get("processing_window", {})
    start, end, fps, frames = (window.get(key) for key in ("start_seconds", "end_seconds", "fps", "frame_count"))
    valid_window = all(type(value) in (int, float) and math.isfinite(value) for value in (start, end, fps)) and type(frames) is int
    output_frames = None
    if not valid_window:
        errors.append(issue("/media_project/processing_window", "window", "素材台窗口缺少合法秒数、fps 或帧数"))
    else:
        output = RULES["output"]
        duration = end - start
        if fps != output["fps"]:
            errors.append(issue("/media_project/processing_window/fps", "h3_fps", "官方输出要求 24 fps"))
        if not output["min_seconds"] * fps <= frames <= output["max_seconds"] * fps:
            errors.append(issue("/media_project/processing_window/frame_count", "h3_frames", f"官方目标输出 96–360 帧（4–15 秒）；当前 {frames} 帧，参考片段最短 2 秒不代表输出最短 2 秒"))
        if not output["min_seconds"] <= duration <= output["max_seconds"]:
            errors.append(issue("/media_project/processing_window", "h3_seconds", f"官方目标输出要求 4–15 秒；当前 {duration:.3f} 秒"))
        if any(abs(value * output["fps"] - round(value * output["fps"])) > 1e-6 for value in (start, end)) or abs(duration * fps - frames) > 1e-6:
            errors.append(issue("/media_project/processing_window", "h3_grid", "窗口起止点及帧数必须一致且对齐 24 fps 网格"))
        local = RULES["local_length"]
        output_frames = max(local["min"], frames)
        output_frames += (local["remainder"] - output_frames) % local["step"]
        if output_frames != frames:
            warnings.append(issue("/media_project/processing_window", "local_length_grid", f"目标 {duration:.3f} 秒 / {frames} 帧；节点处理网格向上对齐为 {output_frames} 帧 / {output_frames / output['fps']:.3f} 秒。这是本地网格容差，官方范围仍为 4–15 秒"))
    if project.get("processing_preset", {}).get("snapshot", {}).get("strategy") != "single_window":
        errors.append(issue("/media_project/processing_preset", "h3_single", "本采访表只接受单窗口；请在素材台切换单窗口预设"))
    if project.get("preset_compatibility", {}).get("compatible") is False:
        for problem in project.get("preset_compatibility", {}).get("issues", []):
            errors.append(issue("/media_project" + problem.get("path", ""), "preset", problem.get("message", "窗口与预设不兼容")))

    by_id = {row["item_id"]: row for row in inventory}
    for item_id, binding in state["bindings"].items():
        if item_id not in by_id and binding["participates"]:
            errors.append(issue(f"/bindings/{item_id}", "stale_media", "参与素材已删除；请清理失效绑定并重新检测"))
    for row, roles in _active(state, inventory):
        path = f"/bindings/{row['item_id']}"
        binding = binding_for(state, row)
        if any(bank not in BANKS_BY_KIND[row["kind"]] for bank in binding["banks"]):
            errors.append(issue(path, "bank_kind", f"{row['display_label']} 的类型与物理接口不匹配"))
        if row["linked_video_clip_id"]:
            errors.append(issue(path, "linked_audio", "绑定原声仅使用同号视频通道；请在素材台解绑后再作为独立音频参与"))
        if not row["enabled"]:
            errors.append(issue(path, "disabled_audio", f"{row['display_label']} 已关闭；取消参与或在素材台启用"))
        if row["kind"] == "audio" and len(binding["banks"]) > 1:
            errors.append(issue(path, "audio_duplicate", "独立音频只能选择 drive_audio 或 ref_audios 中的一个"))
        if row["kind"] == "video" and row["source_audio_enabled"]:
            linked = by_id.get(row["audio_link_id"])
            if not linked or linked["kind"] != "audio" or linked["linked_video_clip_id"] != row["item_id"] or linked["asset_id"] != row["asset_id"] or not linked["enabled"]:
                errors.append(issue(path, "soundtrack_pair", f"{row['display_label']} 原声没有有效同源配对；请在素材台修复原声状态"))
    for item_id, roles in state["media_roles"].items():
        row = by_id.get(item_id)
        if not row:
            warnings.append(issue(f"/media_roles/{item_id}", "semantic_stale", "语义标签指向旧素材；可清理，不影响真实素材路由"))
        elif any(role not in ROLES_BY_KIND[row["kind"]] for role in roles):
            warnings.append(issue(f"/media_roles/{item_id}", "semantic_role", "此类型的语义标签仅作为自由创作说明，不改变接口"))

    origins_to_bank = {"first_frame": "first_frame", "last_frame": "last_frame", "video_soundtrack": "ref_video_audios", "drive_audio": "drive_audio"}
    counts = {bank: 0 for bank in RULES["banks"]}
    totals = {bank: 0.0 for bank in ("ref_videos", "ref_video_audios", "ref_audios", "drive_audio")}
    for call in calls:
        bank = origins_to_bank.get(call["origin"], {"picture": "ref_images", "video": "ref_videos", "audio": "ref_audios"}[call["kind"]])
        counts[bank] += 1
        if not call["resolved"]:
            errors.append(issue("/reference_detection", "detection_source_missing", f"{call['call_label']} 的稳定 ID 不存在或类型不符"))
        if valid_window and call["kind"] != "picture" and call["resolved"]:
            source_row = by_id[call["item_id"]]
            overlap = source_row["source_out_seconds"] - source_row["source_in_seconds"]
            rate = 24 if call["kind"] == "video" or call["soundtrack"] else 44100
            overlap = math.floor(overlap * rate + .5) / rate
            totals[bank] += overlap
            ref = RULES["reference"]
            if not ref["min_seconds"] - 1e-9 <= overlap <= ref["max_seconds"] + 1e-9:
                code = "reference_video_frames" if call["kind"] == "video" else "reference_audio_seconds"
                errors.append(issue("/bindings/" + call["item_id"], code, f"{call['call_label']} 素材台选定参考段 {overlap:.3f} 秒 / {round(overlap * 24)} 帧；参考 AV 每段要求 2–15 秒，请调整素材台源入/出点"))
    for bank, maximum in RULES["banks"].items():
        if counts[bank] > maximum:
            errors.append(issue("/bindings", "media_limit", f"物理接口 {bank} 最多 {maximum} 项；当前 {counts[bank]} 项"))
    # Count transmitted source slots, not role labels or filenames. Each
    # soundtrack is part of its video file; detached clips count independently.
    mixed = sum(counts.values()) - counts["ref_video_audios"]
    if mixed > RULES["reference"]["mixed_sources"]:
        errors.append(issue("/bindings", "mixed_sources", f"混合输入最多 12 个素材项；当前 {mixed}，视频原声不重复计源"))
    for bank, total in totals.items():
        if total > RULES["reference"]["class_total_seconds"] + 1e-9:
            errors.append(issue("/bindings", "reference_total_seconds", f"{bank} 参考总长 {total:.3f} 秒，最多 15 秒；缩短窗口/片段或取消参与"))

    inferred = infer_mode(state, inventory)
    # Mode is a user note, never a routing gate.
    if state["mode"] not in ("auto", inferred):
        warnings.append(issue("/mode", "legacy_mode", f"保存的模式 {state['mode']} 仅作参考；真实接口为 {inferred}"))
    combined_audio_extension = counts["ref_video_audios"] + counts["ref_audios"] + counts["drive_audio"] > 3 or sum(totals[bank] for bank in ("ref_video_audios", "ref_audios", "drive_audio")) > 15 + 1e-9
    extension = inferred == "Hybrid" or bool(counts["drive_audio"]) or (bool(counts["ref_audios"]) and not counts["ref_images"] and not counts["ref_videos"]) or combined_audio_extension
    if extension:
        warnings.append(issue("/bindings", "local_extension", "混合参考或驱动声音组合需使用兼容节点与模型并确认对应接口；官方标准组合能力不作保证"))
    if combined_audio_extension:
        warnings.append(issue("/bindings", "local_audio_channels", "视频配对原声与独立音频分别接收；组合音频数量/总长超过官方明确的独立音频说明，属于本地兼容路径，请确认节点与模型兼容"))
    for call in calls:
        if not call["roles"] and not call["purpose"]:
            warnings.append(issue("/media_roles", "semantic_unassigned", f"{call['call_label']} 已参与，语义用途可留空或补写"))
    available = {kind: sum(call["kind"] == kind for call in calls) for kind in CALL_LABEL_KIND}
    purpose_ids = {call["purpose_item_id"] for call in calls if call["resolved"]}
    fields = [(key, state[key]) for key in TEXT_FIELDS] + [("media_purposes/" + item_id, text) for item_id, text in state["media_purposes"].items() if item_id in purpose_ids]
    for item_id, text in state["media_purposes"].items():
        if text and item_id not in purpose_ids:
            warnings.append(issue("/media_purposes/" + item_id, "unused_purpose", "未参与或已删除素材的用途未送入提示；可清理，不阻止当前执行"))
    for field, text in fields:
        for match in LABEL_RE.finditer(text):
            label, ordinal = match.group(1), int(match.group(2)) if len(match.group(2)) <= 9 else 999999999
            kind = next(kind for kind, value in CALL_LABEL_KIND.items() if value == label)
            if not 1 <= ordinal <= available[kind]:
                legal = f"{label} 1–{available[kind]}" if available[kind] else f"无 {label} 接口"
                errors.append(issue("/" + field, "missing_prompt_reference", f"引用 {label} {ordinal} 不存在；本次有效编号：{legal}。请按检测编号修改引用"))

    detection = state["reference_detection"]
    if detection is not None:
        if calls and state["alignment"] is None:
            errors.append(issue("/alignment", "alignment_missing", "旧快照缺少可核实素材上下文；请首次手动检测，建立当前来源/窗口对齐"))
        expected_stage = {"pictures": [call["item_id"] for call in calls if call["kind"] == "picture"], "videos": [call["item_id"] for call in calls if call["kind"] == "video"]}
        if detection["stage1"] != expected_stage:
            errors.append(issue("/reference_detection/stage1", "stage1_mapping", "Stage① 与物理计划的 Picture/Video 顺序不一致；重新检测"))
        context = alignment_context(state, project, inventory)
        if state["alignment"] is not None and state["alignment"] != context:
            errors.append(issue("/alignment", "alignment_stale", "素材/顺序/参与/接口/原声/尺寸/窗口已改变；点击检测并对齐素材"))
        if all(entry.get("source_kind") == "ZVH3ReferenceOutlet" for plural in ("pictures", "videos", "audios") for entry in detection[plural]):
            expected = planned_detection({"call_references": calls}, conditioning_count=detection["conditioning_count"])
            if compare_detection(detection, expected)["match"] is False:
                errors.append(issue("/reference_detection", "detection_missing", "检测快照与当前机械绑定不同；点击检测并对齐素材"))
    return {"ready": not errors, "effective_mode": inferred, "errors": errors, "warnings": warnings,
            "counts": counts, "mixed_sources": mixed, "reference_totals": totals,
            "local_output_frames": output_frames, "local_extension": extension,
            "local_output": {"requested_frames": frames, "requested_seconds": end - start if valid_window else None,
                             "model_length": output_frames, "predicted_final_frames": output_frames, "actual_final_frames": None},
            "model_visible_references": [
                {"item_id": call["item_id"], "call_label": call["call_label"],
                 "requested_seconds": by_id[call["item_id"]]["source_out_seconds"] - by_id[call["item_id"]]["source_in_seconds"],
                 "export_frames": int(math.floor((by_id[call["item_id"]]["source_out_seconds"] - by_id[call["item_id"]]["source_in_seconds"]) * 24 + .5)),
                 "model_length_verified": False, "assumed_model_length": output_frames,
                 "model_frames": max(0, (min(int(math.floor((by_id[call["item_id"]]["source_out_seconds"] - by_id[call["item_id"]]["source_in_seconds"]) * 24 + .5)), output_frames) - 5) // 17 * 17 + 5)}
                for call in calls if call["kind"] == "video" and call["resolved"] and output_frames is not None
            ]}


def annotate_project_errors(result, errors):
    """Caller supplies fresh registry errors, never client validation fields."""
    for error in errors:
        if error not in result["validation"]["errors"]:
            result["validation"]["errors"].append(copy.deepcopy(error))
    result["validation"]["ready"] = not result["validation"]["errors"]
    if errors:
        result["human_report"] += "\n素材核验失败：" + "；".join(error["message"] for error in errors)


def material_route(row):
    return {
        "first_frame": "first_frame", "last_frame": "last_frame",
        "video_soundtrack": "ref_video_audios", "drive_audio": "drive_audio",
    }.get(row["origin"], {"picture": "ref_images", "video": "ref_videos", "audio": "ref_audios"}[row["kind"]])


def build_user_prompt(state, duration, call_references):
    """Deterministic Chinese layout; no paraphrase, inferred intent or defaults."""
    sections = [f"生成时长：{duration:g} 秒。"]
    sections.extend(f"{FIELD_LABELS[field]}：\n{state[field]}" for field in TEXT_FIELDS if state[field].strip())
    if state["director_focus"] != "balanced":
        sections.append("用户选择的侧重：" + {"dialogue": "对白", "action": "动作"}[state["director_focus"]])
    material_lines = []
    for row in call_references:
        line = f"- {row['call_label']}（{ROUTE_LABELS[material_route(row)]}）"
        if row["roles"]:
            line += "；用途标签：" + "、".join(ROLE_LABELS.get(role, role) for role in row["roles"])
        if row["purpose"].strip():
            line += "\n  用户填写的用途：\n" + row["purpose"]
        material_lines.append(line)
    if material_lines:
        sections.append("参与素材与用途：\n" + "\n".join(material_lines))
    return "\n\n".join(sections)


def build_material_context(project, validation, call_references):
    """Factual routing and separate source/desk clocks, not shot instructions."""
    window = project["processing_window"]
    materials = []
    for row in call_references:
        material = copy.deepcopy(row)
        material["route"] = material_route(row)
        material["role_labels"] = [ROLE_LABELS.get(role, role) for role in row["roles"]]
        materials.append(material)
    return {
        "schema_version": MATERIAL_CONTEXT_VERSION,
        "mode": validation["effective_mode"],
        "duration_seconds": float(window["end_seconds"] - window["start_seconds"]),
        "target_fps": window["fps"],
        "target_frames": window["frame_count"],
        "materials": materials,
    }


def compile_interview(raw_state, project, *, confirm_references=False):
    state = normalize_interview(raw_state)
    inventory = media_inventory(project)
    from .presets import resolve_pending_slots
    pending_notices = resolve_pending_slots(state, inventory)
    call_references = _call_references(state, inventory)
    confirmed = confirm_references or state["reference_detection"] is not None and state["alignment"] == alignment_context(state, project, inventory)
    reference_issues = sync_references(state, call_references, inventory, TEXT_FIELDS, confirmed)
    call_references = _call_references(state, inventory)
    validation = validate_interview(state, project, inventory, call_references)
    validation["warnings"].extend(issue("/preset_pending", "pending_slot", message) for message in pending_notices)
    sent_purposes = {"purpose:" + row["purpose_item_id"] for row in call_references if row["resolved"]}
    for key, message in reference_issues:
        target = "errors" if key in TEXT_FIELDS or key in sent_purposes else "warnings"
        validation[target].append(issue("/" + key, "unresolved_reference" if target == "errors" else "unused_purpose", message))
    validation["ready"] = not validation["errors"]
    if len(json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_JSON_BYTES:
        validation["errors"].append(issue("/reference_texts", "json_size", "引用渲染后的采访状态超过256 KiB，请减少文本/槽位")); validation["ready"] = False
    duration = float(project["processing_window"]["end_seconds"] - project["processing_window"]["start_seconds"])
    user_prompt = build_user_prompt(state, duration, call_references)
    material_context = build_material_context(project, validation, call_references)
    lines = [
        f"H3 基础采访：{'就绪' if validation['ready'] else '未就绪'}",
        f"模式：{validation['effective_mode']}｜导演侧重：{state['director_focus']}｜目标：{duration:.3f} 秒 / {project['processing_window']['frame_count']} 帧",
    ]
    active = _active(state, inventory)
    if call_references:
        lines.append("本次调用标签：")
        lines.extend(f"- 素材台 {row['display_label']} → {row['call_label']}" for row in call_references)
    visual = [row["call_label"] for row in call_references if row["kind"] in ("picture", "video")]
    audio = [row["call_label"] for row in call_references if row["kind"] == "audio"]
    if visual:
        lines.append("固定 H3 素材对齐出口将按本次编号输出视觉参考；Stage①/H3 模板只需预接一次：" + "、".join(visual))
    if audio:
        lines.append("固定 H3 素材对齐出口将区分视频原声、驱动音频和独立参考音频；H3 模板只需预接一次：" + "、".join(audio))
    if active and not visual and not audio:
        lines.append("请点击“检测并对齐素材”生成本次固定 H3 素材出口计划。")
    elif not active and not call_references:
        lines.append("本次为 T2VA，不需要素材出口。")
    if validation["errors"]:
        lines.extend("错误：" + row["message"] for row in validation["errors"])
    if validation["warnings"]:
        lines.extend("提示：" + row["message"] for row in validation["warnings"])
    lines.append("H3 参考选段使用素材台源入/出点，允许目标 GEN 窗口外上下文；不自动投喂完整原文件。")
    lines.extend(model_visibility_lines(validation))
    return {
        "state": state,
        "inventory": inventory,
        "call_references": call_references,
        "validation": validation,
        "alignment_context": alignment_context(state, project, inventory),
        "rules": copy.deepcopy(RULES),
        "user_prompt": user_prompt,
        "material_context_json": dumps(material_context, indent=2),
        "duration_seconds": duration,
        "human_report": "\n".join(lines),
    }


def model_visibility_lines(validation):
    return [
        f"{row['call_label']} 请求参考 {row['requested_seconds']:.3f} 秒 / 出口 {row['export_frames']} 帧 → "
        + ("按已核实 length 的模型可见 " if row["model_length_verified"] else f"假设下游 length={row['assumed_model_length']} 的预测模型可见（实际 length 未核实） ")
        + f"{row['model_frames']} 帧（先截到 model length，再向下 17n+5 对齐；未做 GPU 成片验证）。"
        for row in validation["model_visible_references"]
    ]


def annotate_conditioning(result, project, evidence):
    validation = result["validation"]
    validation["conditioning"] = copy.deepcopy(evidence)
    validation["errors"].extend(copy.deepcopy(evidence["errors"]))
    validation["warnings"].extend(copy.deepcopy(evidence["warnings"]))
    validation["ready"] = not validation["errors"]
    for row in validation["model_visible_references"]:
        row["model_length_verified"] = evidence["length_verified"]
        if evidence["length_verified"]:
            row["assumed_model_length"] = evidence["model_length"]
            row["model_frames"] = max(0, (min(row["export_frames"], evidence["model_length"]) - 5) // 17 * 17 + 5)
    if evidence["length_verified"]:
        validation["local_output"]["model_length"] = evidence["model_length"]
        validation["local_output"]["predicted_final_frames"] = evidence["model_length"]
    result["material_context_json"] = dumps(build_material_context(project, validation, result["call_references"]), indent=2)
    lines = [line for line in result["human_report"].splitlines() if not (line.startswith("<Video ") and "请求参考" in line)]
    lines[0] = f"H3 基础采访：{'就绪' if validation['ready'] else '未就绪'}"
    lines.extend("错误：" + row["message"] for row in evidence["errors"])
    lines.extend("提示：" + row["message"] for row in evidence["warnings"])
    lines.extend(model_visibility_lines(validation))
    result["human_report"] = "\n".join(lines)
    return result


def dumps(value, *, indent=None):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=None if indent else (",", ":"), indent=indent)


__all__ = [
    "AUDIO_ROLES",
    "FOCUSES",
    "InterviewError",
    "MATERIAL_CONTEXT_VERSION",
    "MODES",
    "PICTURE_ROLES",
    "ROLE_LABELS",
    "ROLES_BY_KIND",
    "SCHEMA_VERSION",
    "TEXT_FIELDS",
    "VIDEO_ROLES",
    "build_user_prompt",
    "build_material_context",
    "compile_interview",
    "dumps",
    "empty_interview",
    "infer_mode",
    "media_inventory",
    "normalize_interview",
    "parse_interview",
    "validate_interview",
]
