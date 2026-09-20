"""Clock-bound mask handoff for long-video segment plans.

This module deliberately does not load or run a segmentation model.  It exposes
standard IMAGE/MASK boundaries so SAM, SeC, or another ComfyUI mask producer can
remain an ordinary, replaceable branch in the graph.
"""

import copy
import hashlib
import json
import math
import re

import torch
import torch.nn.functional as functional
import torchaudio

from ..media_evidence.contract import ProjectError, normalize_project, seconds_to_frame
from ..media_evidence.outlet import OutletError, build_outlet_plan, require_valid_project
from ..h3_focus.routing import model_frame_count


SOURCE_KIND = "zv-mask-source"
BUNDLE_KIND = "zv-masked-segment-bundle"
RANGE_WHOLE = "whole"
RANGE_SEGMENT = "segment"
MODE_FIXED = "fixed_region"
MODE_PER_FRAME = "per_frame"
SOURCE_AUDIO_SAMPLE_RATE = 44100
H3_AUDIO_SAMPLE_RATE = 32000
H3_AUDIO_LATENT_FPS = 40
H3_FPS = 24
H3_VIDEO_CHANNELS = 24
H3_AUDIO_CHANNELS = 32
H3_AUDIO_STEREO = 2
H3_MIN_MODEL_FRAMES = 124
NO_SOURCE_AUDIO_POLICIES = ("clocked_silence", "reject")
MASK_PROCESSING_VERSION = "zv-h3-full-frame-mask-c1-v2"
H3_TEMPORAL_GROUP_PATTERN = (1, 4, 4, 4, 4)
H3_SPATIAL_TOKEN = (2, 2)
H3_VIDEO_VAE_GEOMETRY = {
    "vae_ratio_t": 4,
    "clip_length": 17,
    "token_drop": 3,
    "frame_pre_padding": 3,
    "tokens_chunk_size": 5,
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class MaskSegmentError(ValueError):
    """A fail-closed mask/source clock validation error."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise MaskSegmentError(code, message)


def _hash(value):
    try:
        payload = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail("provenance_json", "遮罩时钟证据包含不可序列化或非有限值")
    return hashlib.sha256(payload).hexdigest()


def _integer(value, code, message, minimum=0):
    if type(value) is not int or value < minimum:
        _fail(code, message)
    return value


def _plan(plan, *, require_ready=True):
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        _fail("plan_schema", "需要 ZV 长视频分段计划 v1")
    revision = plan.get("revision")
    source_fingerprint = plan.get("source_fingerprint")
    if not isinstance(revision, str) or not _HEX64.fullmatch(revision):
        _fail("plan_revision", "分段计划缺少有效 revision")
    if not isinstance(source_fingerprint, str) or not _HEX64.fullmatch(source_fingerprint):
        _fail("source_fingerprint", "分段计划缺少有效素材指纹")
    fps = _integer(plan.get("fps"), "plan_fps", "分段计划 fps 必须是正整数", 1)
    if fps > 240:
        _fail("plan_fps", "分段计划 fps 超出 240 fps 上限")
    _integer(plan.get("range_start_frame"), "plan_range", "分段计划起始帧无效")
    _integer(plan.get("target_frame_count"), "plan_range", "分段计划目标帧数无效")
    if not isinstance(plan.get("media_project"), dict):
        _fail("plan_project", "分段计划缺少冻结素材工程")
    if not isinstance(plan.get("segments"), list):
        _fail("plan_segments", "分段计划缺少分段数组")
    validation = plan.get("validation")
    if require_ready:
        if (
            not isinstance(validation, dict)
            or validation.get("ready") is not True
            or not isinstance(validation.get("errors"), list)
            or validation["errors"]
        ):
            _fail("plan_not_ready", "分段计划尚未通过机械校验，不能读取遮罩源")
        if plan.get("stale") is not False:
            _fail("plan_stale", "分段计划的冻结素材已过期，请先刷新计划")
    return plan


def _range_mode(value):
    aliases = {
        RANGE_WHOLE: RANGE_WHOLE, "全片": RANGE_WHOLE,
        RANGE_SEGMENT: RANGE_SEGMENT, "当前分段": RANGE_SEGMENT,
    }
    if value not in aliases:
        _fail("range_mode", "读取范围只能选择全片或当前分段")
    return aliases[value]


def _mask_mode(value):
    aliases = {
        MODE_FIXED: MODE_FIXED, "固定区域": MODE_FIXED,
        MODE_PER_FRAME: MODE_PER_FRAME, "逐帧": MODE_PER_FRAME,
    }
    if value not in aliases:
        _fail("mask_mode", "遮罩模式只能选择固定区域或逐帧")
    return aliases[value]


def _segment(plan, segment_index):
    _integer(segment_index, "segment_index", "分段序号必须从 1 开始", 1)
    if segment_index > len(plan["segments"]):
        _fail("segment_index", "分段序号超出当前计划")
    segment = plan["segments"][segment_index - 1]
    if not isinstance(segment, dict):
        _fail("segment_shape", "分段数据不是对象")
    start = _integer(segment.get("start_frame"), "segment_range", "分段起始帧无效")
    end = _integer(segment.get("end_frame"), "segment_range", "分段结束帧无效")
    count = _integer(segment.get("frame_count"), "segment_range", "分段帧数无效", 1)
    if end - start != count:
        _fail("segment_range", "分段首尾与 frame_count 不一致")
    tail = _integer(segment.get("tail_padding_frames"), "segment_padding", "尾部补帧数无效")
    plan_end = plan["range_start_frame"] + plan["target_frame_count"]
    expected_tail = max(0, end - plan_end)
    if tail != expected_tail or tail >= count:
        _fail("segment_padding", "尾部补帧与分段计划目标范围不一致")
    segment_id = segment.get("segment_id")
    if not isinstance(segment_id, str) or not segment_id:
        _fail("segment_id", "分段缺少稳定 segment_id")
    return segment


def _scope(plan, range_mode, segment_index):
    mode = _range_mode(range_mode)
    if mode == RANGE_WHOLE:
        count = plan["target_frame_count"]
        if count < 1:
            _fail("empty_range", "全片范围没有可读取的视频帧")
        return {
            "range_mode": mode, "segment_index": None, "segment_id": None,
            "absolute_start_frame": plan["range_start_frame"],
            "frame_count": count, "tail_padding_frames": 0,
        }
    segment = _segment(plan, segment_index)
    return {
        "range_mode": mode, "segment_index": segment_index,
        "segment_id": segment["segment_id"],
        "absolute_start_frame": segment["start_frame"],
        "frame_count": segment["frame_count"],
        "tail_padding_frames": segment["tail_padding_frames"],
    }


def _project_and_clip(plan, clip_id, scope):
    if not isinstance(clip_id, str) or not clip_id:
        _fail("clip_id", "需要选择一个视频片段 clip_id")
    try:
        project = normalize_project(plan["media_project"])
    except ProjectError:
        _fail("plan_project", "冻结素材工程结构无效")
    if project["validation"]["errors"]:
        _fail("plan_project", "冻结素材工程仍有机械错误")
    clip = next((row for row in project["video_track"] if row["clip_id"] == clip_id), None)
    if clip is None:
        _fail("clip_missing", "所选视频片段不在冻结素材工程中")
    assets = {row["asset_id"]: row for row in project["assets"]}
    asset = assets.get(clip["asset_id"])
    if asset is None or asset.get("kind") != "video":
        _fail("clip_asset", "所选片段没有有效视频素材")

    fps = plan["fps"]
    timeline_start = seconds_to_frame(clip["timeline_in_seconds"], fps)
    clip_count = seconds_to_frame(clip["source_out_seconds"] - clip["source_in_seconds"], fps)
    timeline_end = timeline_start + clip_count
    actual_count = scope["frame_count"] - scope["tail_padding_frames"]
    absolute_start = scope["absolute_start_frame"]
    absolute_end = absolute_start + actual_count
    if actual_count < 1:
        _fail("empty_source_range", "当前作用范围没有真实源帧可供遮罩处理")
    if absolute_start < timeline_start or absolute_end > timeline_end:
        _fail(
            "single_clip_coverage",
            "当前版本要求一个视频片段完整覆盖所选作用范围；请先整理素材轨道或改选片段",
        )

    source_start_seconds = clip["source_in_seconds"] + (absolute_start - timeline_start) / fps
    source_end_seconds = min(clip["source_out_seconds"], source_start_seconds + actual_count / fps)
    source_start = seconds_to_frame(source_start_seconds, fps)
    source_end = source_start + actual_count
    output_canvas = project.get("output_canvas")
    if isinstance(output_canvas, dict):
        width, height = output_canvas.get("width"), output_canvas.get("height")
    else:
        width, height = asset["probe"].get("width"), asset["probe"].get("height")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        _fail("source_dimensions", "视频素材或统一画布缺少有效宽高")

    local = copy.deepcopy(project)
    local_clip = copy.deepcopy(clip)
    source_audio_enabled = bool(
        clip.get("source_audio_enabled")
        and clip.get("audio_link_id")
        and asset["probe"].get("has_audio")
    )
    local_clip.update(
        timeline_in_seconds=0,
        source_in_seconds=source_start_seconds,
        source_out_seconds=source_end_seconds,
        source_audio_enabled=source_audio_enabled,
        audio_link_id=clip.get("audio_link_id") if source_audio_enabled else None,
    )
    local_audio = []
    if source_audio_enabled:
        linked = next(
            (row for row in project["audio_track"] if row["clip_id"] == clip["audio_link_id"]),
            None,
        )
        if linked is None:
            _fail("source_audio_link", "视频原声已启用但冻结素材缺少对应音频片段")
        linked = copy.deepcopy(linked)
        linked.update(
            timeline_in_seconds=0,
            source_in_seconds=source_start_seconds,
            source_out_seconds=source_end_seconds,
            enabled=True,
            linked_video_clip_id=clip_id,
            source_video_clip_id=clip_id,
        )
        local_audio.append(linked)
    local["assets"] = [copy.deepcopy(asset)]
    local["picture_track"] = []
    local["video_track"] = [local_clip]
    local["audio_track"] = local_audio
    local["processing_window"] = {
        "start_seconds": 0,
        "end_seconds": actual_count / fps,
        "fps": fps,
    }
    return local, {
        "clip_id": clip_id,
        "asset_id": asset["asset_id"],
        "source_handle": asset["source_handle"],
        "clip_timeline_range_frames": {"start": timeline_start, "end": timeline_end},
        "clip_source_range_frames": {"start": source_start, "end": source_end},
        "clip_source_range_seconds": {"start": source_start_seconds, "end": source_end_seconds},
        "expected_width": width,
        "expected_height": height,
        "decoded_frame_count": actual_count,
        "audio_policy": "source_audio" if source_audio_enabled else "clocked_silence",
    }


def _decode_project(project, clip_id):
    """Use the existing registry-backed, bounded outlet decoder."""
    from ..media_evidence.outlet_decode import execute_outlet
    from ..media_evidence.runtime import get_store

    store = get_store()
    try:
        canonical = store.canonical(project)
        require_valid_project(canonical)
        outlet_plan = build_outlet_plan(canonical, "video", clip_id)
        frames, original_audio, manifest, _report = execute_outlet(store, outlet_plan)
    except (ProjectError, OutletError) as error:
        _fail("decode_rejected", f"分段视频读取失败：{error}")
    return frames, original_audio, manifest


def _sampling_evidence(item, decoded_frame_count, plan_tail_repeat_frames):
    if not isinstance(item, dict):
        _fail("sampling_evidence", "受控视频出口没有返回有效采样条目")
    sampling = item.get("sampling")
    if not isinstance(sampling, dict):
        _fail("sampling_evidence", "受控视频出口没有返回采样证据")
    sampled = sampling.get("sampled_source_pts")
    if not isinstance(sampled, list) or len(sampled) != decoded_frame_count:
        _fail("sampling_evidence", "受控视频出口的采样帧数与解码结果不一致")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in sampled):
        _fail("sampling_evidence", "受控视频出口的采样时间必须是有限数值")
    if any(current < previous for previous, current in zip(sampled, sampled[1:])):
        _fail("sampling_evidence", "受控视频出口的采样时间必须单调不减")
    evidence = {
        "method": sampling.get("method"),
        "target_start_seconds": sampling.get("target_start_seconds"),
        "sampled_source_pts": copy.deepcopy(sampled),
        "first_frame_repeated_count": sampling.get("first_frame_repeated_count"),
        "decoder_tail_repeated_count": sampling.get("tail_frame_repeated_count"),
        "plan_tail_repeated_count": plan_tail_repeat_frames,
        "source_vfr": sampling.get("source_vfr"),
        "decoded_pts_range": copy.deepcopy(item.get("decoded_pts_range")),
    }
    for key in ("first_frame_repeated_count", "decoder_tail_repeated_count"):
        _integer(evidence[key], "sampling_evidence", "受控视频出口的重复帧证据无效")
    if evidence["method"] != "previous_pts":
        _fail("sampling_evidence", "受控视频出口使用了未知采样策略")
    return evidence


_SOURCE_FIELDS = {
    "schema_version", "kind", "plan_revision", "source_fingerprint",
    "clip_id", "asset_id", "source_handle", "range_mode", "segment_index",
    "segment_id", "fps", "absolute_start_frame", "frame_count",
    "decoded_frame_count", "tail_repeated_frames", "width", "height",
    "clip_timeline_range_frames", "clip_source_range_frames",
    "clip_source_range_seconds", "sampling_evidence", "sampling_fingerprint",
    "audio_policy", "audio_sample_rate", "audio_channels", "audio_sample_count",
    "audio_provenance",
}


def _fingerprint_source_info(source_info):
    payload = copy.deepcopy(source_info)
    payload.pop("sampling_fingerprint", None)
    return _hash(payload)


def _clock_samples(start_frame, end_frame, sample_rate, fps):
    return round(end_frame * sample_rate / fps) - round(start_frame * sample_rate / fps)


def _source_audio_window(audio, manifest, scope, decoded_count, policy, fps):
    absolute_start = scope["absolute_start_frame"]
    real_end = absolute_start + decoded_count
    scope_end = absolute_start + scope["frame_count"]
    real_samples = _clock_samples(
        absolute_start, real_end, SOURCE_AUDIO_SAMPLE_RATE, fps,
    )
    total_samples = _clock_samples(
        absolute_start, scope_end, SOURCE_AUDIO_SAMPLE_RATE, fps,
    )
    if policy == "source_audio":
        if not isinstance(audio, dict):
            _fail("source_audio_missing", "冻结视频声明启用原声，但受控出口没有返回 AUDIO")
        waveform = audio.get("waveform")
        sample_rate = audio.get("sample_rate")
        if (
            not isinstance(waveform, torch.Tensor)
            or waveform.ndim != 3
            or waveform.shape[0] != 1
            or waveform.shape[1] != 2
            or sample_rate != SOURCE_AUDIO_SAMPLE_RATE
        ):
            _fail("source_audio_shape", "受控视频原声必须是 44100 Hz 双声道 AUDIO")
        if not waveform.is_floating_point() or waveform.is_complex():
            _fail("source_audio_dtype", "受控视频原声必须是浮点实数张量")
        if not torch.isfinite(waveform).all().item():
            _fail("source_audio_values", "受控视频原声包含 NaN 或无穷值")
        if waveform.shape[-1] < real_samples:
            _fail("source_audio_short", "受控视频原声短于冻结帧时钟")
        waveform = waveform[..., :real_samples].detach().contiguous()
        provenance = copy.deepcopy(manifest.get("original_audio"))
        if not isinstance(provenance, dict):
            _fail("source_audio_manifest", "受控视频原声缺少解码清单")
    elif policy == "clocked_silence":
        waveform = torch.zeros((1, 2, real_samples), dtype=torch.float32)
        provenance = None
    else:
        _fail("source_audio_policy", "遮罩源音频策略无效")
    if total_samples < real_samples:
        _fail("source_audio_clock", "遮罩源音频全局帧时钟倒退")
    if total_samples > real_samples:
        waveform = torch.cat(
            (waveform, waveform.new_zeros((1, 2, total_samples - real_samples))),
            dim=-1,
        )
    return {
        "waveform": waveform,
        "sample_rate": SOURCE_AUDIO_SAMPLE_RATE,
    }, provenance


def read_segment_video(segment_plan, clip_id, range_mode=RANGE_WHOLE, segment_index=1):
    """Decode one clock-bound source scope and return IMAGE, provenance and AUDIO."""
    plan = _plan(segment_plan)
    scope = _scope(plan, range_mode, segment_index)
    project, binding = _project_and_clip(plan, clip_id, scope)
    frames, original_audio, manifest = _decode_project(project, clip_id)

    try:
        shape = tuple(frames.shape)
    except (AttributeError, TypeError):
        _fail("decoded_image", "受控视频出口没有返回 IMAGE 张量")
    if len(shape) != 4 or shape[-1] != 3:
        _fail("decoded_image", "受控视频出口返回的 IMAGE 形状无效")
    decoded_count = binding["decoded_frame_count"]
    if shape[0] != decoded_count:
        _fail("decoded_frames", "受控视频出口缺帧，不能建立遮罩时钟")
    if shape[1] != binding["expected_height"] or shape[2] != binding["expected_width"]:
        _fail("decoded_dimensions", "受控视频出口尺寸与冻结素材或统一画布不一致")
    items = manifest.get("items") if isinstance(manifest, dict) else None
    if not isinstance(items, list) or len(items) != 1:
        _fail("decode_manifest", "受控视频出口没有返回唯一视频清单")

    tail = scope["tail_padding_frames"]
    if tail:
        frames = torch.cat((frames, frames[-1:].repeat(tail, 1, 1, 1)), dim=0)
    if frames.shape[0] != scope["frame_count"]:
        _fail("decoded_frames", "尾部补帧后仍未达到分段计划帧数")

    audio, audio_provenance = _source_audio_window(
        original_audio,
        manifest,
        scope,
        decoded_count,
        binding["audio_policy"],
        plan["fps"],
    )
    info = {
        "schema_version": 1,
        "kind": SOURCE_KIND,
        "plan_revision": plan["revision"],
        "source_fingerprint": plan["source_fingerprint"],
        "clip_id": binding["clip_id"],
        "asset_id": binding["asset_id"],
        "source_handle": binding["source_handle"],
        "range_mode": scope["range_mode"],
        "segment_index": scope["segment_index"],
        "segment_id": scope["segment_id"],
        "fps": plan["fps"],
        "absolute_start_frame": scope["absolute_start_frame"],
        "frame_count": scope["frame_count"],
        "decoded_frame_count": decoded_count,
        "tail_repeated_frames": tail,
        "width": shape[2],
        "height": shape[1],
        "clip_timeline_range_frames": binding["clip_timeline_range_frames"],
        "clip_source_range_frames": binding["clip_source_range_frames"],
        "clip_source_range_seconds": binding["clip_source_range_seconds"],
        "sampling_evidence": _sampling_evidence(items[0], decoded_count, tail),
        "audio_policy": binding["audio_policy"],
        "audio_sample_rate": SOURCE_AUDIO_SAMPLE_RATE,
        "audio_channels": 2,
        "audio_sample_count": int(audio["waveform"].shape[-1]),
        "audio_provenance": audio_provenance,
    }
    info["sampling_fingerprint"] = _fingerprint_source_info(info)
    validate_mask_source(plan, info)
    return frames, info, audio


def validate_mask_source(segment_plan, source_info):
    """Verify that source evidence still describes this exact frozen plan."""
    plan = _plan(segment_plan)
    if not isinstance(source_info, dict) or set(source_info) != _SOURCE_FIELDS:
        _fail("source_info_shape", "遮罩源时钟证据字段缺失或包含未知字段")
    if source_info.get("schema_version") != 1 or source_info.get("kind") != SOURCE_KIND:
        _fail("source_info_schema", "需要 ZV_MASK_SOURCE v1")
    fingerprint = source_info.get("sampling_fingerprint")
    if not isinstance(fingerprint, str) or not _HEX64.fullmatch(fingerprint):
        _fail("sampling_fingerprint", "遮罩源缺少有效采样指纹")
    if fingerprint != _fingerprint_source_info(source_info):
        _fail("sampling_fingerprint", "遮罩源采样证据已被修改")
    if source_info["plan_revision"] != plan["revision"]:
        _fail("stale_plan", "遮罩源来自另一版分段计划，请重新读取视频并生成遮罩")
    if source_info["source_fingerprint"] != plan["source_fingerprint"]:
        _fail("stale_source", "遮罩源素材指纹与当前计划不一致")

    index = source_info["segment_index"] if source_info["range_mode"] == RANGE_SEGMENT else 1
    scope = _scope(plan, source_info["range_mode"], index)
    _project, expected = _project_and_clip(plan, source_info["clip_id"], scope)
    expected_values = {
        "range_mode": scope["range_mode"],
        "segment_index": scope["segment_index"],
        "segment_id": scope["segment_id"],
        "fps": plan["fps"],
        "absolute_start_frame": scope["absolute_start_frame"],
        "frame_count": scope["frame_count"],
        "decoded_frame_count": expected["decoded_frame_count"],
        "tail_repeated_frames": scope["tail_padding_frames"],
        "asset_id": expected["asset_id"],
        "source_handle": expected["source_handle"],
        "width": expected["expected_width"],
        "height": expected["expected_height"],
        "clip_timeline_range_frames": expected["clip_timeline_range_frames"],
        "clip_source_range_frames": expected["clip_source_range_frames"],
        "clip_source_range_seconds": expected["clip_source_range_seconds"],
        "audio_policy": expected["audio_policy"],
        "audio_sample_rate": SOURCE_AUDIO_SAMPLE_RATE,
        "audio_channels": 2,
        "audio_sample_count": _clock_samples(
            scope["absolute_start_frame"],
            scope["absolute_start_frame"] + scope["frame_count"],
            SOURCE_AUDIO_SAMPLE_RATE,
            plan["fps"],
        ),
    }
    for key, value in expected_values.items():
        if source_info[key] != value:
            _fail("source_clock_mismatch", f"遮罩源字段 {key} 与当前计划时钟不一致")
    evidence = source_info["sampling_evidence"]
    if not isinstance(evidence, dict):
        _fail("sampling_evidence", "遮罩源缺少解码采样证据")
    sampled = evidence.get("sampled_source_pts")
    if not isinstance(sampled, list) or len(sampled) != source_info["decoded_frame_count"]:
        _fail("sampling_evidence", "遮罩源采样点数量与真实解码帧数不一致")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in sampled):
        _fail("sampling_evidence", "遮罩源采样点必须是有限数值")
    if any(current < previous for previous, current in zip(sampled, sampled[1:])):
        _fail("sampling_evidence", "遮罩源采样点必须单调不减")
    if evidence.get("plan_tail_repeated_count") != source_info["tail_repeated_frames"]:
        _fail("sampling_evidence", "遮罩源尾部重复帧证据不一致")
    if source_info["audio_policy"] == "source_audio":
        if not isinstance(source_info["audio_provenance"], dict):
            _fail("source_audio_manifest", "遮罩源原声缺少绑定清单")
    elif source_info["audio_provenance"] is not None:
        _fail("source_audio_manifest", "静音策略不应声明原声解码清单")
    return source_info


def _validate_mask(mask, source_info, mode):
    if not isinstance(mask, torch.Tensor) or mask.ndim != 3:
        _fail("mask_shape", "必须连接标准 MASK（帧×高×宽）；IMAGE/视频张量不能代替 MASK")
    if mask.shape[0] < 1:
        _fail("mask_missing_frames", "MASK 没有任何帧；全黑遮罩合法，但零帧批次不合法")
    if mask.shape[1] != source_info["height"] or mask.shape[2] != source_info["width"]:
        _fail("mask_dimensions", "MASK 宽高与遮罩源视频不一致")
    if mask.is_complex():
        _fail("mask_dtype", "MASK 不能使用复数张量")
    if not torch.isfinite(mask).all().item():
        _fail("mask_values", "MASK 包含 NaN 或无穷值")
    if mask.numel() and (mask.min().item() < 0 or mask.max().item() > 1):
        _fail("mask_values", "MASK 数值必须位于 0–1")
    if mode == MODE_FIXED:
        if mask.shape[0] != 1:
            _fail("fixed_mask_frames", "固定区域模式必须明确提供且只提供 1 帧 MASK")
    elif mask.shape[0] != source_info["frame_count"]:
        _fail(
            "mask_missing_frames",
            f"逐帧模式需要 {source_info['frame_count']} 帧 MASK，实际为 {mask.shape[0]} 帧",
        )
    return mask


def _tensor_content_summary(value):
    source = value.detach()
    item_area = math.prod(int(part) for part in source.shape[1:])
    chunk_items = max(1, 4_000_000 // max(1, item_area))
    digest = hashlib.sha256()
    minimum = float("inf")
    maximum = float("-inf")
    nonzero = 0
    for start in range(0, source.shape[0], chunk_items):
        chunk = source[start:start + chunk_items].to(
            device="cpu", dtype=torch.float32,
        ).contiguous()
        digest.update(chunk.numpy())
        minimum = min(minimum, float(chunk.min().item()))
        maximum = max(maximum, float(chunk.max().item()))
        nonzero += int(chunk.count_nonzero().item())
    return {
        "shape": list(source.shape),
        "canonical_dtype": "float32",
        "sha256": digest.hexdigest(),
        "minimum": minimum,
        "maximum": maximum,
        "nonzero": nonzero,
    }


def _mask_content_summary(mask):
    return _tensor_content_summary(mask)


def _bundle_fingerprint(bundle):
    return _hash({
        "schema_version": bundle["schema_version"],
        "kind": bundle["kind"],
        "processing_version": bundle["processing_version"],
        "plan_revision": bundle["plan_revision"],
        "source_fingerprint": bundle["source_fingerprint"],
        "mask_mode": bundle["mask_mode"],
        "mask_content": bundle["mask_content"],
        "sampling_fingerprint": bundle["source_info"]["sampling_fingerprint"],
    })


def build_masked_segment_bundle(segment_plan, mask, source_info, mode=MODE_PER_FRAME):
    """Bind a standard MASK batch to one verified video clock."""
    plan = _plan(segment_plan)
    source = validate_mask_source(plan, source_info)
    normalized_mode = _mask_mode(mode)
    mask = _validate_mask(mask, source, normalized_mode)
    bundle = {
        "schema_version": 1,
        "kind": BUNDLE_KIND,
        "processing_version": MASK_PROCESSING_VERSION,
        "plan_revision": plan["revision"],
        "source_fingerprint": plan["source_fingerprint"],
        "mask_mode": normalized_mode,
        "mask": mask,
        "mask_content": _mask_content_summary(mask),
        "source_info": copy.deepcopy(source),
    }
    bundle["bundle_fingerprint"] = _bundle_fingerprint(bundle)
    is_empty = not bool(mask.count_nonzero().item())
    description = "固定单帧广播" if normalized_mode == MODE_FIXED else f"逐帧 {mask.shape[0]} 帧"
    report = f"遮罩分段包已建立：{description}，{source['width']} × {source['height']}；白色 1 表示重绘，黑色 0 表示锁定原 latent。"
    if is_empty:
        report += " 当前是合法的全黑空遮罩。"
    return bundle, report


def _bundle(bundle, plan):
    if not isinstance(bundle, dict) or set(bundle) != {
        "schema_version", "kind", "processing_version", "plan_revision",
        "source_fingerprint", "mask_mode", "mask", "mask_content",
        "source_info", "bundle_fingerprint",
    }:
        _fail("bundle_shape", "遮罩分段包字段缺失或包含未知字段")
    if bundle["schema_version"] != 1 or bundle["kind"] != BUNDLE_KIND:
        _fail("bundle_schema", "需要 ZV_MASKED_SEGMENT_BUNDLE v1")
    if bundle["processing_version"] != MASK_PROCESSING_VERSION:
        _fail("mask_processing_version", "遮罩处理版本不兼容，请重新绑定 MASK")
    if bundle["plan_revision"] != plan["revision"]:
        _fail("stale_plan", "遮罩分段包来自另一版分段计划")
    if bundle["source_fingerprint"] != plan["source_fingerprint"]:
        _fail("stale_source", "遮罩分段包来自另一版素材")
    source = validate_mask_source(plan, bundle["source_info"])
    mode = _mask_mode(bundle["mask_mode"])
    _validate_mask(bundle["mask"], source, mode)
    if bundle["mask_content"] != _mask_content_summary(bundle["mask"]):
        _fail("mask_content_mismatch", "实际 MASK 内容与绑定摘要不一致，请重新绑定")
    if bundle["bundle_fingerprint"] != _bundle_fingerprint(bundle):
        _fail("bundle_fingerprint", "遮罩分段包清单已被修改")
    return source, mode


def slice_mask_for_segment(masked_bundle, segment_plan, segment_index):
    """Return one segment MASK plus explicit clock/repeat evidence.

    Slices originating from the same whole-clip bundle use the same tensor
    indices in overlap regions, making overlapping pixels exactly identical.
    """
    plan = _plan(segment_plan)
    source, mode = _bundle(masked_bundle, plan)
    segment = _segment(plan, segment_index)
    count = segment["frame_count"]
    tail = segment["tail_padding_frames"]
    mask = masked_bundle["mask"]

    if mode == MODE_FIXED:
        result = mask.repeat(count, 1, 1)
        source_offset = 0
        source_frames = 1
        repeated = 0
        broadcast_repeated = count - 1
    elif source["range_mode"] == RANGE_SEGMENT:
        if source["segment_index"] != segment_index or source["segment_id"] != segment["segment_id"]:
            _fail("segment_scope", "当前遮罩包只覆盖另一分段，不能跨段取片")
        if mask.shape[0] != count:
            _fail("mask_missing_frames", "当前分段 MASK 缺帧")
        real_count = count - tail
        result = mask[:real_count] if tail else mask
        if tail:
            if real_count < 1:
                _fail("mask_missing_frames", "尾部补帧前没有可重复的 MASK")
            result = torch.cat((result, result[-1:].repeat(tail, 1, 1)), dim=0)
        source_offset = 0
        source_frames = real_count
        repeated = tail
        broadcast_repeated = 0
    else:
        source_offset = segment["start_frame"] - source["absolute_start_frame"]
        real_count = count - tail
        if source_offset < 0 or source_offset + real_count > mask.shape[0]:
            _fail("mask_missing_frames", "全片 MASK 未覆盖当前分段的真实帧范围")
        result = mask[source_offset:source_offset + real_count]
        if result.shape[0] != real_count:
            _fail("mask_missing_frames", "当前分段 MASK 缺少真实源帧")
        if tail:
            if real_count < 1:
                _fail("mask_missing_frames", "尾部补帧前没有可重复的 MASK")
            result = torch.cat((result, result[-1:].repeat(tail, 1, 1)), dim=0)
        source_frames = real_count
        repeated = tail
        broadcast_repeated = 0
    if result.shape[0] != count:
        _fail("mask_missing_frames", "分段 MASK 取片后的帧数不完整")
    evidence = {
        "schema_version": 1,
        "segment_id": segment["segment_id"],
        "segment_index": segment_index,
        "absolute_start_frame": segment["start_frame"],
        "frame_count": count,
        "overlap_frames": segment.get("overlap_frames", 0),
        "source_mask_offset": source_offset,
        "source_mask_frame_count": source_frames,
        "tail_repeated_frames": repeated,
        "broadcast_repeated_frames": broadcast_repeated,
        "plan_revision": plan["revision"],
        "sampling_fingerprint": source["sampling_fingerprint"],
        "mask_processing_version": masked_bundle["processing_version"],
        "mask_content": copy.deepcopy(masked_bundle["mask_content"]),
        "masked_bundle_fingerprint": masked_bundle["bundle_fingerprint"],
        "mask_polarity": "white_redraw_black_lock",
    }
    return result, evidence


def _validate_source_tensors(source_frames, source_audio, source):
    if (
        not isinstance(source_frames, torch.Tensor)
        or source_frames.ndim != 4
        or source_frames.shape[-1] != 3
    ):
        _fail("source_frames_shape", "遮罩源画面必须是 IMAGE [帧,高,宽,3]")
    expected_shape = (
        source["frame_count"], source["height"], source["width"], 3,
    )
    if tuple(source_frames.shape) != expected_shape:
        _fail(
            "source_frames_shape",
            f"遮罩源画面形状与绑定清单不一致：需要 {expected_shape}，实际 {tuple(source_frames.shape)}",
        )
    if not source_frames.is_floating_point() or source_frames.is_complex():
        _fail("source_frames_dtype", "遮罩源画面必须是浮点实数 IMAGE")
    if not torch.isfinite(source_frames).all().item():
        _fail("source_frames_values", "遮罩源画面包含 NaN 或无穷值")
    if not isinstance(source_audio, dict):
        _fail("source_audio_shape", "遮罩源必须连接 AUDIO 张量")
    waveform = source_audio.get("waveform")
    sample_rate = source_audio.get("sample_rate")
    expected_audio = (1, source["audio_channels"], source["audio_sample_count"])
    if (
        not isinstance(waveform, torch.Tensor)
        or tuple(waveform.shape) != expected_audio
        or sample_rate != source["audio_sample_rate"]
    ):
        _fail(
            "source_audio_shape",
            f"遮罩源 AUDIO 与绑定清单不一致：需要 {expected_audio}@{source['audio_sample_rate']}Hz",
        )
    if not waveform.is_floating_point() or waveform.is_complex():
        _fail("source_audio_dtype", "遮罩源 AUDIO 必须是浮点实数张量")
    if not torch.isfinite(waveform).all().item():
        _fail("source_audio_values", "遮罩源 AUDIO 包含 NaN 或无穷值")
    return waveform


def _slice_source_frames(source_frames, source, segment):
    count = segment["frame_count"]
    tail = segment["tail_padding_frames"]
    real_count = count - tail
    if source["range_mode"] == RANGE_SEGMENT:
        if (
            source["segment_index"] != segment["order"]
            or source["segment_id"] != segment["segment_id"]
        ):
            _fail("segment_scope", "当前遮罩源只覆盖另一分段")
        offset = 0
    else:
        offset = segment["start_frame"] - source["absolute_start_frame"]
    if offset < 0 or offset + real_count > source_frames.shape[0]:
        _fail("source_frames_missing", "遮罩源画面未覆盖当前分段真实帧范围")
    result = source_frames[offset:offset + real_count]
    if result.shape[0] != real_count:
        _fail("source_frames_missing", "遮罩源画面缺少当前分段真实帧")
    if tail:
        if real_count < 1:
            _fail("source_frames_missing", "目标尾部重复前没有真实源帧")
        result = torch.cat((result, result[-1:].repeat(tail, 1, 1, 1)), dim=0)
    return result, offset


def _slice_source_audio(waveform, source, segment, fps):
    absolute_start = source["absolute_start_frame"]
    segment_start = segment["start_frame"]
    segment_end = segment["end_frame"]
    real_end = segment_end - segment["tail_padding_frames"]
    sample_rate = source["audio_sample_rate"]
    first = (
        round(segment_start * sample_rate / fps)
        - round(absolute_start * sample_rate / fps)
    )
    last = (
        round(real_end * sample_rate / fps)
        - round(absolute_start * sample_rate / fps)
    )
    if first < 0 or last <= first or last > waveform.shape[-1]:
        _fail("source_audio_missing", "遮罩源 AUDIO 未覆盖当前分段全局帧时钟")
    sliced = waveform[..., first:last]
    desired = (
        round(segment_end * sample_rate / fps)
        - round(segment_start * sample_rate / fps)
    )
    target_tail_zero_samples = desired - int(sliced.shape[-1])
    if target_tail_zero_samples < 0:
        _fail("source_audio_clock", "目标尾部音频时钟倒退")
    if target_tail_zero_samples:
        sliced = torch.cat(
            (
                sliced,
                sliced.new_zeros((*sliced.shape[:-1], target_tail_zero_samples)),
            ),
            dim=-1,
        )
    return {
        "waveform": sliced.detach().contiguous(),
        "sample_rate": sample_rate,
    }, first, last, target_tail_zero_samples


def _h3_model_length(segment):
    count = segment["frame_count"]
    return max(H3_MIN_MODEL_FRAMES, model_frame_count(count))


def _h3_temporal_groups(frame_count):
    """Map H3 pixel frames to the causal VAE tokens kept after token_drop."""
    pattern = H3_TEMPORAL_GROUP_PATTERN
    starts = (0, 1, 5, 9, 13, 17)
    chunk_frames = starts[-1]
    tokens_per_chunk = len(pattern)
    total = tokens_per_chunk * math.ceil(frame_count / chunk_frames)
    kept = max(1, total - 3)
    groups = []
    for token in range(kept):
        chunk = token // tokens_per_chunk
        phase = token % tokens_per_chunk
        start = chunk * chunk_frames + starts[phase]
        groups.append((min(start, frame_count - 1), min(start + pattern[phase], frame_count)))
    groups[-1] = (groups[-1][0], frame_count)
    return groups


def _h3_video_noise_mask(model_mask, latent_shape):
    """Reduce a pixel MASK on H3's spatial-token and causal temporal grids."""
    latent_t, latent_h, latent_w = latent_shape
    value = model_mask.float().unsqueeze(1)
    if value.shape[-2] >= latent_h and value.shape[-1] >= latent_w:
        value = functional.adaptive_max_pool2d(value, (latent_h, latent_w))
    else:
        value = functional.interpolate(value, size=(latent_h, latent_w), mode="nearest")

    # H3's DiT consumes 2x2 latent-pixel tokens. A touched latent pixel makes
    # the complete token redraw; replicate padding preserves odd right/bottom edges.
    value = functional.pad(
        value,
        (0, -latent_w % 2, 0, -latent_h % 2),
        mode="replicate",
    )
    value = functional.max_pool2d(value, H3_SPATIAL_TOKEN)
    value = value.repeat_interleave(H3_SPATIAL_TOKEN[0], dim=-2).repeat_interleave(
        H3_SPATIAL_TOKEN[1], dim=-1,
    )
    value = value[..., :latent_h, :latent_w]

    groups = _h3_temporal_groups(model_mask.shape[0])
    if len(groups) != latent_t:
        _fail(
            "video_latent_clock",
            f"H3 视频 latent 时间长度与因果 VAE 分组不一致：需要 {len(groups)}，实际 {latent_t}",
        )
    value = torch.stack([value[start:end].amax(dim=0) for start, end in groups], dim=1)
    return value.unsqueeze(0)


def _validate_h3_video_vae_geometry(video_vae):
    inner = getattr(video_vae, "first_stage_model", None)
    expected = H3_VIDEO_VAE_GEOMETRY
    actual = {key: getattr(inner, key, None) for key in expected}
    if actual != expected:
        _fail(
            "video_vae_geometry",
            f"C1 蒙版映射只支持 H3 因果 VAE 时间参数 {expected}，实际 {actual}",
        )


def _fit_model_audio(final_audio, model_length, frame_count, fps):
    waveform = final_audio["waveform"]
    if final_audio["sample_rate"] != H3_AUDIO_SAMPLE_RATE:
        waveform = torchaudio.functional.resample(
            waveform, final_audio["sample_rate"], H3_AUDIO_SAMPLE_RATE,
        )
    logical_samples = round(frame_count * H3_AUDIO_SAMPLE_RATE / fps)
    if waveform.shape[-1] > logical_samples:
        waveform = waveform[..., :logical_samples]
    elif waveform.shape[-1] < logical_samples:
        waveform = torch.cat(
            (
                waveform,
                waveform.new_zeros((*waveform.shape[:-1], logical_samples - waveform.shape[-1])),
            ),
            dim=-1,
        )
    model_samples = round(model_length * H3_AUDIO_SAMPLE_RATE / fps)
    if model_samples < logical_samples:
        _fail("model_audio_clock", "H3 模型音频时钟短于逻辑分段")
    model_padding_samples = model_samples - logical_samples
    if model_padding_samples:
        waveform = torch.cat(
            (
                waveform,
                waveform.new_zeros((*waveform.shape[:-1], model_padding_samples)),
            ),
            dim=-1,
        )
    return {
        "waveform": waveform.detach().contiguous(),
        "sample_rate": H3_AUDIO_SAMPLE_RATE,
    }, logical_samples, model_padding_samples


def _encode_h3_masked_latent(model_frames, model_mask, model_audio, video_vae, audio_vae):
    _validate_h3_video_vae_geometry(video_vae)
    try:
        video = video_vae.encode(model_frames[..., :3])
    except Exception as error:
        _fail("video_vae_encode", f"H3 视频 VAE 编码失败：{error}")
    if (
        not isinstance(video, torch.Tensor)
        or video.ndim != 5
        or video.shape[0] != 1
        or video.shape[1] != H3_VIDEO_CHANNELS
    ):
        shape = tuple(video.shape) if isinstance(video, torch.Tensor) else type(video).__name__
        _fail("video_latent_shape", f"H3 视频 VAE 必须返回 [1,24,T,H,W]，实际 {shape}")
    if not video.is_floating_point() or not torch.isfinite(video).all().item():
        _fail("video_latent_values", "H3 视频 latent 必须是有限浮点张量")

    audio_input = model_audio["waveform"][:1].movedim(1, -1)
    try:
        audio = audio_vae.encode(audio_input)
    except Exception as error:
        _fail("audio_vae_encode", f"H3 音频 VAE 编码失败：{error}")
    if (
        not isinstance(audio, torch.Tensor)
        or audio.ndim != 4
        or audio.shape[0] != 1
        or audio.shape[1] != H3_AUDIO_CHANNELS
        or audio.shape[2] != H3_AUDIO_STEREO
    ):
        shape = tuple(audio.shape) if isinstance(audio, torch.Tensor) else type(audio).__name__
        _fail("audio_latent_shape", f"H3 音频 VAE 必须返回 [1,32,2,T]，实际 {shape}")
    if not audio.is_floating_point() or not torch.isfinite(audio).all().item():
        _fail("audio_latent_values", "H3 音频 latent 必须是有限浮点张量")
    expected_audio_t = round(model_frames.shape[0] * H3_AUDIO_LATENT_FPS / H3_FPS)
    if audio.shape[-1] > expected_audio_t:
        audio = audio[..., :expected_audio_t]
    elif audio.shape[-1] < expected_audio_t:
        audio = functional.pad(audio, (0, expected_audio_t - audio.shape[-1]))
    audio = audio.to(device=video.device, dtype=video.dtype)

    value = _h3_video_noise_mask(
        model_mask, (video.shape[2], video.shape[3], video.shape[4]),
    )
    video_mask = value.to(device=video.device, dtype=video.dtype).expand_as(video)
    audio_mask = torch.zeros_like(audio)
    try:
        import comfy.nested_tensor
    except ImportError:
        _fail("runtime_dependency", "当前 ComfyUI 运行时缺少 nested_tensor")
    return {
        "samples": comfy.nested_tensor.NestedTensor((video, audio)),
        "noise_mask": comfy.nested_tensor.NestedTensor((video_mask, audio_mask)),
    }, video, audio, video_mask, audio_mask


def prepare_h3_masked_segment_latent(
    segment_plan,
    segment_index,
    source_frames,
    source_audio,
    masked_segments,
    video_vae,
    audio_vae,
    no_source_audio_policy="clocked_silence",
):
    """Build one H3 joint AV latent from a clock-bound source and actual MASK tensor."""
    plan = _plan(segment_plan)
    if plan["fps"] != H3_FPS:
        _fail("h3_fps", "H3 蒙版适配器只接受 24 fps 分段计划")
    if no_source_audio_policy not in NO_SOURCE_AUDIO_POLICIES:
        _fail("source_audio_policy", "无源音频策略只能选择 clocked_silence 或 reject")
    source, _mode = _bundle(masked_segments, plan)
    if source["width"] % 32 or source["height"] % 32:
        _fail("h3_geometry", "H3 蒙版源宽高必须保持同一几何并且都是 32 的倍数")
    waveform = _validate_source_tensors(source_frames, source_audio, source)
    if (
        source["audio_policy"] == "clocked_silence"
        and waveform.count_nonzero().item()
    ):
        _fail("source_audio_policy", "clocked_silence 遮罩源 AUDIO 必须保持全零")
    if source["audio_policy"] == "clocked_silence" and no_source_audio_policy == "reject":
        _fail("source_audio_missing", "当前视频没有启用原声，且适配器策略设为 reject")
    segment = _segment(plan, segment_index)
    logical_frames, source_frame_offset = _slice_source_frames(source_frames, source, segment)
    logical_mask, mask_evidence = slice_mask_for_segment(masked_segments, plan, segment_index)
    if logical_mask.shape[0] != logical_frames.shape[0]:
        _fail("mask_source_clock", "当前分段 MASK 与源画面帧数不一致")
    final_audio, source_audio_start, source_audio_end, target_tail_zero_audio_samples = _slice_source_audio(
        waveform, source, segment, plan["fps"],
    )

    model_length = _h3_model_length(segment)
    model_padding_frames = model_length - segment["frame_count"]
    if model_padding_frames:
        model_frames = torch.cat(
            (logical_frames, logical_frames[-1:].repeat(model_padding_frames, 1, 1, 1)),
            dim=0,
        )
        model_mask = torch.cat(
            (logical_mask, logical_mask[-1:].repeat(model_padding_frames, 1, 1)),
            dim=0,
        )
    else:
        model_frames = logical_frames
        model_mask = logical_mask
    model_audio, logical_model_audio_samples, model_audio_padding_samples = _fit_model_audio(
        final_audio, model_length, segment["frame_count"], plan["fps"],
    )
    latent, video_latent, audio_latent, video_noise_mask, audio_noise_mask = (
        _encode_h3_masked_latent(
            model_frames, model_mask, model_audio, video_vae, audio_vae,
        )
    )
    evidence = {
        "schema_version": 1,
        "kind": "zv-h3-masked-segment-latent",
        "plan_revision": plan["revision"],
        "source_fingerprint": plan["source_fingerprint"],
        "sampling_fingerprint": source["sampling_fingerprint"],
        "mask_processing_version": masked_segments["processing_version"],
        "mask_content": copy.deepcopy(masked_segments["mask_content"]),
        "masked_bundle_fingerprint": masked_segments["bundle_fingerprint"],
        "segment_id": segment["segment_id"],
        "segment_index": segment_index,
        "source_frame_offset": source_frame_offset,
        "frame_count": segment["frame_count"],
        "plan_target_tail_repeat_frames": segment["tail_padding_frames"],
        "model_length": model_length,
        "model_grid_repeat_frames": model_padding_frames,
        "source_audio_policy": source["audio_policy"],
        "no_source_audio_policy": no_source_audio_policy,
        "final_audio_sample_rate": final_audio["sample_rate"],
        "final_audio_sample_count": int(final_audio["waveform"].shape[-1]),
        "source_audio_sample_range": [source_audio_start, source_audio_end],
        "plan_target_tail_zero_audio_samples": target_tail_zero_audio_samples,
        "model_audio_sample_rate": model_audio["sample_rate"],
        "model_audio_logical_samples": logical_model_audio_samples,
        "model_audio_zero_padding_samples": model_audio_padding_samples,
        "video_latent_shape": list(video_latent.shape),
        "audio_latent_shape": list(audio_latent.shape),
        "video_noise_mask_shape": list(video_noise_mask.shape),
        "audio_noise_mask_shape": list(audio_noise_mask.shape),
        "pixel_model_mask_content": _mask_content_summary(model_mask),
        "video_noise_mask_content": _tensor_content_summary(video_noise_mask),
        "model_contract": {
            "schema_version": 1,
            "fps": H3_FPS,
            "audio_latent_fps": H3_AUDIO_LATENT_FPS,
            "video_channels": H3_VIDEO_CHANNELS,
            "audio_channels": H3_AUDIO_CHANNELS,
            "audio_stereo": H3_AUDIO_STEREO,
            "video_vae_geometry": copy.deepcopy(H3_VIDEO_VAE_GEOMETRY),
            "temporal_group_pattern": list(H3_TEMPORAL_GROUP_PATTERN),
            "spatial_token": list(H3_SPATIAL_TOKEN),
        },
        "mask_clock": mask_evidence,
        "mask_polarity": "white_redraw_black_lock",
        "audio_mask_policy": "lock_source_or_clocked_silence",
    }
    report = json.dumps(evidence, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return latent, model_frames, model_mask, model_audio, final_audio, report


def restore_h3_masked_latent(av_latent, source_latent, model_mask):
    """Restore the source latent and redraw mask after the LOW→HIGH reconcile boundary."""
    if not isinstance(av_latent, dict) or not isinstance(source_latent, dict):
        _fail("high_latent_shape", "HIGH 蒙版恢复需要两个 H3 nested AV latent")
    try:
        video, audio = av_latent["samples"].unbind()
        source_video, source_audio = source_latent["samples"].unbind()
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        _fail("high_latent_shape", f"无法读取 H3 nested AV latent：{error}")
    if (
        not isinstance(video, torch.Tensor)
        or not isinstance(audio, torch.Tensor)
        or not isinstance(source_video, torch.Tensor)
        or not isinstance(source_audio, torch.Tensor)
        or tuple(source_video.shape) != tuple(video.shape)
        or tuple(source_audio.shape) != tuple(audio.shape)
        or video.ndim != 5
        or audio.ndim != 4
        or video.shape[1] != H3_VIDEO_CHANNELS
        or audio.shape[1:3] != (H3_AUDIO_CHANNELS, H3_AUDIO_STEREO)
    ):
        _fail("high_latent_shape", "C1 HIGH 只支持与源 latent 同一 1x H3 AV 几何")
    if not all(
        tensor.is_floating_point() and torch.isfinite(tensor).all().item()
        for tensor in (video, audio, source_video, source_audio)
    ):
        _fail("high_latent_values", "C1 HIGH latent 必须是有限浮点张量")
    if (
        not isinstance(model_mask, torch.Tensor)
        or model_mask.ndim != 3
        or not model_mask.is_floating_point()
        or model_mask.is_complex()
        or not torch.isfinite(model_mask).all().item()
        or (model_mask.numel() and (model_mask.min().item() < 0 or model_mask.max().item() > 1))
    ):
        _fail("high_mask_shape", "C1 HIGH 需要模型帧 MASK [帧,高,宽]")
    expected_mask_shape = (model_mask.shape[0], video.shape[3] * 16, video.shape[4] * 16)
    if tuple(model_mask.shape) != expected_mask_shape:
        _fail(
            "high_mask_geometry",
            f"C1 HIGH MASK 必须与同一 1x H3 画布一致：需要 {expected_mask_shape}，实际 {tuple(model_mask.shape)}",
        )

    video_mask = _h3_video_noise_mask(
        model_mask, (video.shape[2], video.shape[3], video.shape[4]),
    ).to(device=video.device, dtype=video.dtype).expand_as(video)
    source_video = source_video.to(device=video.device, dtype=video.dtype)
    source_audio = source_audio.to(device=audio.device, dtype=audio.dtype)
    merged_video = torch.where(
        video_mask <= 0,
        source_video,
        torch.where(video_mask >= 1, video, video * video_mask + source_video * (1 - video_mask)),
    )
    audio_mask = torch.zeros_like(source_audio)
    try:
        import comfy.nested_tensor
    except ImportError:
        _fail("runtime_dependency", "当前 ComfyUI 运行时缺少 nested_tensor")
    result = dict(av_latent)
    result["samples"] = comfy.nested_tensor.NestedTensor((merged_video, source_audio))
    result["noise_mask"] = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
    evidence = {
        "schema_version": 1,
        "kind": "zv-h3-high-mask-restore",
        "mask_processing_version": MASK_PROCESSING_VERSION,
        "geometry_policy": "same_canvas_1x",
        "source_policy": "black_source_white_reconciled",
        "audio_policy": "locked_source_latent",
        "video_latent_shape": list(video.shape),
        "audio_latent_shape": list(audio.shape),
        "video_noise_mask_shape": list(video_mask.shape),
        "pixel_model_mask_content": _mask_content_summary(model_mask),
        "video_noise_mask_content": _tensor_content_summary(video_mask),
    }
    return result, json.dumps(
        evidence, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    )


def compose_h3_masked_frames(generated_frames, source_frames, model_mask):
    """Restore locked pixels after decode while preserving generated white-mask pixels."""
    if (
        not isinstance(generated_frames, torch.Tensor)
        or not isinstance(source_frames, torch.Tensor)
        or not isinstance(model_mask, torch.Tensor)
        or generated_frames.ndim != 4
        or generated_frames.shape[-1] != 3
        or tuple(source_frames.shape) != tuple(generated_frames.shape)
        or tuple(model_mask.shape) != tuple(generated_frames.shape[:3])
    ):
        _fail("compose_shape", "C1 像素回贴要求 generated/source/MASK 使用同一 1x 模型画布")
    if not all(
        tensor.is_floating_point() and torch.isfinite(tensor).all().item()
        for tensor in (generated_frames, source_frames, model_mask)
    ):
        _fail("compose_values", "C1 像素回贴输入必须是有限浮点张量")
    if model_mask.numel() and (model_mask.min().item() < 0 or model_mask.max().item() > 1):
        _fail("compose_values", "C1 像素回贴 MASK 必须位于 0–1")

    source = source_frames.to(device=generated_frames.device, dtype=generated_frames.dtype)
    mask = model_mask.to(device=generated_frames.device, dtype=generated_frames.dtype).unsqueeze(-1)
    composed = torch.where(
        mask <= 0,
        source,
        torch.where(mask >= 1, generated_frames, generated_frames * mask + source * (1 - mask)),
    )
    evidence = {
        "schema_version": 1,
        "kind": "zv-h3-masked-frame-compose",
        "mask_processing_version": MASK_PROCESSING_VERSION,
        "geometry_policy": "same_canvas_1x",
        "pixel_policy": "black_source_white_generated_soft_blend",
        "frame_shape": list(composed.shape),
        "pixel_model_mask_content": _mask_content_summary(model_mask),
    }
    return composed, json.dumps(
        evidence, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    )


class ZVSegmentVideoMaskSource:
    """Decode a bounded scope for an external mask model."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "segment_plan": ("ZV_SEGMENT_PLAN",),
                "clip_id": ("STRING", {"default": ""}),
                "range_mode": (["全片", "当前分段"],),
                "segment_index": ("INT", {"default": 1, "min": 1, "max": 4096}),
            },
        }

    RETURN_TYPES = ("IMAGE", "ZV_MASK_SOURCE", "AUDIO")
    RETURN_NAMES = ("frames", "source_info", "source_audio")
    FUNCTION = "read"
    CATEGORY = "ZV/视频创作/长视频"

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        # The media registry is checked on every execution.
        return float("nan")

    def read(self, segment_plan, clip_id, range_mode, segment_index):
        return read_segment_video(segment_plan, clip_id, range_mode, segment_index)


class ZVMaskedSegmentBundle:
    """Bind an external standard MASK to its immutable segment-plan clock."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "segment_plan": ("ZV_SEGMENT_PLAN",),
                "mask": ("MASK",),
                "source_info": ("ZV_MASK_SOURCE",),
                "mode": (["固定区域", "逐帧"],),
            },
        }

    RETURN_TYPES = ("ZV_MASKED_SEGMENT_BUNDLE", "STRING")
    RETURN_NAMES = ("masked_segments", "report")
    FUNCTION = "build"
    CATEGORY = "ZV/视频创作/长视频"

    def build(self, segment_plan, mask, source_info, mode):
        return build_masked_segment_bundle(segment_plan, mask, source_info, mode)


