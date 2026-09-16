import copy
import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
COMFY = ROOT.parents[1]
if str(COMFY) not in sys.path:
    sys.path.insert(0, str(COMFY))
PACKAGE = "zf_long_video_masks_testpkg"
package = importlib.util.module_from_spec(
    importlib.util.spec_from_loader(PACKAGE, loader=None, is_package=True)
)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
SPEC = importlib.util.spec_from_file_location(
    PACKAGE + ".long_video",
    ROOT / "long_video" / "__init__.py",
    submodule_search_locations=[str(ROOT / "long_video")],
)
LONG_VIDEO = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LONG_VIDEO
SPEC.loader.exec_module(LONG_VIDEO)
PLAN = importlib.import_module(SPEC.name + ".plan")
MASKS = importlib.import_module(SPEC.name + ".masks")
CONTRACT = importlib.import_module(PACKAGE + ".media_evidence.contract")


def video_asset(frames, has_audio=False):
    seconds = frames / 24
    return {
        "asset_id": "video",
        "name": "video.mp4",
        "kind": "video",
        "source_handle": "originals/" + "a" * 32 + ".mp4",
        "probe": {
            "size_bytes": 1000,
            "duration_seconds": seconds,
            "width": 8,
            "height": 6,
            "fps": 30,
            "frame_count": round(seconds * 30),
            "frame_count_exact": True,
            "vfr": False,
            "has_audio": has_audio,
            "sample_rate": 44100 if has_audio else None,
            "channels": 2 if has_audio else None,
            "codec": "fixture",
        },
    }


def project(frames, has_audio=False, canvas=None):
    seconds = frames / 24
    value = CONTRACT.empty_project()
    value["assets"] = [video_asset(frames, has_audio)]
    value["video_track"] = [{
        "clip_id": "video-clip",
        "asset_id": "video",
        "timeline_in_seconds": 0,
        "source_in_seconds": 0,
        "source_out_seconds": seconds,
        "source_audio_enabled": has_audio,
        "audio_link_id": "video-audio" if has_audio else None,
    }]
    if has_audio:
        value["audio_track"] = [{
            "clip_id": "video-audio",
            "asset_id": "video",
            "timeline_in_seconds": 0,
            "source_in_seconds": 0,
            "source_out_seconds": seconds,
            "origin": "video_source",
            "enabled": True,
            "linked_video_clip_id": "video-clip",
            "source_video_clip_id": "video-clip",
        }]
    if canvas is not None:
        value["output_canvas"] = {"width": canvas[0], "height": canvas[1]}
    return CONTRACT.normalize_project(value)


def segment_plan(frames=672, *, has_audio=False, canvas=None, **settings):
    value = PLAN.default_settings()
    value.update(settings)
    return PLAN.build_segment_plan(project(frames, has_audio, canvas), value)


def fake_decode(project_value, clip_id):
    assert clip_id == "video-clip"
    window = project_value["processing_window"]
    fps = window["fps"]
    count = round((window["end_seconds"] - window["start_seconds"]) * fps)
    canvas = project_value.get("output_canvas")
    asset = project_value["assets"][0]
    width = canvas["width"] if canvas else asset["probe"]["width"]
    height = canvas["height"] if canvas else asset["probe"]["height"]
    start = project_value["video_track"][0]["source_in_seconds"]
    values = torch.arange(count, dtype=torch.float32)[:, None, None, None]
    frames = values.expand(count, height, width, 3).clone()
    sampled = [start + index / fps for index in range(count)]
    item = {
        "sampling": {
            "method": "previous_pts",
            "target_start_seconds": start,
            "sampled_source_pts": sampled,
            "first_frame_repeated_count": 0,
            "tail_frame_repeated_count": 0,
            "source_vfr": False,
        },
        "decoded_pts_range": {
            "start_seconds": sampled[0],
            "end_seconds": sampled[-1],
        },
    }
    audio = None
    audio_manifest = None
    if project_value["video_track"][0]["source_audio_enabled"]:
        sample_rate = 44100
        sample_count = round(count * sample_rate / fps)
        source_start = round(start * sample_rate)
        values = torch.arange(
            source_start, source_start + sample_count, dtype=torch.float32,
        )[None, None]
        audio = {"waveform": values.repeat(1, 2, 1), "sample_rate": sample_rate}
        audio_manifest = {
            "sample_rate": sample_rate,
            "channels": 2,
            "sample_count": sample_count,
            "source_start_sample": source_start,
        }
    return frames, audio, {"items": [item], "original_audio": audio_manifest}


