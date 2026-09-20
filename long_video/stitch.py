"""Exact segment trimming plus disk-backed long-video assembly.

Only a single model result is accepted in memory at a time.  Useful frames are
encoded immediately, while the small tail needed by the next guide is stored as
a lossless NumPy artifact.  The loop carry therefore contains paths and scalar
metadata, never accumulated IMAGE or AUDIO tensors.
"""

from __future__ import annotations

import copy
import math
import os
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
import uuid

import numpy as np

from .execution import (
    ExecutionPlanError,
    RUN_AUDIO_CONTRACT,
    append_result,
    assert_run_matches_context,
    new_run_manifest,
    normalize_execution_plan,
    normalize_run_manifest,
    segment_context,
)
from .masks import (
    H3_AUDIO_CHANNELS,
    H3_AUDIO_LATENT_FPS,
    H3_AUDIO_STEREO,
    H3_FPS,
    H3_SPATIAL_TOKEN,
    H3_TEMPORAL_GROUP_PATTERN,
    H3_VIDEO_CHANNELS,
    H3_VIDEO_VAE_GEOMETRY,
    MASK_PROCESSING_VERSION,
)


ARTIFACT_DIRECTORY = "zv_long_video"
MAX_GUIDE_BYTES = 512 * 1024 * 1024
OUTPUT_AUDIO_SAMPLE_RATE = RUN_AUDIO_CONTRACT["sample_rate"]
OUTPUT_AUDIO_CHANNELS = RUN_AUDIO_CONTRACT["channels"]
MAX_RESAMPLE_KERNEL_ELEMENTS = 8_000_000
MASK_RUNTIME_VERSION = MASK_PROCESSING_VERSION
RUN_MANIFEST_FILENAME = "run-manifest.json"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class StitchError(ValueError):
    """Raised when generated media cannot satisfy the planned timeline."""


def _error(message):
    raise StitchError(message)


def _shape(value, name, dimensions):
    shape = getattr(value, "shape", None)
    if shape is None or len(shape) != dimensions:
        _error(f"{name} 必须是 {dimensions} 维张量")
    return tuple(int(part) for part in shape)


def _audio_parts(audio, name="audio"):
    if not isinstance(audio, Mapping):
        _error(f"{name} 必须是 ComfyUI AUDIO")
    sample_rate = audio.get("sample_rate")
    waveform = audio.get("waveform")
    if type(sample_rate) is not int or sample_rate <= 0:
        _error(f"{name}.sample_rate 必须是正整数")
    batch, channels, samples = _shape(waveform, f"{name}.waveform", 3)
    if batch != 1 or channels <= 0 or samples <= 0:
        _error(f"{name}.waveform 必须是 [1, channels, samples] 的非空张量")
    return waveform, sample_rate, channels, samples


def _resample_kernel_elements(source_rate, target_rate):
    """Bound torchaudio's polyphase sinc kernel before it allocates the grid."""
    divisor = math.gcd(source_rate, target_rate)
    source = source_rate // divisor
    target = target_rate // divisor
    base = min(source, target) * 0.99
    width = math.ceil(6 * source / base)
    return target * (source + 2 * width)


def _required_audio_end(context, sample_rate):
    fps = context["fps"]
    windows = [context["contribution"]]
    if context.get("next_guide") is not None:
        windows.append(context["next_guide"])
    local_end = max(window["local_end_frame"] for window in windows)
    return round(local_end * sample_rate / fps)


def normalize_output_audio(audio, context):
    """Apply the fixed long-video audio contract before timeline slicing."""

    import torch

    if audio is None:
        samples = round(
            context["frame_count"] * OUTPUT_AUDIO_SAMPLE_RATE / context["fps"]
        )
        return {
            "waveform": torch.zeros((1, OUTPUT_AUDIO_CHANNELS, samples), dtype=torch.float32),
            "sample_rate": OUTPUT_AUDIO_SAMPLE_RATE,
            "_zv_source_sample_rate": None,
            "_zv_source_channels": None,
            "_zv_audio_normalized": False,
            "_zv_audio_policy": "clocked_silence",
            "_zv_resample_adjustment_samples": 0,
        }

    import torchaudio

    waveform, source_rate, source_channels, _samples = _audio_parts(audio)
    if not waveform.is_floating_point() or waveform.is_complex():
        _error("audio.waveform 必须是浮点实数张量")
    if not torch.isfinite(waveform).all().item():
        _error("audio.waveform 包含 NaN 或无穷值")
    required_source_end = _required_audio_end(context, source_rate)
    if waveform.shape[-1] < required_source_end:
        _error(
            f"第 {context['order']} 段源音频不足：按 {source_rate} Hz 帧时钟至少需要 "
            f"{required_source_end} 个采样，实际只有 {waveform.shape[-1]} 个"
        )
    if source_channels == 1:
        waveform = waveform.repeat(1, OUTPUT_AUDIO_CHANNELS, 1)
    elif source_channels != OUTPUT_AUDIO_CHANNELS:
        _error("长视频音频只接受 mono 或 stereo；其他声道布局请先显式下混")
    if source_rate != OUTPUT_AUDIO_SAMPLE_RATE:
        kernel_elements = _resample_kernel_elements(
            source_rate, OUTPUT_AUDIO_SAMPLE_RATE,
        )
        if kernel_elements > MAX_RESAMPLE_KERNEL_ELEMENTS:
            _error(
                "音频采样率与 44100 Hz 的比值会产生过大的 sinc 重采样核；"
                "请先转换为常用采样率（如 32000、44100、48000 或 96000 Hz）"
            )
        waveform = torchaudio.functional.resample(
            waveform, source_rate, OUTPUT_AUDIO_SAMPLE_RATE,
        )
    required_output_end = _required_audio_end(context, OUTPUT_AUDIO_SAMPLE_RATE)
    resample_adjustment = required_output_end - int(waveform.shape[-1])
    if resample_adjustment > 2:
        _error(
            f"第 {context['order']} 段音频重采样后短缺 {resample_adjustment} 个采样，"
            "超出机械舍入边界"
        )
    if resample_adjustment > 0:
        waveform = torch.cat(
            (waveform, waveform[..., -1:].repeat(1, 1, resample_adjustment)),
            dim=-1,
        )
    else:
        resample_adjustment = 0
    return {
        "waveform": waveform.detach().contiguous(),
        "sample_rate": OUTPUT_AUDIO_SAMPLE_RATE,
        "_zv_source_sample_rate": source_rate,
        "_zv_source_channels": source_channels,
        "_zv_audio_normalized": (
            source_rate != OUTPUT_AUDIO_SAMPLE_RATE
            or source_channels != OUTPUT_AUDIO_CHANNELS
        ),
        "_zv_audio_policy": "selected_content",
        "_zv_resample_adjustment_samples": resample_adjustment,
    }


