"""Compile each segment through the existing H3 interview and physical router."""

import copy
import hashlib
import json

from ..h3_focus.interview import TEXT_FIELDS, compile_interview, empty_interview, normalize_interview
from ..h3_focus.reference_plan import build_reference_plan, planned_detection
from ..h3_focus.routing import align_bindings, model_frame_count
from .plan import segment_project


FIELDS = set(TEXT_FIELDS) | {"bindings", "media_roles", "media_purposes", "mode", "director_focus"}
COMPILED_FINGERPRINT_FIELDS = (
    "segment_id", "reference_plan", "user_prompt", "material_context_json",
    "duration_seconds", "frame_count", "model_length", "model_adapter",
)
H3_FPS = 24


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def valid_h3_guide_frames(value):
    return type(value) is int and (value == 1 or value >= 5 and (value - 5) % 17 == 0)


def _fingerprint_media_project(project):
    fields = {
        "picture_track": ("item_id", "asset_id", "order"),
        "video_track": (
            "clip_id", "asset_id", "timeline_in_seconds", "source_in_seconds",
            "source_out_seconds", "source_audio_enabled", "audio_link_id",
        ),
        "audio_track": (
            "clip_id", "asset_id", "timeline_in_seconds", "source_in_seconds",
            "source_out_seconds", "origin", "enabled", "linked_video_clip_id",
            "source_video_clip_id",
        ),
    }
    tracks = {
        key: [
            {field: copy.deepcopy(row.get(field)) for field in names}
            for row in project.get(key, []) if isinstance(row, dict)
        ]
        for key, names in fields.items()
    }
    referenced = {
        row.get("asset_id")
        for rows in tracks.values() for row in rows if isinstance(row, dict)
    }
    assets = [
        copy.deepcopy(row) for row in project.get("assets", [])
        if isinstance(row, dict) and row.get("asset_id") in referenced
    ]
    assets.sort(key=lambda row: (str(row.get("asset_id", "")), str(row.get("kind", "")), str(row.get("source_handle", ""))))
    return {
        "schema_version": project.get("schema_version"),
        "assets": assets,
        **tracks,
        "processing_window": copy.deepcopy(project.get("processing_window")),
        "processing_preset": copy.deepcopy(project.get("processing_preset")),
        "output_canvas": copy.deepcopy(project.get("output_canvas")),
    }


def _fingerprint_reference_plan(reference_plan):
    result = {
        key: copy.deepcopy(value)
        for key, value in reference_plan.items()
        if key not in {"ready", "errors", "warnings", "media_project"}
    }
    result["media_project"] = _fingerprint_media_project(reference_plan.get("media_project", {}))
    return result


def execution_fingerprint(plan_revision, state, rows):
    compiled_rows = []
    for row in rows:
        compiled = {key: copy.deepcopy(row[key]) for key in COMPILED_FINGERPRINT_FIELDS}
        compiled["reference_plan"] = _fingerprint_reference_plan(row["reference_plan"])
        compiled_rows.append(compiled)
    return digest({
        "plan_revision": plan_revision,
        "interview": {"global": copy.deepcopy(state["global"]), "segments": copy.deepcopy(state["segments"])},
        "compiled_rows": compiled_rows,
    })


def empty_segment_interview():
    return {"schema_version": 1, "global": {}, "segments": {}, "alignment": None}


def parse_segment_interview(value):
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("分段采访内容超过 2 MiB")
        value = json.loads(value)
    if not isinstance(value, dict) or value.get("schema_version", 1) != 1:
        raise ValueError("分段采访版本不受支持")
    if set(value) - set(empty_segment_interview()):
        raise ValueError("分段采访包含未知字段")
    state = empty_segment_interview() | copy.deepcopy(value)
    if not isinstance(state["global"], dict) or not isinstance(state["segments"], dict):
        raise ValueError("全局采访与逐段采访必须是对象")
    for row in [state["global"], *state["segments"].values()]:
        if not isinstance(row, dict) or set(row) - FIELDS:
            raise ValueError("采访内容包含不支持的字段")
        normalize_interview(empty_interview() | row)
    return state