@pytest.fixture(autouse=True)
def controlled_decoder(monkeypatch):
    monkeypatch.setattr(MASKS, "_decode_project", fake_decode)


def error_code(call):
    with pytest.raises(MASKS.MaskSegmentError) as caught:
        call()
    return caught.value.code


def test_reader_emits_complete_clock_and_sampling_provenance():
    plan = segment_plan(240, segment_frames=120, overlap_frames=0, overlap_alignment="exact")
    frames, info, audio = MASKS.read_segment_video(plan, "video-clip", "全片", 1)

    assert frames.shape == (240, 6, 8, 3)
    assert info["kind"] == "zv-mask-source"
    assert info["source_handle"] == "originals/" + "a" * 32 + ".mp4"
    assert info["clip_source_range_frames"] == {"start": 0, "end": 240}
    assert info["fps"] == 24
    assert (info["width"], info["height"]) == (8, 6)
    assert info["absolute_start_frame"] == 0
    assert info["frame_count"] == info["decoded_frame_count"] == 240
    assert info["plan_revision"] == plan["revision"]
    assert len(info["sampling_fingerprint"]) == 64
    assert info["audio_policy"] == "clocked_silence"
    assert audio["sample_rate"] == 44100
    assert audio["waveform"].shape == (1, 2, 441000)
    assert not audio["waveform"].count_nonzero().item()
    assert MASKS.validate_mask_source(plan, info) is info


def test_segment_reader_explicitly_repeats_only_declared_tail_padding():
    plan = segment_plan()
    assert plan["segments"][1]["tail_padding_frames"] == 9

    frames, info, audio = MASKS.read_segment_video(plan, "video-clip", "当前分段", 2)

    assert frames.shape == (360, 6, 8, 3)
    assert info["absolute_start_frame"] == 321
    assert info["decoded_frame_count"] == 351
    assert info["tail_repeated_frames"] == 9
    assert info["clip_source_range_frames"] == {"start": 321, "end": 672}
    assert torch.equal(frames[-9:], frames[-10:-9].repeat(9, 1, 1, 1))
    assert info["sampling_evidence"]["plan_tail_repeated_count"] == 9
    assert audio["waveform"].shape[-1] == 661500


def test_non_grid_source_seconds_are_preserved_for_vfr_sampling(monkeypatch):
    value = project(720)
    value["video_track"][0]["source_in_seconds"] = .035
    value["video_track"][0]["source_out_seconds"] = 28.035
    value["assets"][0]["probe"].update(duration_seconds=30, vfr=True)
    plan = PLAN.build_segment_plan(CONTRACT.normalize_project(value), PLAN.default_settings())
    captured = {}
    def decode(project_value, clip_id):
        captured["source_in_seconds"] = project_value["video_track"][0]["source_in_seconds"]
        frames, audio, manifest = fake_decode(project_value, clip_id)
        manifest["items"][0]["sampling"]["source_vfr"] = True
        return frames, audio, manifest
    monkeypatch.setattr(MASKS, "_decode_project", decode)
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "当前分段", 1)
    assert captured["source_in_seconds"] == pytest.approx(.035)
    assert info["clip_source_range_seconds"]["start"] == pytest.approx(.035)
    assert info["sampling_evidence"]["target_start_seconds"] == pytest.approx(.035)
    assert info["sampling_evidence"]["source_vfr"] is True


def test_mask_bundle_accepts_empty_mask_but_rejects_missing_or_video_frames():
    plan = segment_plan(120, segment_frames=120, overlap_frames=0, overlap_alignment="exact")
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "全片", 1)

    empty = torch.zeros((1, 6, 8), dtype=torch.float32)
    fixed, report = MASKS.build_masked_segment_bundle(plan, empty, info, "固定区域")
    assert fixed["mask_mode"] == "fixed_region"
    assert "合法的全黑空遮罩" in report

    per_frame = torch.zeros((120, 6, 8), dtype=torch.float32)
    moving, _report = MASKS.build_masked_segment_bundle(plan, per_frame, info, "逐帧")
    assert moving["mask_mode"] == "per_frame"
    assert moving["processing_version"] == "zv-h3-full-frame-mask-c1-v2"
    assert moving["mask_content"]["shape"] == [120, 6, 8]
    assert len(moving["mask_content"]["sha256"]) == 64

    assert error_code(lambda: MASKS.build_masked_segment_bundle(
        plan, torch.zeros((119, 6, 8)), info, "逐帧"
    )) == "mask_missing_frames"
    assert error_code(lambda: MASKS.build_masked_segment_bundle(
        plan, torch.zeros((0, 6, 8)), info, "逐帧"
    )) == "mask_missing_frames"
    assert error_code(lambda: MASKS.build_masked_segment_bundle(
        plan, torch.zeros((2, 6, 8)), info, "固定区域"
    )) == "fixed_mask_frames"
    assert error_code(lambda: MASKS.build_masked_segment_bundle(
        plan, torch.zeros((120, 5, 8)), info, "逐帧"
    )) == "mask_dimensions"
    # IMAGE/video is B,H,W,C and must not be silently accepted as a MASK.
    assert error_code(lambda: MASKS.build_masked_segment_bundle(
        plan, torch.zeros((120, 6, 8, 3)), info, "逐帧"
    )) == "mask_shape"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, 1.01])