def _slice_audio(audio, context, *, guide=False):
    if audio is None:
        return None
    waveform, sample_rate, _channels, samples = _audio_parts(audio)
    fps = context["fps"]
    window = context["next_guide"] if guide else context["contribution"]
    if window is None:
        return None
    local_start = window["local_start_frame"]
    local_end = window["local_end_frame"]
    source_start = round(local_start * sample_rate / fps)
    source_end = round(local_end * sample_rate / fps)
    global_start = window["global_start_frame"] if guide else window["output_start_frame"]
    global_end = window["global_end_frame"] if guide else window["output_end_frame"]
    desired = round(global_end * sample_rate / fps) - round(global_start * sample_rate / fps)
    if source_start < 0 or source_end <= source_start or source_start >= samples:
        _error(
            f"第 {context['order']} 段音频不足：需要采样 {source_start}:{source_end}，"
            f"实际只有 {samples} 个采样"
        )
    if source_end > samples:
        _error(
            f"第 {context['order']} 段音频不足：需要采样 {source_start}:{source_end}，"
            f"实际只有 {samples} 个采样"
        )
    sliced = waveform[..., source_start:source_end]
    adjustment = desired - int(sliced.shape[-1])
    if abs(adjustment) > 2:
        _error(f"第 {context['order']} 段音频全局采样相位差 {adjustment} 超出机械舍入边界")
    if adjustment < 0:
        sliced = sliced[..., :desired]
    elif adjustment > 0:
        # Q(global_end)-Q(global_start) and Q(local_end)-Q(local_start)
        # can differ by two samples at half-sample ties. Repeat the last real
        # sample to give this contribution its exact global sample interval.
        import torch
        sliced = torch.cat((sliced, sliced[..., -1:].repeat(1, 1, adjustment)), dim=-1)
    return {
        "waveform": sliced.detach().contiguous(),
        "sample_rate": sample_rate,
        "_zv_phase_adjustment_samples": adjustment,
        "_zv_source_sample_rate": audio["_zv_source_sample_rate"],
        "_zv_source_channels": audio["_zv_source_channels"],
        "_zv_audio_normalized": audio["_zv_audio_normalized"],
        "_zv_audio_policy": audio["_zv_audio_policy"],
        "_zv_resample_adjustment_samples": audio["_zv_resample_adjustment_samples"],
    }


def slice_segment_result(context, images, audio=None):
    """Trim model padding, overlap, and target tail from one model result."""

    if not isinstance(context, Mapping) or context.get("schema_version") != 1:
        _error("需要 ZV 单段执行上下文 v1")
    actual_frames, height, width, channels = _shape(images, "images", 4)
    if height <= 0 or width <= 0 or channels != 3:
        _error("images 必须是非空的 RGB IMAGE 张量")
    requested = context["frame_count"]
    if actual_frames < requested:
        _error(
            f"第 {context['order']} 段只生成了 {actual_frames} 帧，"
            f"少于计划请求的 {requested} 帧"
        )
    useful = images[:requested]
    contribution = context["contribution"]
    output_images = useful[
        contribution["local_start_frame"]:contribution["local_end_frame"]
    ].detach().contiguous()
    if int(output_images.shape[0]) != contribution["frame_count"]:
        _error(f"第 {context['order']} 段裁切后的贡献帧数不正确")
    guide_images = None
    if context.get("next_guide") is not None:
        guide = context["next_guide"]
        guide_images = useful[
            guide["local_start_frame"]:guide["local_end_frame"]
        ].detach().contiguous()
        if int(guide_images.shape[0]) != guide["frame_count"]:
            _error(f"第 {context['order']} 段无法提供完整的下一段 guide")
    normalized_audio = normalize_output_audio(audio, context)
    return {
        "images": output_images,
        "audio": _slice_audio(normalized_audio, context),
        "guide_images": guide_images,
        "guide_audio": _slice_audio(normalized_audio, context, guide=True),
        "actual_result_frames": actual_frames,
        "height": height,
        "width": width,
        "channels": channels,
    }


