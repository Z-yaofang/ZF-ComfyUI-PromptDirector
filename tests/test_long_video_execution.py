import importlib
import copy
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import torch
import torchaudio


ROOT = Path(__file__).resolve().parents[1]
COMFY = ROOT.parents[1]
if str(COMFY) not in sys.path:
    sys.path.insert(0, str(COMFY))
PACKAGE = "zf_long_video_execution_testpkg"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
PLAN = importlib.import_module(PACKAGE + ".long_video.plan")
INTERVIEW = importlib.import_module(PACKAGE + ".long_video.interview")
EXECUTION = importlib.import_module(PACKAGE + ".long_video.execution")
STITCH = importlib.import_module(PACKAGE + ".long_video.stitch")
NODES = importlib.import_module(PACKAGE + ".long_video.execution_nodes")
CONTRACT = importlib.import_module(PACKAGE + ".media_evidence.contract")


def execution_plan(*, alignment="exact", segment_frames=124, overlap_frames=None, segment_count=2):
    if overlap_frames is None:
        overlap_frames = 22 if alignment == "exact" else 39
    settings = {
        **PLAN.default_settings(), "mode": "generation_count", "segment_frames": segment_frames,
        "overlap_frames": overlap_frames, "overlap_alignment": alignment, "segment_count": segment_count,
    }
    plan = PLAN.build_segment_plan(CONTRACT.empty_project(), settings)
    result = INTERVIEW.compile_segment_interview(
        plan, {**INTERVIEW.empty_segment_interview(), "global": {"intent": "灯光缓慢变化。"}}, align=True,
    )
    assert result["ready"], result["errors"]
    return result


def audio(value, samples=None, sample_rate=48000, channels=1):
    samples = round(124 * sample_rate / 24) if samples is None else samples
    return {"waveform": torch.full((1, channels, samples), value, dtype=torch.float32), "sample_rate": sample_rate}


def frames(value):
    return torch.full((124, 24, 32, 3), value, dtype=torch.float32)


def mask_runtime_reports(context):
    raw = {
        "shape": [1, 24, 32], "canonical_dtype": "float32", "sha256": "a" * 64,
        "minimum": 0.0, "maximum": 0.0, "nonzero": 0,
    }
    effective = {
        "shape": [context["model_length"], 24, 32], "canonical_dtype": "float32",
        "sha256": "b" * 64, "minimum": 0.0, "maximum": 0.0, "nonzero": 0,
    }
    video_noise = {
        "shape": [1, 24, 37, 2, 2], "canonical_dtype": "float32",
        "sha256": "e" * 64, "minimum": 0.0, "maximum": 0.0, "nonzero": 0,
    }
    model_contract = {
        "schema_version": 1,
        "fps": 24,
        "audio_latent_fps": 40,
        "video_channels": 24,
        "audio_channels": 32,
        "audio_stereo": 2,
        "video_vae_geometry": {
            "vae_ratio_t": 4, "clip_length": 17, "token_drop": 3,
            "frame_pre_padding": 3, "tokens_chunk_size": 5,
        },
        "temporal_group_pattern": [1, 4, 4, 4, 4],
        "spatial_token": [2, 2],
    }
    source = {
        "schema_version": 1, "kind": "zv-h3-masked-segment-latent",
        "plan_revision": context["plan_revision"],
        "source_fingerprint": context["source_fingerprint"],
        "sampling_fingerprint": "c" * 64,
        "mask_processing_version": STITCH.MASK_RUNTIME_VERSION,
        "mask_content": raw, "masked_bundle_fingerprint": "d" * 64,
        "segment_id": context["segment_id"], "segment_index": context["segment_index"] + 1,
        "source_frame_offset": 0, "model_length": context["model_length"],
        "plan_target_tail_repeat_frames": 0, "model_grid_repeat_frames": 0,
        "video_latent_shape": [1, 24, 37, 2, 2],
        "pixel_model_mask_content": effective,
        "video_noise_mask_shape": [1, 24, 37, 2, 2],
        "video_noise_mask_content": video_noise,
        "model_contract": model_contract,
        "mask_clock": {
            "plan_revision": context["plan_revision"], "segment_id": context["segment_id"],
            "segment_index": context["segment_index"] + 1, "mask_content": raw,
        },
    }
    high = {
        "schema_version": 1, "kind": "zv-h3-high-mask-restore",
        "mask_processing_version": STITCH.MASK_RUNTIME_VERSION,
        "geometry_policy": "same_canvas_1x", "source_policy": "black_source_white_reconciled",
        "audio_policy": "locked_source_latent", "video_latent_shape": [1, 24, 37, 2, 2],
        "video_noise_mask_shape": [1, 24, 37, 2, 2],
        "pixel_model_mask_content": effective, "video_noise_mask_content": video_noise,
    }
    compose = {
        "schema_version": 1, "kind": "zv-h3-masked-frame-compose",
        "mask_processing_version": STITCH.MASK_RUNTIME_VERSION,
        "frame_shape": [context["model_length"], 24, 32, 3],
        "pixel_policy": "black_source_white_generated_soft_blend",
        "pixel_model_mask_content": effective,
    }
    return tuple(json.dumps(value) for value in (source, high, compose))


