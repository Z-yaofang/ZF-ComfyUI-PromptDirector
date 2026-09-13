"""Stable track-item bindings and media windows, without file IO or decoders."""

from .contract import ProjectError, normalize_project, seconds_to_frame

SAMPLE_RATE = 44100
MAX_OUTPUT_SECONDS = 600
MAX_VIDEO_FRAMES = 8192
# A complete H3 window at the very common 1080x1920 reference resolution is
# about 8.35 GiB as ComfyUI's float32 IMAGE tensor (360 frames * RGB).  The old
# 4 GiB guard therefore rejected an otherwise valid 15 s / 24 fps H3 input
# before decoding started.  Keep a finite guard, but make it large enough for
# that supported window; 4K reference batches remain rejected.
MAX_OUTPUT_GIB = 12
MAX_OUTPUT_BYTES = MAX_OUTPUT_GIB * 1024 ** 3


class OutletError(ValueError):
    pass


def require_valid_project(project):
    errors = project["validation"]["errors"]
    if not errors:
        return
    messages = {
        "source_unavailable": "素材原文件已丢失或修改，请重新导入",
        "missing_asset": "绑定素材已不存在",
        "track_kind": "轨道中的素材种类不正确",
        "source_window": "片段源窗口越界或没有有效时长",
        "window_range": "处理窗口结束必须大于开始",
        "timeline_limit": "轨道范围超过工程时长上限",
        "duplicate_id": "轨道项或素材 ID 重复",
        "audio_link": "视频和原声音频的绑定关系无效",
        "missing_audio_link": "已启用视频原声，但缺少绑定音频",
        "no_source_audio": "已启用视频原声，但源文件没有音频",
    }
    reasons = list(dict.fromkeys(messages.get(error["code"], "工程字段、来源或裁剪关系无效") for error in errors))
    raise OutletError("素材出口无法执行：" + "；".join(reasons))


def _intersection(clip, window):
    start = max(window["start_seconds"], clip["timeline_in_seconds"])
    end = min(window["end_seconds"], clip["timeline_in_seconds"] + clip["source_out_seconds"] - clip["source_in_seconds"])
    return {"start_seconds": start, "end_seconds": end} if end > start else None


def _entry(item, asset, label, kind, intersection=None, fps=None):
    probe = asset["probe"]
    result = {
        "kind": kind, "label": label, "item_id": item.get("item_id"), "clip_id": item.get("clip_id"),
        "asset_id": item["asset_id"], "source_handle": asset["source_handle"],
        "project_window": intersection, "source_window": None, "requested_source_window": None,
        "target_fps": None, "frame_count": None, "sample_rate": None, "sample_count": None,
        "output_duration_seconds": None, "source_duration_seconds": probe["duration_seconds"],
        "source_width": probe["width"], "source_height": probe["height"],
        "output_width": probe["width"] if kind in ("picture", "video") else None,
        "output_height": probe["height"] if kind in ("picture", "video") else None,
        "resize_during_decode": False, "resize_method": None, "fit_mode": None,
        "source_channels": probe["channels"], "source_vfr": probe["vfr"],
    }
    if intersection is None:
        return result
    duration = intersection["end_seconds"] - intersection["start_seconds"]
    start = item["source_in_seconds"] + intersection["start_seconds"] - item["timeline_in_seconds"]
    result["requested_source_window"] = {"start_seconds": start, "end_seconds": start + duration}
    if kind == "video":
        count = seconds_to_frame(duration, fps)
        if count < 1:
            raise OutletError("绑定视频与处理窗口的交集不足一个目标帧，请扩大处理范围")
        if count > MAX_VIDEO_FRAMES:
            raise OutletError(f"单个视频出口最多 {MAX_VIDEO_FRAMES} 帧，请缩小处理窗口")
        result.update(target_fps=fps, frame_count=count)
        duration = count / fps
    else:
        count = seconds_to_frame(duration, SAMPLE_RATE)
        if count < 1:
            raise OutletError("绑定音频与处理窗口的交集不足一个采样点，请扩大处理范围")
        result.update(sample_rate=SAMPLE_RATE, sample_count=count)
    result.update(source_window={"start_seconds": start, "end_seconds": start + duration}, output_duration_seconds=duration)
    return result


def _video_target_size(target_width, target_height):
    """Validate an optional consumer canvas without guessing orientation or size."""
    if target_width is None and target_height is None:
        return None
    if target_width is None or target_height is None:
        raise OutletError("目标宽度和目标高度必须同时连接，不能只指定一个尺寸")
    if type(target_width) is not int or type(target_height) is not int:
        raise OutletError("目标宽度和目标高度必须是整数")
    if not 32 <= target_width <= 16384 or not 32 <= target_height <= 16384:
        raise OutletError("目标宽度和目标高度必须在 32–16384 像素之间")
    if target_width % 32 or target_height % 32:
        raise OutletError("H3 目标宽度和目标高度必须是 32 的倍数")
    if target_width * target_height > 50_000_000:
        raise OutletError("目标画布像素数超出素材出口支持范围")
    return (target_width, target_height)


def estimate_plan_output_bytes(plan):
    """Estimate resident tensor bytes produced by one decoded outlet plan."""
    estimated = 0
    items = list(plan.get("items", []))
    if plan.get("original_audio"):
        items.append(plan["original_audio"])
    for entry in items:
        if entry["kind"] in ("picture", "video"):
            estimated += entry["output_width"] * entry["output_height"] * 3 * 4 * (entry["frame_count"] or 1)
        else:
            estimated += entry["sample_count"] * 2 * 4
    return estimated


