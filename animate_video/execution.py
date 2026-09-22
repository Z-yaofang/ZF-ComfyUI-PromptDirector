"""Load authored clips and collect original workflow results without frame edits."""

import copy
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

import numpy as np
import torch

from ..media_evidence.outlet import SAMPLE_RATE, build_outlet_plan
from ..media_evidence.outlet_decode import execute_outlet
from ..media_evidence.presets import builtin
from .assembly import encode_video_chunk
from .plan import AnimatePlanError, normalize_plan


DIRECTORY = "zv_animate_segments"
GUIDE_FRAMES = 21


def ready_plan(value):
    plan = normalize_plan(value)
    if not plan["validation"]["ready"]:
        raise AnimatePlanError(plan["validation"]["errors"])
    return plan


def _guide_window(previous, current, seam_mode):
    if seam_mode != "continuation_21":
        return None
    return {"target_segment_id": current["segment_id"]}


def segment_context(value, index):
    plan = ready_plan(value)
    if type(index) is not int or not 0 <= index < len(plan["segments"]):
        raise ValueError("Animate 循环段号超出计划范围")
    row = plan["segments"][index]
    mode = plan["settings"]["seam_mode"]
    incoming = _guide_window(plan["segments"][index - 1], row, mode) if index else None
    outgoing = _guide_window(row, plan["segments"][index + 1], mode) if index + 1 < len(plan["segments"]) else None
    return {"schema_version": 1, "plan_fingerprint": plan["plan_fingerprint"],
            "mask_enabled": plan["settings"]["mask_enabled"],
            "index": index, "segment_count": len(plan["segments"]), "fps": plan["fps"],
            "target_frame_count": plan["target_frame_count"], "segment": copy.deepcopy(row),
            "incoming_guide": incoming, "outgoing_guide": outgoing}


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _run_dir(root, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("Animate 运行 ID 无效")
    base = Path(root).resolve() / DIRECTORY
    directory = (base / run_id).resolve()
    if directory.parent != base or base.resolve().parent != Path(root).resolve():
        raise ValueError("Animate 落盘目录越界")
    return directory


def _artifact(directory, name):
    if not isinstance(name, str) or not re.fullmatch(r"segment-[0-9]{4,}(-guide)?\.(mp4|npy)", name):
        raise ValueError("Animate 分段文件名无效")
    path = (directory / name).resolve()
    if path.parent != directory:
        raise ValueError("Animate 分段文件越界")
    return path


def load_run(root, result, fingerprint, completed_count):
    if not isinstance(result, dict) or result.get("schema_version") != 1:
        raise ValueError("Animate 缺少上一段运行结果")
    directory = _run_dir(root, result.get("run_id"))
    path = directory / "manifest.json"
    if not path.is_file() or _hash(path) != result.get("manifest_sha256"):
        raise ValueError("Animate 运行记录已丢失或变化，请重新运行")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (result.get("plan_fingerprint") != fingerprint or manifest.get("plan_fingerprint") != fingerprint
            or manifest.get("run_id") != result.get("run_id")
            or result.get("completed_count") != completed_count or len(manifest.get("segments", [])) != completed_count):
        raise ValueError("Animate 上一段结果与当前计划或循环顺序不一致")
    return directory, manifest


def load_guide(context, previous_result, root):
    if context["index"] == 0:
        if previous_result is not None:
            raise ValueError("Animate 首段不能复用旧运行结果")
        return None
    directory, manifest = load_run(root, previous_result, context["plan_fingerprint"], context["index"])
    guide = manifest["segments"][-1]["guide"]
    expected = context["incoming_guide"]
    if expected is None:
        if guide is not None:
            raise ValueError("Animate 硬切段意外收到衔接帧")
        return None
    if guide is None or guide["window"] != expected:
        raise ValueError("Animate 衔接历史与当前源起点不一致")
    path = _artifact(directory, guide["file"])
    if not path.is_file() or _hash(path) != guide["sha256"]:
        raise ValueError("Animate 衔接文件已丢失或变化")
    frames = np.load(path, allow_pickle=False)
    if list(frames.shape) != guide["shape"] or frames.shape[0] != min(GUIDE_FRAMES, manifest["segments"][-1]["frames"]) or frames.dtype != np.float32:
        raise ValueError("Animate 衔接帧形状不一致")
    return torch.from_numpy(frames)


def _vhs_load(**kwargs):
    import nodes
    loader = nodes.NODE_CLASS_MAPPINGS.get("VHS_LoadVideo")
    if loader is None:
        raise ValueError("Animate 一次成片需要安装 VideoHelperSuite 的 VHS_LoadVideo 节点")
    return loader().load_video(**kwargs)


def decode_segment(plan, context, store, width=None, height=None, loader=None):
    """Use the original VHS loader; alignment and pose processing stay in the graph."""
    row = context["segment"]
    project = copy.deepcopy(plan["media_project"])
    clip = next(item for item in project["video_track"] if item["clip_id"] == row["clip_id"])
    picture_row = next(item for item in project["picture_track"] if item["item_id"] == row["picture_id"])
    project["video_track"] = [clip]
    project["picture_track"] = [picture_row]
    project["audio_track"] = [item for item in project["audio_track"] if item["clip_id"] == clip["audio_link_id"]]
    used_assets = {clip["asset_id"], picture_row["asset_id"], *(item["asset_id"] for item in project["audio_track"])}
    project["assets"] = [asset for asset in project["assets"] if asset["asset_id"] in used_assets]
    project.pop("output_canvas", None)
    duration = clip["source_out_seconds"] - clip["source_in_seconds"]
    clip["timeline_in_seconds"] = 0
    for item in project["audio_track"]:
        item["timeline_in_seconds"] = 0
    project["processing_window"] = {"start_seconds": 0, "end_seconds": duration, "fps": context["fps"]}
    project["processing_preset"] = builtin()
    canonical = store.canonical(project)
    if canonical["validation"]["errors"]:
        raise AnimatePlanError(canonical["validation"]["errors"])
    fps = context["fps"]
    start, end = row["load_start_frame"], row["load_end_frame"]
    if end - start != row["frame_count"]:
        raise ValueError("Animate 源切点与计划帧数不一致")
    dimensions = [0 if value is None else value for value in (width, height)]
    if any(type(value) is not int or not 0 <= value <= 16384 for value in dimensions):
        raise ValueError("Animate 原流加载尺寸必须是 0–16384 的整数；0 保持 VHS 自动尺寸")
    video_asset = next(asset for asset in canonical["assets"] if asset["asset_id"] == clip["asset_id"])
    # Use a Comfy input-relative path, retaining the native loader's path boundary checks.
    video_name = store.resolve(video_asset["source_handle"]).relative_to(store.input_root).as_posix()
    frames, count, audio, info = (loader or _vhs_load)(
        video=video_name, force_rate=fps,
        custom_width=dimensions[0], custom_height=dimensions[1], frame_load_cap=row["frame_count"],
        skip_first_frames=start, select_every_nth=1, format="None")
    if count != row["frame_count"] or len(frames) != row["frame_count"]:
        raise ValueError(f"原流 VHS 入口实际读取 {len(frames)} 帧，素材台选定 {row['frame_count']} 帧；不会暗补帧或移动切点")
    if row["source_audio_enabled"] and audio is not None:
        try:
            # VHS returns lazy audio. Materialize it before the GPU graph starts.
            audio = dict(audio)
        except Exception as error:
            raise ValueError(
                f"Animate 第 {context['index'] + 1} 段原声加载失败（素材范围 "
                f"{row['source_start_seconds']:.3f}–{row['source_end_seconds']:.3f} 秒）；"
                "原 VHS 未能读取该段音轨，尚未开始本段生成。请检查原声，或在素材台停用该段原声。"
            ) from error
    image_plan = build_outlet_plan(canonical, "picture", row["picture_id"])
    picture, _unused, _manifest, _report = execute_outlet(store, image_plan)
    return picture, frames, audio if row["source_audio_enabled"] else None, info


def _contribution_audio(audio, context, actual_frames, output_start):
    row, fps = context["segment"], context["fps"]
    if audio is None and row["source_audio_enabled"]:
        raise ValueError("Animate 本段原声已启用，但录制入口没有收到原声音频")
    samples = round((output_start + actual_frames) * SAMPLE_RATE / fps) - round(output_start * SAMPLE_RATE / fps)
    source_rate, source_count = None, 0
    if audio is None:
        original = torch.empty((1, 2, 0), dtype=torch.float32)
    else:
        if not isinstance(audio, Mapping):
            raise ValueError("Animate 原声必须是 ComfyUI AUDIO")
        source_rate, original = audio.get("sample_rate"), audio.get("waveform")
        if type(source_rate) is not int or not 0 < source_rate <= 2 ** 31 - 1:
            raise ValueError("Animate 原声音频采样率必须是有效正整数")
        if (not isinstance(original, torch.Tensor) or original.ndim != 3
                or original.shape[0] != 1 or original.shape[1] not in (1, 2)):
            raise ValueError("Animate 原声必须是 [1, 1或2声道, samples]；多声道请先显式下混")
        if not original.is_floating_point() or original.is_complex() or not torch.isfinite(original).all().item():
            raise ValueError("Animate 原声必须是有限浮点实数张量")
        source_count = int(original.shape[-1])
        original = original.detach().to(device="cpu", dtype=torch.float32)
        if original.shape[1] == 1:
            original = original.repeat(1, 2, 1)
        if source_count and source_rate != SAMPLE_RATE:
            # Bound torchaudio's polyphase kernel before it allocates the grid.
            divisor = math.gcd(source_rate, SAMPLE_RATE)
            source, target = source_rate // divisor, SAMPLE_RATE // divisor
            width = math.ceil(6 * source / (min(source, target) * .99))
            if target * (source + 2 * width) > 8_000_000:
                raise ValueError("Animate 原声采样率会产生过大的重采样核；请先转为 32000、44100、48000 或 96000 Hz")
            import torchaudio
            original = torchaudio.functional.resample(original, source_rate, SAMPLE_RATE)
    source_samples = int(original.shape[-1])
    # A legitimate source track may end before its video, including an empty tail
    # selection. Never stretch/repeat it, or include audio beyond the authored cut.
    selected_samples = min(source_samples, round(row["frame_count"] * SAMPLE_RATE / fps))
    waveform = original[..., :min(selected_samples, samples)].clone()
    deficit = samples - waveform.shape[-1]
    if deficit:
        waveform = torch.nn.functional.pad(waveform, (0, deficit))
    fit = {"source_samples": source_samples, "source_input_samples": source_count,
           "output_samples": samples, "trimmed_tail_samples": source_samples - min(selected_samples, samples),
           "padded_silence_samples": deficit,
           "source_sample_rate": source_rate,
           "silent_track": audio is None}
    return {"waveform": waveform, "sample_rate": SAMPLE_RATE}, fit


def persist_segment(context, frames, audio, previous_result, root, encoder=encode_video_chunk):
    row = context["segment"]
    if not isinstance(frames, torch.Tensor) or frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError("Animate 解码结果必须是 [帧,高,宽,3] 的 IMAGE")
    if frames.shape[0] < 1:
        raise ValueError(f"Animate 第 {context['index'] + 1} 段原流最终输出为空，不能合成")
    if context["index"]:
        directory, manifest = load_run(root, previous_result, context["plan_fingerprint"], context["index"])
        if manifest["shape"] != list(frames.shape[1:]):
            raise ValueError("Animate 各段生成尺寸不同，请使用同一输出画布")
    else:
        if previous_result is not None:
            raise ValueError("Animate 首段不能写入旧运行")
        run_id = uuid.uuid4().hex
        directory = _run_dir(root, run_id)
        directory.mkdir(parents=True, exist_ok=False)
        manifest = {"schema_version": 1, "run_id": run_id, "plan_fingerprint": context["plan_fingerprint"],
                    "fps": context["fps"], "shape": list(frames.shape[1:]), "segments": []}
    effective = frames.detach().to(device="cpu", dtype=torch.float32)
    if not torch.isfinite(effective).all().item():
        raise ValueError("Animate 解码画面含非有限像素")
    contribution = effective
    actual_frames = int(frames.shape[0])
    output_start = manifest["segments"][-1]["output_end_frame"] if manifest["segments"] else 0
    sound, audio_fit = _contribution_audio(audio, context, actual_frames, output_start)
    name = f"segment-{context['index'] + 1:04d}.mp4"
    path = _artifact(directory, name)
    probe = encoder(contribution, sound, context["fps"], str(path))
    if (probe["encoded_frame_count"] != actual_frames or probe["fps"] != context["fps"]
            or probe["audio_sample_rate"] != SAMPLE_RATE or probe["audio_channels"] != 2
            or probe["decoded_audio_sample_count"] < sound["waveform"].shape[-1]):
        raise ValueError("Animate 落盘结果未通过视频帧数/原声时钟校验")
    record = {"segment_id": row["segment_id"], "file": name, "sha256": _hash(path),
        "frames": actual_frames, "expected_frame_count": row["frame_count"], "frame_delta": actual_frames - row["frame_count"],
        "output_start_frame": output_start, "output_end_frame": output_start + actual_frames,
        "audio_samples": sound["waveform"].shape[-1], "audio_fit": audio_fit,
        "guide": None}
    manifest["segments"].append(record)
    guide = context["outgoing_guide"]
    if guide is not None:
        history = contribution[-GUIDE_FRAMES:].contiguous().clone()
        guide_name = f"segment-{context['index'] + 1:04d}-guide.npy"
        guide_path = _artifact(directory, guide_name)
        np.save(guide_path, history.contiguous().numpy(), allow_pickle=False)
        record["guide"] = {"file": guide_name, "sha256": _hash(guide_path), "shape": list(history.shape), "window": guide}
    manifest_path = directory / "manifest.json"
    temporary = directory / "manifest.pending.json"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(manifest_path)
    return {"schema_version": 1, "run_id": manifest["run_id"], "plan_fingerprint": context["plan_fingerprint"],
            "completed_count": len(manifest["segments"]), "manifest_sha256": _hash(manifest_path),
            "last_segment": {key: record[key] for key in ("frames", "expected_frame_count", "frame_delta", "audio_fit")}}


def complete_run(plan, result, root):
    plan = ready_plan(plan)
    directory, manifest = load_run(root, result, plan["plan_fingerprint"], len(plan["segments"]))
    total = 0
    paths = []
    for expected, row in zip(plan["segments"], manifest["segments"]):
        count = row["frames"]
        if (row["segment_id"] != expected["segment_id"] or type(count) is not int or count < 1
                or row["expected_frame_count"] != expected["frame_count"] or row["frame_delta"] != count - expected["frame_count"]
                or row["output_start_frame"] != total or row["output_end_frame"] != total + count):
            raise ValueError("Animate 成片分段序列不完整或帧区间不一致")
        path = _artifact(directory, row["file"])
        if not path.is_file() or _hash(path) != row["sha256"]:
            raise ValueError("Animate 分段成片文件已丢失或变化")
        total += count
        paths.append(path)
    manifest["expected_frame_count"] = plan["target_frame_count"]
    manifest["actual_frame_count"] = total
    manifest["frame_delta"] = total - plan["target_frame_count"]
    return paths, manifest
