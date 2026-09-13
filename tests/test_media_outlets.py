"""Stable identity, time-window planning, and real standard media outlet regressions."""
import copy
from fractions import Fraction
import importlib
import importlib.util
import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zf_outlet_test_fixtures", ROOT / "tests" / "media_outlet_smoke.py")
SMOKE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SMOKE
SPEC.loader.exec_module(SMOKE)
C, S = SMOKE.C, SMOKE.S
O = importlib.import_module(SMOKE.SPEC.name + ".outlet")
D = importlib.import_module(SMOKE.SPEC.name + ".outlet_decode")
N = importlib.import_module(SMOKE.SPEC.name + ".outlet_nodes")
R = importlib.import_module(SMOKE.SPEC.name + ".runtime")


def asset(kind, identifier, audio=False):
    return {"asset_id": identifier, "name": identifier + ".fixture", "kind": kind, "source_handle": "originals/" + "a" * 32 + {"picture": ".png", "video": ".mkv", "audio": ".wav"}[kind], "probe": {"size_bytes": 500, "duration_seconds": None if kind == "picture" else 20, "width": None if kind == "audio" else 32, "height": None if kind == "audio" else 24, "fps": 30 if kind == "video" else None, "frame_count": 600 if kind == "video" else None, "frame_count_exact": kind == "video", "vfr": False if kind == "video" else None, "has_audio": audio or kind == "audio", "sample_rate": 48000 if audio or kind == "audio" else None, "channels": 1 if audio or kind == "audio" else None, "codec": "fixture"}}


def project():
    p = C.empty_project()
    p["processing_window"].update(start_seconds=10, end_seconds=12.25, fps=10)
    p["assets"] = [asset("picture", "p1"), asset("picture", "p2"), asset("video", "v", True), asset("audio", "a")]
    p["picture_track"] = [dict(item_id="first", asset_id="p1", order=1), dict(item_id="second", asset_id="p2", order=2)]
    p["video_track"] = [dict(clip_id="video", asset_id="v", timeline_in_seconds=9, source_in_seconds=2, source_out_seconds=6, source_audio_enabled=True, audio_link_id="original")]
    p["audio_track"] = [dict(clip_id="original", asset_id="v", timeline_in_seconds=9, source_in_seconds=2, source_out_seconds=6, origin="video_source", enabled=True, linked_video_clip_id="video", source_video_clip_id="video"), dict(clip_id="audio", asset_id="a", timeline_in_seconds=11, source_in_seconds=.5, source_out_seconds=2.5, origin="standalone", enabled=True, linked_video_clip_id=None, source_video_clip_id=None)]
    return p


def test_picture_binding_survives_reorder_and_label_updates():
    p = project()
    first = O.build_outlet_plan(p, "picture", "first")["items"][0]
    p["picture_track"][0]["order"] = 3
    after = O.build_outlet_plan(p, "picture", "first")["items"][0]
    assert first["label"] == "Picture 1" and after["label"] == "Picture 2"
    assert first["asset_id"] == after["asset_id"] == "p1"
    assert after["item_id"] == "first" and after["source_window"] is None and after["project_window"] is None


@pytest.mark.parametrize("kind,binding,track", [("picture", "first", "picture_track"), ("video", "video", "video_track"), ("audio", "audio", "audio_track")])
def test_deleted_binding_never_falls_back_to_another_item(kind, binding, track):
    p = project()
    p[track] = [item for item in p[track] if item.get("item_id", item.get("clip_id")) != binding]
    if kind == "video":
        p["audio_track"] = [item for item in p["audio_track"] if item["clip_id"] != "original"]
    with pytest.raises(O.OutletError, match="绑定|不存在"):
        O.build_outlet_plan(p, kind, binding)


@pytest.mark.parametrize("kind,binding", [("picture", "video"), ("video", "first"), ("audio", "video"), ("audio", "original"), ("video", ""), ("unsupported", None)])
def test_binding_kind_and_linked_audio_rejected(kind, binding):
    with pytest.raises(O.OutletError):
        O.build_outlet_plan(project(), kind, binding)


