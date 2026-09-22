"""Pair existing desk clips without changing their source cuts or project clock."""

import copy
from fractions import Fraction
import hashlib
import json
import math
import re

from ..media_evidence.contract import ProjectError, normalize_project


MAX_SEGMENTS = 4096


class AnimatePlanError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("；".join(row["message"] for row in issues))


def _issue(path, code, message):
    return {"path": path, "code": code, "message": message}


def default_settings():
    return {"schema_version": 1, "seam_mode": "hard_cut", "mask_enabled": False, "mask_tasks": {}}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _frame(seconds, fps):
    return math.floor(seconds * fps + .5 + 1e-9)


def _rate(value):
    rate = float(Fraction(str(value)).limit_denominator(1_000_000))
    integer = round(rate)
    return float(integer) if abs(rate - integer) <= 1e-4 else rate


def same_frame_rate(source, target):
    return source is not None and math.isclose(_rate(source), _rate(target), rel_tol=1e-6, abs_tol=1e-6)


def _settings(value):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise AnimatePlanError([_issue("/settings", "type", "分段设置必须是对象")])
    result = {**default_settings(), **copy.deepcopy(value)}
    if set(value) - set(default_settings()):
        raise AnimatePlanError([_issue("/settings", "unknown_field", "存在未知分段设置字段")])
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise AnimatePlanError([_issue("/settings/schema_version", "schema_version", "不支持的 Animate 设置版本")])
    if result["seam_mode"] not in ("hard_cut", "continuation_21"):
        raise AnimatePlanError([_issue("/settings/seam_mode", "seam_mode", "请选择硬切或原生 21 帧承接")])
    if type(result["mask_enabled"]) is not bool or not isinstance(result["mask_tasks"], dict):
        raise AnimatePlanError([_issue("/settings", "mask_settings", "遮罩设置需包含全局开关与各段填写内容")])
    for task in result["mask_tasks"].values():
        if not isinstance(task, dict) or set(task) - {"asset_id", "source_frame", "prompt"}:
            raise AnimatePlanError([_issue("/settings/mask_tasks", "mask_task", "每段只保存视频来源、参考帧和遮罩目标词")])
    return result


def _project(value):
    try:
        result = normalize_project(value)
    except ProjectError as exc:
        raise AnimatePlanError(exc.errors) from None
    # Browser preview failure is not evidence that the registered original is missing.
    validation = value.get("validation") if isinstance(value.get("validation"), dict) else {}
    inherited = validation.get("errors") if isinstance(validation.get("errors"), list) else []
    for row in inherited:
        if isinstance(row, dict) and row.get("code") == "source_unavailable" and row not in result["validation"]["errors"]:
            result["validation"]["errors"].append(copy.deepcopy(row))
    return result


def _source_facts(project):
    videos = [{key: row[key] for key in ("clip_id", "asset_id", "timeline_in_seconds", "source_in_seconds", "source_out_seconds", "source_audio_enabled", "audio_link_id")} for row in project["video_track"]]
    pictures = [{key: row[key] for key in ("item_id", "asset_id", "order")} for row in project["picture_track"]]
    linked = {row["audio_link_id"] for row in videos if row["audio_link_id"]}
    audios = [{key: row[key] for key in ("clip_id", "asset_id", "origin", "enabled", "linked_video_clip_id", "source_in_seconds", "source_out_seconds")} for row in project["audio_track"] if row["clip_id"] in linked]
    referenced = {row["asset_id"] for row in videos + pictures + audios}
    assets = sorted(({key: row[key] for key in ("asset_id", "kind", "source_handle", "probe")} for row in project["assets"] if row["asset_id"] in referenced), key=lambda row: row["asset_id"])
    return {"assets": assets, "video_track": videos, "picture_track": pictures, "audio_track": audios, "project_clock": project["project_clock"], "output_canvas": project.get("output_canvas")}


def _source_clips(project, fps):
    assets = {row["asset_id"]: row for row in project["assets"]}
    clips, offset = [], 0
    for clip in project["video_track"]:
        load_start = _frame(clip["source_in_seconds"], fps)
        load_end = _frame(clip["source_out_seconds"], fps)
        frames = max(0, load_end - load_start)
        probe = assets.get(clip["asset_id"], {}).get("probe", {})
        clips.append({
            "clip_id": clip["clip_id"], "asset_id": clip["asset_id"],
            "name": assets.get(clip["asset_id"], {}).get("name", clip["asset_id"]),
            "timeline_in_seconds": clip["timeline_in_seconds"],
            "source_in_seconds": clip["source_in_seconds"], "source_out_seconds": clip["source_out_seconds"],
            "load_start_frame": load_start, "load_end_frame": load_end,
            "frame_count": frames, "output_start_frame": offset, "output_end_frame": offset + frames,
            "source_fps": probe.get("fps"), "source_frame_count_exact": probe.get("frame_count_exact", False),
            "source_audio_enabled": clip["source_audio_enabled"], "audio_link_id": clip["audio_link_id"],
        })
        offset += frames
    pictures = [{**row, "name": assets.get(row["asset_id"], {}).get("name", row["asset_id"])} for row in project["picture_track"]]
    return clips, pictures