def test_exact_layout_uses_explicit_h3_call_adapter():
    plan = execution_plan(alignment="exact")
    assert all(row["model_padding"]["adapter"] == "none" for row in plan["segment_plan"]["segments"])
    normalized = EXECUTION.normalize_execution_plan(plan)
    assert [row["model_adapter"] for row in normalized["segments"]] == ["h3", "h3"]
    assert EXECUTION.segment_context(normalized, 0)["model_length"] == 124


def test_h3_adapter_rejects_silent_guide_truncation_but_generic_plan_keeps_exact_overlap():
    settings = {
        **PLAN.default_settings(), "mode": "generation_count", "segment_frames": 124,
        "overlap_frames": 13, "overlap_alignment": "exact", "segment_count": 2,
    }
    generic = PLAN.build_segment_plan(CONTRACT.empty_project(), settings)
    assert generic["validation"]["ready"]
    assert generic["segments"][1]["overlap_frames"] == 13
    compiled = INTERVIEW.compile_segment_interview(
        generic, {**INTERVIEW.empty_segment_interview(), "global": {"intent": "灯光缓慢变化。"}}, align=True,
    )
    assert not compiled["ready"]
    assert any(row["code"] == "h3_guide_length" for row in compiled["errors"])
    with pytest.raises(EXECUTION.ExecutionPlanError, match="H3 Guide"):
        invalid = dict(compiled)
        invalid["ready"] = True
        invalid["errors"] = []
        EXECUTION.normalize_execution_plan(invalid)


@pytest.mark.parametrize("overlap", [1, 5, 22, 39])
def test_h3_adapter_accepts_legal_guide_lengths(overlap):
    plan = PLAN.build_segment_plan(CONTRACT.empty_project(), {
        **PLAN.default_settings(), "mode": "generation_count", "segment_frames": 124,
        "overlap_frames": overlap, "overlap_alignment": "exact", "segment_count": 2,
    })
    compiled = INTERVIEW.compile_segment_interview(plan, INTERVIEW.empty_segment_interview(), align=True)
    assert compiled["ready"], compiled["errors"]
    assert EXECUTION.normalize_execution_plan(compiled)["segments"][1]["segment_id"]


def test_h3_execution_rejects_non_24fps_and_tampered_compiled_prompt():
    plan = PLAN.build_segment_plan(CONTRACT.empty_project(), {
        **PLAN.default_settings(), "mode": "generation_count", "fps": 30,
        "segment_frames": 150, "overlap_frames": 0, "overlap_alignment": "exact", "segment_count": 1,
    })
    assert plan["validation"]["ready"]
    compiled = INTERVIEW.compile_segment_interview(plan, INTERVIEW.empty_segment_interview(), align=True)
    assert not compiled["ready"] and any(row["code"] == "h3_fps" for row in compiled["errors"])

    valid = execution_plan()
    valid["segments"][0]["stage1_task"] += " 已被篡改"
    with pytest.raises(EXECUTION.ExecutionPlanError, match="执行指纹"):
        EXECUTION.normalize_execution_plan(valid)