def test_intersection_half_up_and_original_audio_align_to_actual_video_frames():
    plan = O.build_outlet_plan(project(), "video", "video")
    video, original = plan["items"][0], plan["original_audio"]
    assert video["project_window"] == {"start_seconds": 10, "end_seconds": 12.25}
    assert video["requested_source_window"] == {"start_seconds": 3, "end_seconds": 5.25}
    assert video["source_window"] == {"start_seconds": 3, "end_seconds": 5.3}
    assert video["target_fps"] == 10 and video["frame_count"] == 23
    assert original["source_window"] == video["source_window"]
    assert original["sample_count"] == 101430 and original["sample_rate"] == 44100
    assert original["clip_id"] == "original" and original["label"] == "Video 1 原声"


def test_independent_audio_clips_to_own_intersection():
    plan = O.build_outlet_plan(project(), "audio", "audio")
    item = plan["items"][0]
    assert item["project_window"] == {"start_seconds": 11, "end_seconds": 12.25}
    assert item["source_window"] == {"start_seconds": .5, "end_seconds": 1.75}
    assert item["sample_count"] == 55125 and item["label"] == "Audio 1"
    assert plan["original_audio"] is None


@pytest.mark.parametrize("kind,binding,start,end", [("video", "video", 13, 15), ("video", "video", 7, 9), ("audio", "audio", 13, 15), ("audio", "audio", 8, 11)])
def test_half_open_empty_intersections_fail(kind, binding, start, end):
    p = project()
    p["processing_window"].update(start_seconds=start, end_seconds=end)
    with pytest.raises(O.OutletError):
        O.build_outlet_plan(p, kind, binding)


def test_derived_fields_and_labels_are_ignored_without_mutating_input():
    p = project()
    p["processing_window"].update(frame_count=999, start_frame=999, end_frame=999)
    p["video_track"][0].update(duration_seconds=999, timeline_out_seconds=999, source_in_frame=999, project_frame_count=999)
    p["label_map"] = [{"untrusted": "labels"}]
    p["validation"] = {"errors": [], "warnings": []}
    original = copy.deepcopy(p)
    plan = O.build_outlet_plan(p, "video", "video")
    assert plan["items"][0]["frame_count"] == 23
    assert plan["items"][0]["label"] == "Video 1"
    assert p == original


def test_timeline_includes_linked_audio_once_and_respects_enabled():
    p = project()
    plan = O.build_outlet_plan(p, "timeline_audio")
    assert [item["clip_id"] for item in plan["items"]] == ["original", "audio"]
    assert plan["window"]["sample_count"] == 99225
    p["video_track"][0]["source_audio_enabled"] = False
    assert O.build_outlet_plan(p, "video", "video")["original_audio"] is None
    assert [item["clip_id"] for item in O.build_outlet_plan(p, "timeline_audio")["items"]] == ["audio"]
    p["audio_track"][1]["enabled"] = False
    assert O.build_outlet_plan(p, "timeline_audio")["items"] == []
    with pytest.raises(O.OutletError):
        O.build_outlet_plan(p, "audio", "audio")


def test_many_items_have_no_artificial_h3_slot_limit():
    p = project()
    p["picture_track"] = [dict(item_id=f"pic{i}", asset_id="p1", order=i) for i in range(20)]
    p["video_track"] += [dict(p["video_track"][0], clip_id=f"v{i}", audio_link_id=None, source_audio_enabled=False, timeline_in_seconds=10 + i / 10) for i in range(5)]
    p["audio_track"] += [dict(p["audio_track"][1], clip_id=f"a{i}", timeline_in_seconds=10 + i / 10) for i in range(5)]
    assert O.build_outlet_plan(p, "picture", "pic19")["items"][0]["label"] == "Picture 20"
    assert O.build_outlet_plan(p, "video", "v4")["items"][0]["clip_id"] == "v4"
    assert O.build_outlet_plan(p, "audio", "a4")["items"][0]["clip_id"] == "a4"


