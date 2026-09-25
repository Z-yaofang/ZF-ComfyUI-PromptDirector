"""Outer-loop parity: preserve source cuts and the original graph's actual output."""

import copy
from fractions import Fraction
import importlib
import importlib.util
from pathlib import Path
import sys
import subprocess
import types

import av
import numpy as np
import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
COMFY = ROOT.parents[1]
sys.path.insert(0, str(COMFY))
PACKAGE = "zf_animate_execution_testpkg"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
EXECUTION = importlib.import_module(PACKAGE + ".animate_video.execution")
ASSEMBLY = importlib.import_module(PACKAGE + ".animate_video.assembly")
PLAN = importlib.import_module(PACKAGE + ".animate_video.plan")
NODES = importlib.import_module(PACKAGE + ".animate_video.nodes")
MASKING = importlib.import_module(PACKAGE + ".animate_video.masking")


def test_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


test_module.__test__ = False
FIXTURE = test_module("zf_animate_runtime_fixtures", "test_animate_plan.py")
MEDIA = test_module("zf_animate_runtime_media", "media_outlet_smoke.py")


def plan(lengths=(8, 5, 1), mode="continuation_21", fps=30, audio=False):
    start, windows = 0, []
    for length in lengths:
        windows.append((start, start + length))
        start += length
    source = FIXTURE.upstream_clips(FIXTURE.project(start, pictures=len(lengths), audio=audio, fps=fps), windows)
    return PLAN.build_plan(source, FIXTURE.settings(mode), fps=fps)


def numbered(count, offset=0):
    return (torch.arange(count, dtype=torch.float32) + offset).reshape(-1, 1, 1, 1).expand(-1, 24, 32, 3).clone()


@pytest.mark.parametrize("mode", ["hard_cut", "continuation_21"])
def test_mask_index_uses_local_source_and_actual_front_padding_not_transition(mode):
    original = plan((8, 5, 1), mode=mode)
    settings = {**original["settings"], "mask_enabled": True, "mask_tasks": {
        f"clip-{i}": {"asset_id": "video", "source_frame": frame, "prompt": f"target {i}"}
        for i, frame in enumerate((7, 8, 13))}}
    value = PLAN.build_plan(original["media_project"], settings, fps=30)
    for i, (count, padding, expected) in enumerate(((8, 1, 8), (5, 4, 4), (1, 4, 4))):
        context = EXECUTION.segment_context(value, i)
        index, text = MASKING.ZVAnimateMaskFrame().align(context, numbered(count + padding), padding)
        assert index == expected and text == f"target {i}"
        with pytest.raises(ValueError, match="前补帧接线"):
            MASKING.ZVAnimateMaskFrame().align(context, numbered(count), padding)
        white = torch.ones(1, 24, 32)
        assert MASKING.ZVAnimateMaskSeed().validate(context, white)[0] is white
        with pytest.raises(ValueError, match=f"第 {i + 1} 段.*未得到有效遮罩"):
            MASKING.ZVAnimateMaskSeed().validate(context, torch.zeros_like(white))


def test_global_mask_gate_does_not_request_mask_path_in_motion_mode(monkeypatch):
    gate = MASKING.ZVAnimateMaskGate()
    context = EXECUTION.segment_context(plan(), 0)
    assert gate.check_lazy_status(context) == []
    assert gate.route(context) == {"ui": {"gifs": []}, "result": (None, None)}
    context["mask_enabled"] = True
    assert gate.check_lazy_status(context) == ["mask", "bg_images"]
    frames, masks = numbered(8), torch.ones(8, 24, 32)
    assert gate.check_lazy_status(context, masks) == ["bg_images"]
    calls = []
    ui = {"gifs": [{"filename": "mask.mp4", "type": "temp"}]}

    class Preview:
        def combine_video(self, **kwargs):
            calls.append(kwargs)
            return {"ui": ui}

    monkeypatch.setitem(sys.modules, "nodes", types.SimpleNamespace(NODE_CLASS_MAPPINGS={"VHS_VideoCombine": Preview}))
    shown = gate.route(context, masks, frames)
    assert shown["result"] == (masks, frames) and shown["ui"] is ui
    assert len(calls) == 1 and calls[0]["images"] is frames
    assert {key: value for key, value in calls[0].items() if key != "images"} == {
        "frame_rate": 30, "loop_count": 0, "filename_prefix": "Animate-mask-bg-segment-1",
        "format": "video/h264-mp4", "pingpong": False, "save_output": False}
    assert not getattr(MASKING.ZVAnimateMaskGate, "OUTPUT_NODE", False)
    with pytest.raises(ValueError, match="帧数/尺寸"):
        gate.route(context, masks[:1], frames)


