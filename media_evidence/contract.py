"""Model-neutral project facts. Seconds own time; Python owns track labels."""

import copy
import json
import math
from pathlib import Path
import re
from .presets import builtin, compatibility, normalize_snapshot, rule_errors

SOURCE_MESSAGES = {
    "registry_missing": "素材登记文件不可见；云端存储可能未同步，请重新导入",
    "registry_unreadable": "素材登记文件暂时无法读取，请稍后重试；若持续失败请重新导入",
    "registry_invalid": "素材登记文件无效或损坏，请重新导入",
    "source_missing": "素材原文件不可见；云端上传存储可能未同步，请重新导入",
    "source_unreadable": "素材原文件暂时无法读取，请稍后重试；若持续失败请重新导入",
    "source_size_changed": "素材原文件大小已改变，请重新导入",
    "source_content_changed": "素材原文件内容已改变，请重新导入",
    "source_metadata_changed": "旧素材登记缺少内容摘要且文件时间已改变，请重新导入",
    "source_unstable": "素材原文件在校验时仍在变化，请稍后重试或重新导入",
}


def source_message(message, fallback):
    """Return only server-authored source diagnostics; never echo arbitrary text."""
    return message if message in SOURCE_MESSAGES.values() else fallback


SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "zv-media-project-v2.schema.json").read_text(encoding="utf-8"))
DERIVED_CLIP = {"timeline_out_seconds", "duration_seconds", "source_in_frame", "source_out_frame", "source_frame_count", "project_frame_count", "frame_estimated"}


class ProjectError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Invalid media project")


def problem(path, code, message):
    return {"path": path, "code": code, "message": message}


def empty_project():
    return {"schema_version": 2, "project_clock": {"fps": 24}, "assets": [], "picture_track": [], "video_track": [], "audio_track": [], "processing_window": {"start_seconds": 0, "end_seconds": 10, "fps": 24}, "processing_preset": builtin()}


def parse_project(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Non-finite number")

    if not isinstance(text, str) or len(text.encode("utf-8")) > 2 * 1024 * 1024:
        raise ProjectError([problem("", "json_size", "Project JSON must fit within 2 MiB")])
    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
        pending = [(result, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 32:
                raise ValueError("JSON nesting limit")
            if isinstance(item, (dict, list)):
                pending.extend((child, depth+1) for child in (item.values() if isinstance(item, dict) else item))
        return result
    except (ValueError, TypeError, RecursionError):
        raise ProjectError([problem("", "invalid_json", "Expected JSON without duplicate keys or non-finite values")]) from None


def shape_errors(value, schema=SCHEMA, path=""):
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "null": value is None, "boolean": type(value) is bool, "integer": type(value) is int, "number": type(value) is int or (type(value) is float and math.isfinite(value))}
    if types and not any(valid[t] for t in types):
        return [problem(path, "type", "Incorrect field type")]
    errors = []
    if ("const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"])) or ("enum" in schema and value not in schema["enum"]):
        return [problem(path, "choice", "Unsupported field value or schema version")]
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(problem(path + "/" + name, "required", "Required field is missing"))
        for name, item in value.items():
            if name not in schema.get("properties", {}):
                errors.append(problem(path, "unknown_field", "Unknown fields cannot be stored"))
            else:
                errors.extend(shape_errors(item, schema["properties"][name], path + "/" + name))
    elif isinstance(value, list):
        if len(value) > schema.get("maxItems", 512):
            return [problem(path, "item_limit", "Too many project entries")]
        for index, item in enumerate(value):
            errors.extend(shape_errors(item, schema["items"], f"{path}/{index}"))
    elif isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4096):
            errors.append(problem(path, "length", "Invalid text length"))
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(problem(path, "format", "Invalid ID or safe source handle"))
    elif type(value) in (int, float):
        if not schema.get("minimum", -9007199254740991) <= value <= schema.get("maximum", 9007199254740991):
            errors.append(problem(path, "range", "Number is outside the supported range"))
        multiple = schema.get("multipleOf")
        if multiple is not None and value % multiple != 0:
            errors.append(problem(path, "multiple", "Number is not aligned to the required multiple"))
    return errors