def test_mask_bundle_rejects_nonfinite_and_out_of_range_values(value):
    plan = segment_plan(120, segment_frames=120, overlap_frames=0, overlap_alignment="exact")
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "全片", 1)
    mask = torch.zeros((120, 6, 8), dtype=torch.float32)
    mask[0, 0, 0] = value
    assert error_code(lambda: MASKS.build_masked_segment_bundle(
        plan, mask, info, "逐帧",
    )) == "mask_values"


def test_generation_without_source_video_fails_before_decode():
    plan = PLAN.build_segment_plan(CONTRACT.empty_project(), {
        **PLAN.default_settings(), "mode": "generation_count", "segment_frames": 124,
        "overlap_frames": 39, "overlap_alignment": "h3_guide", "segment_count": 1,
    })
    assert plan["validation"]["ready"]
    assert error_code(lambda: MASKS.read_segment_video(plan, "", "全片", 1)) == "clip_id"
    assert error_code(lambda: MASKS.read_segment_video(plan, "missing-video", "全片", 1)) == "clip_missing"


def test_clock_provenance_rejects_tampering_and_other_plan_revision():
    plan = segment_plan(120, segment_frames=120, overlap_frames=0, overlap_alignment="exact")
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "全片", 1)

    tampered = copy.deepcopy(info)
    tampered["frame_count"] -= 1
    assert error_code(lambda: MASKS.validate_mask_source(plan, tampered)) == "sampling_fingerprint"

    another = copy.deepcopy(plan)
    another["revision"] = "f" * 64
    assert error_code(lambda: MASKS.validate_mask_source(another, info)) == "stale_plan"


def test_mask_bundle_rejects_runtime_tensor_mutation_after_binding():
    plan = segment_plan(120, segment_frames=120, overlap_frames=0, overlap_alignment="exact")
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "全片", 1)
    mask = torch.zeros((120, 6, 8), dtype=torch.float32)
    bundle, _report = MASKS.build_masked_segment_bundle(plan, mask, info, "逐帧")
    mask[0, 0, 0] = 1
    assert error_code(lambda: MASKS.slice_mask_for_segment(bundle, plan, 1)) == "mask_content_mismatch"


def test_mask_content_summary_is_stable_and_changes_for_one_pixel():
    plan = segment_plan(120, segment_frames=120, overlap_frames=0, overlap_alignment="exact")
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "全片", 1)
    first = torch.zeros((120, 6, 8), dtype=torch.float32)
    second = first.clone()
    third = first.clone()
    third[73, 4, 2] = 1

    first_bundle, _ = MASKS.build_masked_segment_bundle(plan, first, info, "逐帧")
    second_bundle, _ = MASKS.build_masked_segment_bundle(plan, second, info, "逐帧")
    third_bundle, _ = MASKS.build_masked_segment_bundle(plan, third, info, "逐帧")

    assert first_bundle["mask_content"] == second_bundle["mask_content"]
    assert first_bundle["bundle_fingerprint"] == second_bundle["bundle_fingerprint"]
    assert first_bundle["mask_content"]["sha256"] != third_bundle["mask_content"]["sha256"]
    assert first_bundle["bundle_fingerprint"] != third_bundle["bundle_fingerprint"]


def test_whole_clip_slice_has_identical_overlap_and_explicit_tail_repeat():
    plan = segment_plan()
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "全片", 1)
    values = torch.arange(672, dtype=torch.float32) / 671
    mask = values[:, None, None].expand(672, 6, 8).clone()
    bundle, _report = MASKS.build_masked_segment_bundle(plan, mask, info, "逐帧")

    first, first_info = MASKS.slice_mask_for_segment(bundle, plan, 1)
    second, second_info = MASKS.slice_mask_for_segment(bundle, plan, 2)

    assert first.shape == second.shape == (360, 6, 8)
    assert torch.equal(first[-39:], second[:39])
    assert first_info["overlap_frames"] == 0
    assert second_info["overlap_frames"] == 39
    assert second_info["source_mask_offset"] == 321
    assert second_info["source_mask_frame_count"] == 351
    assert second_info["tail_repeated_frames"] == 9
    assert torch.equal(second[-9:], second[-10:-9].repeat(9, 1, 1))