def test_disk_backed_nodes_encode_probe_restore_guide_and_native_concat(tmp_path, monkeypatch):
    monkeypatch.setattr(NODES, "_temp_root", lambda: str(tmp_path))
    plan = execution_plan(alignment="exact")
    count, setup_report = NODES.ZVLongVideoExecutionSetup().setup(plan)
    assert count == 2 and "关闭迭代缓存" in setup_report
    entry, recorder = NODES.ZVLongVideoExecutionEntry(), NODES.ZVLongVideoSegmentRecorder()
    first = entry.enter(plan, 0)
    generated, final = audio(0), audio(.75)
    run, report = recorder.record(first[0], frames(.2), generated, final)
    assert "final_audio 内容优先" in report
    assert "44100 Hz/2 ch" in report
    manifest_path = Path(run["run_dir"]) / STITCH.RUN_MANIFEST_FILENAME
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == run
    assert run["results"][0]["guide_application"]["status"] == "not_required"
    probe = run["results"][0]["encoded_probe"]
    assert probe["encoded_frame_count"] == 124 and probe["fps"] == 24
    assert probe["audio_sample_rate"] == 44100 and probe["audio_channels"] == 2
    assert probe["audio_content_sample_count"] == 227850
    assert probe["decoded_audio_sample_count"] == 227850 + probe["audio_padding_samples"]
    assert 0 <= probe["audio_padding_samples"] <= 4096
    guide_path = Path(run["results"][0]["guide"]["frames_path"])
    assert guide_path.stat().st_size < first[0]["next_guide"]["frame_count"] * 24 * 32 * 3 + 1024
    second = entry.enter(plan, 1, run)
    assert second[10] is True and second[11].shape == (22, 24, 32, 3)
    assert torch.allclose(second[11], torch.full_like(second[11], .2), atol=1 / 255)
    run, _report = recorder.record(second[0], frames(.8), audio(-.75), previous_result=run,
                                   guide_application_note="示例图中 LOW/HIGH 均接入 lazy switch；本字段只是声明")
    assert run["completed"]
    assert run["results"][1]["guide_application"] == {
        "expected": True, "external_application_verified": False,
        "declaration": "示例图中 LOW/HIGH 均接入 lazy switch；本字段只是声明",
        "status": "external_application_declared_unverified",
    }
    video, target, end_report = NODES.ZVLongVideoExecutionEnd().finish(plan, [run])
    assert target == 226 and "native VIDEO" in end_report and "实际应用" in end_report
    stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stored_manifest["final_validation"]["status"] == "passed"
    assert stored_manifest["final_validation"]["mask_runtime_status"] == "absent"
    components = video.get_components()
    assert tuple(components.images.shape) == (226, 24, 32, 3)
    assert components.frame_rate == 24
    assert components.audio["sample_rate"] == 44100
    assert components.audio["waveform"].shape == (1, 2, 415275)
    assert components.audio["waveform"][..., 4000:223850].mean() > .4
    assert components.audio["waveform"][..., 231850:-4000].mean() < -.4

    from comfy_api.latest import InputImpl, Types
    saved = tmp_path / "final.mp4"
    video.save_to(str(saved), format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264)
    restored = InputImpl.VideoFromFile(str(saved), duration=target / 24).get_components()
    assert tuple(restored.images.shape) == (226, 24, 32, 3)
    assert restored.audio["waveform"].shape == (1, 2, 415275)
    assert restored.audio["waveform"][..., 4000:223850].mean() > .35
    assert restored.audio["waveform"][..., 231850:-4000].mean() < -.35