def stitch_tensors(execution_plan, results):
    """Reference in-memory stitcher for unit tests and short diagnostic clips.

    Production long-video nodes intentionally do not call this function.
    """

    plan = normalize_execution_plan(execution_plan)
    rows = plan["segments"]
    if isinstance(results, Mapping):
        ordered = []
        for row in rows:
            if row["segment_id"] not in results:
                _error(f"缺少分段结果 {row['segment_id']}")
            ordered.append(results[row["segment_id"]])
    elif isinstance(results, Sequence) and not isinstance(results, (str, bytes, bytearray)):
        if len(results) != len(rows):
            _error("结果数量与执行计划不一致")
        ordered = list(results)
    else:
        _error("results 必须是按段数组或 segment_id 映射")

    image_parts = []
    audio_parts = []
    sample_rate = None
    for index, raw_result in enumerate(ordered):
        if isinstance(raw_result, Mapping):
            images = raw_result.get("images")
            audio = raw_result.get("audio")
        else:
            images = raw_result
            audio = None
        sliced = slice_segment_result(segment_context(plan, index), images, audio)
        image_parts.append(sliced["images"])
        audio_parts.append(sliced["audio"])
        if sliced["audio"] is not None:
            current_rate = sliced["audio"]["sample_rate"]
            if sample_rate is None:
                sample_rate = current_rate
            elif sample_rate != current_rate:
                _error("所有分段音频的采样率必须相同")

    if any(value is None for value in audio_parts) and any(value is not None for value in audio_parts):
        _error("分段音频必须全部存在或全部省略")
    try:
        import torch

        images = torch.cat(image_parts, dim=0)
    except RuntimeError as error:
        raise StitchError("分段图像尺寸不一致，无法拼接") from error
    target = plan["segment_plan"]["target_frame_count"]
    if int(images.shape[0]) != target:
        _error(f"拼接得到 {images.shape[0]} 帧，与目标 {target} 帧不一致")
    audio = None
    if audio_parts and all(value is not None for value in audio_parts):
        try:
            waveform = torch.cat([value["waveform"] for value in audio_parts], dim=-1)
        except RuntimeError as error:
            raise StitchError("分段音频声道不一致，无法拼接") from error
        expected_samples = round(target * sample_rate / plan["segment_plan"]["fps"])
        if int(waveform.shape[-1]) != expected_samples:
            _error(f"拼接音频为 {waveform.shape[-1]} 采样，预期 {expected_samples} 采样")
        audio = {"waveform": waveform, "sample_rate": sample_rate}
    return {"images": images, "audio": audio, "fps": plan["segment_plan"]["fps"]}


def _resolved(path):
    return Path(path).expanduser().resolve(strict=False)


def _is_within(root, path):
    root_text = os.path.normcase(str(_resolved(root)))
    path_text = os.path.normcase(str(_resolved(path)))
    try:
        return os.path.commonpath((root_text, path_text)) == root_text
    except ValueError:
        return False


def _safe_artifact_path(root, path, *, suffix=None, must_exist=False):
    root = _resolved(root)
    path = _resolved(path)
    if not _is_within(root, path):
        _error(f"运行产物路径越界：{path}")
    if suffix is not None and path.suffix.lower() != suffix:
        _error(f"运行产物扩展名必须是 {suffix}")
    if must_exist and (not path.is_file() or path.stat().st_size <= 0):
        _error(f"运行产物不存在或为空：{path}")
    return path


def _artifact_root(temp_root):
    root = _resolved(temp_root)
    root.mkdir(parents=True, exist_ok=True)
    artifacts = root / ARTIFACT_DIRECTORY
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts.resolve(strict=True)


def _run_directory(context, previous_run, temp_root):
    artifacts = _artifact_root(temp_root)
    if previous_run is None:
        if context["segment_index"] != 0:
            _error("非第一段缺少上一轮运行清单")
        run_id = uuid.uuid4().hex
        run_dir = artifacts / f"run-{run_id}"
        run_dir.mkdir(parents=False, exist_ok=False)
        return new_run_manifest(context, run_dir, run_id), run_dir
    manifest = assert_run_matches_context(context, previous_run)
    run_dir = _safe_artifact_path(artifacts, manifest["run_dir"])
    if not run_dir.is_dir():
        _error("上一轮运行目录不存在")
    return manifest, run_dir


def _as_numpy(tensor):
    return tensor.detach().to(device="cpu", dtype=getattr(__import__("torch"), "float32")).contiguous().numpy()


def _write_npy_atomic(path, tensor):
    if tensor.numel() > MAX_GUIDE_BYTES:
        _error("下一段 guide 超过 512 MiB 磁盘预算，请降低分辨率或重叠帧数")
    import torch
    if not torch.isfinite(tensor).all().item() or tensor.numel() and (tensor.min().item() < 0 or tensor.max().item() > 1):
        _error("guide IMAGE 必须是有限的 0–1 数值")
    temporary = path.with_name("." + path.stem + ".part.npy")
    try:
        with temporary.open("wb") as handle:
            values = tensor.detach().to(device="cpu", dtype=torch.float32).clamp(0, 1)
            np.save(handle, (values * 255).round().to(dtype=torch.uint8).contiguous().numpy(), allow_pickle=False)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def _write_audio_atomic(path, audio):
    temporary = path.with_name("." + path.stem + ".part.npz")
    waveform = _as_numpy(audio["waveform"])
    try:
        with temporary.open("wb") as handle:
            np.savez(handle, waveform=waveform, sample_rate=np.int64(audio["sample_rate"]))
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def _write_json_atomic(path, value):
    temporary = path.with_name("." + path.stem + ".part.json")
    try:
        try:
            payload = json.dumps(
                value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2,
            ) + "\n"
        except (TypeError, ValueError, UnicodeError) as error:
            raise StitchError("运行清单必须是有限标量/字符串组成的纯 JSON，不能包含张量") from error
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def _content_summary(value, name, dimensions):
    if not isinstance(value, Mapping) or set(value) != {
        "shape", "canonical_dtype", "sha256", "minimum", "maximum", "nonzero",
    }:
        _error(f"{name} 缺少完整内容摘要")
    shape = value["shape"]
    if (
        not isinstance(shape, list)
        or len(shape) != dimensions
        or any(type(part) is not int or part < 1 for part in shape)
        or value["canonical_dtype"] != "float32"
        or not isinstance(value["sha256"], str)
        or not _HEX64.fullmatch(value["sha256"])
        or isinstance(value["minimum"], bool)
        or not isinstance(value["minimum"], (int, float))
        or isinstance(value["maximum"], bool)
        or not isinstance(value["maximum"], (int, float))
        or not math.isfinite(value["minimum"])
        or not math.isfinite(value["maximum"])
        or not 0 <= value["minimum"] <= value["maximum"] <= 1
        or type(value["nonzero"]) is not int
        or not 0 <= value["nonzero"] <= math.prod(shape)
    ):
        _error(f"{name} 内容摘要无效")
    return dict(value)