def merged_interview(global_fields, segment_fields):
    state = empty_interview()
    for source in (global_fields, segment_fields):
        for key, value in source.items():
            if key in ("bindings", "media_roles", "media_purposes"):
                state[key].update(copy.deepcopy(value))
            elif key in TEXT_FIELDS and state[key] and value:
                state[key] += "\n" + value
            else:
                state[key] = copy.deepcopy(value)
    return state


def compile_segment_interview(plan, raw_state, *, align=False):
    state = parse_segment_interview(raw_state)
    errors = copy.deepcopy(plan["validation"]["errors"])
    if plan.get("fps") != H3_FPS:
        errors.append({"code": "h3_fps", "message": f"H3 分段执行固定为 {H3_FPS} fps；当前计划为 {plan.get('fps')} fps"})
    rows = []
    for segment in plan["segments"]:
        identifier = segment["segment_id"]
        if segment.get("seam") == "guide" and not valid_h3_guide_frames(segment.get("overlap_frames")):
            errors.append({
                "code": "h3_guide_length", "segment_id": identifier,
                "message": (
                    f"第 {segment['order']} 段重叠 {segment.get('overlap_frames')} 帧不符合 H3 Guide 的 1 或 5+17k 规则；"
                    "请切换“H3 衔接帧对齐”后重新排列"
                ),
            })
        project = segment_project(plan, identifier)
        draft = merged_interview(state["global"], state["segments"].get(identifier, {}))
        first = compile_interview(draft, project, confirm_references=True)
        align_bindings(first["state"], first["inventory"])
        first = compile_interview(first["state"], project, confirm_references=True)
        draft = first["state"]
        draft["alignment"] = first["alignment_context"]
        draft["reference_detection"] = planned_detection(first)
        compiled = compile_interview(draft, project, confirm_references=True)
        for problem in [*project["validation"]["errors"], *compiled["validation"]["errors"]]:
            errors.append({**problem, "segment_id": identifier, "message": f"第 {segment['order']} 段：{problem['message']}"})
        rows.append({
            "segment_id": identifier,
            **{key: compiled[key] for key in ("user_prompt", "material_context_json", "duration_seconds", "inventory", "call_references")},
            "reference_plan": build_reference_plan(project, compiled),
            "frame_count": segment["frame_count"],
            "model_length": model_frame_count(segment["frame_count"]),
            "model_adapter": "h3",
            "validation": compiled["validation"],
        })
    fingerprint = execution_fingerprint(plan["revision"], state, rows)
    if align and not errors:
        state["alignment"] = fingerprint
    if state["alignment"] != fingerprint:
        errors.append({"code": "alignment_stale", "message": "分段或采访内容已变化，请点击“检测并对齐全部分段”"})
    ready = bool(rows) and not errors
    return {
        "schema_version": 1, "plan_revision": plan["revision"], "segment_plan": plan,
        "fingerprint": fingerprint, "ready": ready, "segments": rows,
        "state": state, "errors": errors,
        "report": (f"{len(rows)} 段 · {'已对齐，可执行' if ready else '未就绪'}\n"
                   + "\n".join(row["message"] for row in errors)),
    }


class ZVSegmentInterview:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "segment_plan": ("ZV_SEGMENT_PLAN",),
            "interview_data": ("STRING", {"multiline": True, "default": json.dumps(empty_segment_interview())}),
        }}

    RETURN_TYPES = ("ZV_SEGMENT_EXECUTION_PLAN", "STRING", "BOOLEAN")
    RETURN_NAMES = ("execution_plan", "检查报告", "ready")
    FUNCTION = "compile"
    CATEGORY = "ZV/视频创作/长视频"

    def compile(self, segment_plan, interview_data):
        result = compile_segment_interview(segment_plan, interview_data)
        return result, result["report"], result["ready"]


__all__ = [
    "COMPILED_FINGERPRINT_FIELDS", "H3_FPS", "ZVSegmentInterview", "compile_segment_interview",
    "empty_segment_interview", "execution_fingerprint", "parse_segment_interview", "valid_h3_guide_frames",
]