def test_full_h3_window_accepts_1080p_video_but_still_rejects_4k_batch():
    p = project()
    video_asset = next(item for item in p["assets"] if item["asset_id"] == "v")
    video_asset["probe"].update(width=1080, height=1920, duration_seconds=20)
    p["processing_window"].update(start_seconds=0, end_seconds=15, fps=24)
    p["video_track"][0].update(
        timeline_in_seconds=0, source_in_seconds=0, source_out_seconds=15,
    )
    p["audio_track"][0].update(
        timeline_in_seconds=0, source_in_seconds=0, source_out_seconds=15,
    )

    expected_bytes = 1080 * 1920 * 3 * 4 * 360
    assert expected_bytes > 4 * 1024 ** 3
    plan = O.build_outlet_plan(p, "video", "video")
    assert plan["items"][0]["frame_count"] == 360
    assert expected_bytes < O.MAX_OUTPUT_BYTES

    video_asset["probe"].update(width=3840, height=2160)
    with pytest.raises(O.OutletError, match="12 GiB"):
        O.build_outlet_plan(p, "video", "video")

    fitted = O.build_outlet_plan(
        p, "video", "video", target_width=640, target_height=1152,
    )
    item = fitted["items"][0]
    assert (item["source_width"], item["source_height"]) == (3840, 2160)
    assert (item["output_width"], item["output_height"]) == (640, 1152)
    assert item["resize_during_decode"] is True
    assert item["resize_method"] == "bilinear" and item["fit_mode"] == "center_crop_fill"


@pytest.mark.parametrize("width,height", [(640, None), (None, 1152), (0, 1152), (641, 1152), (640.0, 1152)])
def test_video_target_size_requires_a_complete_h3_canvas(width, height):
    with pytest.raises(O.OutletError, match="目标|H3"):
        O.build_outlet_plan(project(), "video", "video", target_width=width, target_height=height)


def test_video_inherits_desk_canvas_and_legacy_explicit_inputs_take_priority():
    p = project()
    p["output_canvas"] = {"width": 640, "height": 1152}
    inherited = O.build_outlet_plan(p, "video", "video")["items"][0]
    explicit = O.build_outlet_plan(
        p, "video", "video", target_width=1152, target_height=640,
    )["items"][0]
    assert (inherited["output_width"], inherited["output_height"]) == (640, 1152)
    assert (explicit["output_width"], explicit["output_height"]) == (1152, 640)
    assert inherited["resize_during_decode"] is explicit["resize_during_decode"] is True


def test_partial_legacy_override_does_not_mix_with_desk_canvas():
    p = project()
    p["output_canvas"] = {"width": 640, "height": 1152}
    with pytest.raises(O.OutletError, match="同时连接"):
        O.build_outlet_plan(p, "video", "video", target_width=1152)


@pytest.mark.parametrize("mutation", [lambda p: p["processing_window"].update(fps=0), lambda p: p["processing_window"].update(end_seconds=10), lambda p: p["video_track"][0].update(source_out_seconds=21), lambda p: p["assets"][2].update(kind="picture"), lambda p: p["assets"][0].update(source_handle="C:/private.png")])
def test_invalid_project_and_paths_fail_clearly(mutation):
    p = project()
    mutation(p)
    with pytest.raises(O.OutletError):
        O.build_outlet_plan(p, "video", "video")


def test_vfr_uses_real_pts_including_duplicates_and_first_frame():
    assert D.sample_pts_indices([0, .04, .17, .3, .31], .1, 10, 4) == [1, 2, 3, 4]
    assert D.sample_pts_indices([.1, .1, .3], 0, 10, 4) == [0, 1, 1, 2]
    assert D.sample_pts_indices([0, .04, .17], 0, 25, 6) == [0, 1, 1, 1, 1, 2]


@pytest.mark.parametrize("stamps", [[], [None], [0, None], [0, float("nan")], [0, float("inf")], [.1, 0]])
def test_missing_invalid_or_reversed_pts_rejected(stamps):
    with pytest.raises(O.OutletError):
        D.sample_pts_indices(stamps, 0, 10, 2)


@pytest.mark.parametrize("node,outputs,binding", [(N.ZVPictureOutlet, ("IMAGE", "STRING", "STRING"), "item_id"), (N.ZVVideoOutlet, ("IMAGE", "AUDIO", "STRING", "STRING"), "clip_id"), (N.ZVAudioOutlet, ("AUDIO", "STRING", "STRING"), "clip_id"), (N.ZVTimelineAudioOutlet, ("AUDIO", "STRING", "STRING"), None), (N.ZVProcessingWindowOutlet, ("FLOAT", "FLOAT", "FLOAT", "FLOAT", "INT"), None)])
def test_nodes_have_fixed_standard_ports_and_refresh_source_facts(node, outputs, binding):
    assert node.RETURN_TYPES == outputs
    assert node.CATEGORY == "ZV/视频创作/素材取证"
    required = node.INPUT_TYPES()["required"]
    assert next(iter(required)) == "media_project" and required["media_project"][0] == "ZV_MEDIA_PROJECT"
    if binding:
        assert required[binding][0] == "STRING"
    if node is N.ZVVideoOutlet:
        optional = node.INPUT_TYPES()["optional"]
        assert list(optional) == ["target_width", "target_height"]
        assert all(spec[1]["forceInput"] for spec in optional.values())
    assert math.isnan(node.IS_CHANGED(media_project=project()))