def _mask_summary(value, name):
    return _content_summary(value, name, 3)


def _video_noise_mask_summary(value, name):
    return _content_summary(value, name, 5)


def _mask_report(value, name):
    if not isinstance(value, str) or not value.strip():
        _error(f"C1 运行缺少 {name} 证据")
    try:
        report = json.loads(value)
    except (TypeError, ValueError) as error:
        raise StitchError(f"C1 {name} 证据不是有效 JSON") from error
    if not isinstance(report, Mapping):
        _error(f"C1 {name} 证据必须是对象")
    return report


def build_mask_runtime_evidence(context, source_json="", high_json="", compose_json=""):
    """Reduce three connected C1 reports to scalar/string run-manifest evidence."""
    values = (source_json, high_json, compose_json)
    present = [isinstance(value, str) and bool(value.strip()) for value in values]
    if not any(present):
        return None
    if not all(present):
        _error("C1 运行必须同时连接源、HIGH 恢复和像素回贴证据")
    source = _mask_report(source_json, "源 latent")
    high = _mask_report(high_json, "HIGH 恢复")
    compose = _mask_report(compose_json, "像素回贴")
    if (
        source.get("kind") != "zv-h3-masked-segment-latent"
        or source.get("plan_revision") != context["plan_revision"]
        or source.get("segment_id") != context["segment_id"]
        or source.get("segment_index") != context["segment_index"] + 1
        or source.get("model_length") != context["model_length"]
    ):
        _error("C1 源 latent 证据未绑定当前 plan/segment/model_length")
    if high.get("kind") != "zv-h3-high-mask-restore" or compose.get("kind") != "zv-h3-masked-frame-compose":
        _error("C1 HIGH/像素回贴证据种类不正确")
    versions = {
        source.get("mask_processing_version"),
        high.get("mask_processing_version"),
        compose.get("mask_processing_version"),
    }
    if versions != {MASK_RUNTIME_VERSION}:
        _error("C1 MASK 处理版本不一致")
    raw_summary = _mask_summary(source.get("mask_content"), "raw")
    pixel_mask = _mask_summary(source.get("pixel_model_mask_content"), "source pixel model MASK")
    if pixel_mask != _mask_summary(high.get("pixel_model_mask_content"), "HIGH pixel model MASK"):
        _error("C1 源 latent 与 HIGH 没有消费同一像素域 model MASK")
    if pixel_mask != _mask_summary(compose.get("pixel_model_mask_content"), "compose pixel model MASK"):
        _error("C1 HIGH 与像素回贴没有消费同一像素域 model MASK")
    if pixel_mask["shape"][0] != context["model_length"]:
        _error("C1 像素域 model MASK 帧数与当前 H3 model_length 不一致")
    source_noise = _video_noise_mask_summary(
        source.get("video_noise_mask_content"), "source video_noise_mask",
    )
    high_noise = _video_noise_mask_summary(
        high.get("video_noise_mask_content"), "HIGH video_noise_mask",
    )
    if source_noise != high_noise:
        _error("C1 LOW 源 latent 与 HIGH 没有使用同一实际 video_noise_mask")
    if source_noise["shape"] != source.get("video_noise_mask_shape"):
        _error("C1 源 video_noise_mask 摘要形状与报告不一致")
    if high_noise["shape"] != high.get("video_noise_mask_shape"):
        _error("C1 HIGH video_noise_mask 摘要形状与报告不一致")
    model_contract = source.get("model_contract")
    expected_model_contract = {
        "schema_version": 1,
        "fps": H3_FPS,
        "audio_latent_fps": H3_AUDIO_LATENT_FPS,
        "video_channels": H3_VIDEO_CHANNELS,
        "audio_channels": H3_AUDIO_CHANNELS,
        "audio_stereo": H3_AUDIO_STEREO,
        "video_vae_geometry": H3_VIDEO_VAE_GEOMETRY,
        "temporal_group_pattern": list(H3_TEMPORAL_GROUP_PATTERN),
        "spatial_token": list(H3_SPATIAL_TOKEN),
    }
    if model_contract != expected_model_contract:
        _error("C1 源 latent 缺少已验证的 H3 模型几何合同")
    mask_clock = source.get("mask_clock")
    if (
        not isinstance(mask_clock, Mapping)
        or mask_clock.get("plan_revision") != context["plan_revision"]
        or mask_clock.get("segment_id") != context["segment_id"]
        or mask_clock.get("segment_index") != context["segment_index"] + 1
        or mask_clock.get("mask_content") != raw_summary
    ):
        _error("C1 分段 MASK 时钟证据未绑定当前 segment")
    for field in ("source_fingerprint", "sampling_fingerprint", "masked_bundle_fingerprint"):
        value = source.get(field)
        if not isinstance(value, str) or not _HEX64.fullmatch(value):
            _error(f"C1 源证据缺少有效 {field}")
    if source["source_fingerprint"] != context.get("source_fingerprint"):
        _error("C1 源证据未绑定当前分段计划的 source_fingerprint")
    return {
        "schema_version": 1,
        "kind": "zv-h3-mask-runtime-evidence",
        "processing_version": MASK_RUNTIME_VERSION,
        "plan_revision": context["plan_revision"],
        "segment_id": context["segment_id"],
        "segment_index": context["segment_index"],
        "source_fingerprint": source["source_fingerprint"],
        "sampling_fingerprint": source["sampling_fingerprint"],
        "masked_bundle_fingerprint": source["masked_bundle_fingerprint"],
        "raw_mask_content": raw_summary,
        "pixel_model_mask_content": pixel_mask,
        "source_video_noise_mask_content": source_noise,
        "effective_high_video_noise_mask_content": high_noise,
        "model_contract": copy.deepcopy(model_contract),
        "plan_target_tail_repeat_frames": source.get("plan_target_tail_repeat_frames"),
        "model_grid_repeat_frames": source.get("model_grid_repeat_frames"),
        "source_frame_offset": source.get("source_frame_offset"),
        "source_video_latent_shape": source.get("video_latent_shape"),
        "high_video_latent_shape": high.get("video_latent_shape"),
        "high_video_noise_mask_shape": high.get("video_noise_mask_shape"),
        "high_geometry_policy": high.get("geometry_policy"),
        "high_source_policy": high.get("source_policy"),
        "high_audio_policy": high.get("audio_policy"),
        "compose_frame_shape": compose.get("frame_shape"),
        "compose_pixel_policy": compose.get("pixel_policy"),
    }