def seconds_to_frame(seconds, fps):
    return math.floor(seconds * fps + 0.5)


def frame_to_seconds(frame, fps):
    return frame / fps


def normalize_project(project):
    if not isinstance(project, dict):
        raise ProjectError([problem("", "type", "Project must be an object")])
    result = copy.deepcopy(project)
    result.pop("outlet_slots", None)
    if type(result.get("schema_version")) is int and result["schema_version"] == 1:
        result["schema_version"] = 2
        result.setdefault("processing_preset", builtin("builtin.minimax-h3.single"))
    preset = result.get("processing_preset")
    if isinstance(preset, dict) and "snapshot" in preset:
        preset["snapshot"] = normalize_snapshot(preset["snapshot"])
    result.pop("validation", None)
    result.pop("preset_compatibility", None)
    result.pop("label_map", None)
    for key in ("video_track", "audio_track"):
        if isinstance(result.get(key), list):
            for clip in result[key]:
                if isinstance(clip, dict):
                    for field in DERIVED_CLIP:
                        clip.pop(field, None)
    if isinstance(result.get("processing_window"), dict):
        for key in ("start_frame", "end_frame", "frame_count"):
            result["processing_window"].pop(key, None)
    errors = shape_errors(result)
    if errors:
        raise ProjectError(errors)
    preset_errors = rule_errors(result["processing_preset"]["snapshot"])
    if preset_errors:
        raise ProjectError([problem("/processing_preset", "preset_rules", message) for message in preset_errors])
    warnings = []
    assets = {a["asset_id"]: a for a in result["assets"]}
    if len(assets) != len(result["assets"]):
        errors.append(problem("/assets", "duplicate_id", "Asset IDs must be unique"))
    result["picture_track"].sort(key=lambda item: (item["order"], item["item_id"]))
    for track in ("video_track", "audio_track"):
        result[track].sort(key=lambda clip: (clip["timeline_in_seconds"], clip["clip_id"]))
    ids = set()
    for track in ("picture_track", "video_track", "audio_track"):
        for i, item in enumerate(result[track]):
            item_id = item.get("item_id", item.get("clip_id"))
            if item_id in ids:
                errors.append(problem(f"/{track}/{i}", "duplicate_id", "Track item IDs must be unique across all tracks"))
            ids.add(item_id)
            if item["asset_id"] not in assets:
                errors.append(problem(f"/{track}/{i}/asset_id", "missing_asset", "Track item references a missing asset"))
    videos = {clip["clip_id"]: clip for clip in result["video_track"]}
    audios = {clip["clip_id"]: clip for clip in result["audio_track"]}
    for i, video in enumerate(result["video_track"]):
        a = assets.get(video["asset_id"])
        if a and a["kind"] != "video":
            errors.append(problem(f"/video_track/{i}", "track_kind", "Video track only accepts video assets"))
        if video["audio_link_id"]:
            audio = audios.get(video["audio_link_id"])
            if not audio or audio["linked_video_clip_id"] != video["clip_id"] or audio["origin"] != "video_source" or audio["asset_id"] != video["asset_id"]:
                errors.append(problem(f"/video_track/{i}/audio_link_id", "audio_link", "Video and source-audio links must be reciprocal"))
            else:
                changed = any(audio[key] != video[key] for key in ("timeline_in_seconds", "source_in_seconds", "source_out_seconds"))
                for key in ("timeline_in_seconds", "source_in_seconds", "source_out_seconds"):
                    audio[key] = video[key]
                audio["enabled"] = video["source_audio_enabled"]
                if changed:
                    warnings.append(problem(f"/video_track/{i}", "audio_followed", "Bound source audio follows the video window and position"))
        elif video["source_audio_enabled"]:
            errors.append(problem(f"/video_track/{i}", "missing_audio_link", "Enabled source audio requires an explicit linked audio clip"))
        if video["source_audio_enabled"] and a and not a["probe"]["has_audio"]:
            errors.append(problem(f"/video_track/{i}", "no_source_audio", "This source video has no audio stream"))
    for i, audio in enumerate(result["audio_track"]):
        a = assets.get(audio["asset_id"])
        if a and (a["kind"] != ("audio" if audio["origin"] == "standalone" else "video") or not a["probe"]["has_audio"]):
            errors.append(problem(f"/audio_track/{i}", "track_kind", "Audio clips require an audio asset or the audio stream of a video"))
        if audio["linked_video_clip_id"]:
            video = videos.get(audio["linked_video_clip_id"])
            if audio["origin"] != "video_source" or not video or video["audio_link_id"] != audio["clip_id"] or video["asset_id"] != audio["asset_id"]:
                errors.append(problem(f"/audio_track/{i}", "audio_link", "Audio link does not identify its matching video"))
    fps = result["project_clock"]["fps"]
    for track in ("video_track", "audio_track"):
        result[track].sort(key=lambda clip: (clip["timeline_in_seconds"], clip["clip_id"]))
        for i, clip in enumerate(result[track]):
            a = assets.get(clip["asset_id"])
            if not a:
                continue
            probe = a["probe"]
            start, end = clip["source_in_seconds"], clip["source_out_seconds"]
            duration = end - start
            if duration <= 0 or probe["duration_seconds"] is None or end > probe["duration_seconds"] + 1e-6:
                errors.append(problem(f"/{track}/{i}", "source_window", "Clip needs a positive source window within the original duration"))
            source_fps = probe["fps"] if a["kind"] == "video" else None
            clip.update(duration_seconds=duration, timeline_out_seconds=clip["timeline_in_seconds"] + duration,
                        source_in_frame=seconds_to_frame(start, source_fps) if source_fps else None,
                        source_out_frame=seconds_to_frame(end, source_fps) if source_fps else None,
                        source_frame_count=seconds_to_frame(duration, source_fps) if source_fps else None,
                        project_frame_count=seconds_to_frame(max(0, duration), fps),
                        frame_estimated=bool(source_fps and not probe["frame_count_exact"]))
            if clip["timeline_out_seconds"] > 43200:
                errors.append(problem(f"/{track}/{i}", "timeline_limit", "Project timeline is limited to 12 hours"))
            if probe["vfr"] is not False and a["kind"] == "video":
                warnings.append(problem(f"/{track}/{i}", "estimated_frames", "Source frame positions are estimates; use source seconds for cuts"))
    labels = []
    for i, item in enumerate(result["picture_track"], 1):
        item["order"] = i
        if item["asset_id"] in assets and assets[item["asset_id"]]["kind"] != "picture":
            errors.append(problem(f"/picture_track/{i-1}", "track_kind", "Picture track only accepts still images"))
        labels.append({"track": "picture", "item_id": item["item_id"], "asset_id": item["asset_id"], "label": f"Picture {i}", "ordinal": i})
    video_labels = {}
    for i, clip in enumerate(result["video_track"], 1):
        video_labels[clip["clip_id"]] = f"Video {i}"
        labels.append({"track": "video", "item_id": clip["clip_id"], "asset_id": clip["asset_id"], "label": f"Video {i}", "ordinal": i})
    count = 0
    for clip in result["audio_track"]:
        linked = clip["linked_video_clip_id"]
        if linked:
            label, ordinal = video_labels.get(linked, "Missing video") + " 原声", None
        else:
            count += 1
            label, ordinal = f"Audio {count}", count
        labels.append({"track": "audio", "item_id": clip["clip_id"], "asset_id": clip["asset_id"], "label": label, "ordinal": ordinal})
    window = result["processing_window"]
    start, end, rate = window["start_seconds"], window["end_seconds"], window["fps"]
    first, last = seconds_to_frame(start, rate), seconds_to_frame(end, rate)
    window.update(start_frame=first, end_frame=last, frame_count=max(0, last-first))
    if end <= start:
        errors.append(problem("/processing_window", "window_range", "处理窗口结束必须大于开始；原值未改写"))
    result["preset_compatibility"] = compatibility(window, result["processing_preset"])
    result["label_map"] = labels
    result["validation"] = {"errors": errors, "warnings": warnings}
    return result