def test_mask_slice_node_maps_zero_based_loop_first_and_last_indices():
    plan = segment_plan()
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "全片", 1)
    values = torch.arange(672, dtype=torch.float32) / 671
    mask = values[:, None, None].expand(672, 6, 8).clone()
    bundle, _report = MASKS.build_masked_segment_bundle(plan, mask, info, "逐帧")

    node = MASKS.ZVSegmentMaskSlice()
    first, first_json = node.slice(bundle, plan, 0)
    last, last_json = node.slice(bundle, plan, len(plan["segments"]) - 1)
    first_evidence, last_evidence = json.loads(first_json), json.loads(last_json)

    assert first_evidence["segment_index"] == 1
    assert last_evidence["segment_index"] == len(plan["segments"])
    assert torch.equal(first[-39:], last[:39])


def test_segment_scoped_mask_cannot_be_used_for_another_segment():
    plan = segment_plan()
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "当前分段", 1)
    mask = torch.zeros((360, 6, 8), dtype=torch.float32)
    bundle, _report = MASKS.build_masked_segment_bundle(plan, mask, info, "逐帧")

    same, evidence = MASKS.slice_mask_for_segment(bundle, plan, 1)
    assert same is mask
    assert evidence["tail_repeated_frames"] == 0
    assert evidence["broadcast_repeated_frames"] == 0
    assert error_code(lambda: MASKS.slice_mask_for_segment(bundle, plan, 2)) == "segment_scope"


def test_segment_scoped_tail_ignores_supplied_padding_masks_and_repeats_last_real_mask():
    plan = segment_plan()
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "当前分段", 2)
    values = torch.arange(360, dtype=torch.float32) / 359
    mask = values[:, None, None].expand(360, 6, 8).clone()
    bundle, _report = MASKS.build_masked_segment_bundle(plan, mask, info, "逐帧")

    sliced, evidence = MASKS.slice_mask_for_segment(bundle, plan, 2)

    assert evidence["source_mask_frame_count"] == 351
    assert evidence["tail_repeated_frames"] == 9
    assert evidence["broadcast_repeated_frames"] == 0
    assert torch.equal(sliced[:351], mask[:351])
    assert torch.equal(sliced[-9:], mask[350:351].repeat(9, 1, 1))
    assert not torch.equal(sliced[-1], mask[-1])


def test_fixed_mask_reports_broadcast_separately_from_plan_tail_padding():
    plan = segment_plan()
    _frames, info, _audio = MASKS.read_segment_video(plan, "video-clip", "当前分段", 2)
    bundle, _report = MASKS.build_masked_segment_bundle(
        plan, torch.ones((1, 6, 8)), info, "固定区域",
    )
    sliced, evidence = MASKS.slice_mask_for_segment(bundle, plan, 2)
    assert sliced.shape[0] == 360
    assert evidence["tail_repeated_frames"] == 0
    assert evidence["broadcast_repeated_frames"] == 359


@pytest.mark.parametrize("change,code", [
    (lambda value: value.pop("validation"), "plan_not_ready"),
    (lambda value: value.__setitem__("validation", {"ready": True}), "plan_not_ready"),
    (lambda value: value.__setitem__("stale", True), "plan_stale"),
])
def test_mask_entry_rejects_unvalidated_or_stale_plan(change, code):
    plan = segment_plan(120, segment_frames=120, overlap_frames=0, overlap_alignment="exact")
    change(plan)
    assert error_code(lambda: MASKS.read_segment_video(plan, "video-clip", "全片", 1)) == code


@pytest.mark.parametrize("sampled", [[0.0, float("nan")], [0.2, 0.1]])
def test_sampling_pts_must_be_finite_and_monotonic(monkeypatch, sampled):
    plan = segment_plan(2, segment_frames=2, overlap_frames=0, overlap_alignment="exact")
    def broken(project_value, clip_id):
        frames, audio, manifest = fake_decode(project_value, clip_id)
        manifest["items"][0]["sampling"]["sampled_source_pts"] = sampled
        return frames, audio, manifest
    monkeypatch.setattr(MASKS, "_decode_project", broken)
    assert error_code(lambda: MASKS.read_segment_video(plan, "video-clip", "全片", 1)) == "sampling_evidence"