def _validate_mask_runtime_evidence(context, value):
    if value is None:
        return None
    if not isinstance(value, Mapping) or value.get("kind") != "zv-h3-mask-runtime-evidence":
        _error("运行清单 C1 MASK 证据无效")
    if (
        value.get("schema_version") != 1
        or value.get("processing_version") != MASK_RUNTIME_VERSION
        or value.get("plan_revision") != context["plan_revision"]
        or value.get("segment_id") != context["segment_id"]
        or value.get("segment_index") != context["segment_index"]
        or value.get("source_fingerprint") != context.get("source_fingerprint")
    ):
        _error("运行清单 C1 MASK 证据未绑定当前分段")
    _mask_summary(value.get("raw_mask_content"), "run raw")
    pixel_mask = _mask_summary(value.get("pixel_model_mask_content"), "run pixel model MASK")
    if pixel_mask["shape"][0] != context["model_length"]:
        _error("运行清单 C1 像素域 model MASK 帧数错误")
    source_noise = _video_noise_mask_summary(
        value.get("source_video_noise_mask_content"), "run source video_noise_mask",
    )
    high_noise = _video_noise_mask_summary(
        value.get("effective_high_video_noise_mask_content"), "run HIGH video_noise_mask",
    )
    if source_noise != high_noise:
        _error("运行清单 C1 LOW/HIGH 实际 video_noise_mask 不一致")
    if source_noise["shape"] != value.get("source_video_latent_shape"):
        _error("运行清单 C1 source video_noise_mask 与 latent 形状不一致")
    if high_noise["shape"] != value.get("high_video_latent_shape"):
        _error("运行清单 C1 HIGH video_noise_mask 与 latent 形状不一致")
    expected_model_contract = {
        "schema_version": 1,
        "fps": H3_FPS,
        "audio_latent_fps": H3_AUDIO_LATENT_FPS,
        "video_channels": H3_VIDEO_CHANNELS,
        "audio_channels": H3_AUDIO_CHANNELS,
        "audio_stereo": H3_AUDIO_STEREO,
        "video_vae_geometry": H3_VIDEO_VAE_GEOMETRY,
        "temporal_group_pattern": list(H3_TEMPORAL_GROUP_PATTERN),
        "spatial_token": list(H3_SPATIAL_TOKEN),
    }
    if value.get("model_contract") != expected_model_contract:
        _error("运行清单 C1 H3 模型几何合同无效")
    for field in ("source_fingerprint", "sampling_fingerprint", "masked_bundle_fingerprint"):
        field_value = value.get(field)
        if not isinstance(field_value, str) or not _HEX64.fullmatch(field_value):
            _error(f"运行清单 C1 MASK 缺少有效 {field}")
    return dict(value)


