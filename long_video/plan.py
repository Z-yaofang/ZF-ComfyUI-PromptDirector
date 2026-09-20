import copy
import hashlib
import json
import math
import re

from ..h3_focus.routing import model_frame_count
from ..media_evidence.contract import ProjectError, normalize_project
from ..media_evidence.presets import builtin


MAX_SEGMENTS = 4096
H3_MIN_REFERENCE_FRAMES = 48
SEGMENT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


class SegmentPlanError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("Invalid long-video segment plan")


def _issue(path, code, message):
    return {"path": path, "code": code, "message": message}


def default_settings():
    return {
        "schema_version": 1,
        "mode": "source_auto",
        "fps": 24,
        "segment_frames": 360,
        "overlap_frames": 48,
        "overlap_alignment": "h3_guide",
        "segment_count": 1,
        "segments": [],
        "range_start_frame": None,
        "range_end_frame": None,
        "source_snapshot": None,
        "source_fingerprint": None,
        "refresh_sources": False,
    }


def _json_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mechanical_project(project):
    referenced = {
        item["asset_id"]
        for track in ("picture_track", "video_track", "audio_track")
        for item in project.get(track, [])
    }
    assets = []
    for asset in project.get("assets", []):
        if asset.get("asset_id") in referenced:
            assets.append({key: copy.deepcopy(asset.get(key)) for key in ("asset_id", "kind", "source_handle", "probe")})
    assets.sort(key=lambda row: row["asset_id"])
    result = {
        "schema_version": project.get("schema_version"),
        "assets": assets,
        "picture_track": [{key: item.get(key) for key in ("item_id", "asset_id", "order")} for item in project.get("picture_track", [])],
        "video_track": [{key: item.get(key) for key in ("clip_id", "asset_id", "timeline_in_seconds", "source_in_seconds", "source_out_seconds", "source_audio_enabled", "audio_link_id")} for item in project.get("video_track", [])],
        "audio_track": [{key: item.get(key) for key in ("clip_id", "asset_id", "timeline_in_seconds", "source_in_seconds", "source_out_seconds", "origin", "enabled", "linked_video_clip_id", "source_video_clip_id")} for item in project.get("audio_track", [])],
    }
    if "output_canvas" in project:
        result["output_canvas"] = copy.deepcopy(project["output_canvas"])
    return result


def project_fingerprint(project):
    return _json_hash(_mechanical_project(normalize_project(project)))


def canonical_task_project(project, store):
    """Recheck only media referenced by the three tracks against the registry."""
    if isinstance(project, dict):
        referenced = {
            row.get("asset_id")
            for key in ("picture_track", "video_track", "audio_track")
            for row in project.get(key, []) if isinstance(row, dict)
        }
        assets = project.get("assets", []) if isinstance(project.get("assets"), list) else []
        inherited = []
        validation = project.get("validation") if isinstance(project.get("validation"), dict) else {}
        for row in validation.get("errors", []) if isinstance(validation.get("errors"), list) else []:
            if not isinstance(row, dict) or row.get("code") != "source_unavailable":
                continue
            match = re.match(r"^/assets/(\d+)(?:/|$)", str(row.get("path", "")))
            if match and int(match.group(1)) < len(assets) and assets[int(match.group(1))].get("asset_id") in referenced:
                inherited.append(_issue(
                    row.get("path", "/assets"), "source_unavailable",
                    "已上轨素材原文件丢失或改变，请重新导入",
                ))
        if inherited:
            raise SegmentPlanError(inherited)
    value = normalize_project(project)
    referenced = {row["asset_id"] for key in ("picture_track", "video_track", "audio_track") for row in value[key]}
    value["assets"] = [row for row in value["assets"] if row["asset_id"] in referenced]
    canonical = store.canonical(value)
    unavailable = [row for row in canonical["validation"]["errors"] if row["code"] == "source_unavailable"]
    if unavailable:
        raise SegmentPlanError([_issue(row["path"], row["code"], "已上轨素材原文件丢失或改变，请重新导入") for row in unavailable])
    return canonical