def test_missing_sampling_item_is_a_controlled_error(monkeypatch):
    plan = segment_plan(2, segment_frames=2, overlap_frames=0, overlap_alignment="exact")
    monkeypatch.setattr(MASKS, "_decode_project", lambda *_args: (
        torch.zeros((2, 6, 8, 3)), None, {"items": [None], "original_audio": None},
    ))
    assert error_code(lambda: MASKS.read_segment_video(plan, "video-clip", "全片", 1)) == "sampling_evidence"


def test_reader_rejects_scope_not_covered_by_one_selected_clip():
    plan = segment_plan(240, segment_frames=120, overlap_frames=0, overlap_alignment="exact")
    changed = copy.deepcopy(plan)
    changed["media_project"]["video_track"][0]["source_out_seconds"] = 5
    # Keep a syntactically valid revision so the coverage failure is the relevant boundary.
    changed["revision"] = "e" * 64
    assert error_code(lambda: MASKS.read_segment_video(
        changed, "video-clip", "全片", 1
    )) == "single_clip_coverage"


def test_node_contract_keeps_mask_models_external():
    assert MASKS.ZVSegmentVideoMaskSource.RETURN_TYPES == ("IMAGE", "ZV_MASK_SOURCE", "AUDIO")
    assert MASKS.ZVMaskedSegmentBundle.INPUT_TYPES()["required"]["mask"] == ("MASK",)
    assert MASKS.ZVMaskedSegmentBundle.RETURN_TYPES == ("ZV_MASKED_SEGMENT_BUNDLE", "STRING")
    assert MASKS.ZVSegmentMaskSlice.RETURN_TYPES == ("MASK", "STRING")
    assert MASKS.ZVH3MaskedSegmentLatent.RETURN_TYPES == (
        "LATENT", "IMAGE", "MASK", "AUDIO", "AUDIO", "STRING", "INT",
    )
    assert MASKS.ZVH3MaskedLatentRestore.RETURN_TYPES == ("LATENT", "STRING")
    assert MASKS.ZVH3MaskedFrameCompose.RETURN_TYPES == ("IMAGE", "STRING")


