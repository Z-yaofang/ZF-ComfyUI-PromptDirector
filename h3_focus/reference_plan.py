"""Stable H3 reference routing produced by the interview.

The plan contains stable material IDs and the canonical media project, never
decoded tensors.  Its limits deliberately mirror the installed T8 H3 node:
first/last frame are independent sockets, followed by nine ref images, three
videos with same-numbered soundtracks, and three standalone reference audios.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping

from .routing import RULES


SCHEMA_VERSION = "zv-h3-reference-plan-v1"
H3_REFERENCE_LIMITS = {bank: RULES["banks"][bank] for bank in ("ref_images", "ref_videos", "ref_video_audios", "ref_audios")}
H3_REFERENCE_LIMITS["drive_audios"] = RULES["banks"]["drive_audio"]
# This is a convenient selection profile, not a model limit.  Keeping it in
# metadata lets the UI offer the familiar default without shrinking the fixed
# backend contract.
COMMON_SELECTION_PRESET = {
    # Community shorthand counts visible source files, not the semantic H3
    # sub-banks (anchors, video soundtracks, drive audio, and so on).
    "pictures": 6,
    "videos": 3,
    "audios": 3,
}

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


class ReferencePlanError(ValueError):
    pass


def _empty_routes():
    return {
        "first_frame": None,
        "last_frame": None,
        "ref_images": [],
        "ref_videos": [],
        "ref_video_audios": [],
        "drive_audio": None,
        "ref_audios": [],
    }


def empty_reference_plan(*, errors=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": False,
        "media_project": None,
        "routes": _empty_routes(),
        "call_references": [],
        "limits": copy.deepcopy(H3_REFERENCE_LIMITS),
        "selection_preset": copy.deepcopy(COMMON_SELECTION_PRESET),
        "errors": copy.deepcopy(errors or []),
        "warnings": [],
        "reference_selection": "desk_selected_source_segment",
    }


def build_reference_plan(media_project, compiled):
    """Build a tensor-free plan from one compiled interview result."""
    routes = _empty_routes()
    calls = copy.deepcopy(compiled.get("call_references", []))
    for row in calls:
        kind = row.get("kind")
        item_id = row.get("item_id")
        origin = row.get("origin", "standalone" if kind == "audio" else "reference")
        if kind == "picture":
            if origin == "first_frame":
                routes["first_frame"] = item_id
            elif origin == "last_frame":
                routes["last_frame"] = item_id
            else:
                routes["ref_images"].append(item_id)
        elif kind == "video":
            routes["ref_videos"].append(item_id)
        elif kind == "audio":
            if origin == "video_soundtrack":
                routes["ref_video_audios"].append(item_id)
            elif origin == "drive_audio":
                routes["drive_audio"] = item_id
            else:
                routes["ref_audios"].append(item_id)

    validation = compiled.get("validation", {})
    plan = {
        "schema_version": SCHEMA_VERSION,
        "ready": bool(validation.get("ready", False)),
        "media_project": copy.deepcopy(media_project),
        "routes": routes,
        "call_references": calls,
        "limits": copy.deepcopy(H3_REFERENCE_LIMITS),
        "selection_preset": copy.deepcopy(COMMON_SELECTION_PRESET),
        "errors": copy.deepcopy(validation.get("errors", [])),
        "warnings": copy.deepcopy(validation.get("warnings", [])),
        "reference_selection": "desk_selected_source_segment",
        "model_visibility": copy.deepcopy(validation.get("model_visible_references", [])),
        "rules_version": RULES["version"],
    }
    # Treat internal planner mistakes as an invalid plan rather than silently
    # dropping a reference.  normalize_reference_plan supplies precise details.
    try:
        return normalize_reference_plan(plan)
    except ReferencePlanError as exc:
        plan["ready"] = False
        plan["errors"].append({"path": "/routes", "code": "reference_plan", "message": str(exc)})
        return plan


def planned_detection(compiled, *, conditioning_count=0):
    """Return the compact snapshot implied by the fixed outlet contract.

    This is used to revalidate a manual "detect and align" action without
    trying to recover runtime stable IDs from individual downstream wires.
    """
    result = {"version": 1, "pictures": [], "videos": [], "audios": []}
    image_index = video_index = ref_audio_index = 0
    video_ordinals = {}
    for row in compiled.get("call_references", []):
        kind = row.get("kind")
        origin = row.get("origin", "standalone" if kind == "audio" else "reference")
        item_id = row.get("item_id")
        if kind == "picture":
            if origin == "first_frame":
                port = "first_frame"
            elif origin == "last_frame":
                port = "last_frame"
            else:
                image_index += 1
                port = f"ref_image_{image_index}"
            result["pictures"].append({
                "item_id": item_id, "source_kind": "ZVH3ReferenceOutlet",
                "source_port": port, "origin": origin,
            })
        elif kind == "video":
            video_index += 1
            video_ordinals[item_id] = video_index
            result["videos"].append({
                "item_id": item_id, "source_kind": "ZVH3ReferenceOutlet",
                "source_port": f"ref_video_{video_index}", "origin": "reference",
            })
        elif kind == "audio":
            if origin == "video_soundtrack":
                ordinal = video_ordinals.get(item_id)
                port = f"ref_video_audio_{ordinal}" if ordinal else "ref_video_audio"
            elif origin == "drive_audio":
                port = "drive_audio"
            else:
                ref_audio_index += 1
                port = f"ref_audio_{ref_audio_index}"
            result["audios"].append({
                "item_id": item_id, "source_kind": "ZVH3ReferenceOutlet",
                "source_port": port, "origin": origin,
            })
    result["stage1"] = {
        "pictures": [row["item_id"] for row in result["pictures"]],
        "videos": [row["item_id"] for row in result["videos"]],
    }
    result["conditioning_count"] = max(0, int(conditioning_count))
    return result


def _binding(value, path, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ReferencePlanError(f"{path} 缺少合法稳定素材 ID")
    return value


def _bindings(value, path, maximum):
    if not isinstance(value, list):
        raise ReferencePlanError(f"{path} 必须是稳定素材 ID 列表")
    if len(value) > maximum:
        raise ReferencePlanError(f"{path} 最多 {maximum} 项，当前 {len(value)} 项")
    return [_binding(item, f"{path}/{index}") for index, item in enumerate(value)]


def normalize_reference_plan(value):
    if not isinstance(value, Mapping):
        raise ReferencePlanError("H3 素材计划必须是对象")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ReferencePlanError("H3 素材计划版本不受支持，请重新检测并对齐素材")
    routes = value.get("routes")
    if not isinstance(routes, Mapping):
        raise ReferencePlanError("H3 素材计划缺少 routes")
    allowed_routes = set(_empty_routes())
    unknown = set(routes) - allowed_routes
    if unknown:
        raise ReferencePlanError("H3 素材计划包含未知出口：" + "、".join(sorted(map(str, unknown))))
    normalized_routes = {
        "first_frame": _binding(routes.get("first_frame"), "/routes/first_frame", optional=True),
        "last_frame": _binding(routes.get("last_frame"), "/routes/last_frame", optional=True),
        "ref_images": _bindings(routes.get("ref_images", []), "/routes/ref_images", H3_REFERENCE_LIMITS["ref_images"]),
        "ref_videos": _bindings(routes.get("ref_videos", []), "/routes/ref_videos", H3_REFERENCE_LIMITS["ref_videos"]),
        "ref_video_audios": _bindings(routes.get("ref_video_audios", []), "/routes/ref_video_audios", H3_REFERENCE_LIMITS["ref_video_audios"]),
        "drive_audio": _binding(routes.get("drive_audio"), "/routes/drive_audio", optional=True),
        "ref_audios": _bindings(routes.get("ref_audios", []), "/routes/ref_audios", H3_REFERENCE_LIMITS["ref_audios"]),
    }
    video_ids = normalized_routes["ref_videos"]
    soundtracks = normalized_routes["ref_video_audios"]
    if any(item_id not in video_ids for item_id in soundtracks):
        raise ReferencePlanError("视频原声必须来自本次同号参考视频")
    if len(set(soundtracks)) != len(soundtracks):
        raise ReferencePlanError("同一参考视频原声不能重复占用多个 H3 音频口")
    if len(set(video_ids)) != len(video_ids):
        raise ReferencePlanError("同一参考视频不能重复占用多个 H3 视频口")
    if len(set(normalized_routes["ref_images"])) != len(normalized_routes["ref_images"]):
        raise ReferencePlanError("同一参考图片不能重复占用多个 H3 ref_image 口")
    independent = [
        item_id for item_id in [normalized_routes["drive_audio"], *normalized_routes["ref_audios"]]
        if item_id is not None
    ]
    if len(set(independent)) != len(independent):
        raise ReferencePlanError("同一独立音频不能同时占用多个 H3 音频口")

    result = copy.deepcopy(dict(value))
    result["routes"] = normalized_routes
    result["ready"] = bool(value.get("ready", False))
    result["limits"] = copy.deepcopy(H3_REFERENCE_LIMITS)
    result["selection_preset"] = copy.deepcopy(COMMON_SELECTION_PRESET)
    result["call_references"] = copy.deepcopy(value.get("call_references", [])) if isinstance(value.get("call_references", []), list) else []
    result["errors"] = copy.deepcopy(value.get("errors", [])) if isinstance(value.get("errors", []), list) else []
    result["warnings"] = copy.deepcopy(value.get("warnings", [])) if isinstance(value.get("warnings", []), list) else []
    if result.get("media_project") is not None and not isinstance(result["media_project"], Mapping):
        raise ReferencePlanError("H3 素材计划中的 media_project 无效")
    return result


__all__ = [
    "COMMON_SELECTION_PRESET",
    "H3_REFERENCE_LIMITS",
    "ReferencePlanError",
    "SCHEMA_VERSION",
    "build_reference_plan",
    "empty_reference_plan",
    "normalize_reference_plan",
    "planned_detection",
]