def persist_segment(
    context,
    images,
    audio,
    previous_run,
    temp_root,
    encoder,
    guide_application_evidence="",
    mask_runtime_evidence=None,
):
    """Encode one useful contribution and append its paths to the loop carry.

    ``encoder`` receives ``(images, audio, fps, path)`` and may return probe
    metadata.  It must close the output before returning so the file can be
    atomically renamed on Windows.
    """

    if not callable(encoder):
        _error("encoder 必须可调用")
    mask_runtime_evidence = _validate_mask_runtime_evidence(context, mask_runtime_evidence)
    sliced = slice_segment_result(context, images, audio)
    manifest, run_dir = _run_directory(context, previous_run, temp_root)
    token = uuid.uuid4().hex[:12]
    prefix = f"segment-{context['order']:04d}-{token}"
    final_video = _safe_artifact_path(run_dir, run_dir / f"{prefix}.mp4", suffix=".mp4")
    temporary_video = _safe_artifact_path(run_dir, run_dir / f".{prefix}.part.mp4", suffix=".mp4")
    created = []
    try:
        probe = encoder(sliced["images"], sliced["audio"], context["fps"], str(temporary_video))
        if not temporary_video.is_file() or temporary_video.stat().st_size <= 0:
            _error("视频编码器没有写出有效的分段文件")
        if probe is not None and not isinstance(probe, Mapping):
            _error("视频编码器返回的探测信息必须是对象")
        probe = dict(probe or {})
        encoded_frames = probe.get("encoded_frame_count")
        expected_frames = context["contribution"]["frame_count"]
        if encoded_frames is not None and encoded_frames != expected_frames:
            _error(f"编码文件为 {encoded_frames} 帧，预期 {expected_frames} 帧")
        os.replace(temporary_video, final_video)
        created.append(final_video)

        guide_record = None
        if sliced["guide_images"] is not None:
            guide = context["next_guide"]
            frames_path = _safe_artifact_path(run_dir, run_dir / f"{prefix}-guide.npy", suffix=".npy")
            _write_npy_atomic(frames_path, sliced["guide_images"])
            created.append(frames_path)
            audio_path = None
            if sliced["guide_audio"] is not None:
                audio_path = _safe_artifact_path(run_dir, run_dir / f"{prefix}-guide-audio.npz", suffix=".npz")
                _write_audio_atomic(audio_path, sliced["guide_audio"])
                created.append(audio_path)
            guide_record = {
                "frames_path": str(frames_path),
                "audio_path": str(audio_path) if audio_path is not None else None,
                "frame_count": guide["frame_count"],
                "global_start_frame": guide["global_start_frame"],
                "global_end_frame": guide["global_end_frame"],
                "target_segment_id": guide["target_segment_id"],
                "audio_sample_rate": sliced["guide_audio"]["sample_rate"] if sliced["guide_audio"] is not None else None,
                "audio_phase_adjustment_samples": sliced["guide_audio"].get("_zv_phase_adjustment_samples", 0) if sliced["guide_audio"] is not None else None,
            }

        contribution = context["contribution"]
        output_audio = sliced["audio"]
        evidence = guide_application_evidence.strip() if isinstance(guide_application_evidence, str) else ""
        guide_expected = context.get("incoming_guide") is not None
        entry = {
            "schema_version": 1,
            "segment_index": context["segment_index"],
            "segment_id": context["segment_id"],
            "order": context["order"],
            "contribution_path": str(final_video),
            "contribution_frames": contribution["frame_count"],
            "output_start_frame": contribution["output_start_frame"],
            "output_end_frame": contribution["output_end_frame"],
            "actual_result_frames": sliced["actual_result_frames"],
            "width": sliced["width"],
            "height": sliced["height"],
            "channels": sliced["channels"],
            "has_audio": output_audio is not None,
            "audio_sample_rate": output_audio["sample_rate"] if output_audio is not None else None,
            "audio_channels": int(output_audio["waveform"].shape[1]) if output_audio is not None else None,
            "audio_source_sample_rate": output_audio.get("_zv_source_sample_rate") if output_audio is not None else None,
            "audio_source_channels": output_audio.get("_zv_source_channels") if output_audio is not None else None,
            "audio_normalized": output_audio.get("_zv_audio_normalized") if output_audio is not None else None,
            "audio_policy": output_audio.get("_zv_audio_policy") if output_audio is not None else None,
            "audio_resample_adjustment_samples": output_audio.get("_zv_resample_adjustment_samples", 0) if output_audio is not None else None,
            "audio_phase_adjustment_samples": output_audio.get("_zv_phase_adjustment_samples", 0) if output_audio is not None else None,
            "encoded_probe": probe,
            "guide": guide_record,
            "guide_application": {
                "expected": guide_expected,
                "external_application_verified": False,
                "declaration": evidence or None,
                "status": (
                    "external_application_declared_unverified"
                    if guide_expected and evidence
                    else "external_application_unverified"
                    if guide_expected
                    else "not_required"
                ),
            },
            "mask_runtime": mask_runtime_evidence,
        }
        updated = append_result(context, manifest, entry)
        manifest_path = _safe_artifact_path(
            run_dir, run_dir / RUN_MANIFEST_FILENAME, suffix=".json",
        )
        _write_json_atomic(manifest_path, updated)
        return updated
    except BaseException:
        if temporary_video.exists():
            temporary_video.unlink()
        for path in reversed(created):
            if path.is_file():
                path.unlink()
        raise


def _load_npy(path):
    try:
        value = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as error:
        raise StitchError(f"无法读取 guide 图像：{error}") from error
    if value.dtype != np.uint8:
        _error("guide 图像数据类型无效")
    import torch

    return torch.from_numpy(np.asarray(value, dtype=np.float32).copy()).div_(255)


def _load_audio(path):
    try:
        with np.load(path, allow_pickle=False) as value:
            waveform = np.asarray(value["waveform"], dtype=np.float32).copy()
            sample_rate = int(value["sample_rate"])
    except (OSError, ValueError, KeyError) as error:
        raise StitchError(f"无法读取 guide 音频：{error}") from error
    import torch

    audio = {"waveform": torch.from_numpy(waveform), "sample_rate": sample_rate}
    _audio_parts(audio, "guide_audio")
    return audio