def test_recorder_persists_and_end_revalidates_complete_mask_runtime_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(NODES, "_temp_root", lambda: str(tmp_path))
    plan = execution_plan(alignment="exact", segment_count=1)
    context = EXECUTION.segment_context(plan, 0)
    source_json, high_json, compose_json = mask_runtime_reports(context)

    run, _report = NODES.ZVLongVideoSegmentRecorder().record(
        context,
        frames(.4),
        generated_audio=audio(.1),
        mask_source_evidence=source_json,
        mask_high_evidence=high_json,
        mask_compose_evidence=compose_json,
    )
    evidence = run["results"][0]["mask_runtime"]

    assert evidence["plan_revision"] == context["plan_revision"]
    assert evidence["source_fingerprint"] == context["source_fingerprint"]
    assert evidence["raw_mask_content"]["sha256"] == "a" * 64
    assert evidence["pixel_model_mask_content"]["sha256"] == "b" * 64
    assert evidence["effective_high_video_noise_mask_content"]["sha256"] == "e" * 64
    manifest_path = Path(run["run_dir"]) / STITCH.RUN_MANIFEST_FILENAME
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == run
    finalized = STITCH.validate_complete_run(plan, run, tmp_path)
    assert finalized["results"][0]["mask_runtime"] == evidence
    assert finalized["final_validation"]["status"] == "passed"
    assert finalized["final_validation"]["mask_runtime_status"] == "complete"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == finalized

    damaged = copy.deepcopy(run)
    damaged["results"][0]["mask_runtime"]["effective_high_video_noise_mask_content"]["sha256"] = "x" * 64
    with pytest.raises(STITCH.StitchError, match="摘要"):
        STITCH.validate_complete_run(plan, damaged, tmp_path)

    with pytest.raises(STITCH.StitchError, match="同时连接"):
        STITCH.build_mask_runtime_evidence(context, source_json, high_json, "")


def test_end_rejects_mask_sampling_source_change_between_segments(tmp_path, monkeypatch):
    monkeypatch.setattr(NODES, "_temp_root", lambda: str(tmp_path))
    plan = execution_plan(alignment="exact")
    recorder = NODES.ZVLongVideoSegmentRecorder()
    run = None
    for index in range(2):
        context = EXECUTION.segment_context(plan, index)
        source_json, high_json, compose_json = mask_runtime_reports(context)
        if index:
            source = json.loads(source_json)
            source["sampling_fingerprint"] = "f" * 64
            source_json = json.dumps(source)
        run, _report = recorder.record(
            context,
            frames(.4 + index / 10),
            generated_audio=audio(.1, sample_rate=44100, channels=2),
            previous_result=run,
            mask_source_evidence=source_json,
            mask_high_evidence=high_json,
            mask_compose_evidence=compose_json,
        )

    with pytest.raises(STITCH.StitchError, match="同一来源与 raw MASK"):
        STITCH.validate_complete_run(plan, run, tmp_path)


def test_guide_disk_budget_and_run_tampering_are_rejected(tmp_path):
    with pytest.raises(STITCH.StitchError, match="512 MiB"):
        STITCH._write_npy_atomic(tmp_path / "huge.npy", torch.empty((STITCH.MAX_GUIDE_BYTES + 1,), device="meta"))
    plan = execution_plan()
    context = EXECUTION.segment_context(plan, 0)
    run = EXECUTION.new_run_manifest(context, tmp_path, "run")
    run["completed"], run["results"] = True, [{}]
    with pytest.raises(STITCH.StitchError):
        STITCH.validate_complete_run(plan, run)


def test_atomic_numpy_writers_remove_part_files_after_failure(tmp_path, monkeypatch):
    image_target = tmp_path / "guide.npy"
    real_save = STITCH.np.save
    def broken_save(handle, *args, **kwargs):
        real_save(handle, *args, **kwargs)
        raise OSError("synthetic save failure")
    monkeypatch.setattr(STITCH.np, "save", broken_save)
    with pytest.raises(OSError, match="synthetic"):
        STITCH._write_npy_atomic(image_target, torch.zeros((1, 2, 2, 3)))
    assert not (tmp_path / ".guide.part.npy").exists()

    monkeypatch.setattr(STITCH.np, "save", real_save)
    monkeypatch.setattr(STITCH.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("synthetic replace failure")))
    audio_target = tmp_path / "guide-audio.npz"
    with pytest.raises(OSError, match="synthetic"):
        STITCH._write_audio_atomic(audio_target, audio(0))
    assert not (tmp_path / ".guide-audio.part.npz").exists()


def test_run_manifest_atomic_writer_rejects_tensors_and_removes_part_file(tmp_path):
    target = tmp_path / STITCH.RUN_MANIFEST_FILENAME
    with pytest.raises(STITCH.StitchError, match="纯 JSON"):
        STITCH._write_json_atomic(target, {"forbidden": torch.zeros(1)})
    assert not target.exists()
    assert not (tmp_path / ".run-manifest.part.json").exists()