def test_processing_window_outlet_returns_canonical_parameters_without_media_decode(monkeypatch):
    monkeypatch.setattr(R, "get_store", lambda: pytest.fail("Parameter outlet must not touch the media store"))
    assert N.ZVProcessingWindowOutlet.RETURN_NAMES == (
        "start_seconds", "end_seconds", "duration_seconds", "fps", "frame_count"
    )
    assert N.ZVProcessingWindowOutlet().export_window(project()) == (10.0, 12.25, 2.25, 10.0, 23)


@pytest.mark.parametrize("mutation", [
    lambda p: p["processing_window"].update(end_seconds=10),
    lambda p: p["processing_window"].update(fps=0),
])
def test_processing_window_outlet_rejects_invalid_window(mutation):
    p = project()
    mutation(p)
    with pytest.raises(O.OutletError, match="处理窗口|目标帧率"):
        N.ZVProcessingWindowOutlet().export_window(p)


@pytest.fixture(scope="module")
def real_media(tmp_path_factory):
    directory = tmp_path_factory.mktemp("outlet-real")
    store, p = SMOKE.imported_project(directory)
    return directory, store, p


def test_real_nodes_standard_tensors_and_timeline_mix(tmp_path):
    assert SMOKE.run_real_checks(tmp_path) >= 30


@pytest.mark.parametrize("damage", ["missing", "changed", "unregistered"])
def test_node_rechecks_source_registry_before_decoding(tmp_path, monkeypatch, damage):
    from PIL import Image

    store = S.MediaStore(tmp_path)
    path, handle, name = store.allocate("image.png")
    Image.new("RGB", (4, 4), "red").save(path)
    entry = store.finish_import(path, handle, name)
    p = C.empty_project()
    p["assets"] = [entry]
    p["picture_track"] = [dict(item_id="picture", asset_id=entry["asset_id"], order=1)]
    if damage == "missing":
        path.unlink()
    elif damage == "changed":
        path.write_bytes(path.read_bytes() + b"changed length")
    else:
        (store.root / "cache" / (path.stem + ".json")).unlink()
    monkeypatch.setattr(R, "_store", store)
    with pytest.raises(O.OutletError, match="来源|源|失效|重新|改变|不存在"):
        N.ZVPictureOutlet().export_media(p, "picture")


def test_node_ignores_forged_probe_and_preserves_project(real_media, monkeypatch):
    directory, store, p = real_media
    p = copy.deepcopy(p)
    p["assets"][0]["probe"].update(width=1, height=1)
    original = copy.deepcopy(p)
    monkeypatch.setattr(R, "_store", store)
    image, text, _ = N.ZVPictureOutlet().export_media(p, "red")
    assert tuple(image.shape) == (1, 24, 32, 3)
    manifest = SMOKE.assert_private_manifest(text, directory)
    assert manifest["items"][0]["shape"] == [1, 24, 32, 3] and p == original


def test_half_up_video_extension_zero_pads_original_instead_of_reading_past_cut(real_media, monkeypatch):
    import torch

    directory, store, p = real_media
    p = copy.deepcopy(p)
    p["processing_window"].update(start_seconds=11, end_seconds=12.25, fps=10)
    monkeypatch.setattr(R, "_store", store)
    video, audio, text, _ = N.ZVVideoOutlet().export_media(p, "voiced")
    manifest = SMOKE.assert_private_manifest(text, directory)
    assert video.shape[0] == 13 and audio["waveform"].shape[-1] == 57330
    assert torch.count_nonzero(audio["waveform"][:, :, -2205:]).item() == 0
    assert audio["waveform"][0, 0, -2305].item() > .19
    assert manifest["original_audio"]["zero_padding_samples"] >= 2205
    assert manifest["original_audio"]["requested_source_window"]["end_seconds"] == 1.5
    assert manifest["original_audio"]["source_window"]["end_seconds"] == 1.55