class ZVSegmentMaskSlice:
    """Select the standard MASK for the current finite-loop iteration."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "masked_segments": ("ZV_MASKED_SEGMENT_BUNDLE",),
            "segment_plan": ("ZV_SEGMENT_PLAN",),
            "segment_index": ("INT", {"forceInput": True}),
        }}

    RETURN_TYPES = ("MASK", "STRING")
    RETURN_NAMES = ("mask", "clock_evidence_json")
    FUNCTION = "slice"
    CATEGORY = "ZV/视频创作/长视频"

    def slice(self, masked_segments, segment_plan, segment_index):
        mask, evidence = slice_mask_for_segment(masked_segments, segment_plan, segment_index + 1)
        return mask, json.dumps(evidence, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class ZVH3MaskedSegmentLatent:
    """Encode one verified full-frame source segment into an H3 masked AV latent."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "segment_plan": ("ZV_SEGMENT_PLAN",),
                "segment_index": ("INT", {"forceInput": True}),
                "source_frames": ("IMAGE",),
                "source_audio": ("AUDIO",),
                "masked_segments": ("ZV_MASKED_SEGMENT_BUNDLE",),
                "video_vae": ("VAE",),
                "audio_vae": ("VAE",),
                "no_source_audio_policy": (list(NO_SOURCE_AUDIO_POLICIES),),
            },
        }

    RETURN_TYPES = ("LATENT", "IMAGE", "MASK", "AUDIO", "AUDIO", "STRING", "INT")
    RETURN_NAMES = (
        "av_latent", "model_frames", "model_mask", "model_audio", "final_audio",
        "clock_evidence_json", "model_length",
    )
    FUNCTION = "prepare"
    CATEGORY = "ZV/视频创作/长视频"

    def prepare(
        self,
        segment_plan,
        segment_index,
        source_frames,
        source_audio,
        masked_segments,
        video_vae,
        audio_vae,
        no_source_audio_policy,
    ):
        result = prepare_h3_masked_segment_latent(
            segment_plan,
            segment_index + 1,
            source_frames,
            source_audio,
            masked_segments,
            video_vae,
            audio_vae,
            no_source_audio_policy,
        )
        return (*result, json.loads(result[-1])["model_length"])