def _task_errors(project):
    referenced = {row["asset_id"] for key in ("video_track", "picture_track") for row in project[key]}
    linked = {row["audio_link_id"] for row in project["video_track"] if row["audio_link_id"]}
    result = []
    for issue in project["validation"]["errors"]:
        path = issue["path"]
        if path.startswith("/processing_window"):
            continue
        asset = re.match(r"^/assets/(\d+)(?:/|$)", path)
        if asset and int(asset[1]) < len(project["assets"]) and project["assets"][int(asset[1])]["asset_id"] not in referenced:
            continue
        audio = re.match(r"^/audio_track/(\d+)(?:/|$)", path)
        if audio and int(audio[1]) < len(project["audio_track"]) and project["audio_track"][int(audio[1])]["clip_id"] not in linked:
            continue
        result.append(copy.deepcopy(issue))
    return result


def build_plan(media_project, settings=None, fps=None):
    config = _settings(settings)
    project = _project(media_project)
    errors = _task_errors(project)
    warnings, seen_warnings, estimated_frames = [], set(), False
    for issue in project["validation"]["warnings"]:
        if issue.get("code") == "estimated_frames":
            estimated_frames = True
            continue
        key = (issue.get("code"), issue.get("message"))
        if key not in seen_warnings:
            warnings.append(copy.deepcopy(issue)); seen_warnings.add(key)
    if estimated_frames:
        warnings.append(_issue("/video_track", "estimated_frames", "源帧位置为估算值；分段沿用素材台保存的秒切点，不要求重新对齐"))
    assets = {row["asset_id"]: row for row in project["assets"]}
    first_video = project["video_track"][0] if project["video_track"] else None
    source_fps = assets.get(first_video["asset_id"], {}).get("probe", {}).get("fps") if first_video else None
    fps_origin = "workflow" if fps is not None else "source" if source_fps else "project"
    if fps is None:
        fps = source_fps if source_fps is not None and source_fps > 0 else project["project_clock"]["fps"]
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 0 < fps <= 240:
        raise AnimatePlanError([_issue("/fps", "fps", "工作流帧率必须大于 0 且不超过素材出口支持的 240 fps")])
    fps = _rate(fps)
    if first_video and fps_origin == "project":
        warnings.append(_issue("/fps", "source_fps_unknown", f"首段源帧率未知，暂用素材台工程帧率 {fps:g} fps"))
    clips, pictures = _source_clips(project, fps)
    if any(abs(clip["timeline_in_seconds"] - clip["output_start_frame"] / fps) > 1 / fps for clip in clips):
        warnings.append(_issue("/video_track", "sequential_sources", "视频按素材台左右顺序连续拼接；素材台的空档或不同视频间的重叠不保留"))
    if not clips:
        errors.append(_issue("/video_track", "missing_video", "请先把视频加入素材台视频轨道"))
    for index, clip in enumerate(clips):
        if clip["frame_count"] < 1:
            errors.append(_issue(f"/video_track/{index}", "empty_clip", "视频裁剪范围不足一个目标帧"))
        if clip["source_fps"] is not None and not same_frame_rate(clip["source_fps"], fps):
            warnings.append(_issue(f"/video_track/{index}", "fps_resampled", f"{clip['name']} 源帧率 {clip['source_fps']:g}，将按 {fps} fps 重采样；分段和成片帧数以重采样后的 {clip['frame_count']} 帧为准"))
    if any(row["origin"] == "standalone" and row["enabled"] for row in project["audio_track"]):
        warnings.append(_issue("/audio_track", "standalone_audio_unused", "Animate 仅保留每个视频配对的原声，独立音轨不参与本次拼接"))
    if len(clips) > MAX_SEGMENTS:
        errors.append(_issue("/video_track", "segment_limit", f"视频片段不能超过 {MAX_SEGMENTS} 段"))
    if len(pictures) != len(clips):
        errors.append(_issue("/picture_track", "picture_count_mismatch", f"图片与视频需一一对应：当前 {len(pictures)} 张图片、{len(clips)} 段视频，请在素材台按左右顺序补齐或移除多余图片"))
    segments = []
    for index, clip in enumerate(clips):
        path = f"/segments/{index}"
        picture = pictures[index] if index < len(pictures) else None
        if picture is None:
            errors.append(_issue(path + "/picture_id", "missing_picture", f"第 {index + 1} 段缺少配对图片，请在素材台补齐"))
        frames = clip["frame_count"]
        guide_frames = min(21, clips[index - 1]["frame_count"]) if index and config["seam_mode"] == "continuation_21" else 0
        reference_fps = _rate(clip["source_fps"]) if clip["source_fps"] else fps
        frame_min = _frame(clip["source_in_seconds"], reference_fps)
        frame_max = _frame(clip["source_out_seconds"], reference_fps) - 1
        mask_task = None
        if config["mask_enabled"]:
            task = config["mask_tasks"].get(clip["clip_id"], {})
            frame, prompt = task.get("source_frame"), task.get("prompt", "")
            if task.get("asset_id") != clip["asset_id"]:
                errors.append(_issue(path + "/mask_task", "mask_source_changed", f"第 {index + 1} 段：请填写当前视频的遮罩目标词和参考帧"))
            if not isinstance(prompt, str) or not prompt.strip():
                errors.append(_issue(path + "/mask_task/prompt", "mask_prompt_missing", f"第 {index + 1} 段：请填写遮罩目标词"))
            if type(frame) is not int or not frame_min <= frame <= frame_max:
                errors.append(_issue(path + "/mask_task/source_frame", "mask_frame_range", f"第 {index + 1} 段：原视频源帧需在 {frame_min + 1}–{frame_max + 1}（同素材台，从 1 起），不会自动移动参考帧或切点"))
            else:
                local_index = _frame(frame / reference_fps, fps) - clip["load_start_frame"]
                if not 0 <= local_index < frames:
                    errors.append(_issue(path + "/mask_task/source_frame", "mask_frame_resample", f"第 {index + 1} 段：参考帧经原流帧率换算后不在本段，请重新选帧"))
                mask_task = {"asset_id": clip["asset_id"], "source_frame": frame,
                             "source_fps": reference_fps, "local_index": local_index,
                             "prompt": prompt.strip() if isinstance(prompt, str) else ""}
        segments.append({
            "segment_id": f"segment-{index + 1:04d}", "clip_id": clip["clip_id"], "ordinal": index + 1,
            "start_frame": 0, "end_frame": frames, "effective_end_frame": frames, "frame_count": frames,
            "picture_id": picture["item_id"] if picture else None, "picture_asset_id": picture["asset_id"] if picture else None,
            "video_asset_id": clip["asset_id"], "source_in_seconds": clip["source_in_seconds"],
            "source_start_seconds": clip["source_in_seconds"], "source_end_seconds": clip["source_out_seconds"],
            "load_start_frame": clip["load_start_frame"], "load_end_frame": clip["load_end_frame"],
            "source_audio_enabled": clip["source_audio_enabled"], "audio_link_id": clip["audio_link_id"],
            "global_start_frame": clip["output_start_frame"], "global_end_frame": clip["output_end_frame"],
            "guide_frame_count": guide_frames, "contribution_start_frame": 0,
            "contribution_end_frame": frames, "output_start_frame": clip["output_start_frame"],
            "output_end_frame": clip["output_end_frame"],
            "mask_task": mask_task, "mask_frame_min": frame_min, "mask_frame_max": frame_max,
            "mask_reference_fps": reference_fps,
        })
    plan = {
        "schema_version": 1, "settings": config, "media_project": project,
        "source_fingerprint": _hash(_source_facts(project)), "fps": fps, "fps_origin": fps_origin,
        "source_clips": clips, "pictures": pictures, "segments": segments,
        "target_frame_count": sum(row["frame_count"] for row in clips),
        "validation": {"ready": not errors, "errors": errors, "warnings": warnings},
    }
    plan["plan_fingerprint"] = _hash({"source": _source_facts(project), "fps": fps, "settings": config, "segments": segments})
    return plan


def normalize_plan(value):
    if not isinstance(value, dict) or value.get("schema_version") != 1 or type(value.get("schema_version")) is not int:
        raise AnimatePlanError([_issue("/schema_version", "schema_version", "不支持的 Animate 计划版本")])
    if not isinstance(value.get("settings"), dict) or not isinstance(value.get("media_project"), dict):
        raise AnimatePlanError([_issue("", "plan", "Animate 计划缺少素材或衔接设置")])
    if value.get("fps_origin") not in ("workflow", "source", "project"):
        raise AnimatePlanError([_issue("/fps_origin", "fps_origin", "Animate 计划缺少帧率来源")])
    rebuilt = build_plan(value["media_project"], value["settings"], value.get("fps") if value["fps_origin"] == "workflow" else None)
    if value.get("plan_fingerprint") != rebuilt["plan_fingerprint"] or value.get("segments") != rebuilt["segments"]:
        raise AnimatePlanError([_issue("/plan_fingerprint", "plan_changed", "分段计划已变化，请重新生成计划")])
    return rebuilt