def test_video_is_fitted_during_decode_without_changing_aligned_audio(real_media, monkeypatch):
    import torch

    directory, store, p = real_media
    monkeypatch.setattr(R, "_store", store)
    source, source_audio, _, _ = N.ZVVideoOutlet().export_media(p, "voiced")
    fitted, fitted_audio, text, report = N.ZVVideoOutlet().export_media(
        p, "voiced", target_width=64, target_height=96,
    )
    manifest = SMOKE.assert_private_manifest(text, directory)
    item = manifest["items"][0]
    assert tuple(source.shape) == (15, 24, 32, 3)
    assert tuple(fitted.shape) == (15, 96, 64, 3)
    assert fitted.dtype == torch.float32 and fitted.device.type == "cpu"
    assert torch.isfinite(fitted).all() and 0 <= fitted.min() <= fitted.max() <= 1
    assert torch.equal(source_audio["waveform"], fitted_audio["waveform"])
    assert item["shape"] == [15, 96, 64, 3]
    assert item["source_width"] == 32 and item["source_height"] == 24
    assert item["output_width"] == 64 and item["output_height"] == 96
    assert item["resize_during_decode"] is True
    assert "未先构造原尺寸批次" in report


@pytest.mark.parametrize("limit,value,kind,binding", [("MAX_VIDEO_FRAMES", 1, "video", "voiced"), ("MAX_OUTPUT_BYTES", 1, "picture", "red"), ("MAX_AUDIO_SECONDS", .1, "audio", "independent")])
def test_output_budget_fails_before_large_allocation(real_media, monkeypatch, limit, value, kind, binding):
    _, store, p = real_media
    plan = O.build_outlet_plan(store.canonical(p), kind, binding)
    monkeypatch.setattr(D, limit, value)
    with pytest.raises(O.OutletError):
        D.execute_outlet(store, plan)


def test_video_binding_survives_timeline_reorder():
    p = project()
    p["video_track"].append(dict(p["video_track"][0], clip_id="other", audio_link_id=None, source_audio_enabled=False, timeline_in_seconds=10))
    before = O.build_outlet_plan(p, "video", "video")["items"][0]
    p["video_track"][1]["timeline_in_seconds"] = 8
    after = O.build_outlet_plan(p, "video", "video")["items"][0]
    assert before["label"] == "Video 1" and after["label"] == "Video 2"
    assert before["clip_id"] == after["clip_id"] == "video" and before["source_window"] == after["source_window"]


def test_streaming_video_selection_uses_pts_not_average_fps(real_media, monkeypatch):
    import av
    import numpy as np

    _, store, p = real_media
    p = copy.deepcopy(p)
    p["processing_window"].update(start_seconds=10.5, end_seconds=11, fps=10)
    p["video_track"][0].update(timeline_in_seconds=10.5, source_in_seconds=0, source_out_seconds=.5)
    frames = []
    for index, pts in enumerate([0, 40, 170, 300, 310]):
        frame = av.VideoFrame.from_ndarray(np.full((24, 32, 3), index * 30, dtype=np.uint8), format="rgb24")
        frame.pts, frame.time_base = pts, Fraction(1, 1000)
        frames.append(frame)
    monkeypatch.setattr(D, "_frames", lambda container, stream, budget: iter(frames))
    plan = O.build_outlet_plan(store.canonical(p), "video", "silent")
    video, _, manifest, _ = D.execute_outlet(store, plan)
    assert manifest["items"][0]["sampling"]["sampled_source_pts"] == [0, .04, .17, .3, .31]
    assert np.allclose(video[:, 0, 0, 0].numpy(), np.arange(5) * 30 / 255)


@pytest.mark.parametrize("damage", ["missing_pts", "size_change"])
def test_streaming_video_rejects_missing_pts_and_frame_size_change(real_media, monkeypatch, damage):
    import av
    import numpy as np

    _, store, p = real_media
    frames = []
    for index in range(2):
        width = 33 if damage == "size_change" and index else 32
        frame = av.VideoFrame.from_ndarray(np.zeros((24, width, 3), dtype=np.uint8), format="rgb24")
        frame.pts, frame.time_base = (None if damage == "missing_pts" else 500 + index * 100), Fraction(1, 1000)
        frames.append(frame)
    monkeypatch.setattr(D, "_frames", lambda container, stream, budget: iter(frames))
    plan = O.build_outlet_plan(store.canonical(p), "video", "silent")
    with pytest.raises(O.OutletError, match="PTS|尺寸"):
        D.execute_outlet(store, plan)