class ZVH3MaskedLatentRestore:
    """Reapply the C1 source latent and mask after two-pass HIGH reconcile."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "av_latent": ("LATENT",),
            "source_latent": ("LATENT",),
            "model_mask": ("MASK",),
        }}

    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("av_latent", "evidence_json")
    FUNCTION = "restore"
    CATEGORY = "ZV/视频创作/长视频"

    def restore(self, av_latent, source_latent, model_mask):
        return restore_h3_masked_latent(av_latent, source_latent, model_mask)


class ZVH3MaskedFrameCompose:
    """Compose decoded redraw pixels over the clock-bound source canvas."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "generated_frames": ("IMAGE",),
            "source_frames": ("IMAGE",),
            "model_mask": ("MASK",),
        }}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("frames", "evidence_json")
    FUNCTION = "compose"
    CATEGORY = "ZV/视频创作/长视频"

    def compose(self, generated_frames, source_frames, model_mask):
        return compose_h3_masked_frames(generated_frames, source_frames, model_mask)


__all__ = [
    "MaskSegmentError", "ZVH3MaskedFrameCompose", "ZVH3MaskedLatentRestore",
    "ZVH3MaskedSegmentLatent", "ZVMaskedSegmentBundle",
    "ZVSegmentMaskSlice", "ZVSegmentVideoMaskSource", "build_masked_segment_bundle",
    "compose_h3_masked_frames", "prepare_h3_masked_segment_latent", "read_segment_video",
    "restore_h3_masked_latent", "slice_mask_for_segment", "validate_mask_source",
]
