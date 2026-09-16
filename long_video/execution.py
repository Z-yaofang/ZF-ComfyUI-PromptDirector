"""Pure contracts for finite long-video execution.

The sampler is deliberately absent from this module.  An execution context is a
small, JSON-compatible instruction for one loop iteration; the real H3 graph is
expected to live between the entry and result nodes.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence

from .interview import H3_FPS, execution_fingerprint, parse_segment_interview, valid_h3_guide_frames


EXECUTION_PLAN_VERSION = 1
RUN_MANIFEST_VERSION = 1
MAX_SEGMENTS = 4096
RUN_AUDIO_CONTRACT = {"version": 1, "sample_rate": 44100, "channels": 2}


class ExecutionPlanError(ValueError):
    """Raised when an execution plan, context, or run manifest is inconsistent."""


def _error(message):
    raise ExecutionPlanError(message)


def _require_int(value, name, minimum=None):
    if type(value) is not int or minimum is not None and value < minimum:
        suffix = "" if minimum is None else f"且不小于 {minimum}"
        _error(f"{name} 必须是整数{suffix}")
    return value


def _require_text(value, name, *, allow_empty=False):
    if not isinstance(value, str) or not allow_empty and not value:
        _error(f"{name} 必须是{'字符串' if allow_empty else '非空字符串'}")
    return value


def _as_mapping(value, name):
    if not isinstance(value, Mapping):
        _error(f"{name} 必须是对象")
    return value


def _as_rows(value, name):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _error(f"{name} 必须是数组")
    return value


def planned_contribution(segment_plan, segment_index):
    """Return the exact useful window for one generated segment.

    Segment and target ranges are half-open.  Model padding is intentionally not
    consulted: it is only an H3 generation constraint and never timeline truth.
    """

    plan = _as_mapping(segment_plan, "segment_plan")
    segments = _as_rows(plan.get("segments"), "segment_plan.segments")
    index = _require_int(segment_index, "segment_index", 0)
    if index >= len(segments):
        _error(f"segment_index {index} 超出分段范围")
    segment = _as_mapping(segments[index], f"segment_plan.segments[{index}]")
    start = _require_int(segment.get("start_frame"), f"segments[{index}].start_frame", 0)
    end = _require_int(segment.get("end_frame"), f"segments[{index}].end_frame", 1)
    frame_count = _require_int(segment.get("frame_count"), f"segments[{index}].frame_count", 1)
    overlap = _require_int(segment.get("overlap_frames"), f"segments[{index}].overlap_frames", 0)
    tail_padding = _require_int(segment.get("tail_padding_frames", 0), f"segments[{index}].tail_padding_frames", 0)
    seam = segment.get("seam")
    if seam not in ("first", "guide", "hard_cut"):
        _error(f"segments[{index}].seam 无效")
    if end - start != frame_count:
        _error(f"segments[{index}] 的 frame_count 与半开区间不一致")
    if overlap >= frame_count or tail_padding >= frame_count:
        _error(f"segments[{index}] 的重叠或尾部补帧覆盖了整段")
    if seam != "guide" and overlap:
        _error(f"segments[{index}] 只有 guide 接缝可以声明重叠帧")

    range_start = _require_int(plan.get("range_start_frame"), "segment_plan.range_start_frame", 0)
    target_count = _require_int(plan.get("target_frame_count"), "segment_plan.target_frame_count", 1)
    range_end = range_start + target_count
    local_start = overlap if seam == "guide" else 0
    global_start = max(start + local_start, range_start)
    global_end = min(end - tail_padding, range_end)
    local_start = global_start - start
    local_end = global_end - start
    if local_start < 0 or local_end > frame_count or local_end <= local_start:
        _error(f"segments[{index}] 没有可输出的有效帧")
    return {
        "local_start_frame": local_start,
        "local_end_frame": local_end,
        "frame_count": local_end - local_start,
        "global_start_frame": global_start,
        "global_end_frame": global_end,
        "output_start_frame": global_start - range_start,
        "output_end_frame": global_end - range_start,
    }


def planned_incoming_guide(segment_plan, segment_index):
    """Describe the previous result tail required by the current segment."""

    plan = _as_mapping(segment_plan, "segment_plan")
    segments = _as_rows(plan.get("segments"), "segment_plan.segments")
    index = _require_int(segment_index, "segment_index", 0)
    if index >= len(segments):
        _error(f"segment_index {index} 超出分段范围")
    segment = _as_mapping(segments[index], f"segment_plan.segments[{index}]")
    if segment.get("seam") != "guide":
        return None
    if index == 0:
        _error("第一段不能使用 guide 接缝")
    overlap = _require_int(segment.get("overlap_frames"), f"segments[{index}].overlap_frames", 1)
    start = _require_int(segment.get("start_frame"), f"segments[{index}].start_frame", 0)
    previous = _as_mapping(segments[index - 1], f"segment_plan.segments[{index - 1}]")
    previous_end = _require_int(previous.get("end_frame"), f"segments[{index - 1}].end_frame", 1)
    if start != previous_end - overlap:
        _error(f"segments[{index}] 的 guide 全局范围与上一段尾帧不一致")
    return {
        "frame_count": overlap,
        "global_start_frame": start,
        "global_end_frame": start + overlap,
        "frame_idx": 0,
        "source_segment_id": previous.get("segment_id"),
    }


def planned_next_guide(segment_plan, segment_index):
    """Describe the current result tail that must be persisted for the next segment."""

    plan = _as_mapping(segment_plan, "segment_plan")
    segments = _as_rows(plan.get("segments"), "segment_plan.segments")
    index = _require_int(segment_index, "segment_index", 0)
    if index + 1 >= len(segments):
        return None
    incoming = planned_incoming_guide(plan, index + 1)
    if incoming is None:
        return None
    segment = _as_mapping(segments[index], f"segment_plan.segments[{index}]")
    frame_count = _require_int(segment.get("frame_count"), f"segments[{index}].frame_count", 1)
    tail_padding = _require_int(segment.get("tail_padding_frames", 0), f"segments[{index}].tail_padding_frames", 0)
    overlap = incoming["frame_count"]
    local_end = frame_count
    local_start = local_end - overlap
    if local_start < 0 or local_end > frame_count - tail_padding:
        _error(f"segments[{index}] 的有效尾帧不足以生成下一段 guide")
    return {
        **incoming,
        "local_start_frame": local_start,
        "local_end_frame": local_end,
        "target_segment_id": _as_mapping(segments[index + 1], f"segment_plan.segments[{index + 1}]").get("segment_id"),
    }


def normalize_execution_plan(value):
    """Validate and copy a segmented-interview execution plan."""

    raw = _as_mapping(value, "execution_plan")
    if raw.get("schema_version") != EXECUTION_PLAN_VERSION:
        _error("需要 ZV 分段执行计划 v1")
    if raw.get("ready") is not True:
        _error("分段采访尚未就绪，不能执行")
    plan = _as_mapping(raw.get("segment_plan"), "execution_plan.segment_plan")
    if plan.get("schema_version") != 1:
        _error("需要 ZV 分段计划 v1")
    validation = _as_mapping(plan.get("validation"), "segment_plan.validation")
    if validation.get("ready") is not True or validation.get("errors"):
        _error("分段计划包含错误，不能执行")
    if plan.get("stale") is True:
        _error("分段计划使用了过期素材，请先刷新")
    revision = _require_text(plan.get("revision"), "segment_plan.revision")
    if raw.get("plan_revision") != revision:
        _error("分段采访与当前分段计划版本不一致")
    _require_text(plan.get("plan_id"), "segment_plan.plan_id")
    fingerprint = _require_text(raw.get("fingerprint"), "execution_plan.fingerprint")
    if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
        _error("execution_plan.fingerprint 必须是 SHA-256")
    try:
        state = parse_segment_interview(raw.get("state"))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        _error(f"execution_plan.state 无效：{error}")
    fps = _require_int(plan.get("fps"), "segment_plan.fps", 1)
    if fps != H3_FPS:
        _error(f"H3 分段执行固定为 {H3_FPS} fps")
    _require_int(plan.get("range_start_frame"), "segment_plan.range_start_frame", 0)
    target_count = _require_int(plan.get("target_frame_count"), "segment_plan.target_frame_count", 1)

    segments = _as_rows(plan.get("segments"), "segment_plan.segments")
    rows = _as_rows(raw.get("segments"), "execution_plan.segments")
    if not segments or len(segments) > MAX_SEGMENTS:
        _error(f"分段数量必须在 1 到 {MAX_SEGMENTS} 之间")
    if len(rows) != len(segments):
        _error("分段采访数量与分段计划不一致")

    seen = set()
    cursor = 0
    previous_end = None
    for index, (segment_value, row_value) in enumerate(zip(segments, rows)):
        segment = _as_mapping(segment_value, f"segment_plan.segments[{index}]")
        row = _as_mapping(row_value, f"execution_plan.segments[{index}]")
        identifier = _require_text(segment.get("segment_id"), f"segments[{index}].segment_id")
        if identifier in seen:
            _error(f"segment_id {identifier!r} 重复")
        seen.add(identifier)
        order = _require_int(segment.get("order"), f"segments[{index}].order", 1)
        if order != index + 1:
            _error("分段 order 必须从 1 连续递增")
        start = _require_int(segment.get("start_frame"), f"segments[{index}].start_frame", 0)
        end = _require_int(segment.get("end_frame"), f"segments[{index}].end_frame", 1)
        frame_count = _require_int(segment.get("frame_count"), f"segments[{index}].frame_count", 1)
        overlap = _require_int(segment.get("overlap_frames"), f"segments[{index}].overlap_frames", 0)
        seam = segment.get("seam")
        if end - start != frame_count:
            _error(f"segments[{index}] 的 frame_count 与范围不一致")
        if index == 0:
            if seam != "first" or overlap:
                _error("第一段必须是无重叠的 first 接缝")
        else:
            expected_overlap = max(0, previous_end - start)
            if start > previous_end:
                _error(f"segments[{index}] 与上一段之间存在漏帧")
            expected_seam = "guide" if expected_overlap else "hard_cut"
            if overlap != expected_overlap or seam != expected_seam:
                _error(f"segments[{index}] 的接缝或重叠帧与时间范围不一致")
            if seam == "guide" and not valid_h3_guide_frames(overlap):
                _error(
                    f"segments[{index}] 的重叠 {overlap} 帧不符合 H3 Guide 的 1 或 5+17k 规则；"
                    "请切换 H3 衔接帧对齐后重新排列"
                )
        previous_end = end
        model_padding = _as_mapping(segment.get("model_padding"), f"segments[{index}].model_padding")
        layout_adapter = model_padding.get("adapter")
        layout_length = model_padding.get("model_length")
        if layout_adapter == "h3":
            layout_length = _require_int(layout_length, f"segments[{index}].model_padding.model_length", 1)
            if layout_length < frame_count:
                _error(f"segments[{index}] 的 model_length 小于请求帧数")
        elif layout_adapter == "none":
            if layout_length is not None:
                _error(f"segments[{index}] 的通用模式不应声明 model_length")
        else:
            _error(f"segments[{index}].model_padding.adapter 无效")

        if row.get("segment_id") != identifier:
            _error(f"execution_plan.segments[{index}] 的 segment_id 未对齐")
        if row.get("frame_count") != frame_count:
            _error(f"execution_plan.segments[{index}] 的请求帧数未对齐")
        call_adapter = row.get("model_adapter")
        if call_adapter != "h3":
            _error(f"execution_plan.segments[{index}].model_adapter 必须是 h3")
        call_length = _require_int(row.get("model_length"), f"execution_plan.segments[{index}].model_length", 1)
        if call_length < frame_count or call_length != 1 and (call_length < 5 or (call_length - 5) % 17):
            _error(f"execution_plan.segments[{index}].model_length 不符合 H3 帧规则")
        _as_mapping(row.get("reference_plan"), f"execution_plan.segments[{index}].reference_plan")
        for field in ("system_prompt", "stage1_task", "stage2_prefix", "stage3_prefix"):
            _require_text(row.get(field), f"execution_plan.segments[{index}].{field}", allow_empty=True)
        duration = row.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            _error(f"execution_plan.segments[{index}].duration_seconds 必须为正数")

        contribution = planned_contribution(plan, index)
        if contribution["output_start_frame"] != cursor:
            _error(f"segments[{index}] 的输出贡献与最终时间线不连续")
        cursor = contribution["output_end_frame"]
        for field in ("output_start_frame", "output_end_frame", "output_frame_count"):
            if field in segment:
                expected = contribution["frame_count"] if field == "output_frame_count" else contribution[field]
                if segment[field] != expected:
                    _error(f"segments[{index}].{field} 与执行计算不一致")
        planned_incoming_guide(plan, index)
        planned_next_guide(plan, index)

    if fingerprint != execution_fingerprint(raw["plan_revision"], state, rows):
        _error("分段采访执行指纹与实际提示词或参考依赖不一致，请重新检测并对齐")
    if cursor != target_count:
        _error(f"分段贡献合计 {cursor} 帧，与目标 {target_count} 帧不一致")
    if fps <= 0:
        _error("fps 必须大于 0")
    return copy.deepcopy(dict(raw))


def execution_count(execution_plan):
    return len(normalize_execution_plan(execution_plan)["segments"])


def segment_context(execution_plan, segment_index):
    """Build the small payload consumed by one loop-body result writer."""

    normalized = normalize_execution_plan(execution_plan)
    index = _require_int(segment_index, "segment_index", 0)
    plan = normalized["segment_plan"]
    if index >= len(plan["segments"]):
        _error(f"segment_index {index} 超出分段范围")
    segment = plan["segments"][index]
    row = normalized["segments"][index]
    incoming_guide = planned_incoming_guide(plan, index)
    stage1_task = row["stage1_task"]
    if incoming_guide is not None:
        overlap_seconds = incoming_guide["frame_count"] / plan["fps"]
        continuity = (
            "[分段连续性约束]\n"
            f"当前段 0–{overlap_seconds:.3f} 秒是上一段已发生画面的连续延伸；"
            "保持动作、构图和时序连续，不要把它复述成新剧情。"
            "只在该重叠区间之后推进本段的新要求。"
        )
        stage1_task = stage1_task.rstrip() + ("\n\n" if stage1_task.strip() else "") + continuity
    return {
        "schema_version": 1,
        "execution_fingerprint": normalized["fingerprint"],
        "plan_revision": normalized["plan_revision"],
        "plan_id": plan["plan_id"],
        "source_fingerprint": plan["source_fingerprint"],
        "segment_index": index,
        "segment_count": len(plan["segments"]),
        "segment_ids": [item["segment_id"] for item in plan["segments"]],
        "segment_id": segment["segment_id"],
        "order": segment["order"],
        "fps": plan["fps"],
        "range_start_frame": plan["range_start_frame"],
        "target_frame_count": plan["target_frame_count"],
        "segment": copy.deepcopy(segment),
        "contribution": planned_contribution(plan, index),
        "incoming_guide": incoming_guide,
        "next_guide": planned_next_guide(plan, index),
        "is_last": index == len(plan["segments"]) - 1,
        "reference_plan": copy.deepcopy(row["reference_plan"]),
        "system_prompt": row["system_prompt"],
        "stage1_task": stage1_task,
        "stage2_prefix": row["stage2_prefix"],
        "stage3_prefix": row["stage3_prefix"],
        "duration_seconds": float(row["duration_seconds"]),
        "frame_count": row["frame_count"],
        "model_length": row["model_length"],
        "model_adapter": row["model_adapter"],
        "audio_contract": copy.deepcopy(RUN_AUDIO_CONTRACT),
    }


def _unwrap_manifest(value):
    if isinstance(value, (list, tuple)) and len(value) == 1 and isinstance(value[0], Mapping):
        return value[0]
    return value


def normalize_run_manifest(value):
    raw = _as_mapping(_unwrap_manifest(value), "run_result")
    if raw.get("schema_version") != RUN_MANIFEST_VERSION or raw.get("kind") != "zv_long_video_run":
        _error("需要 ZV 长视频运行清单 v1")
    for field in ("execution_fingerprint", "plan_revision", "plan_id", "run_id", "run_dir"):
        _require_text(raw.get(field), f"run_result.{field}")
    _require_int(raw.get("fps"), "run_result.fps", 1)
    _require_int(raw.get("target_frame_count"), "run_result.target_frame_count", 1)
    if raw.get("audio_contract") != RUN_AUDIO_CONTRACT:
        _error("运行清单音频合同缺失或不兼容，请从第一段重新执行")
    segment_ids = _as_rows(raw.get("segment_ids"), "run_result.segment_ids")
    results = _as_rows(raw.get("results"), "run_result.results")
    if not all(isinstance(value, str) and value for value in segment_ids):
        _error("run_result.segment_ids 必须全部是非空字符串")
    if len(results) > len(segment_ids):
        _error("run_result.results 超过计划分段数量")
    if type(raw.get("completed")) is not bool:
        _error("run_result.completed 必须是布尔值")
    if raw.get("final_validation") is not None and not isinstance(raw["final_validation"], Mapping):
        _error("run_result.final_validation 必须是对象或 null")
    return copy.deepcopy(dict(raw))


def new_run_manifest(context, run_dir, run_id):
    context = _as_mapping(context, "segment_context")
    if context.get("schema_version") != 1 or context.get("segment_index") != 0:
        _error("只能从第一段创建运行清单")
    if context.get("audio_contract") != RUN_AUDIO_CONTRACT:
        _error("分段上下文音频合同缺失或不兼容")
    return {
        "schema_version": RUN_MANIFEST_VERSION,
        "kind": "zv_long_video_run",
        "execution_fingerprint": context["execution_fingerprint"],
        "plan_revision": context["plan_revision"],
        "plan_id": context["plan_id"],
        "fps": context["fps"],
        "target_frame_count": context["target_frame_count"],
        "segment_ids": list(context["segment_ids"]),
        "audio_contract": copy.deepcopy(RUN_AUDIO_CONTRACT),
        "run_id": str(run_id),
        "run_dir": str(run_dir),
        "results": [],
        "completed": False,
        "final_validation": None,
    }


def append_result(context, previous_run, result_entry):
    """Append one JSON-compatible artifact record to the loop carry."""

    context = _as_mapping(context, "segment_context")
    entry = _as_mapping(result_entry, "result_entry")
    index = _require_int(context.get("segment_index"), "segment_context.segment_index", 0)
    if previous_run is None:
        _error("第一段运行清单必须先由落盘器创建")
    manifest = normalize_run_manifest(previous_run)
    identity = {
        "execution_fingerprint": context.get("execution_fingerprint"),
        "plan_revision": context.get("plan_revision"),
        "plan_id": context.get("plan_id"),
        "fps": context.get("fps"),
        "target_frame_count": context.get("target_frame_count"),
        "segment_ids": context.get("segment_ids"),
        "audio_contract": context.get("audio_contract"),
    }
    for field, expected in identity.items():
        if manifest.get(field) != expected:
            _error(f"上一轮运行清单的 {field} 与当前执行不一致")
    if len(manifest["results"]) != index:
        _error(f"当前是第 {index + 1} 段，但运行清单已有 {len(manifest['results'])} 段")
    if entry.get("segment_id") != context.get("segment_id") or entry.get("segment_index") != index:
        _error("落盘结果与当前分段不一致")
    manifest["results"].append(copy.deepcopy(dict(entry)))
    manifest["completed"] = len(manifest["results"]) == len(manifest["segment_ids"])
    return manifest


def assert_run_matches_context(context, previous_run):
    """Validate the loop carry before loading an incoming guide."""

    context = _as_mapping(context, "segment_context")
    index = _require_int(context.get("segment_index"), "segment_context.segment_index", 0)
    if index == 0:
        if previous_run is not None:
            _error("第一段不应收到上一轮运行清单")
        return None
    if previous_run is None:
        _error(f"第 {index + 1} 段缺少上一轮运行清单")
    manifest = normalize_run_manifest(previous_run)
    for field in ("execution_fingerprint", "plan_revision", "plan_id", "fps", "target_frame_count", "segment_ids", "audio_contract"):
        if manifest.get(field) != context.get(field):
            _error(f"上一轮运行清单的 {field} 与当前执行不一致")
    if len(manifest["results"]) != index:
        _error(f"第 {index + 1} 段要求恰好已有 {index} 个落盘结果")
    expected_previous = context["segment_ids"][index - 1]
    if manifest["results"][-1].get("segment_id") != expected_previous:
        _error("上一轮结果不是当前分段的直接前驱")
    return manifest