class FakeVideoVAE:
    def __init__(self):
        self.last_input = None
        self.first_stage_model = type("FakeH3InnerVAE", (), {
            "vae_ratio_t": 4,
            "clip_length": 17,
            "token_drop": 3,
            "frame_pre_padding": 3,
            "tokens_chunk_size": 5,
        })()

    def encode(self, frames):
        self.last_input = frames.clone()
        count, height, width, _channels = frames.shape
        latent_t = ((count - 5) // 17) * 5 + 2
        return torch.zeros((1, 24, latent_t, height // 16, width // 16))


class FakeAudioVAE:
    def __init__(self):
        self.last_input = None

    def encode(self, waveform):
        self.last_input = waveform.clone()
        latent_t = round(waveform.shape[1] * 40 / 32000)
        return torch.zeros((1, 32, 2, latent_t))


def h3_mask_fixture(frames, *, segment_frames, overlap=39, start=0, has_audio=True):
    plan = segment_plan(
        max(frames + start, 240),
        has_audio=has_audio,
        canvas=(32, 32),
        segment_frames=segment_frames,
        overlap_frames=overlap,
        overlap_alignment="h3_guide",
        range_start_frame=start,
        range_end_frame=start + frames,
    )
    source_frames, info, source_audio = MASKS.read_segment_video(
        plan, "video-clip", "全片", 1,
    )
    mask_values = torch.linspace(0, 1, frames)[:, None, None]
    mask = mask_values.expand(frames, 32, 32).clone()
    bundle, _report = MASKS.build_masked_segment_bundle(plan, mask, info, "逐帧")
    return plan, source_frames, source_audio, bundle


def prepare_h3(fixture, segment_index):
    plan, source_frames, source_audio, bundle = fixture
    video_vae, audio_vae = FakeVideoVAE(), FakeAudioVAE()
    result = MASKS.prepare_h3_masked_segment_latent(
        plan,
        segment_index,
        source_frames,
        source_audio,
        bundle,
        video_vae,
        audio_vae,
        "clocked_silence",
    )
    return result, video_vae, audio_vae


def test_h3_masked_adapter_exact_124_preserves_geometry_and_builds_nested_masks():
    fixture = h3_mask_fixture(124, segment_frames=124, overlap=39)
    (latent, model_frames, model_mask, model_audio, final_audio, report), _, _ = prepare_h3(
        fixture, 1,
    )
    evidence = json.loads(report)
    video, audio = latent["samples"].unbind()
    video_mask, audio_mask = latent["noise_mask"].unbind()

    assert model_frames.shape == (124, 32, 32, 3)
    assert model_mask.shape == (124, 32, 32)
    assert model_audio["sample_rate"] == 32000
    assert model_audio["waveform"].shape[-1] == round(124 * 32000 / 24)
    assert final_audio["sample_rate"] == 44100
    assert final_audio["waveform"].shape[-1] == round(124 * 44100 / 24)
    assert video.shape == video_mask.shape == (1, 24, 37, 2, 2)
    assert audio.shape == audio_mask.shape == (1, 32, 2, 207)
    assert not audio_mask.count_nonzero().item()
    assert evidence["model_grid_repeat_frames"] == 0
    assert evidence["plan_target_tail_repeat_frames"] == 0
    assert evidence["mask_processing_version"] == "zv-h3-full-frame-mask-c1-v2"
    assert len(evidence["mask_content"]["sha256"]) == 64
    assert evidence["pixel_model_mask_content"]["shape"] == [124, 32, 32]
    assert evidence["video_noise_mask_content"]["shape"] == [1, 24, 37, 2, 2]
    assert evidence["model_contract"]["video_vae_geometry"] == {
        "vae_ratio_t": 4, "clip_length": 17, "token_drop": 3,
        "frame_pre_padding": 3, "tokens_chunk_size": 5,
    }


def test_h3_masked_adapter_107_to_124_repeats_image_mask_and_zero_pads_only_model_audio():
    fixture = h3_mask_fixture(107, segment_frames=107, overlap=39)
    (latent, model_frames, model_mask, model_audio, final_audio, report), video_vae, audio_vae = prepare_h3(
        fixture, 1,
    )
    evidence = json.loads(report)
    logical_audio_samples = round(107 * 32000 / 24)

    assert evidence["frame_count"] == 107
    assert evidence["model_length"] == 124
    assert evidence["model_grid_repeat_frames"] == 17
    assert torch.equal(model_frames[-17:], model_frames[106:107].repeat(17, 1, 1, 1))
    assert torch.equal(model_mask[-17:], model_mask[106:107].repeat(17, 1, 1))
    assert torch.equal(video_vae.last_input, model_frames)
    assert not audio_vae.last_input[:, logical_audio_samples:, :].count_nonzero().item()
    assert model_audio["waveform"].shape[-1] == round(124 * 32000 / 24)
    assert final_audio["waveform"].shape[-1] == round(107 * 44100 / 24)
    assert evidence["model_audio_zero_padding_samples"] == (
        round(124 * 32000 / 24) - logical_audio_samples
    )
    assert latent["samples"].is_nested


def test_h3_masked_adapter_generic_150_frames_uses_158_frame_model_grid():
    fixture = h3_mask_fixture(150, segment_frames=150, overlap=39)
    plan = fixture[0]
    assert plan["segments"][0]["model_padding"]["adapter"] == "h3"
    # The adapter derives H3 geometry from frame_count even for a generic plan.
    plan["segments"][0]["model_padding"] = {
        "adapter": "none", "requested_frames": 150, "model_length": None,
        "predicted_final_frames": None, "actual_final_frames": None,
    }
    (latent, model_frames, model_mask, model_audio, final_audio, report), _, _ = prepare_h3(
        fixture, 1,
    )
    evidence = json.loads(report)

    assert evidence["frame_count"] == 150
    assert evidence["model_length"] == 158
    assert evidence["model_grid_repeat_frames"] == 8
    assert model_frames.shape[0] == model_mask.shape[0] == 158
    assert model_audio["waveform"].shape[-1] == round(158 * 32000 / 24)
    assert final_audio["waveform"].shape[-1] == round(150 * 44100 / 24)
    assert latent["samples"].unbind()[0].shape[2] == 47


@pytest.mark.parametrize("pixel_frame,latent_frame", [
    (1, 1), (5, 2), (16, 4), (18, 6), (40, 12), (80, 23),
])
def test_h3_causal_temporal_mask_groups_match_encoder(pixel_frame, latent_frame):
    frames = torch.zeros((124, 32, 32, 3), dtype=torch.float32)
    mask = torch.zeros((124, 32, 32), dtype=torch.float32)
    mask[pixel_frame] = 1
    audio = {
        "waveform": torch.zeros((1, 2, round(124 * 32000 / 24))),
        "sample_rate": 32000,
    }

    latent, _video, _audio, video_mask, _audio_mask = MASKS._encode_h3_masked_latent(
        frames, mask, audio, FakeVideoVAE(), FakeAudioVAE(),
    )
    active = torch.where(video_mask[0, 0].flatten(1).amax(dim=1) > 0)[0].tolist()

    assert active == [latent_frame]
    assert latent["noise_mask"].is_nested


def test_h3_spatial_mask_expands_one_latent_pixel_to_complete_2x2_token():
    frames = torch.zeros((124, 32, 32, 3), dtype=torch.float32)
    mask = torch.zeros((124, 32, 32), dtype=torch.float32)
    mask[0, 0, 0] = 1
    audio = {
        "waveform": torch.zeros((1, 2, round(124 * 32000 / 24))),
        "sample_rate": 32000,
    }

    _latent, _video, _audio, video_mask, _audio_mask = MASKS._encode_h3_masked_latent(
        frames, mask, audio, FakeVideoVAE(), FakeAudioVAE(),
    )

    assert torch.equal(video_mask[0, 0, 0], torch.ones((2, 2)))
    assert not video_mask[0, 0, 1:].count_nonzero().item()


def test_h3_mask_adapter_rejects_same_shape_vae_with_different_temporal_geometry():
    video_vae = FakeVideoVAE()
    video_vae.first_stage_model.token_drop = 0
    frames = torch.zeros((124, 32, 32, 3), dtype=torch.float32)
    mask = torch.zeros((124, 32, 32), dtype=torch.float32)
    audio = {
        "waveform": torch.zeros((1, 2, round(124 * 32000 / 24))),
        "sample_rate": 32000,
    }

    assert error_code(lambda: MASKS._encode_h3_masked_latent(
        frames, mask, audio, video_vae, FakeAudioVAE(),
    )) == "video_vae_geometry"


def test_h3_high_restore_uses_source_in_black_video_and_all_audio_regions():
    import comfy.nested_tensor

    fixture = h3_mask_fixture(124, segment_frames=124, overlap=39)
    (source_latent, _frames, model_mask, _model_audio, _final_audio, _report), _, _ = prepare_h3(
        fixture, 1,
    )
    source_video, source_audio = source_latent["samples"].unbind()
    reconciled = {
        "samples": comfy.nested_tensor.NestedTensor((
            torch.full_like(source_video, 7), torch.full_like(source_audio, 9),
        )),
    }
    binary = torch.zeros_like(model_mask)
    binary[62:] = 1

    restored, report = MASKS.restore_h3_masked_latent(reconciled, source_latent, binary)
    video, audio = restored["samples"].unbind()
    video_mask, audio_mask = restored["noise_mask"].unbind()
    evidence = json.loads(report)

    assert torch.equal(video[video_mask == 0], source_video[video_mask == 0])
    assert torch.equal(video[video_mask == 1], torch.full_like(video[video_mask == 1], 7))
    assert torch.equal(audio, source_audio)
    assert not audio_mask.count_nonzero().item()
    assert evidence["geometry_policy"] == "same_canvas_1x"
    assert evidence["audio_policy"] == "locked_source_latent"
    assert evidence["pixel_model_mask_content"]["shape"] == [124, 32, 32]
    assert evidence["video_noise_mask_content"]["shape"] == [1, 24, 37, 2, 2]
    assert evidence["video_noise_mask_content"]["sha256"] != evidence["pixel_model_mask_content"]["sha256"]


@pytest.mark.parametrize("change,code", [
    (lambda mask: mask.__setitem__((0, 0, 0), float("nan")), "high_mask_shape"),
    (lambda mask: mask.__setitem__((0, 0, 0), 1.1), "high_mask_shape"),
    (lambda mask: mask.resize_(124, 31, 32), "high_mask_geometry"),
])
def test_h3_high_restore_rejects_invalid_standard_mask(change, code):
    fixture = h3_mask_fixture(124, segment_frames=124, overlap=39)
    (source_latent, _frames, model_mask, _model_audio, _final_audio, _report), _, _ = prepare_h3(
        fixture, 1,
    )
    change(model_mask)
    assert error_code(lambda: MASKS.restore_h3_masked_latent(
        source_latent, source_latent, model_mask,
    )) == code


def test_h3_frame_compose_restores_black_and_preserves_white_pixels_exactly():
    generated = torch.full((2, 4, 4, 3), 9, dtype=torch.float32)
    source = torch.full_like(generated, 2)
    mask = torch.zeros((2, 4, 4), dtype=torch.float32)
    mask[:, :, 2:] = 1
    mask[:, 0, 1] = .5

    composed, report = MASKS.compose_h3_masked_frames(generated, source, mask)
    evidence = json.loads(report)

    assert torch.equal(composed[:, 1:, :2], source[:, 1:, :2])
    assert torch.equal(composed[:, :, 2:], generated[:, :, 2:])
    assert torch.equal(composed[:, 0, 0], source[:, 0, 0])
    assert torch.equal(composed[:, 0, 1], torch.full((2, 3), 5.5))
    assert evidence["pixel_policy"] == "black_source_white_generated_soft_blend"


def test_h3_masked_adapter_nonzero_global_start_uses_exact_audio_clock_slice():
    fixture = h3_mask_fixture(209, segment_frames=124, overlap=39, start=5)
    plan, _source_frames, _source_audio, _bundle = fixture
    (result, _video_vae, _audio_vae) = prepare_h3(fixture, 2)
    _latent, _frames, _mask, _model_audio, final_audio, report = result
    evidence = json.loads(report)
    segment = plan["segments"][1]
    expected_first = round(segment["start_frame"] * 44100 / 24)
    expected_last = round(segment["end_frame"] * 44100 / 24)

    assert final_audio["waveform"][0, 0, 0].item() == expected_first
    assert final_audio["waveform"][0, 0, -1].item() == expected_last - 1
    assert final_audio["waveform"].shape[-1] == expected_last - expected_first
    assert evidence["source_audio_sample_range"] == [
        expected_first - round(5 * 44100 / 24),
        expected_last - round(5 * 44100 / 24),
    ]


def test_h3_masked_adapter_two_segments_share_exact_39_frame_overlap():
    fixture = h3_mask_fixture(209, segment_frames=124, overlap=39)
    first = prepare_h3(fixture, 1)[0]
    second = prepare_h3(fixture, 2)[0]
    first_frames, first_mask, first_audio = first[1], first[2], first[4]["waveform"]
    second_frames, second_mask, second_audio = second[1], second[2], second[4]["waveform"]
    overlap_samples = round(124 * 44100 / 24) - round(85 * 44100 / 24)

    assert torch.equal(first_frames[-39:], second_frames[:39])
    assert torch.equal(first_mask[-39:], second_mask[:39])
    assert torch.equal(first_audio[..., -overlap_samples:], second_audio[..., :overlap_samples])
    first_video_mask = first[0]["noise_mask"].unbind()[0]
    second_video_mask = second[0]["noise_mask"].unbind()[0]
    assert torch.equal(first_video_mask[:, :, -12:], second_video_mask[:, :, :12])


def test_h3_masked_adapter_rejects_stale_revision_and_source_shape_mismatch():
    fixture = h3_mask_fixture(124, segment_frames=124, overlap=39)
    plan, source_frames, source_audio, bundle = fixture
    changed = copy.deepcopy(plan)
    changed["revision"] = "e" * 64
    assert error_code(lambda: MASKS.prepare_h3_masked_segment_latent(
        changed, 1, source_frames, source_audio, bundle,
        FakeVideoVAE(), FakeAudioVAE(), "clocked_silence",
    )) == "stale_plan"
    assert error_code(lambda: MASKS.prepare_h3_masked_segment_latent(
        plan, 1, source_frames[:-1], source_audio, bundle,
        FakeVideoVAE(), FakeAudioVAE(), "clocked_silence",
    )) == "source_frames_shape"


def test_h3_masked_adapter_200_target_separates_plan_tail_from_model_grid_padding():
    fixture = h3_mask_fixture(200, segment_frames=107, overlap=39)
    plan = fixture[0]
    segment_index = next(
        index for index, row in enumerate(plan["segments"], 1)
        if row["tail_padding_frames"]
    )
    result = prepare_h3(fixture, segment_index)[0]
    _latent, model_frames, model_mask, _model_audio, final_audio, report = result
    evidence = json.loads(report)
    segment = plan["segments"][segment_index - 1]

    assert evidence["plan_target_tail_repeat_frames"] == segment["tail_padding_frames"]
    assert evidence["model_grid_repeat_frames"] == 17
    assert evidence["model_length"] == 124
    assert model_frames.shape[0] == model_mask.shape[0] == 124
    assert final_audio["waveform"].shape[-1] == (
        round(segment["end_frame"] * 44100 / 24)
        - round(segment["start_frame"] * 44100 / 24)
    )