def load_previous_guide(context, previous_run, temp_root):
    """Load only the exact de-padded previous tail required by this iteration."""

    manifest = assert_run_matches_context(context, previous_run)
    incoming = context.get("incoming_guide")
    if incoming is None:
        return None, None
    if manifest is None:
        _error("guide 接缝缺少上一轮运行清单")
    last = manifest["results"][-1]
    guide = last.get("guide")
    if not isinstance(guide, Mapping):
        _error("上一段没有持久化当前段所需的 guide 尾帧")
    for field in ("frame_count", "global_start_frame", "global_end_frame"):
        if guide.get(field) != incoming[field]:
            _error(f"上一段 guide 的 {field} 与当前计划不一致")
    if guide.get("target_segment_id") != context["segment_id"]:
        _error("上一段 guide 的目标 segment_id 与当前段不一致")
    artifacts = _artifact_root(temp_root)
    run_dir = _safe_artifact_path(artifacts, manifest["run_dir"])
    frames_path = _safe_artifact_path(run_dir, guide.get("frames_path"), suffix=".npy", must_exist=True)
    frames = _load_npy(frames_path)
    frame_count, _height, _width, channels = _shape(frames, "guide_frames", 4)
    if frame_count != incoming["frame_count"] or channels != 3:
        _error("上一段 guide 图像形状与当前计划不一致")
    audio = None
    if guide.get("audio_path") is None:
        _error("上一段 guide 缺少固定音频合同要求的同步音频")
    else:
        audio_path = _safe_artifact_path(run_dir, guide["audio_path"], suffix=".npz", must_exist=True)
        audio = _load_audio(audio_path)
        if guide.get("audio_sample_rate") != audio["sample_rate"]:
            _error("上一段 guide 音频采样率与清单不一致")
        waveform, sample_rate, channels, samples = _audio_parts(audio, "guide_audio")
        if sample_rate != OUTPUT_AUDIO_SAMPLE_RATE or channels != OUTPUT_AUDIO_CHANNELS:
            _error(
                f"上一段 guide 必须符合 {OUTPUT_AUDIO_SAMPLE_RATE} Hz/"
                f"{OUTPUT_AUDIO_CHANNELS} ch 音频合同"
            )
        expected_samples = (
            round(incoming["global_end_frame"] * sample_rate / context["fps"])
            - round(incoming["global_start_frame"] * sample_rate / context["fps"])
        )
        if samples != expected_samples:
            _error(
                f"上一段 guide 音频采样数不正确：需要 {expected_samples}，实际 {samples}"
            )
        import torch
        if not waveform.is_floating_point() or waveform.is_complex() or not torch.isfinite(waveform).all().item():
            _error("上一段 guide 音频必须是有限浮点实数张量")
    return frames, audio