def _require_integer(value, path, minimum=None, maximum=None):
    if type(value) is not int or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        limit = "整数"
        if minimum is not None:
            limit += f"且不小于 {minimum}"
        if maximum is not None:
            limit += f"、不大于 {maximum}"
        raise SegmentPlanError([_issue(path, "integer", f"必须是{limit}")])
    return value


def _settings(value):
    if not isinstance(value, dict):
        raise SegmentPlanError([_issue("/settings", "type", "分段设置必须是 JSON 对象")])
    result = default_settings()
    unknown = sorted(set(value) - set(result))
    if unknown:
        raise SegmentPlanError([_issue("/settings", "unknown_field", "未知分段设置字段：" + "、".join(unknown))])
    result.update(copy.deepcopy(value))
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise SegmentPlanError([_issue("/settings/schema_version", "schema_version", "不支持的分段设置版本")])
    if result["mode"] not in ("source_auto", "source_manual", "generation_count", "generation_manual"):
        raise SegmentPlanError([_issue("/settings/mode", "mode", "请选择自动源分段、手工源分段、按段数生成或手工生成分段")])
    _require_integer(result["fps"], "/settings/fps", 1, 240)
    _require_integer(result["segment_frames"], "/settings/segment_frames", 1, 1000000)
    _require_integer(result["overlap_frames"], "/settings/overlap_frames", 0, 999999)
    _require_integer(result["segment_count"], "/settings/segment_count", 1, MAX_SEGMENTS)
    if result["overlap_alignment"] not in ("exact", "h3_guide"):
        raise SegmentPlanError([_issue("/settings/overlap_alignment", "overlap_alignment", "重叠对齐策略必须是 exact 或 h3_guide")])
    if type(result["refresh_sources"]) is not bool:
        raise SegmentPlanError([_issue("/settings/refresh_sources", "type", "刷新素材必须是布尔值")])
    if not isinstance(result["segments"], list) or len(result["segments"]) > MAX_SEGMENTS:
        raise SegmentPlanError([_issue("/settings/segments", "segments", f"手工分段必须是至多 {MAX_SEGMENTS} 项的数组")])
    for key in ("range_start_frame", "range_end_frame"):
        if result[key] is not None:
            _require_integer(result[key], "/settings/" + key, 0, 2147483647)
    if result["source_snapshot"] is not None and not isinstance(result["source_snapshot"], dict):
        raise SegmentPlanError([_issue("/settings/source_snapshot", "type", "冻结素材快照必须是素材工程对象")])
    if result["source_fingerprint"] is not None and (not isinstance(result["source_fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", result["source_fingerprint"])):
        raise SegmentPlanError([_issue("/settings/source_fingerprint", "fingerprint", "素材指纹格式无效")])
    if result["source_snapshot"] is not None and result["source_fingerprint"] is None and not result["refresh_sources"]:
        raise SegmentPlanError([_issue("/settings/source_fingerprint", "missing_fingerprint", "旧冻结副本缺少来源指纹，请显式刷新素材")])
    return result


def _target_track_snapshot(project, fps):
    pictures = [{"item_id": item["item_id"], "asset_id": item["asset_id"], "order": item["order"]} for item in project["picture_track"]]
    tracks = {"pictures": pictures, "video": [], "audio": []}
    for kind in ("video", "audio"):
        for clip in project[kind + "_track"]:
            timeline_in = math.floor(clip["timeline_in_seconds"] * fps + .5)
            duration = math.floor((clip["source_out_seconds"] - clip["source_in_seconds"]) * fps + .5)
            source_in = math.floor(clip["source_in_seconds"] * fps + .5)
            row = {
                "clip_id": clip["clip_id"],
                "asset_id": clip["asset_id"],
                "timeline_in_frame": timeline_in,
                "timeline_out_frame": timeline_in + duration,
                "source_in_frame": source_in,
                "source_out_frame": source_in + duration,
                "source_in_seconds": clip["source_in_seconds"],
                "source_out_seconds": clip["source_out_seconds"],
            }
            if kind == "video":
                row.update(source_audio_enabled=clip["source_audio_enabled"], audio_link_id=clip["audio_link_id"])
            else:
                row.update(origin=clip["origin"], enabled=clip["enabled"], linked_video_clip_id=clip["linked_video_clip_id"], source_video_clip_id=clip["source_video_clip_id"])
            tracks[kind].append(row)
    return tracks


def _effective_overlap(requested, alignment):
    if alignment == "exact":
        return requested
    if requested < 1:
        raise SegmentPlanError([_issue("/settings/overlap_frames", "overlap", "H3 Guide 请求重叠至少为 1 帧")])
    return 1 if requested < 5 else 5 + 17 * ((requested - 5) // 17)


def _model_padding(frames, alignment):
    if alignment != "h3_guide":
        return {"adapter": "none", "requested_frames": frames, "model_length": None, "predicted_final_frames": None, "actual_final_frames": None}
    length = model_frame_count(frames)
    return {"adapter": "h3", "requested_frames": frames, "model_length": length, "predicted_final_frames": length, "actual_final_frames": None}


def _source_range(tracks, settings):
    enabled_audio = [row for row in tracks["audio"] if row["enabled"]]
    timed = tracks["video"] + enabled_audio
    inferred_start = min((row["timeline_in_frame"] for row in timed), default=0)
    inferred_end = max((row["timeline_out_frame"] for row in timed), default=0)
    start = inferred_start if settings["range_start_frame"] is None else settings["range_start_frame"]
    end = inferred_end if settings["range_end_frame"] is None else settings["range_end_frame"]
    return start, end


def _task_project(project, range_start, range_end, fps):
    """Validate frozen tracks under the segment desk's own processing window."""
    result = copy.deepcopy(project)
    referenced = {row["asset_id"] for key in ("picture_track", "video_track", "audio_track") for row in result[key]}
    result["assets"] = [row for row in result["assets"] if row["asset_id"] in referenced]
    result["processing_window"] = {
        "start_seconds": range_start / fps,
        "end_seconds": max(range_start + 1, range_end) / fps,
        "fps": fps,
    }
    result["processing_preset"] = builtin("builtin.generic")
    return normalize_project(result)


def _manual_windows(rows):
    result = []
    seen = set()
    for index, row in enumerate(rows):
        path = f"/settings/segments/{index}"
        if not isinstance(row, dict):
            raise SegmentPlanError([_issue(path, "type", "每个手工分段必须是对象")])
        segment_id = row.get("segment_id")
        if not isinstance(segment_id, str) or not SEGMENT_ID.fullmatch(segment_id) or segment_id in seen:
            raise SegmentPlanError([_issue(path + "/segment_id", "segment_id", "分段 ID 必须合法且唯一")])
        seen.add(segment_id)
        start = _require_integer(row.get("start_frame"), path + "/start_frame", 0, 2147483647)
        end = _require_integer(row.get("end_frame"), path + "/end_frame", 0, 2147483647)
        result.append((segment_id, start, end))
    return sorted(result, key=lambda row: (row[1], row[2], row[0]))


def _segment_ids(settings, count):
    hints = sorted(
        (row for row in settings["segments"] if isinstance(row, dict)),
        key=lambda row: (
            row.get("start_frame") if type(row.get("start_frame")) is int else 2147483647,
            row.get("end_frame") if type(row.get("end_frame")) is int else 2147483647,
            row.get("segment_id") if isinstance(row.get("segment_id"), str) else "",
        ),
    )
    result = []
    used = set()
    for index in range(count):
        value = hints[index].get("segment_id") if index < len(hints) and isinstance(hints[index], dict) else None
        if not isinstance(value, str) or not SEGMENT_ID.fullmatch(value) or value in used:
            ordinal = index + 1
            value = f"segment-{ordinal:04d}"
            while value in used:
                ordinal += 1
                value = f"segment-{ordinal:04d}"
        result.append(value)
        used.add(value)
    return result


def _auto_windows(settings, start, end, overlap):
    length = settings["segment_frames"]
    stride = length - overlap
    if stride <= 0:
        raise SegmentPlanError([_issue("/settings/overlap_frames", "overlap", "实际重叠必须小于单段帧数")])
    total = end - start
    count = max(1, math.ceil(max(0, total - overlap) / stride))
    if count > MAX_SEGMENTS:
        raise SegmentPlanError([_issue("/settings/segment_frames", "segment_limit", f"自动分段将产生 {count} 段，超过上限 {MAX_SEGMENTS}")])
    ids = _segment_ids(settings, count)
    return [(ids[index], start + index * stride, start + index * stride + length) for index in range(count)]


def _rebalance_h3_auto_tail(windows, range_start, range_end, errors):
    """Borrow source clock from the prior call when the final H3 call is tiny."""
    if not windows:
        return windows
    result = list(windows)
    segment_id, start, end = result[-1]
    real_count = max(0, min(end, range_end) - max(start, range_start))
    if real_count >= H3_MIN_REFERENCE_FRAMES:
        return result
    deficit = H3_MIN_REFERENCE_FRAMES - real_count
    if len(result) < 2:
        errors.append(_issue(
            "/segments/0/source_slices/video", "h3_reference_video_frames",
            f"H3 源视频分段至少需要 {H3_MIN_REFERENCE_FRAMES} 个真实参考帧；当前只有 {real_count} 帧",
        ))
        return result
    previous_id, previous_start, previous_end = result[-2]
    shifted_previous_end = previous_end - deficit
    shifted_start, shifted_end = start - deficit, end - deficit
    if (
        shifted_previous_end - previous_start < H3_MIN_REFERENCE_FRAMES
        or shifted_start < range_start
        or shifted_end <= shifted_start
    ):
        errors.append(_issue(
            f"/segments/{len(result)-1}/source_slices/video", "h3_reference_video_frames",
            f"末段只有 {real_count} 个真实参考帧，且上一段无法借出 {deficit} 帧；请调整单段长度或任务范围",
        ))
        return result
    result[-2] = (previous_id, previous_start, shifted_previous_end)
    result[-1] = (segment_id, shifted_start, shifted_end)
    return result


def _generation_windows(settings, start, overlap):
    length = settings["segment_frames"]
    stride = length - overlap
    if stride <= 0:
        raise SegmentPlanError([_issue("/settings/overlap_frames", "overlap", "实际重叠必须小于单段帧数")])
    ids = _segment_ids(settings, settings["segment_count"])
    return [(ids[index], start + index * stride, start + index * stride + length) for index in range(settings["segment_count"])]


def _slices(tracks, start, end, fps):
    result = {"pictures": copy.deepcopy(tracks["pictures"]), "video": [], "audio": []}
    for kind in ("video", "audio"):
        for clip in tracks[kind]:
            if kind == "audio" and not clip["enabled"]:
                continue
            left = max(start, clip["timeline_in_frame"])
            right = min(end, clip["timeline_out_frame"])
            if right <= left:
                continue
            row = {
                "clip_id": clip["clip_id"],
                "asset_id": clip["asset_id"],
                "timeline_in_frame": left,
                "timeline_out_frame": right,
                "segment_in_frame": left - start,
                "segment_out_frame": right - start,
                "source_in_frame": clip["source_in_frame"] + left - clip["timeline_in_frame"],
                "source_out_frame": clip["source_in_frame"] + right - clip["timeline_in_frame"],
                "source_in_seconds": clip["source_in_seconds"] + (left - clip["timeline_in_frame"]) / fps,
                "source_out_seconds": min(clip["source_out_seconds"], clip["source_in_seconds"] + (right - clip["timeline_in_frame"]) / fps),
            }
            result[kind].append(row)
    return result


def _coverage_errors(tracks, start, end):
    intervals = sorted((max(start, row["timeline_in_frame"]), min(end, row["timeline_out_frame"])) for row in tracks["video"] if row["timeline_out_frame"] > start and row["timeline_in_frame"] < end)
    errors = []
    cursor = start
    for left, right in intervals:
        if left > cursor:
            errors.append(_issue("/media_project/video_track", "video_gap", f"视频轨在目标帧 {cursor}–{left} 没有素材"))
        cursor = max(cursor, right)
    if cursor < end:
        errors.append(_issue("/media_project/video_track", "video_gap", f"视频轨在目标帧 {cursor}–{end} 没有素材"))
    return errors


def _segments(windows, tracks, range_start, range_end, mode, alignment, fps, errors):
    result = []
    previous_end = None
    for index, (segment_id, start, end) in enumerate(windows):
        path = f"/segments/{index}"
        if end <= start:
            errors.append(_issue(path, "segment_range", "分段结束帧必须大于开始帧"))
        overlap = 0 if previous_end is None else max(0, previous_end - start)
        if previous_end is None:
            seam = "first"
        elif start < previous_end:
            seam = "guide"
        else:
            seam = "hard_cut"
            if start > previous_end:
                errors.append(_issue(path, "segment_gap", f"分段之间漏选了 {start - previous_end} 帧"))
        if overlap >= end - start:
            errors.append(_issue(path, "overlap", "重叠不能覆盖整个当前分段"))
        if overlap and alignment == "h3_guide" and overlap != (1 if overlap < 5 else 5 + 17 * ((overlap - 5) // 17)):
            errors.append(_issue(path + "/overlap_frames", "overlap_grid", f"实际重叠 {overlap} 帧不符合 H3 Guide 网格"))
        contribution_start = max(range_start, start + overlap)
        contribution_end = min(end, range_end)
        if contribution_end < contribution_start:
            errors.append(_issue(path, "segment_covered", "当前分段完全被前一段重叠或尾部补帧覆盖"))
            contribution_end = contribution_start
        frame_count = max(0, end - start)
        result.append({
            "segment_id": segment_id,
            "order": index + 1,
            "start_frame": start,
            "end_frame": end,
            "frame_count": frame_count,
            "overlap_frames": overlap,
            "seam": seam,
            "output_start_frame": contribution_start - range_start,
            "output_end_frame": contribution_end - range_start,
            "output_frame_count": max(0, contribution_end - contribution_start),
            "tail_padding_frames": max(0, end - range_end),
            "model_padding": _model_padding(frame_count, alignment),
            "source_slices": _slices(tracks, start, min(end, range_end), fps),
        })
        previous_end = end
    return result


def build_segment_plan(media_project, settings):
    config = _settings(settings)
    try:
        upstream = normalize_project(media_project)
    except ProjectError as error:
        raise SegmentPlanError([_issue("/media_project" + row["path"], row["code"], row["message"]) for row in error.errors]) from None
    upstream_fingerprint = _json_hash(_mechanical_project(upstream))
    if config["refresh_sources"] or config["source_snapshot"] is None:
        snapshot = copy.deepcopy(upstream)
        source_fingerprint = upstream_fingerprint
    else:
        try:
            snapshot = normalize_project(config["source_snapshot"])
        except ProjectError as error:
            raise SegmentPlanError([_issue("/settings/source_snapshot" + row["path"], row["code"], row["message"]) for row in error.errors]) from None
        source_fingerprint = config["source_fingerprint"] or upstream_fingerprint
    stale = source_fingerprint != upstream_fingerprint
    snapshot_fingerprint = _json_hash(_mechanical_project(snapshot))
    tracks = _target_track_snapshot(snapshot, config["fps"])
    range_start, range_end = _source_range(tracks, config)
    errors = []
    warnings = []
    task_upstream = _task_project(upstream, range_start, range_end, config["fps"])
    task_snapshot = _task_project(snapshot, range_start, range_end, config["fps"])
    errors.extend(copy.deepcopy(task_upstream["validation"]["errors"]))
    errors.extend(_issue("/settings/source_snapshot" + row["path"], row["code"], row["message"]) for row in task_snapshot["validation"]["errors"])
    warnings.extend(copy.deepcopy(task_snapshot["validation"]["warnings"]))
    if stale:
        errors.append(_issue("/source_fingerprint", "source_stale", "上游素材已变化；当前分段仍使用冻结副本，请显式刷新素材"))
    overlap = _effective_overlap(config["overlap_frames"], config["overlap_alignment"])
    if config["mode"] == "generation_count":
        range_start = 0 if config["range_start_frame"] is None else config["range_start_frame"]
        windows = _generation_windows(config, range_start, overlap)
        range_end = windows[-1][2] if windows else range_start
    elif config["mode"] == "generation_manual":
        windows = _manual_windows(config["segments"])
        if not windows:
            errors.append(_issue("/settings/segments", "segments_empty", "手工生成分段至少需要一段"))
            range_start = 0 if config["range_start_frame"] is None else config["range_start_frame"]
            range_end = range_start if config["range_end_frame"] is None else config["range_end_frame"]
        else:
            range_start = windows[0][1] if config["range_start_frame"] is None else config["range_start_frame"]
            range_end = max(row[2] for row in windows) if config["range_end_frame"] is None else config["range_end_frame"]
            if windows[0][1] > range_start:
                errors.append(_issue("/segments/0", "segment_gap", f"开头漏选了 {windows[0][1] - range_start} 帧"))
            elif windows[0][1] < range_start:
                errors.append(_issue("/segments/0", "range_start", "第一段不能早于目标范围"))
            if windows[-1][2] < range_end:
                errors.append(_issue(f"/segments/{len(windows)-1}", "segment_gap", f"结尾漏选了 {range_end - windows[-1][2]} 帧"))
    else:
        if range_end <= range_start:
            errors.append(_issue("/range_end_frame", "source_range", "源分段需要非空的视频时间范围"))
        errors.extend(_coverage_errors(tracks, range_start, range_end))
        if config["mode"] == "source_auto":
            windows = _auto_windows(config, range_start, range_end, overlap)
            if config["overlap_alignment"] == "h3_guide":
                windows = _rebalance_h3_auto_tail(windows, range_start, range_end, errors)
        else:
            windows = _manual_windows(config["segments"])
            if not windows:
                errors.append(_issue("/settings/segments", "segments_empty", "手工分段至少需要一段"))
            elif windows[0][1] > range_start:
                errors.append(_issue("/segments/0", "segment_gap", f"开头漏选了 {windows[0][1] - range_start} 帧"))
            elif windows[0][1] < range_start:
                errors.append(_issue("/segments/0", "range_start", "第一段不能早于任务范围"))
            if windows and windows[-1][2] < range_end:
                errors.append(_issue(f"/segments/{len(windows)-1}", "segment_gap", f"结尾漏选了 {range_end - windows[-1][2]} 帧"))
    if range_end <= range_start:
        errors.append(_issue("/range_end_frame", "source_range", "长视频目标范围必须至少包含一帧"))
    segments = _segments(windows, tracks, range_start, range_end, config["mode"], config["overlap_alignment"], config["fps"], errors)
    if config["mode"] == "source_auto" and config["overlap_alignment"] == "h3_guide":
        for segment_index, segment in enumerate(segments):
            real_count = segment["frame_count"] - segment["tail_padding_frames"]
            if real_count < H3_MIN_REFERENCE_FRAMES and not any(
                row["code"] == "h3_reference_video_frames" and row["path"].startswith(f"/segments/{segment_index}")
                for row in errors
            ):
                errors.append(_issue(
                    f"/segments/{segment_index}/source_slices/video", "h3_reference_video_frames",
                    f"H3 源视频分段至少需要 {H3_MIN_REFERENCE_FRAMES} 个真实参考帧；当前只有 {real_count} 帧",
                ))
            for slice_index, source_slice in enumerate(segment["source_slices"]["video"]):
                frames = source_slice["timeline_out_frame"] - source_slice["timeline_in_frame"]
                if frames < H3_MIN_REFERENCE_FRAMES:
                    errors.append(_issue(
                        f"/segments/{segment_index}/source_slices/video/{slice_index}",
                        "h3_reference_video_frames",
                        f"H3 单个参考视频切片至少需要 {H3_MIN_REFERENCE_FRAMES} 帧；当前只有 {frames} 帧，请调整分段或素材切点",
                    ))
    target_frame_count = max(0, range_end - range_start)
    identity = {"source_fingerprint": source_fingerprint, "mode": config["mode"]}
    plan = {
        "schema_version": 1,
        "plan_id": "segment-plan-" + _json_hash(identity)[:16],
        "revision": "",
        "mode": config["mode"],
        "fps": config["fps"],
        "range_start_frame": range_start,
        "target_frame_count": target_frame_count,
        "requested_overlap_frames": config["overlap_frames"],
        "effective_overlap_frames": overlap,
        "overlap_alignment": config["overlap_alignment"],
        "source_fingerprint": source_fingerprint,
        "snapshot_fingerprint": snapshot_fingerprint,
        "upstream_fingerprint": upstream_fingerprint,
        "stale": stale,
        "media_project": snapshot,
        "source_tracks": tracks,
        "segments": segments,
        "validation": {"ready": not errors, "errors": errors, "warnings": warnings},
    }
    revision_source = {
        key: copy.deepcopy(plan[key])
        for key in (
            "schema_version", "mode", "fps", "range_start_frame", "target_frame_count",
            "requested_overlap_frames", "effective_overlap_frames", "overlap_alignment",
            "snapshot_fingerprint", "source_tracks", "segments",
        )
    }
    plan["revision"] = _json_hash(revision_source)
    return plan


def segment_project(plan, segment_id):
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise SegmentPlanError([_issue("/plan", "schema_version", "需要 ZV 分段计划 v1")])
    segment = next((row for row in plan.get("segments", []) if row.get("segment_id") == segment_id), None)
    if segment is None:
        raise SegmentPlanError([_issue("/segment_id", "missing_segment", "分段计划中不存在该 segment_id")])
    project = copy.deepcopy(plan["media_project"])
    fps = plan["fps"]
    originals = {
        "picture": {row["item_id"]: row for row in project["picture_track"]},
        "video": {row["clip_id"]: row for row in project["video_track"]},
        "audio": {row["clip_id"]: row for row in project["audio_track"]},
    }
    project["picture_track"] = [copy.deepcopy(originals["picture"][row["item_id"]]) for row in segment["source_slices"]["pictures"] if row["item_id"] in originals["picture"]]
    for kind in ("video", "audio"):
        clips = []
        for row in segment["source_slices"][kind]:
            original = originals[kind].get(row["clip_id"])
            if original is None:
                continue
            clip = copy.deepcopy(original)
            clip["timeline_in_seconds"] = row["segment_in_frame"] / fps
            clip["source_in_seconds"] = row["source_in_seconds"]
            clip["source_out_seconds"] = row["source_out_seconds"]
            clips.append(clip)
        project[kind + "_track"] = clips
    video_ids = {row["clip_id"] for row in project["video_track"]}
    audio_ids = {row["clip_id"] for row in project["audio_track"]}
    for video in project["video_track"]:
        if video["audio_link_id"] not in audio_ids:
            video["audio_link_id"] = None
            video["source_audio_enabled"] = False
    project["audio_track"] = [row for row in project["audio_track"] if row["linked_video_clip_id"] is None or row["linked_video_clip_id"] in video_ids]
    used_assets = {row["asset_id"] for key in ("picture_track", "video_track", "audio_track") for row in project[key]}
    project["assets"] = [row for row in project["assets"] if row["asset_id"] in used_assets]
    project["processing_window"] = {"start_seconds": 0, "end_seconds": segment["frame_count"] / fps, "fps": fps}
    # Each execution row is one H3 call even when the long-video layout itself
    # uses exact overlaps. Do not carry an auto-segment preset into that call.
    project["processing_preset"] = builtin("builtin.minimax-h3.single")
    return normalize_project(project)