@pytest.mark.parametrize("sample_rate", [44100, 32000])
def test_multisegment_audio_uses_global_sample_boundaries(tmp_path, monkeypatch, sample_rate):
    monkeypatch.setattr(NODES, "_temp_root", lambda: str(tmp_path))
    plan = execution_plan(alignment="exact")
    entry, recorder = NODES.ZVLongVideoExecutionEntry(), NODES.ZVLongVideoSegmentRecorder()
    first = entry.enter(plan, 0)
    run, _ = recorder.record(first[0], frames(.2), audio(.7, sample_rate=sample_rate))
    second = entry.enter(plan, 1, run)
    run, _ = recorder.record(second[0], frames(.8), audio(-.7, sample_rate=sample_rate), previous_result=run)
    video, frame_count, _ = NODES.ZVLongVideoExecutionEnd().finish(plan, [run])
    components = video.get_components()
    assert components.audio["sample_rate"] == 44100
    assert components.audio["waveform"].shape[1] == 2
    boundary = round(124 * 44100 / 24)
    expected = round(frame_count * 44100 / 24)
    assert components.audio["waveform"].shape[-1] == expected
    assert components.audio["waveform"][..., 1000:boundary - 1000].mean() > .35
    assert components.audio["waveform"][..., boundary + 1000:-1000].mean() < -.35

    from comfy_api.latest import InputImpl, Types
    saved = tmp_path / f"final-source-{sample_rate}.mp4"
    video.save_to(str(saved), format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264)
    restored = InputImpl.VideoFromFile(
        str(saved), duration=(expected + .25) / 44100,
    ).get_components()
    assert tuple(restored.images.shape) == (frame_count, 24, 32, 3)
    assert restored.audio["waveform"].shape[-1] == expected


def test_selected_audio_contract_normalizes_32k_44k_48k_and_mono_stereo(tmp_path, monkeypatch):
    monkeypatch.setattr(NODES, "_temp_root", lambda: str(tmp_path))
    plan = execution_plan(alignment="exact", segment_count=3)
    entry, recorder = NODES.ZVLongVideoExecutionEntry(), NODES.ZVLongVideoSegmentRecorder()
    run = None
    selected = [
        (audio(.2, sample_rate=32000, channels=1), None),
        (audio(-.9, sample_rate=48000, channels=1), audio(.4, sample_rate=44100, channels=2)),
        (audio(.6, sample_rate=48000, channels=1), None),
    ]
    for index, (generated, final) in enumerate(selected):
        values = entry.enter(plan, index, run)
        run, _report = recorder.record(
            values[0], frames(.1 + index / 10), generated, final,
            previous_result=run,
        )

    assert [row["audio_source_sample_rate"] for row in run["results"]] == [32000, 44100, 48000]
    assert [row["audio_source_channels"] for row in run["results"]] == [1, 2, 1]
    assert [row["audio_normalized"] for row in run["results"]] == [True, False, True]
    assert all(row["audio_sample_rate"] == 44100 for row in run["results"])
    assert all(row["audio_channels"] == 2 for row in run["results"])
    assert all(row["audio_policy"] == "selected_content" for row in run["results"])

    video, frame_count, _report = NODES.ZVLongVideoExecutionEnd().finish(plan, [run])
    components = video.get_components()
    assert components.audio["sample_rate"] == 44100
    assert components.audio["waveform"].shape == (
        1, 2, round(frame_count * 44100 / 24),
    )


def test_missing_audio_becomes_clocked_silence_before_recording(tmp_path, monkeypatch):
    monkeypatch.setattr(NODES, "_temp_root", lambda: str(tmp_path))
    plan = execution_plan(alignment="exact", segment_count=1)
    context = NODES.ZVLongVideoExecutionEntry().enter(plan, 0)[0]
    run, report = NODES.ZVLongVideoSegmentRecorder().record(context, frames(.2))
    row = run["results"][0]
    assert "同步静音" in report
    assert row["audio_policy"] == "clocked_silence"
    assert row["audio_source_sample_rate"] is None
    assert row["audio_source_channels"] is None
    assert row["audio_sample_rate"] == 44100 and row["audio_channels"] == 2
    video, frame_count, _report = NODES.ZVLongVideoExecutionEnd().finish(plan, [run])
    output = video.get_components().audio
    assert output["waveform"].shape == (1, 2, round(frame_count * 44100 / 24))
    assert not torch.count_nonzero(output["waveform"])