def validate_complete_run(execution_plan, run_result, temp_root=None):
    """Validate exact length and return a safe ordered file manifest."""

    plan = normalize_execution_plan(execution_plan)
    segment_plan = plan["segment_plan"]
    manifest = normalize_run_manifest(run_result)
    expected_identity = {
        "execution_fingerprint": plan["fingerprint"],
        "plan_revision": plan["plan_revision"],
        "plan_id": segment_plan["plan_id"],
        "fps": segment_plan["fps"],
        "target_frame_count": segment_plan["target_frame_count"],
        "segment_ids": [row["segment_id"] for row in segment_plan["segments"]],
        "audio_contract": RUN_AUDIO_CONTRACT,
    }
    for field, expected in expected_identity.items():
        if manifest.get(field) != expected:
            _error(f"运行清单的 {field} 与执行计划不一致")
    if not manifest["completed"] or len(manifest["results"]) != len(plan["segments"]):
        _error("长视频运行尚未完成全部分段")

    run_dir = None
    if temp_root is not None:
        artifacts = _artifact_root(temp_root)
        run_dir = _safe_artifact_path(artifacts, manifest["run_dir"])
        if not run_dir.is_dir():
            _error("运行目录不存在")
    cursor = 0
    dimensions = None
    audio_signature = None
    audio_presence = []
    mask_presence = []
    mask_identity = None
    for index, (expected_row, entry) in enumerate(zip(plan["segments"], manifest["results"])):
        if not isinstance(entry, Mapping):
            _error(f"第 {index + 1} 个运行结果不是对象")
        context = segment_context(plan, index)
        contribution = context["contribution"]
        if entry.get("segment_index") != index or entry.get("segment_id") != expected_row["segment_id"]:
            _error(f"第 {index + 1} 个运行结果未对齐")
        if entry.get("contribution_frames") != contribution["frame_count"]:
            _error(f"第 {index + 1} 个运行结果帧数不正确")
        if entry.get("output_start_frame") != cursor or entry.get("output_end_frame") != contribution["output_end_frame"]:
            _error(f"第 {index + 1} 个运行结果在最终时间线上不连续")
        cursor = contribution["output_end_frame"]
        guide_application = entry.get("guide_application")
        if not isinstance(guide_application, Mapping):
            _error(f"第 {index + 1} 个运行结果缺少 guide 应用记录")
        guide_expected = context.get("incoming_guide") is not None
        if guide_application.get("expected") is not guide_expected:
            _error(f"第 {index + 1} 个运行结果的 guide 预期状态不正确")
        declaration = guide_application.get("declaration")
        if guide_application.get("external_application_verified") is not False:
            _error(f"第 {index + 1} 个运行结果不能把用户声明当成 guide 已应用证据")
        expected_status = ("external_application_declared_unverified" if guide_expected and isinstance(declaration, str) and declaration.strip()
                           else "external_application_unverified" if guide_expected else "not_required")
        if guide_application.get("status") != expected_status:
            _error(f"第 {index + 1} 个运行结果的 guide 声明状态自相矛盾")
        mask_runtime = _validate_mask_runtime_evidence(context, entry.get("mask_runtime"))
        mask_presence.append(mask_runtime is not None)
        if mask_runtime is not None:
            current_mask_identity = (
                mask_runtime["processing_version"],
                mask_runtime["source_fingerprint"],
                mask_runtime["sampling_fingerprint"],
                mask_runtime["masked_bundle_fingerprint"],
                mask_runtime["raw_mask_content"],
            )
            if mask_identity is None:
                mask_identity = current_mask_identity
            elif mask_identity != current_mask_identity:
                _error("各分段 C1 MASK 证据没有绑定同一来源与 raw MASK")
        current_dimensions = (entry.get("width"), entry.get("height"), entry.get("channels"))
        if dimensions is None:
            dimensions = current_dimensions
        elif dimensions != current_dimensions:
            _error("各分段输出尺寸不一致")
        has_audio = entry.get("has_audio") is True
        audio_presence.append(has_audio)
        if has_audio:
            signature = (entry.get("audio_sample_rate"), entry.get("audio_channels"))
            if signature != (OUTPUT_AUDIO_SAMPLE_RATE, OUTPUT_AUDIO_CHANNELS):
                _error(
                    f"第 {index + 1} 个运行结果不符合固定的 "
                    f"{OUTPUT_AUDIO_SAMPLE_RATE} Hz stereo 音频契约"
                )
            source_rate = entry.get("audio_source_sample_rate")
            source_channels = entry.get("audio_source_channels")
            policy = entry.get("audio_policy")
            if policy == "clocked_silence":
                if source_rate is not None or source_channels is not None or entry.get("audio_normalized") is not False:
                    _error(f"第 {index + 1} 个运行结果的同步静音证据无效")
            elif policy == "selected_content":
                if type(source_rate) is not int or source_rate <= 0 or source_channels not in (1, 2):
                    _error(f"第 {index + 1} 个运行结果的源音频格式证据无效")
                expected_normalized = (
                    source_rate != OUTPUT_AUDIO_SAMPLE_RATE
                    or source_channels != OUTPUT_AUDIO_CHANNELS
                )
                if entry.get("audio_normalized") is not expected_normalized:
                    _error(f"第 {index + 1} 个运行结果的音频归一化证据无效")
            else:
                _error(f"第 {index + 1} 个运行结果缺少音频策略证据")
            if audio_signature is None:
                audio_signature = signature
            elif audio_signature != signature:
                _error("各分段音频格式不一致")
        probe = entry.get("encoded_probe")
        if not isinstance(probe, Mapping) or probe.get("encoded_frame_count") != contribution["frame_count"]:
            _error(f"第 {index + 1} 个分段文件没有精确帧数探测证据")
        if probe.get("fps") != segment_plan["fps"]:
            _error(f"第 {index + 1} 个分段文件帧率不正确")
        expected_samples = round(contribution["output_end_frame"] * probe.get("audio_sample_rate", 0) / segment_plan["fps"]) - round(contribution["output_start_frame"] * probe.get("audio_sample_rate", 0) / segment_plan["fps"]) if has_audio else None
        if has_audio and probe.get("audio_content_sample_count") != expected_samples:
            _error(f"第 {index + 1} 个分段文件音频内容采样数不正确")
        if has_audio:
            padding = probe.get("audio_padding_samples")
            decoded = probe.get("decoded_audio_sample_count")
            if type(padding) is not int or not 0 <= padding <= 4096 or decoded != expected_samples + padding:
                _error(f"第 {index + 1} 个分段文件 AAC 尾部padding证据无效")
            phase_adjustment = entry.get("audio_phase_adjustment_samples")
            if type(phase_adjustment) is not int or abs(phase_adjustment) > 2:
                _error(f"第 {index + 1} 个分段文件缺少有效的全局音频采样相位证据")
            resample_adjustment = entry.get("audio_resample_adjustment_samples")
            if type(resample_adjustment) is not int or not 0 <= resample_adjustment <= 2:
                _error(f"第 {index + 1} 个分段文件缺少有效的重采样舍入证据")
        path = entry.get("contribution_path")
        if run_dir is not None:
            _safe_artifact_path(run_dir, path, suffix=".mp4", must_exist=True)
        elif not isinstance(path, str) or not path:
            _error("运行结果缺少分段文件路径")
    if any(audio_presence) and not all(audio_presence):
        _error("分段音频必须全部存在或全部省略")
    if any(mask_presence) and not all(mask_presence):
        _error("C1 MASK 运行证据必须覆盖全部分段")
    target = segment_plan["target_frame_count"]
    if cursor != target or sum(row["contribution_frames"] for row in manifest["results"]) != target:
        _error(f"运行结果不是精确的 {target} 帧")
    manifest["final_validation"] = {
        "schema_version": 1,
        "status": "passed",
        "segment_count": len(manifest["results"]),
        "target_frame_count": target,
        "contribution_frame_count": sum(
            row["contribution_frames"] for row in manifest["results"]
        ),
        "output_dimensions": {
            "width": dimensions[0], "height": dimensions[1], "channels": dimensions[2],
        },
        "audio_contract_status": "complete" if all(audio_presence) else "absent",
        "audio_sample_rate": audio_signature[0] if audio_signature else None,
        "audio_channels": audio_signature[1] if audio_signature else None,
        "mask_runtime_status": "complete" if all(mask_presence) else "absent",
        "mask_processing_version": MASK_RUNTIME_VERSION if all(mask_presence) else None,
    }
    if run_dir is not None:
        manifest_path = _safe_artifact_path(
            run_dir, run_dir / RUN_MANIFEST_FILENAME, suffix=".json",
        )
        _write_json_atomic(manifest_path, manifest)
    return manifest


def contribution_paths(execution_plan, run_result, temp_root=None):
    manifest = validate_complete_run(execution_plan, run_result, temp_root)
    return [row["contribution_path"] for row in manifest["results"]]
