"""Detect the effective H3 reference order from a submitted ComfyUI prompt.

The detector deliberately consumes the server-side API prompt rather than the
saved LiteGraph workflow.  Frontend-only virtual nodes (including ZFI) have
already been resolved by the time a normal ComfyUI prompt reaches this code.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import copy
import re
from .routing import model_frame_count

_GRID_EXPRESSION = "max(5,round(a))+(5-(max(5,round(a))%17))%17"


def validate_conditioning_settings(prompt, interview_unique_id, *, effective_mode, has_drive_audio=False, project_frame_count=None):
    """Audit literals and one known same-project frame-count chain; never eval code."""
    nodes = {str(key): node for key, node in prompt.items() if isinstance(node, Mapping)} if isinstance(prompt, Mapping) else {}
    interview_id = str(interview_unique_id)
    ids = sorted((key for key, node in nodes.items() if node.get("class_type") == T8_CLASS and _has_ancestor(nodes, key, interview_id)), key=_node_sort_key)
    result = {"errors": [], "warnings": [], "length_verified": False, "model_length": None, "lengths": []}
    errors = result["errors"]
    same_project = _as_link(_inputs(nodes, interview_id).get("media_project"), nodes)
    audio_modes = set()
    for key in ids:
        inputs = _inputs(nodes, key)
        raw_task = inputs.get("task_type", "auto")
        match = re.match(r"^[A-Za-z0-9]+", raw_task.strip()) if isinstance(raw_task, str) else None
        task = match.group().lower() if match else None
        if task not in {"auto", effective_mode.lower()}:
            _add_error(errors, "conditioning_task", f"实际素材模式为 {effective_mode}，但 task_type={raw_task!r}；请设为 auto 或 {effective_mode}，并确认模型家族。", node_id=key)
        audio = inputs.get("audio_mode", "native")
        if not isinstance(audio, str) or audio not in {"native", "reference_only", "lock_source", "remix_source"} or (audio != "native" and not has_drive_audio):
            _add_error(errors, "conditioning_audio_mode", f"audio_mode={audio!r} 不适用当前 drive_audio；无驱动音频请设 native。", node_id=key)
        if isinstance(audio, str):
            audio_modes.add(audio)
        raw = inputs.get("length")
        length, proof = None, "unverified_dynamic_or_missing"
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw == int(raw) and 5 <= raw <= 3600:
            length, proof = model_frame_count(int(raw)), "literal"
        link = _as_link(raw, nodes)
        if link is not None and project_frame_count is not None:
            math_id, slot = link
            math_inputs = _inputs(nodes, math_id)
            expression = math_inputs.get("expression")
            normalized = re.sub(r"\s+", "", expression) if isinstance(expression, str) else None
            count_link = _as_link(math_inputs.get("values.a"), nodes)
            if nodes[math_id].get("class_type") == "ComfyMathExpression" and slot == 1 and normalized == _GRID_EXPRESSION and count_link is not None:
                outlet_id, count_slot = count_link
                if nodes[outlet_id].get("class_type") == "ZVProcessingWindowOutlet" and count_slot == 4 and same_project is not None and _as_link(_inputs(nodes, outlet_id).get("media_project"), nodes) == same_project:
                    length, proof = model_frame_count(project_frame_count), "known_grid_expression_same_project"
        result["lengths"].append({"node_id": key, "length": length, "proof": proof})
        if length is not None and project_frame_count is not None and length != model_frame_count(project_frame_count):
            _add_error(errors, "conditioning_length_target", f"节点 {key} 实际 length={length}，与 GEN {project_frame_count} 帧向上对齐后的 {model_frame_count(project_frame_count)} 不一致。", node_id=key)
    known = {row["length"] for row in result["lengths"] if row["length"] is not None}
    if len(known) > 1:
        _add_error(errors, "conditioning_length_mismatch", "LOW/HIGH 实际 length 不一致。")
    if len(audio_modes) > 1:
        _add_error(errors, "conditioning_audio_mismatch", "LOW/HIGH 的 audio_mode 不一致；请统一音频策略。")
    result["length_verified"] = bool(ids) and len(known) == 1 and all(row["length"] is not None for row in result["lengths"])
    if result["length_verified"]:
        result["model_length"] = next(iter(known))
    else:
        result["warnings"].append({"code": "conditioning_length_unverified", "message": "实际下游 length 未核实；参考可见帧数仅按 GEN 向上对齐的 length 假设预测。"})
    return result


T8_CLASS = "MiniMaxH3AudioConditioningT8"
STAGE_LLM_CLASS = "ZFPromptDirectorLocalLLM"
INTERVIEW_CLASS = "ZVH3InterviewForm"
HUB_CLASS = "ZVH3ReferenceOutlet"

_REF_IMAGE_RE = re.compile(r"^ref_images\.ref_image_(\d+)$")
_REF_VIDEO_RE = re.compile(r"^ref_videos\.ref_video_(\d+)$")
_REF_VIDEO_AUDIO_RE = re.compile(r"^ref_video_audios\.ref_video_audio_(\d+)$")
_REF_AUDIO_RE = re.compile(r"^ref_audios\.ref_audio_(\d+)$")

_OUTLET_BINDINGS = {
    "ZVPictureOutlet": "item_id",
    "ZVVideoOutlet": "clip_id",
    "ZVAudioOutlet": "clip_id",
}
_EXPECTED_SOURCES = {
    "picture": {("ZVPictureOutlet", 0)},
    "video": {("ZVVideoOutlet", 0)},
    "audio": {("ZVAudioOutlet", 0), ("ZVVideoOutlet", 1)},
}

# ZVH3ReferenceOutlet is an append-only socket contract.  The T8 autogrow
# groups use zero-based input suffixes while the hub uses one-based labels.
_HUB_CONDITIONING_INPUTS = (
    ("first_frame", 0),
    ("last_frame", 1),
    *((f"ref_images.ref_image_{index}", 2 + index) for index in range(9)),
    *((f"ref_videos.ref_video_{index}", 11 + index) for index in range(3)),
    *((f"ref_video_audios.ref_video_audio_{index}", 14 + index) for index in range(3)),
    ("drive_audio", 17),
    ("final_audio", 18),
    *((f"ref_audios.ref_audio_{index}", 19 + index) for index in range(3)),
)
_HUB_STAGE1_INPUTS = (
    *((f"image{index + 1}", index) for index in range(11)),
    ("video_frames", 11),
    ("video_frames2", 12),
    ("video_frames3", 13),
)


def _node_id(value) -> str:
    return str(value)


def _node_sort_key(value: str):
    return (0, int(value)) if value.isdigit() else (1, value)


def _as_link(value, nodes):
    """Return a normalized ComfyUI link or ``None`` for a literal value."""
    if not isinstance(value, list) or len(value) != 2:
        return None
    if not isinstance(value[0], (str, int)) or isinstance(value[0], bool):
        return None
    if not isinstance(value[1], (int, float)) or isinstance(value[1], bool):
        return None
    source_id = _node_id(value[0])
    if source_id not in nodes:
        return None
    try:
        slot = int(value[1])
    except (OverflowError, TypeError, ValueError):
        return None
    if slot < 0 or float(value[1]) != slot:
        return None
    return source_id, slot


def _inputs(nodes, node_id):
    node = nodes.get(node_id, {})
    value = node.get("inputs", {}) if isinstance(node, Mapping) else {}
    return value if isinstance(value, Mapping) else {}


def _upstream(nodes, node_id):
    for value in _inputs(nodes, node_id).values():
        link = _as_link(value, nodes)
        if link is not None:
            yield link


def _has_ancestor(nodes, node_id, ancestor_id):
    pending = [node_id]
    visited = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        for source_id, _slot in _upstream(nodes, current):
            if source_id == ancestor_id:
                return True
            pending.append(source_id)
    return False


def _distance_to_ancestor_output(nodes, node_id, ancestor_id, output_slot):
    """Shortest upstream edge distance to one particular ancestor output."""
    pending = deque([(node_id, 0)])
    visited = {node_id}
    while pending:
        current, distance = pending.popleft()
        for source_id, slot in _upstream(nodes, current):
            if source_id == ancestor_id and slot == output_slot:
                return distance + 1
            if source_id not in visited:
                visited.add(source_id)
                pending.append((source_id, distance + 1))
    return None


def _add_error(errors, code, message, **context):
    row = {"code": code, "message": message}
    row.update({key: value for key, value in context.items() if value is not None})
    if row not in errors:
        errors.append(row)


def _source_for_input(nodes, target_id, input_name, expected_kind, errors):
    value = _inputs(nodes, target_id).get(input_name)
    if value is None:
        return None
    link = _as_link(value, nodes)
    if link is None:
        _add_error(
            errors,
            "invalid_media_link",
            f"{input_name} 不是可解析的 ComfyUI 节点连线。",
            node_id=target_id,
            input_name=input_name,
        )
        return None

    source_id, output_slot = link
    source_node = nodes[source_id]
    outlet_type = str(source_node.get("class_type", ""))
    source = {
        "binding_id": None,
        "outlet_type": outlet_type,
        "output_slot": output_slot,
    }

    binding_key = _OUTLET_BINDINGS.get(outlet_type)
    if binding_key is None:
        _add_error(
            errors,
            "unsupported_media_source",
            f"{input_name} 未直连受支持的 ZV 素材出口。",
            node_id=target_id,
            input_name=input_name,
            source_node_id=source_id,
            source_type=outlet_type or "unknown",
        )
    else:
        binding = _inputs(nodes, source_id).get(binding_key)
        if isinstance(binding, str) and binding:
            source["binding_id"] = binding
        else:
            _add_error(
                errors,
                "missing_stable_binding",
                f"{outlet_type} 没有可静态确认的稳定素材 ID。",
                node_id=target_id,
                input_name=input_name,
                source_node_id=source_id,
            )

    if (outlet_type, output_slot) not in _EXPECTED_SOURCES[expected_kind]:
        _add_error(
            errors,
            "wrong_outlet_output",
            f"{input_name} 的素材出口类型或输出槽与 {expected_kind} 不匹配。",
            node_id=target_id,
            input_name=input_name,
            source_node_id=source_id,
            source_type=outlet_type or "unknown",
            output_slot=output_slot,
        )
    return source


def _entry(ordinal, kind, role, source, **extra):
    row = {
        "ordinal": ordinal,
        "kind": kind,
        "role": role,
        **(source or {"binding_id": None, "outlet_type": "", "output_slot": None}),
    }
    row.update(extra)
    return row


def _numbered_inputs(inputs, pattern):
    rows = []
    for name, value in inputs.items():
        match = pattern.fullmatch(str(name))
        if match and value is not None:
            rows.append((int(match.group(1)), str(name)))
    return sorted(rows)


def _literal_bool(inputs, name, default, node_id, errors):
    value = inputs.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    _add_error(
        errors,
        "dynamic_reference_flag",
        f"{name} 不是静态布尔值；无法在执行前精确确认音频编号。",
        node_id=node_id,
        input_name=name,
    )
    return default


def _conditioning_map(nodes, node_id, errors):
    inputs = _inputs(nodes, node_id)
    pictures = []
    videos = []
    audios = []

    for input_name, role in (("first_frame", "first_frame"), ("last_frame", "last_frame")):
        if inputs.get(input_name) is not None:
            source = _source_for_input(nodes, node_id, input_name, "picture", errors)
            pictures.append(_entry(len(pictures) + 1, "picture", role, source))

    for _socket_ordinal, input_name in _numbered_inputs(inputs, _REF_IMAGE_RE):
        source = _source_for_input(nodes, node_id, input_name, "picture", errors)
        pictures.append(_entry(len(pictures) + 1, "picture", "reference_image", source))

    video_inputs = _numbered_inputs(inputs, _REF_VIDEO_RE)
    soundtrack_inputs = dict(_numbered_inputs(inputs, _REF_VIDEO_AUDIO_RE))
    video_ordinals = {socket_ordinal for socket_ordinal, _name in video_inputs}
    for socket_ordinal in sorted(set(soundtrack_inputs) - video_ordinals):
        _add_error(
            errors,
            "orphan_video_soundtrack",
            f"ref_video_audio_{socket_ordinal} 没有同编号 ref_video_{socket_ordinal}。",
            node_id=node_id,
            input_name=soundtrack_inputs[socket_ordinal],
        )

    for socket_ordinal, input_name in video_inputs:
        source = _source_for_input(nodes, node_id, input_name, "video", errors)
        soundtrack = None
        soundtrack_name = soundtrack_inputs.get(socket_ordinal)
        if soundtrack_name is not None:
            soundtrack = _source_for_input(nodes, node_id, soundtrack_name, "audio", errors)
            if not (
                source
                and soundtrack
                and source.get("outlet_type") == "ZVVideoOutlet"
                and soundtrack.get("outlet_type") == "ZVVideoOutlet"
                and source.get("output_slot") == 0
                and soundtrack.get("output_slot") == 1
                and source.get("binding_id") is not None
                and source.get("binding_id") == soundtrack.get("binding_id")
            ):
                _add_error(
                    errors,
                    "video_soundtrack_pair_mismatch",
                    f"ref_video_audio_{socket_ordinal} 不是同一视频出口的 original_audio。",
                    node_id=node_id,
                    input_name=soundtrack_name,
                )
        videos.append(
            _entry(
                len(videos) + 1,
                "video",
                "reference_video",
                source,
                soundtrack=copy.deepcopy(soundtrack),
            )
        )
        if soundtrack is not None:
            audios.append(_entry(len(audios) + 1, "audio", "video_soundtrack", soundtrack))

    add_drive_reference = _literal_bool(
        inputs, "add_source_as_reference", True, node_id, errors
    )
    if inputs.get("drive_audio") is not None and add_drive_reference:
        source = _source_for_input(nodes, node_id, "drive_audio", "audio", errors)
        audios.append(_entry(len(audios) + 1, "audio", "drive_audio", source))

    for _socket_ordinal, input_name in _numbered_inputs(inputs, _REF_AUDIO_RE):
        source = _source_for_input(nodes, node_id, input_name, "audio", errors)
        audios.append(_entry(len(audios) + 1, "audio", "reference_audio", source))

    return {"pictures": pictures, "videos": videos, "audios": audios}


def _hub_ids(nodes, interview_id):
    result = []
    for node_id, node in nodes.items():
        if node.get("class_type") != HUB_CLASS:
            continue
        if _as_link(_inputs(nodes, node_id).get("reference_plan"), nodes) == (interview_id, 8):
            result.append(node_id)
    return sorted(result, key=_node_sort_key)


def _require_hub_link(nodes, target_id, input_name, hub_id, output_slot, errors):
    actual = _as_link(_inputs(nodes, target_id).get(input_name), nodes)
    if actual == (hub_id, output_slot):
        return
    source = "未连接" if actual is None else f"节点 {actual[0]} 输出 {actual[1]}"
    _add_error(
        errors,
        "fixed_hub_wiring",
        f"{input_name} 应连接固定 H3 素材出口 {output_slot}，当前为{source}。",
        node_id=target_id,
        input_name=input_name,
        hub_node_id=hub_id,
        expected_output_slot=output_slot,
    )


def _fixed_audio_settings(nodes, node_id, errors):
    inputs = _inputs(nodes, node_id)
    add_drive = _literal_bool(
        inputs, "add_source_as_reference", True, node_id, errors
    )
    if not add_drive:
        _add_error(
            errors,
            "fixed_hub_audio_numbering",
            "固定出口要求 add_source_as_reference=true，才能让采访表的 drive_audio 占用同一 <Audio N>。",
            node_id=node_id,
            input_name="add_source_as_reference",
        )
    primary = inputs.get("prompt_primary_audio_ordinal", 1)
    if isinstance(primary, bool):
        primary_value = None
    else:
        try:
            primary_value = int(primary)
            if isinstance(primary, float) and not primary.is_integer():
                primary_value = None
            if isinstance(primary, str) and str(primary_value) != primary.strip():
                primary_value = None
        except (TypeError, ValueError):
            primary_value = None
    if primary_value != 0:
        _add_error(
            errors,
            "fixed_hub_audio_numbering",
            "固定出口要求 prompt_primary_audio_ordinal=0，避免 T8 重新排列采访表已经确定的 <Audio N>。",
            node_id=node_id,
            input_name="prompt_primary_audio_ordinal",
        )


def validate_reference_hub_wiring(prompt, interview_unique_id, *, effective_mode=None, has_drive_audio=False, project_frame_count=None):
    """Validate the physical fixed-hub template without needing tensor IDs.

    The plan supplies stable material IDs at runtime; this audit separately
    proves that every semantic hub output reaches the matching T8 and Stage①
    socket. Missing target branches are tolerated for partial execution, but
    every present branch must be complete.
    """
    result = {
        "hub_count": 0,
        "conditioning_count": 0,
        "stage1_count": 0,
        "errors": [],
    }
    errors = result["errors"]
    if not isinstance(prompt, Mapping):
        _add_error(errors, "invalid_prompt", "PROMPT 必须是 ComfyUI 节点字典。")
        return result
    nodes = {
        _node_id(node_id): node
        for node_id, node in prompt.items()
        if isinstance(node, Mapping)
    }
    interview_id = _node_id(interview_unique_id)
    hub_ids = _hub_ids(nodes, interview_id)
    result["hub_count"] = len(hub_ids)
    if len(hub_ids) != 1:
        _add_error(
            errors,
            "fixed_hub_count",
            f"本采访表必须连接且只连接一个固定 H3 素材出口；当前 {len(hub_ids)} 个。",
            node_id=interview_id,
        )
        return result
    hub_id = hub_ids[0]

    conditioning_ids = sorted(
        (
            node_id for node_id, node in nodes.items()
            if node.get("class_type") == T8_CLASS
            and _has_ancestor(nodes, node_id, interview_id)
        ),
        key=_node_sort_key,
    )
    result["conditioning_count"] = len(conditioning_ids)
    for node_id in conditioning_ids:
        for input_name, output_slot in _HUB_CONDITIONING_INPUTS:
            _require_hub_link(nodes, node_id, input_name, hub_id, output_slot, errors)
        _fixed_audio_settings(nodes, node_id, errors)
    if effective_mode is not None:
        result["conditioning"] = validate_conditioning_settings(prompt, interview_id, effective_mode=effective_mode, has_drive_audio=has_drive_audio, project_frame_count=project_frame_count)
        errors.extend(result["conditioning"]["errors"])

    stage_distances = []
    for node_id, node in nodes.items():
        if node.get("class_type") != STAGE_LLM_CLASS:
            continue
        distance = _distance_to_ancestor_output(nodes, node_id, interview_id, 1)
        if distance is not None:
            stage_distances.append((distance, node_id))
    nearest = min((distance for distance, _node_id_value in stage_distances), default=None)
    stage_ids = sorted(
        (node_id for distance, node_id in stage_distances if distance == nearest),
        key=_node_sort_key,
    ) if nearest is not None else []
    result["stage1_count"] = len(stage_ids)
    for node_id in stage_ids:
        for input_name, output_slot in _HUB_STAGE1_INPUTS:
            _require_hub_link(nodes, node_id, input_name, hub_id, output_slot, errors)

    # In the full H3 branch Stage① is part of the promised three-stage loop. A
    # Stage①-only partial execution has no conditioning nodes and stays valid.
    if conditioning_ids and not stage_ids:
        _add_error(
            errors,
            "fixed_hub_stage1_missing",
            "固定 H3 素材出口已接 Conditioning，但没有找到使用本采访表的 Stage① 多模态节点。",
            node_id=interview_id,
        )
    return result


def _stage1_map(nodes, node_id, errors):
    inputs = _inputs(nodes, node_id)
    pictures = []
    videos = []
    # Stage① receives the complete H3 visual sequence: the two keyframes are
    # separate from the nine generic reference-image sockets.
    for index in range(1, 12):
        input_name = f"image{index}"
        if inputs.get(input_name) is not None:
            source = _source_for_input(nodes, node_id, input_name, "picture", errors)
            pictures.append(_entry(len(pictures) + 1, "picture", "stage1_picture", source))
    for input_name in ("video_frames", "video_frames2", "video_frames3"):
        if inputs.get(input_name) is not None:
            source = _source_for_input(nodes, node_id, input_name, "video", errors)
            videos.append(_entry(len(videos) + 1, "video", "stage1_video", source))
    return {"pictures": pictures, "videos": videos}


def _source_sequence(entries):
    return [
        {
            "binding_id": row.get("binding_id"),
            "outlet_type": row.get("outlet_type"),
            "output_slot": row.get("output_slot"),
        }
        for row in entries
    ]


def detect_reference_wiring(prompt, interview_unique_id):
    """Return the effective dense H3/Stage1 media order for one interview.

    Only T8 conditioning and local multimodal nodes whose upstream ancestry
    contains ``interview_unique_id`` participate in the result.
    """
    result = {
        "pictures": [],
        "videos": [],
        "audios": [],
        "stage1": {"node_count": 0, "pictures": [], "videos": []},
        "conditioning_count": 0,
        "errors": [],
    }
    errors = result["errors"]
    if not isinstance(prompt, Mapping):
        _add_error(errors, "invalid_prompt", "PROMPT 必须是 ComfyUI 节点字典。")
        return result

    nodes = {
        _node_id(node_id): node
        for node_id, node in prompt.items()
        if isinstance(node, Mapping)
    }
    interview_id = _node_id(interview_unique_id)
    interview = nodes.get(interview_id)
    if interview is None:
        _add_error(
            errors,
            "interview_node_missing",
            "PROMPT 中找不到指定采访节点。",
            node_id=interview_id,
        )
        return result
    if interview.get("class_type") != INTERVIEW_CLASS:
        _add_error(
            errors,
            "interview_node_type",
            "unique_id 指向的不是 ZVH3InterviewForm。",
            node_id=interview_id,
            source_type=str(interview.get("class_type", "")),
        )

    conditioning_ids = sorted(
        (
            node_id
            for node_id, node in nodes.items()
            if node.get("class_type") == T8_CLASS
            and _has_ancestor(nodes, node_id, interview_id)
        ),
        key=_node_sort_key,
    )
    result["conditioning_count"] = len(conditioning_ids)
    conditioning_maps = []
    for node_id in conditioning_ids:
        conditioning_maps.append((node_id, _conditioning_map(nodes, node_id, errors)))

    if conditioning_maps:
        baseline_id, baseline = conditioning_maps[0]
        result["pictures"] = baseline["pictures"]
        result["videos"] = baseline["videos"]
        result["audios"] = baseline["audios"]
        for node_id, current in conditioning_maps[1:]:
            if current != baseline:
                _add_error(
                    errors,
                    "conditioning_mapping_mismatch",
                    "同一采访链路上的 LOW/HIGH T8 参考映射不一致。",
                    node_id=node_id,
                    baseline_node_id=baseline_id,
                )
    else:
        _add_error(
            errors,
            "conditioning_missing",
            "没有找到 ancestry 包含该采访节点的 MiniMax H3 T8 conditioning。",
            node_id=interview_id,
        )

    stage_distances = []
    for node_id, node in nodes.items():
        if node.get("class_type") != STAGE_LLM_CLASS:
            continue
        distance = _distance_to_ancestor_output(nodes, node_id, interview_id, 1)
        if distance is not None:
            stage_distances.append((distance, node_id))
    if stage_distances:
        nearest = min(distance for distance, _node_id_value in stage_distances)
        stage_ids = sorted(
            (node_id for distance, node_id in stage_distances if distance == nearest),
            key=_node_sort_key,
        )
    else:
        stage_ids = []

    result["stage1"]["node_count"] = len(stage_ids)
    stage_maps = []
    for node_id in stage_ids:
        stage_maps.append((node_id, _stage1_map(nodes, node_id, errors)))
    if stage_maps:
        baseline_stage_id, baseline_stage = stage_maps[0]
        result["stage1"]["pictures"] = baseline_stage["pictures"]
        result["stage1"]["videos"] = baseline_stage["videos"]
        for node_id, current in stage_maps[1:]:
            if current != baseline_stage:
                _add_error(
                    errors,
                    "stage1_nodes_mismatch",
                    "多个候选 Stage1 的视觉素材映射不一致。",
                    node_id=node_id,
                    baseline_node_id=baseline_stage_id,
                )

    if conditioning_maps:
        h3_picture_sources = _source_sequence(result["pictures"])
        h3_video_sources = _source_sequence(result["videos"])
        stage_picture_sources = _source_sequence(result["stage1"]["pictures"])
        stage_video_sources = _source_sequence(result["stage1"]["videos"])
        if (h3_picture_sources or h3_video_sources) and not stage_maps:
            _add_error(
                errors,
                "stage1_missing",
                "H3 已连接视觉参考，但没有找到对应的 Stage1 本地多模态节点。",
                node_id=interview_id,
            )
        else:
            if stage_picture_sources != h3_picture_sources:
                _add_error(
                    errors,
                    "stage1_picture_mapping_mismatch",
                    "Stage1 与 H3 的 Picture N 稳定素材顺序不一致。",
                    node_id=interview_id,
                )
            if stage_video_sources != h3_video_sources:
                _add_error(
                    errors,
                    "stage1_video_mapping_mismatch",
                    "Stage1 与 H3 的 Video N 稳定素材顺序不一致。",
                    node_id=interview_id,
                )
    return result


def _port_name(outlet_type, output_slot):
    return {
        ("ZVPictureOutlet", 0): "image",
        ("ZVVideoOutlet", 0): "frames",
        ("ZVVideoOutlet", 1): "original_audio",
        ("ZVAudioOutlet", 0): "audio",
    }.get((outlet_type, output_slot), str(output_slot))


def _source_kind(outlet_type):
    return {
        "ZVPictureOutlet": "picture",
        "ZVVideoOutlet": "video",
        "ZVAudioOutlet": "audio",
    }.get(outlet_type, str(outlet_type or ""))


def _snapshot_entry(row, plural):
    if "item_id" in row:
        # Already in the compact frontend/interview representation.
        result = {
            "item_id": row.get("item_id"),
            "source_kind": row.get("source_kind"),
            "source_port": row.get("source_port"),
        }
        default_origin = "standalone" if plural == "audios" else "reference"
        result["origin"] = row.get("origin", default_origin)
        return result
    role = row.get("role")
    origins = {
        "first_frame": "first_frame",
        "last_frame": "last_frame",
        "reference_image": "reference",
        "reference_video": "reference",
        "video_soundtrack": "video_soundtrack",
        "drive_audio": "drive_audio",
        "reference_audio": "standalone",
    }
    outlet_type = row.get("outlet_type")
    output_slot = row.get("output_slot")
    return {
        "item_id": row.get("binding_id"),
        "source_kind": _source_kind(outlet_type),
        "source_port": _port_name(outlet_type, output_slot),
        "origin": origins.get(role, "standalone" if plural == "audios" else "reference"),
    }


def detection_snapshot(value):
    """Convert rich backend detection or a saved compact value to one schema."""
    if not isinstance(value, Mapping):
        return value
    result = {"version": 1}
    for plural in ("pictures", "videos", "audios"):
        rows = value.get(plural, [])
        result[plural] = [
            _snapshot_entry(row, plural)
            for row in rows
            if isinstance(row, Mapping)
        ] if isinstance(rows, list) else rows
    stage = value.get("stage1", {})
    if isinstance(stage, Mapping):
        result["stage1"] = {}
        for plural in ("pictures", "videos"):
            rows = stage.get(plural, [])
            if isinstance(rows, list):
                result["stage1"][plural] = [
                    row.get("item_id", row.get("binding_id")) if isinstance(row, Mapping) else row
                    for row in rows
                ]
            else:
                result["stage1"][plural] = rows
    else:
        result["stage1"] = stage
    result["conditioning_count"] = value.get("conditioning_count", 0)
    return result


def compare_detection(saved, actual):
    """Compare a saved frontend snapshot with a fresh backend detection."""
    saved_view = detection_snapshot(saved)
    actual_view = detection_snapshot(actual)
    differences = []
    if not isinstance(saved_view, Mapping) or not isinstance(actual_view, Mapping):
        differences.append({"field": "detection", "saved": saved_view, "actual": actual_view})
    else:
        for field in ("pictures", "videos", "audios", "stage1", "conditioning_count"):
            if saved_view.get(field) != actual_view.get(field):
                differences.append(
                    {
                        "field": field,
                        "saved": saved_view.get(field),
                        "actual": actual_view.get(field),
                    }
                )
    actual_errors = copy.deepcopy(actual.get("errors", [])) if isinstance(actual, Mapping) else []
    return {
        "match": not differences and not actual_errors,
        "differences": differences,
        "errors": actual_errors,
    }


# Concise alias for callers that do not need to mention wiring explicitly.
detect_references = detect_reference_wiring


__all__ = [
    "compare_detection",
    "detect_reference_wiring",
    "detect_references",
    "detection_snapshot",
    "validate_reference_hub_wiring",
]