def test_multichannel_audio_is_rejected_at_the_segment_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(NODES, "_temp_root", lambda: str(tmp_path))
    plan = execution_plan(alignment="exact", segment_count=1)
    context = NODES.ZVLongVideoExecutionEntry().enter(plan, 0)[0]
    with pytest.raises(STITCH.StitchError, match="mono 或 stereo"):
        NODES.ZVLongVideoSegmentRecorder().record(
            context, frames(.2), audio(.1, sample_rate=48000, channels=3),
        )


def test_audio_resample_rejects_oversized_sinc_kernel_before_torchaudio(monkeypatch):
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("dangerous resampler allocation was reached")

    monkeypatch.setattr(torchaudio.functional, "resample", forbidden)
    context = EXECUTION.segment_context(execution_plan(segment_count=1), 0)
    required = round(124 * 44101 / 24)
    with pytest.raises(STITCH.StitchError, match="过大的 sinc 重采样核"):
        STITCH.normalize_output_audio(
            audio(.1, samples=required, sample_rate=44101, channels=1), context,
        )
    assert called is False


@pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050])
def test_common_source_rates_are_clock_checked_before_resample(sample_rate):
    context = EXECUTION.segment_context(execution_plan(segment_count=1), 0)
    source_samples = round(124 * sample_rate / 24)
    result = STITCH.slice_segment_result(
        context,
        frames(.2),
        audio(.25, samples=source_samples, sample_rate=sample_rate, channels=1),
    )
    assert result["audio"]["waveform"].shape == (1, 2, round(124 * 44100 / 24))
    assert result["audio"]["_zv_source_sample_rate"] == sample_rate
    assert 0 <= result["audio"]["_zv_resample_adjustment_samples"] <= 2


def test_source_rate_clock_rejects_real_one_sample_shortage_before_resample(monkeypatch):
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("short source reached resampler")

    monkeypatch.setattr(torchaudio.functional, "resample", forbidden)
    context = EXECUTION.segment_context(execution_plan(segment_count=1), 0)
    required = round(124 * 48000 / 24)
    with pytest.raises(STITCH.StitchError, match="源音频不足"):
        STITCH.normalize_output_audio(
            audio(.1, samples=required - 1, sample_rate=48000, channels=1), context,
        )
    assert called is False


def test_audio_nonfinite_values_are_rejected_before_resample(monkeypatch):
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("nonfinite source reached resampler")

    monkeypatch.setattr(torchaudio.functional, "resample", forbidden)
    context = EXECUTION.segment_context(execution_plan(segment_count=1), 0)
    value = audio(.1, sample_rate=32000, channels=1)
    value["waveform"][..., 0] = float("nan")
    with pytest.raises(STITCH.StitchError, match="NaN 或无穷值"):
        STITCH.normalize_output_audio(value, context)
    assert called is False


def test_legacy_loop_carry_without_audio_contract_is_rejected_before_guide_load(tmp_path):
    plan = execution_plan(alignment="h3_guide", segment_count=2)
    first = EXECUTION.segment_context(plan, 0)
    legacy = EXECUTION.new_run_manifest(first, tmp_path, "legacy")
    legacy.pop("audio_contract")
    second = EXECUTION.segment_context(plan, 1)
    with pytest.raises(EXECUTION.ExecutionPlanError, match="音频合同缺失或不兼容"):
        STITCH.load_previous_guide(second, legacy, tmp_path)