def test_audio_pts_gaps_are_zero_filled_without_joining_sound(real_media, monkeypatch):
    import av
    import numpy as np

    _, store, p = real_media
    p = copy.deepcopy(p)
    p["processing_window"].update(start_seconds=0, end_seconds=1)
    p["audio_track"][1].update(timeline_in_seconds=0, source_in_seconds=0, source_out_seconds=1)
    frames = []
    for pts in [0, 22050]:
        frame = av.AudioFrame.from_ndarray(np.full((1, 11025), .25, dtype=np.float32), format="fltp", layout="mono")
        frame.pts, frame.time_base, frame.sample_rate = pts, Fraction(1, 44100), 44100
        frames.append(frame)
    monkeypatch.setattr(D, "_frames", lambda container, stream, budget: iter(frames))
    plan = O.build_outlet_plan(store.canonical(p), "audio", "independent")
    sound, _, manifest, _ = D.execute_outlet(store, plan)
    values = sound["waveform"][0, 0].numpy()
    assert np.all(values[:11025] == .25) and np.all(values[22050:33075] == .25)
    assert np.count_nonzero(values[11025:22050]) == np.count_nonzero(values[33075:]) == 0
    assert manifest["items"][0]["zero_padding_samples"] == 22050


def test_real_video_preserves_audio_start_offset_and_pts_gap(tmp_path, monkeypatch):
    import av
    import numpy as np

    store = S.MediaStore(tmp_path)
    path, handle, name = store.allocate("offset-and-gap.mkv")
    with av.open(str(path), "w") as container:
        video = container.add_stream("ffv1", rate=12)
        video.width, video.height, video.pix_fmt = 32, 24, "yuv444p"
        audio = container.add_stream("pcm_s16le", rate=44100)
        audio.layout = "mono"
        for index in range(18):
            frame = av.VideoFrame.from_ndarray(np.zeros((24, 32, 3), dtype=np.uint8), format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, 12)
            for packet in video.encode(frame):
                container.mux(packet)
        for packet in video.encode(None):
            container.mux(packet)
        for start in [11025, 22050, 44100, 55125]:
            frame = av.AudioFrame.from_ndarray(np.full((1, 11025), 8192, dtype=np.int16), format="s16", layout="mono")
            frame.sample_rate, frame.pts, frame.time_base = 44100, start, Fraction(1, 44100)
            for packet in audio.encode(frame):
                container.mux(packet)
        for packet in audio.encode(None):
            container.mux(packet)
    entry = store.finish_import(path, handle, name)
    p = C.empty_project()
    p["assets"] = [entry]
    p["processing_window"].update(start_seconds=0, end_seconds=1.5, fps=10)
    p["video_track"] = [dict(clip_id="video", asset_id=entry["asset_id"], timeline_in_seconds=0, source_in_seconds=0, source_out_seconds=1.5, source_audio_enabled=True, audio_link_id="original")]
    p["audio_track"] = [dict(clip_id="original", asset_id=entry["asset_id"], timeline_in_seconds=0, source_in_seconds=0, source_out_seconds=1.5, origin="video_source", enabled=True, linked_video_clip_id="video", source_video_clip_id="video")]
    monkeypatch.setattr(R, "_store", store)
    frames, audio, text, _ = N.ZVVideoOutlet().export_media(p, "video")
    manifest = SMOKE.assert_private_manifest(text, tmp_path)
    values = audio["waveform"][0, 0].numpy()
    assert frames.shape[0] == 15 and len(values) == 66150
    assert not np.count_nonzero(values[:11025]) and not np.count_nonzero(values[33075:44100])
    assert np.all(values[11025:33075] == .25) and np.all(values[44100:] == .25)
    assert manifest["original_audio"]["zero_padding_samples"] == 22050


@pytest.mark.parametrize("limit,value", [("MAX_DECODE_FRAMES", 1), ("MAX_DECODE_PACKETS", 0), ("MAX_DECODE_SECONDS", -1)])
def test_decode_work_budget_is_enforced(real_media, monkeypatch, limit, value):
    _, store, p = real_media
    plan = O.build_outlet_plan(store.canonical(p), "video", "voiced")
    monkeypatch.setattr(D, limit, value)
    with pytest.raises(O.OutletError):
        D.execute_outlet(store, plan)