@pytest.mark.parametrize("mask_ndim", [2, 3])
@pytest.mark.parametrize("channels", [3, 4])
@pytest.mark.parametrize("mask_scale", [1, 2])
def test_mask_seed_preview_preserves_inputs_and_returns_core_image_ui(monkeypatch, mask_ndim, channels, mask_scale):
    captured = {}
    ui = {"images": [{"filename": "seed.png", "subfolder": "", "type": "temp"}]}

    class Preview:
        def save_images(self, images, filename_prefix):
            captured.update(images=images, filename_prefix=filename_prefix)
            return {"ui": ui}

    monkeypatch.setitem(sys.modules, "nodes", types.SimpleNamespace(NODE_CLASS_MAPPINGS={"PreviewImage": Preview}))
    context = {"segment": {"ordinal": 2, "mask_task": {"source_frame": 155, "prompt": "shirt"}}}
    mask = torch.zeros(1, 24 // mask_scale, 32 // mask_scale, dtype=torch.float16)
    mask[:, 2:8, 4:10] = .8
    if mask_ndim == 2:
        mask = mask[0]
    reference = torch.full((1, 24, 32, channels), .2, dtype=torch.float16)
    old_mask, old_reference = mask.clone(), reference.clone()
    output = MASKING.ZVAnimateMaskSeed().validate(context, mask, reference)
    assert output["result"][0] is mask and output["ui"] is ui
    assert torch.equal(mask, old_mask) and torch.equal(reference, old_reference)
    assert MASKING.ZVAnimateMaskSeed.INPUT_TYPES()["optional"]["reference_image"] == ("IMAGE",)
    assert not getattr(MASKING.ZVAnimateMaskSeed, "OUTPUT_NODE", False)
    comparison = captured["images"]
    assert comparison.shape == (1, 24, 96, 3)
    assert comparison.device.type == "cpu" and comparison.dtype == torch.float32
    assert captured["filename_prefix"] == "Animate-mask-seed-2"
    original, overlay, binary = comparison.split(32, dim=2)
    assert torch.equal(original, reference[..., :3].float())
    displayed_seed = mask.reshape(1, 24 // mask_scale, 32 // mask_scale, 1).float()
    displayed_seed = displayed_seed.repeat_interleave(mask_scale, dim=1).repeat_interleave(mask_scale, dim=2)
    alpha = displayed_seed * .6
    expected = original * (1 - alpha)
    expected[..., 1:2] += alpha
    assert torch.equal(overlay, expected)
    assert torch.equal(binary, (displayed_seed > .5).float().expand(-1, -1, -1, 3))


def test_mask_seed_without_reference_does_not_load_preview_backend(monkeypatch):
    monkeypatch.setitem(sys.modules, "nodes", types.SimpleNamespace(NODE_CLASS_MAPPINGS={}))
    context = {"segment": {"ordinal": 1, "mask_task": {"source_frame": 0, "prompt": "shirt"}}}
    mask = torch.ones(1, 24, 32)
    result = MASKING.ZVAnimateMaskSeed().validate(context, mask)
    assert isinstance(result, tuple) and len(result) == 1 and result[0] is mask


@pytest.mark.parametrize("shape", [(2, 24, 32, 3), (1, 24, 32, 2), (24, 32, 3)])
def test_mask_seed_preview_requires_single_rgb_or_rgba_reference_frame(shape):
    context = {"segment": {"ordinal": 1, "mask_task": {"source_frame": 0, "prompt": "shirt"}}}
    with pytest.raises(ValueError, match="单张 RGB 或 RGBA 参考帧"):
        MASKING.ZVAnimateMaskSeed().validate(context, torch.ones(1, 24, 32), torch.ones(shape))


class FakeEncoder:
    def __init__(self):
        self.frames, self.audio = {}, {}

    def __call__(self, images, sound, fps, path):
        path = Path(path)
        self.frames[path] = images.clone()
        self.audio[path] = sound["waveform"].clone()
        path.write_bytes(b"generated-frame-fixture")
        return {"encoded_frame_count": len(images), "fps": fps, "audio_sample_rate": 44100,
                "audio_channels": 2, "decoded_audio_sample_count": sound["waveform"].shape[-1]}


@pytest.mark.parametrize("mode", ["hard_cut", "continuation_21"])
@pytest.mark.parametrize("counts", [(8, 5, 1), (7, 4, 2), (10, 9, 4)])
def test_recorder_preserves_actual_frames_and_short_tail_without_padding(tmp_path, mode, counts):
    value, encoder, previous = plan(mode=mode), FakeEncoder(), None
    for index, count in enumerate(counts):
        context = EXECUTION.segment_context(value, index)
        assert "model_frame_count" not in context
        guide = EXECUTION.load_guide(context, previous, tmp_path)
        if index and mode == "continuation_21":
            assert torch.equal(guide, numbered(counts[index - 1], (index - 1) * 100)[-21:])
        else:
            assert guide is None
        previous = EXECUTION.persist_segment(context, numbered(count, index * 100), None, previous, tmp_path, encoder)
    paths, manifest = EXECUTION.complete_run(value, previous, tmp_path)
    assert manifest["actual_frame_count"] == sum(counts)
    assert manifest["expected_frame_count"] == 14
    assert manifest["frame_delta"] == sum(counts) - 14
    for index, (path, row) in enumerate(zip(paths, manifest["segments"])):
        assert torch.equal(encoder.frames[path], numbered(counts[index], index * 100))
        assert row["frame_delta"] == counts[index] - (8, 5, 1)[index]
        assert row["output_start_frame"] == sum(counts[:index])
        assert row["output_end_frame"] == sum(counts[:index + 1])


def test_native_21_uses_exact_previous_final_tail_and_not_model_padding(tmp_path):
    value, encoder = plan((30, 30)), FakeEncoder()
    first, second = [EXECUTION.segment_context(value, index) for index in (0, 1)]
    run = EXECUTION.persist_segment(first, numbered(29), None, None, tmp_path, encoder)
    guide = EXECUTION.load_guide(second, run, tmp_path)
    assert torch.equal(guide[:, 0, 0, 0], torch.arange(8, 29, dtype=torch.float32))


@pytest.mark.parametrize("actual", [6, 10])
def test_actual_video_length_changes_only_audio_tail_with_explicit_evidence(tmp_path, actual):
    value, encoder = plan((8,), audio=True), FakeEncoder()
    context = EXECUTION.segment_context(value, 0)
    samples = round(8 * 44100 / 30)
    source = {"sample_rate": 44100, "waveform": torch.ones((1, 2, samples)) * .3}
    before = source["waveform"].clone()
    run = EXECUTION.persist_segment(context, numbered(actual), source, None, tmp_path, encoder)
    paths, manifest = EXECUTION.complete_run(value, run, tmp_path)
    target = round(actual * 44100 / 30)
    fit = manifest["segments"][0]["audio_fit"]
    wave = encoder.audio[paths[0]]
    assert wave.shape[-1] == target
    assert fit["trimmed_tail_samples"] == max(0, samples - target)
    assert fit["padded_silence_samples"] == max(0, target - samples)
    assert torch.all(wave[..., :min(samples, target)] == .3)
    assert torch.count_nonzero(wave[..., samples:]) == 0
    assert torch.equal(source["waveform"], before)


@pytest.mark.parametrize("fps", [29, 30000 / 1001, 60000 / 1001])
def test_actual_audio_clock_telescopes_without_repeated_previous_audio(tmp_path, fps):
    value, encoder, run = plan(audio=True, fps=fps), FakeEncoder(), None
    for index, actual in enumerate((7, 6, 2)):
        context = EXECUTION.segment_context(value, index)
        count = context["segment"]["frame_count"]
        source = {"sample_rate": 44100, "waveform": torch.full((1, 2, round(count * 44100 / fps)), (index + 1) / 10)}
        run = EXECUTION.persist_segment(context, numbered(actual), source, run, tmp_path, encoder)
    paths, manifest = EXECUTION.complete_run(value, run, tmp_path)
    assert sum(row["audio_samples"] for row in manifest["segments"]) == round(15 * 44100 / fps)
    for index, path in enumerate(paths):
        assert encoder.audio[path][0, 0, 0].item() == pytest.approx((index + 1) / 10)


@pytest.mark.parametrize("bad", ["empty", "nonfinite"])
def test_empty_or_invalid_original_result_is_not_published(tmp_path, bad):
    value, encoder = plan((8,)), FakeEncoder()
    frames = numbered(0) if bad == "empty" else numbered(8)
    if bad == "nonfinite":
        frames[0, 0, 0, 0] = float("nan")
    with pytest.raises(ValueError):
        EXECUTION.persist_segment(EXECUTION.segment_context(value, 0), frames, None, None, tmp_path, encoder)
    assert not encoder.frames


def test_manifest_and_guide_tampering_fail_before_next_iteration(tmp_path):
    value, encoder = plan((30, 30)), FakeEncoder()
    first, second = [EXECUTION.segment_context(value, index) for index in (0, 1)]
    run = EXECUTION.persist_segment(first, numbered(30), None, None, tmp_path, encoder)
    directory, manifest = EXECUTION.load_run(tmp_path, run, value["plan_fingerprint"], 1)
    (directory / manifest["segments"][0]["guide"]["file"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="衔接文件"):
        EXECUTION.load_guide(second, run, tmp_path)
    (directory / "manifest.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="运行记录"):
        EXECUTION.load_run(tmp_path, run, value["plan_fingerprint"], 1)


def original_vhs():
    package = types.ModuleType("zf_original_vhs_fixture")
    package.__path__ = [str(COMFY / "custom_nodes" / "ComfyUI-VideoHelperSuite" / "videohelpersuite")]
    sys.modules.setdefault(package.__name__, package)
    # The loader only needs this registry and queue handle, not model imports or a server.
    with pytest.MonkeyPatch.context() as patch:
        if "nodes" not in sys.modules:
            registry = types.ModuleType("nodes")
            registry.VHSLoadFormats = {}
            patch.setitem(sys.modules, "nodes", registry)
        if "server" not in sys.modules:
            server = types.ModuleType("server")
            server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(prompt_queue=None))
            patch.setitem(sys.modules, "server", server)
        elif not hasattr(sys.modules["server"].PromptServer, "instance"):
            patch.setattr(sys.modules["server"].PromptServer, "instance", types.SimpleNamespace(prompt_queue=None), raising=False)
        return importlib.import_module(package.__name__ + ".load_video_nodes").LoadVideoUpload()


@pytest.mark.parametrize("fps", [12, 24])
@pytest.mark.parametrize("size", [(0, 0), (64, 96)])
def test_entry_matches_actual_original_vhs_frames_info_audio_and_resize(tmp_path, monkeypatch, fps, size):
    store, source = MEDIA.imported_project(tmp_path)
    import folder_paths
    monkeypatch.setattr(folder_paths, "input_directory", str(store.input_root))
    value = PLAN.build_plan(source, FIXTURE.settings(), fps=fps)
    assert value["validation"]["ready"]
    loader = original_vhs()
    for index, row in enumerate(value["segments"]):
        context = EXECUTION.segment_context(value, index)
        picture, frames, audio, info = EXECUTION.decode_segment(value, context, store, *size, loader=loader.load_video)
        asset = next(asset for asset in source["assets"] if asset["asset_id"] == row["video_asset_id"])
        expected, count, original_audio, original_info = loader.load_video(video=store.resolve(asset["source_handle"]).relative_to(store.input_root).as_posix(), force_rate=fps,
            custom_width=size[0], custom_height=size[1], skip_first_frames=row["load_start_frame"],
            frame_load_cap=row["frame_count"], select_every_nth=1, format="None")
        assert torch.equal(frames, expected)
        assert count == len(frames) == row["frame_count"]
        assert info == original_info and len(info) == 10
        assert picture.shape[0] == 1
        if row["source_audio_enabled"]:
            assert audio["sample_rate"] == original_audio["sample_rate"]
            assert torch.equal(audio["waveform"], original_audio["waveform"])
        else:
            assert audio is None


def test_near_integer_source_rate_preserves_every_native_frame_across_cuts(tmp_path, monkeypatch):
    store, source = MEDIA.imported_project(tmp_path)
    import folder_paths
    monkeypatch.setattr(folder_paths, "input_directory", str(store.input_root))
    path, handle, name = store.allocate("near-30-fps.mp4")
    source_fps = Fraction(30000001, 1000000)
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264rgb", rate=source_fps)
        stream.width, stream.height, stream.pix_fmt = 32, 24, "rgb24"
        stream.options = {"crf": "0", "preset": "ultrafast"}
        for index in range(355):
            pixels = np.empty((24, 32, 3), dtype=np.uint8)
            pixels[:] = (index % 256, index // 256, 100)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = index, 1 / source_fps
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    asset = store.finish_import(path, handle, name)
    assert 30 < asset["probe"]["fps"] < 30.00001
    source["assets"].append(asset)
    cuts = (0, 3.8, float(355 / source_fps))
    source["video_track"] = [dict(clip_id=f"near-{index}", asset_id=asset["asset_id"],
        timeline_in_seconds=start, source_in_seconds=start, source_out_seconds=end,
        source_audio_enabled=False, audio_link_id=None)
        for index, (start, end) in enumerate(zip(cuts, cuts[1:]))]
    source["audio_track"] = []
    settings = {**FIXTURE.settings("hard_cut"), "mask_enabled": True, "mask_tasks": {
        f"near-{index}": {"asset_id": asset["asset_id"], "source_frame": frame, "prompt": "target"}
        for index, frame in enumerate((113, 155))}}
    value = PLAN.build_plan(source, settings, fps=30)
    assert value["validation"]["ready"]
    assert [row["frame_count"] for row in value["segments"]] == [114, 241]
    loader = original_vhs()
    inputs = dict(video=path.relative_to(store.input_root).as_posix(), custom_width=0,
        custom_height=0, select_every_nth=1, format="None")
    native, count, _audio, _info = loader.load_video(**inputs, force_rate=0,
        frame_load_cap=0, skip_first_frames=0)
    assert count == len(native) == 355
    assert torch.unique(native[:, 0, 0], dim=0).shape[0] == 355
    # The original forced-30 path drops a real frame, including on the second read.
    forced_first, _count, _audio, _info = loader.load_video(**inputs, force_rate=30,
        frame_load_cap=114, skip_first_frames=0)
    forced_tail, forced_count, _audio, _info = loader.load_video(**inputs, force_rate=30,
        frame_load_cap=241, skip_first_frames=114)
    assert forced_count == 240
    assert torch.equal(forced_first, torch.cat((native[:1], native[2:115])))
    assert torch.equal(forced_tail, native[115:])
    decoded = []
    for index in range(2):
        context = EXECUTION.segment_context(value, index)
        _picture, frames, audio, _info = EXECUTION.decode_segment(value, context, store, loader=loader.load_video)
        assert audio is None
        local_index, text = MASKING.ZVAnimateMaskFrame().align(context, frames, 0)
        assert local_index == (113, 41)[index] and text == "target"
        decoded.append(frames)
    assert [len(frames) for frames in decoded] == [114, 241]
    assert torch.equal(decoded[0][0], native[0])
    assert torch.equal(decoded[1][0], native[114])
    assert torch.equal(torch.cat(decoded), native)


def test_actual_frame_difference_is_visible_in_nodes_and_end(tmp_path, monkeypatch):
    monkeypatch.setattr(NODES, "_temp_root", lambda: tmp_path)
    value = plan((8, 5))
    run = None
    for index, count in enumerate((7, 6)):
        context = EXECUTION.segment_context(value, index)
        run, report = NODES.ZVAnimateSegmentRecorder().record(context, torch.full((count, 24, 32, 3), .2 + .3 * index), previous_result=run)
        assert "⚠ 帧数差异" in report
        assert f"实际 {count} 帧" in report
    output = NODES.ZVAnimateExecutionEnd().finish(value, [run])
    video, count, report = output["result"]
    assert output["ui"] == {"text": [report]}
    assert count == 13
    assert "8→7（-1）" in report and "5→6（+1）" in report
    assert video.get_components().images.shape[0] == 13
    with av.open(str(video._animate_path)) as source:
        assert [frame.pts * frame.time_base for frame in source.decode(video=0)] == [Fraction(index, 30) for index in range(13)]


def test_entry_public_slots_keep_original_vhs_four_output_contract():
    assert NODES.ZVAnimateExecutionEntry.RETURN_TYPES[1:5] == ("IMAGE", "INT", "AUDIO", "VHS_VIDEOINFO")
    assert NODES.ZVAnimateExecutionEntry.RETURN_NAMES[1:5] == ("source_frames", "frame_count", "source_audio", "video_info")
    assert "fps" in NODES.ZVAnimateSegmentDesk.INPUT_TYPES()["optional"]
    assert NODES.ZVAnimateSegmentDesk.INPUT_TYPES()["optional"]["fps"][0] == "INT,FLOAT"
    assert not any(name.startswith("dependency_") for name in NODES.ZVAnimateSegmentRecorder.INPUT_TYPES()["optional"])
    quality = NODES.ZVAnimateExecutionEnd.INPUT_TYPES()["optional"]["output_quality"]
    assert quality[1]["default"] == ASSEMBLY.DEFAULT_OUTPUT_QUALITY
    assert set(quality[0]) == set(ASSEMBLY.OUTPUT_QUALITY_PROFILES)


@pytest.mark.parametrize("source_rate", [44100, 48000])
@pytest.mark.parametrize("source_seconds", [0, .5])
def test_short_or_empty_valid_audio_preserves_content_and_reports_silent_tail(tmp_path, source_rate, source_seconds):
    value, encoder = plan((30,), audio=True), FakeEncoder()
    context = EXECUTION.segment_context(value, 0)
    source = {"sample_rate": source_rate, "waveform": torch.full((1, 1, round(source_seconds * source_rate)), .3)}
    before = source["waveform"].clone()
    run = EXECUTION.persist_segment(context, numbered(30), source, None, tmp_path, encoder)
    paths, manifest = EXECUTION.complete_run(value, run, tmp_path)
    wave, fit = encoder.audio[paths[0]], manifest["segments"][0]["audio_fit"]
    assert wave.shape == (1, 2, 44100)
    assert torch.equal(wave[:, 0], wave[:, 1])
    assert fit["source_input_samples"] == round(source_seconds * source_rate)
    assert fit["source_samples"] == round(source_seconds * 44100)
    assert fit["trimmed_tail_samples"] == 0
    assert fit["padded_silence_samples"] == 44100 - fit["source_samples"]
    assert torch.count_nonzero(wave[..., fit["source_samples"]:]) == 0
    assert torch.equal(source["waveform"], before)
    if source_seconds:
        assert wave[0, 0, 1000].item() == pytest.approx(.3, abs=.002)


def test_audio_past_authored_cut_is_not_used_to_fill_longer_generated_video():
    context = EXECUTION.segment_context(plan((30,), audio=True), 0)
    source = {"sample_rate": 44100, "waveform": torch.full((1, 2, 88200), .2)}
    sound, fit = EXECUTION._contribution_audio(source, context, 45, 0)
    assert sound["waveform"].shape[-1] == 66150
    assert torch.count_nonzero(sound["waveform"][..., 44100:]) == 0
    assert fit["trimmed_tail_samples"] == 44100
    assert fit["padded_silence_samples"] == 22050


@pytest.mark.parametrize("bad", ["none", "channels", "integer", "nonfinite", "rate", "kernel"])
def test_invalid_or_missing_enabled_audio_does_not_silently_become_silence(bad):
    context = EXECUTION.segment_context(plan((30,), audio=True), 0)
    source = {"sample_rate": 44100, "waveform": torch.zeros((1, 2, 100))}
    if bad == "none":
        source = None
    elif bad == "channels":
        source["waveform"] = torch.zeros((1, 6, 100))
    elif bad == "integer":
        source["waveform"] = torch.zeros((1, 2, 100), dtype=torch.int16)
    elif bad == "nonfinite":
        source["waveform"][0, 0, 0] = float("nan")
    elif bad == "rate":
        source["sample_rate"] = True
    elif bad == "kernel":
        source["sample_rate"] = 47999
    with pytest.raises(ValueError):
        EXECUTION._contribution_audio(source, context, 30, 0)


def test_actual_vhs_short_source_audio_records_instead_of_failing_after_generation(tmp_path, monkeypatch):
    MEDIA.make_fixtures(tmp_path)
    loader = original_vhs()
    import folder_paths
    monkeypatch.setattr(folder_paths, "input_directory", str(tmp_path))
    ffmpeg = sys.modules["zf_original_vhs_fixture.utils"].ffmpeg_path
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(tmp_path / "voiced.mkv"),
        "-filter_complex", "[0:a]atrim=end=1.5[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy",
        "-c:a", "pcm_s16le", str(tmp_path / "short-audio.mkv")], check=True)
    frames, count, audio, _info = loader.load_video(video="short-audio.mkv", force_rate=12,
        custom_width=0, custom_height=0, frame_load_cap=36, skip_first_frames=0, select_every_nth=1, format="None")
    assert count == 36 and audio["waveform"].shape[-1] == 72000 and audio["sample_rate"] == 48000
    value, encoder = plan((36,), mode="hard_cut", fps=12, audio=True), FakeEncoder()
    result = EXECUTION.persist_segment(EXECUTION.segment_context(value, 0), frames, audio, None, tmp_path, encoder)
    paths, manifest = EXECUTION.complete_run(value, result, tmp_path)
    fit = manifest["segments"][0]["audio_fit"]
    assert manifest["actual_frame_count"] == 36
    assert fit["padded_silence_samples"] == 66150 and fit["source_input_samples"] == 72000
    assert encoder.audio[paths[0]].shape[-1] == 132300


@pytest.mark.parametrize("enabled", [True, False])
def test_vhs_empty_audio_tail_fails_at_entry_before_generation_unless_disabled(tmp_path, monkeypatch, enabled):
    import folder_paths
    import shutil
    store, source = MEDIA.imported_project(tmp_path)
    loader = original_vhs()
    monkeypatch.setattr(folder_paths, "input_directory", str(store.input_root))
    ffmpeg = sys.modules["zf_original_vhs_fixture.utils"].ffmpeg_path
    short = tmp_path / "short-audio.mkv"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(tmp_path / "fixtures" / "voiced.mkv"),
        "-filter_complex", "[0:a]atrim=end=1.5[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "pcm_s16le", str(short)], check=True)
    path, handle, name = store.allocate(short.name)
    shutil.copyfile(short, path)
    asset = store.finish_import(path, handle, name)
    source["assets"].append(asset)
    clip = next(row for row in source["video_track"] if row["source_audio_enabled"])
    clip.update(asset_id=asset["asset_id"], source_in_seconds=2, source_out_seconds=3,
                timeline_in_seconds=0, source_audio_enabled=enabled)
    sound = next(row for row in source["audio_track"] if row["clip_id"] == clip["audio_link_id"])
    sound.update(asset_id=asset["asset_id"], source_in_seconds=2, source_out_seconds=3, timeline_in_seconds=0, enabled=enabled)
    source["video_track"], source["audio_track"], source["picture_track"] = [clip], [sound], source["picture_track"][:1]
    value = PLAN.build_plan(source, FIXTURE.settings(), fps=12)
    assert value["validation"]["ready"]
    context = EXECUTION.segment_context(value, 0)
    if enabled:
        monkeypatch.setattr(EXECUTION, "execute_outlet", lambda *args: pytest.fail("audio failure must precede further input and GPU work"))
        with pytest.raises(ValueError, match="第 1 段原声加载失败.*2.000–3.000") as error:
            EXECUTION.decode_segment(value, context, store, loader=loader.load_video)
        assert isinstance(error.value.__cause__, ValueError)
    else:
        _picture, frames, audio, _info = EXECUTION.decode_segment(value, context, store, loader=loader.load_video)
        assert len(frames) == 12 and audio is None