@pytest.mark.parametrize("damage,match", [
    ("rate", "44100 Hz/2 ch"),
    ("mono", "44100 Hz/2 ch"),
    ("short", "音频采样数不正确"),
    ("nan", "有限浮点实数"),
])
def test_previous_guide_audio_is_validated_before_h3(tmp_path, damage, match):
    plan = execution_plan(alignment="h3_guide", segment_count=2)
    first = EXECUTION.segment_context(plan, 0)

    def fake_encoder(images, selected_audio, fps, path):
        Path(path).write_bytes(b"segment")
        samples = int(selected_audio["waveform"].shape[-1])
        return {
            "encoded_frame_count": int(images.shape[0]),
            "fps": fps,
            "audio_sample_rate": selected_audio["sample_rate"],
            "audio_content_sample_count": samples,
            "decoded_audio_sample_count": samples,
            "audio_padding_samples": 0,
            "audio_channels": int(selected_audio["waveform"].shape[1]),
        }

    run = STITCH.persist_segment(
        first,
        frames(.2),
        audio(.1, sample_rate=44100, channels=2),
        None,
        tmp_path,
        fake_encoder,
    )
    guide = run["results"][0]["guide"]
    audio_path = Path(guide["audio_path"])
    with np.load(audio_path, allow_pickle=False) as stored:
        waveform = np.asarray(stored["waveform"], dtype=np.float32).copy()
        sample_rate = int(stored["sample_rate"])
    if damage == "rate":
        sample_rate = 32000
        guide["audio_sample_rate"] = 32000
    elif damage == "mono":
        waveform = waveform[:, :1]
    elif damage == "short":
        waveform = waveform[..., :-1]
    else:
        waveform[..., 0] = np.nan
    np.savez(audio_path, waveform=waveform, sample_rate=np.array(sample_rate, dtype=np.int64))

    second = EXECUTION.segment_context(plan, 1)
    with pytest.raises(STITCH.StitchError, match=match):
        STITCH.load_previous_guide(second, run, tmp_path)


def test_audio_normalization_precedes_nonzero_global_clock_slice():
    plan = execution_plan(alignment="exact", segment_count=1)
    context = EXECUTION.segment_context(plan, 0)
    context["contribution"] = {
        **context["contribution"],
        "output_start_frame": 120,
        "output_end_frame": 244,
    }
    result = STITCH.slice_segment_result(
        context, frames(.2), audio(.5, sample_rate=32000, channels=1),
    )
    assert result["audio"]["sample_rate"] == 44100
    assert result["audio"]["waveform"].shape == (1, 2, 227850)
    assert result["audio"]["_zv_source_sample_rate"] == 32000
    assert result["audio"]["_zv_phase_adjustment_samples"] == 0


@pytest.mark.parametrize("segment_frames,overlap,segment_count,sample_rate", [
    (107, 1, 2, 44100),
    (141, 5, 3, 32000),
    (124, 5, 3, 44100),
])
def test_audio_phase_normalization_handles_half_sample_ties(
    tmp_path, monkeypatch, segment_frames, overlap, segment_count, sample_rate,
):
    monkeypatch.setattr(NODES, "_temp_root", lambda: str(tmp_path))
    plan = execution_plan(
        alignment="exact", segment_frames=segment_frames,
        overlap_frames=overlap, segment_count=segment_count,
    )
    entry, recorder = NODES.ZVLongVideoExecutionEntry(), NODES.ZVLongVideoSegmentRecorder()
    run = None
    for index in range(segment_count):
        values = entry.enter(plan, index, run)
        count = values[0]["model_length"]
        model_frames = torch.full((count, 16, 16, 3), .2 + index / 10, dtype=torch.float32)
        model_audio = audio(
            .6 if index % 2 == 0 else -.6,
            samples=round(count * sample_rate / 24), sample_rate=sample_rate,
        )
        run, _ = recorder.record(values[0], model_frames, model_audio, previous_result=run)
        assert abs(run["results"][-1]["audio_phase_adjustment_samples"]) <= 2
    video, frame_count, _ = NODES.ZVLongVideoExecutionEnd().finish(plan, [run])
    assert video.get_components().audio["sample_rate"] == 44100
    assert video.get_components().audio["waveform"].shape[1] == 2
    expected = round(frame_count * 44100 / 24)
    assert video.get_components().audio["waveform"].shape[-1] == expected

    from comfy_api.latest import InputImpl, Types
    saved = tmp_path / f"phase-{segment_frames}-{overlap}-source-{sample_rate}.mp4"
    video.save_to(str(saved), format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264)
    restored = InputImpl.VideoFromFile(str(saved), duration=(expected + .25) / 44100).get_components()
    assert restored.audio["waveform"].shape[-1] == expected
    assert restored.images.shape[0] == frame_count