def require_combined_output_budget(plans, *, label="多个素材出口"):
    """Reject a bank whose simultaneously resident tensors exceed the guard."""
    estimated = sum(estimate_plan_output_bytes(plan) for plan in plans)
    if estimated > MAX_OUTPUT_BYTES:
        raise OutletError(
            f"{label}预计张量合计超过 {MAX_OUTPUT_GIB} GiB，"
            "请在素材台连接较小的统一宽高，或减少本次参考视频/处理时长"
        )
    return estimated


def _check_size(plan):
    if plan["kind"] == "timeline_audio":
        if plan["window"]["end_seconds"] - plan["window"]["start_seconds"] > MAX_OUTPUT_SECONDS:
            raise OutletError(f"单次时间线混音最多 {MAX_OUTPUT_SECONDS} 秒，请缩小处理窗口")
        return
    for entry in plan["items"] + ([plan["original_audio"]] if plan["original_audio"] else []):
        if (entry["output_duration_seconds"] or 0) > MAX_OUTPUT_SECONDS:
            raise OutletError(f"单次素材出口最多 {MAX_OUTPUT_SECONDS} 秒，请缩小处理窗口")
        if entry["kind"] in ("picture", "video"):
            if not entry["source_width"] or not entry["source_height"]:
                raise OutletError("图片或视频缺少有效尺寸，请重新导入素材")
    estimated = estimate_plan_output_bytes(plan)
    if estimated > MAX_OUTPUT_BYTES:
        raise OutletError(
            f"单次素材出口预计张量超过 {MAX_OUTPUT_GIB} GiB，"
            "请缩小处理窗口或使用较小的原始素材"
        )


def build_outlet_plan(project, kind, binding_id=None, target_width=None, target_height=None):
    if kind not in ("picture", "video", "audio", "timeline_audio"):
        raise OutletError("不支持的素材出口类型")
    explicit_target = target_width is not None or target_height is not None
    target_size = _video_target_size(target_width, target_height) if kind == "video" and explicit_target else None
    try:
        p = normalize_project(project)
    except ProjectError:
        raise OutletError("素材工程结构、处理窗口或目标帧率无效，请先在素材台修正") from None
    if kind == "video" and target_size is None and p.get("output_canvas") is not None:
        canvas = p["output_canvas"]
        target_size = _video_target_size(canvas["width"], canvas["height"])
    require_valid_project(p)
    window = p["processing_window"]
    plan = {"kind": kind, "binding_id": binding_id, "window": {
        "start_seconds": window["start_seconds"], "end_seconds": window["end_seconds"],
        "target_fps": window["fps"], "sample_rate": SAMPLE_RATE,
        "sample_count": seconds_to_frame(window["end_seconds"] - window["start_seconds"], SAMPLE_RATE),
    }, "items": [], "original_audio": None}
    assets = {asset["asset_id"]: asset for asset in p["assets"]}
    labels = {item["item_id"]: item["label"] for item in p["label_map"]}
    if kind == "timeline_audio":
        if plan["window"]["sample_count"] < 1:
            raise OutletError("处理窗口不足一个音频采样点，请扩大处理范围")
        plan["binding_id"] = None
        for clip in p["audio_track"]:
            intersection = _intersection(clip, window)
            if clip["enabled"] and intersection:
                plan["items"].append(_entry(clip, assets[clip["asset_id"]], labels[clip["clip_id"]], "audio", intersection))
    else:
        id_key = "item_id" if kind == "picture" else "clip_id"
        item = next((item for item in p[kind + "_track"] if item[id_key] == binding_id), None)
        if item is None:
            raise OutletError("绑定素材已不存在或不属于此出口类型，请重新选择轨道项创建出口")
        asset = assets[item["asset_id"]]
        if kind == "audio":
            if item["linked_video_clip_id"]:
                raise OutletError("该音频与视频绑定，请使用对应视频出口的原声端口")
            if not item["enabled"]:
                raise OutletError("绑定音频已停用，请在素材台启用后执行")
        intersection = None if kind == "picture" else _intersection(item, window)
        if kind != "picture" and intersection is None:
            raise OutletError("绑定素材与当前处理窗口没有交集，请调整处理窗口")
        entry = _entry(item, asset, labels[binding_id], kind, intersection, window["fps"])
        if kind == "video" and target_size is not None:
            entry.update(
                output_width=target_size[0], output_height=target_size[1],
                resize_during_decode=True, resize_method="bilinear",
                fit_mode="center_crop_fill",
            )
        plan["items"].append(entry)
        if kind == "video" and item["source_audio_enabled"] and asset["probe"]["has_audio"]:
            original = next(clip for clip in p["audio_track"] if clip["clip_id"] == item["audio_link_id"])
            audio = _entry(original, asset, labels[original["clip_id"]], "audio", dict(intersection))
            audio.update(source_window=dict(entry["source_window"]), output_duration_seconds=entry["output_duration_seconds"],
                         sample_count=seconds_to_frame(entry["output_duration_seconds"], SAMPLE_RATE))
            plan["original_audio"] = audio
    _check_size(plan)
    return plan
