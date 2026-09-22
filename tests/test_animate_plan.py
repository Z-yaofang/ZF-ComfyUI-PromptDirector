import copy
import importlib
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "zf_animate_plan_testpkg"
package = importlib.util.module_from_spec(importlib.util.spec_from_loader(PACKAGE, loader=None, is_package=True))
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
PLAN = importlib.import_module(PACKAGE + ".animate_video.plan")
CONTRACT = importlib.import_module(PACKAGE + ".media_evidence.contract")


def asset(kind, identifier, frames=0, fps=30):
    return {"asset_id": identifier, "name": identifier, "kind": kind,
        "source_handle": "originals/" + ("a" if kind == "video" else "b") * 32 + (".mp4" if kind == "video" else ".png"),
        "probe": {"size_bytes": 1000, "duration_seconds": frames / fps if kind == "video" else None,
            "width": 320, "height": 180, "fps": fps if kind == "video" else None,
            "frame_count": frames if kind == "video" else None, "frame_count_exact": kind == "video",
            "vfr": False if kind == "video" else None, "has_audio": kind == "video",
            "sample_rate": 48000 if kind == "video" else None, "channels": 2 if kind == "video" else None, "codec": "fixture"}}


def project(frames=650, pictures=1, audio=False, fps=30):
    value = CONTRACT.empty_project()
    value["assets"] = [asset("video", "video", frames, fps)] + [asset("picture", f"picture-{i}") for i in range(pictures)]
    value["picture_track"] = [{"item_id": f"pic-{i}", "asset_id": f"picture-{i}", "order": i + 1} for i in range(pictures)]
    value["video_track"] = [{"clip_id": "clip", "asset_id": "video", "timeline_in_seconds": 0,
        "source_in_seconds": 0, "source_out_seconds": frames / fps, "source_audio_enabled": audio, "audio_link_id": "sound" if audio else None}]
    if audio:
        value["audio_track"] = [{"clip_id": "sound", "asset_id": "video", "timeline_in_seconds": 0,
            "source_in_seconds": 0, "source_out_seconds": frames / fps, "origin": "video_source", "enabled": True,
            "linked_video_clip_id": "clip", "source_video_clip_id": "clip"}]
    return CONTRACT.normalize_project(value)


def upstream_clips(value, windows):
    result = copy.deepcopy(value)
    first = result["video_track"][0]
    fps = next(row for row in result["assets"] if row["asset_id"] == first["asset_id"])["probe"]["fps"]
    sound = next((row for row in result["audio_track"] if row["clip_id"] == first["audio_link_id"]), None)
    result["video_track"], result["audio_track"] = [], []
    for index, (start, end) in enumerate(windows):
        clip_id, audio_id = f"clip-{index}", f"sound-{index}"
        result["video_track"].append({**first, "clip_id": clip_id, "timeline_in_seconds": start / fps,
            "source_in_seconds": start / fps, "source_out_seconds": end / fps, "audio_link_id": audio_id if sound else None})
        if sound:
            result["audio_track"].append({**sound, "clip_id": audio_id, "linked_video_clip_id": clip_id,
                "source_video_clip_id": clip_id, "timeline_in_seconds": start / fps,
                "source_in_seconds": start / fps, "source_out_seconds": end / fps})
    return result


def settings(mode="hard_cut"):
    return {"schema_version": 1, "seam_mode": mode}


def codes(plan, severity="errors"):
    return {row["code"] for row in plan["validation"][severity]}


@pytest.mark.parametrize("count", [3, 4, 5])
def test_global_mask_mode_binds_reference_and_words_to_clips_after_reorder(count):
    source = upstream_clips(project(40 * count, pictures=count), [(i * 40, (i + 1) * 40) for i in range(count)])
    config = {**settings(), "mask_enabled": True, "mask_tasks": {
        f"clip-{i}": {"asset_id": "video", "source_frame": i * 40 + 3, "prompt": f"object {i}"} for i in range(count)}}
    value = PLAN.build_plan(source, config)
    assert value["validation"]["ready"]
    assert [row["mask_task"]["local_index"] for row in value["segments"]] == [3] * count
    source["video_track"][0]["timeline_in_seconds"] = 100
    reordered = PLAN.build_plan(source, config)
    assert reordered["segments"][-1]["clip_id"] == "clip-0"
    assert reordered["segments"][-1]["mask_task"]["prompt"] == "object 0"
    assert reordered["segments"][-1]["mask_task"]["source_frame"] == 3


def test_mask_source_change_out_of_range_empty_words_and_global_off():
    source = upstream_clips(project(100, pictures=2), [(0, 40), (40, 100)])
    config = {**settings(), "mask_enabled": True, "mask_tasks": {
        "clip-0": {"asset_id": "wrong", "source_frame": 414, "prompt": "shirt"},
        "clip-1": {"asset_id": "video", "source_frame": 40, "prompt": ""}}}
    value = PLAN.build_plan(source, config)
    assert {"mask_source_changed", "mask_frame_range", "mask_prompt_missing"} <= codes(value)
    assert [(row["source_in_seconds"], row["source_out_seconds"]) for row in value["media_project"]["video_track"]] == [(0, 40 / 30), (40 / 30, 100 / 30)]
    config["mask_enabled"] = False
    off = PLAN.build_plan(source, config)
    assert off["validation"]["ready"]
    assert all(row["mask_task"] is None for row in off["segments"])
    assert off["settings"]["mask_tasks"] == config["mask_tasks"]


def test_native_source_frame_maps_to_resampled_batch_without_changing_cut():
    source = upstream_clips(project(180, pictures=1, fps=60), [(60, 180)])
    config = {**settings(), "mask_enabled": True, "mask_tasks": {
        "clip-0": {"asset_id": "video", "source_frame": 90, "prompt": "shirt"}}}
    value = PLAN.build_plan(source, config, fps=30)
    assert value["validation"]["ready"]
    row = value["segments"][0]
    assert row["source_start_seconds"] == 1 and row["source_end_seconds"] == 3
    assert row["mask_task"]["source_frame"] == 90 and row["mask_task"]["local_index"] == 15


@pytest.mark.parametrize("cut", [304, 305, 306, 307])
@pytest.mark.parametrize("mode", ["hard_cut", "continuation_21"])
def test_authored_clip_boundaries_never_move_or_get_model_padding(cut, mode):
    source = upstream_clips(project(650, pictures=2, audio=True), [(7, cut), (cut, 650)])
    before = copy.deepcopy(source)
    value = PLAN.build_plan(source, settings(mode))
    assert value["validation"]["ready"]
    assert source == before
    assert value["target_frame_count"] == 643
    assert [row["frame_count"] for row in value["segments"]] == [cut - 7, 650 - cut]
    for clip, row in zip(source["video_track"], value["segments"]):
        assert row["source_start_seconds"] == clip["source_in_seconds"]
        assert row["source_end_seconds"] == clip["source_out_seconds"]
        assert row["contribution_start_frame"] == 0
        assert row["contribution_end_frame"] == row["frame_count"]
        assert "model_frame_count" not in row and "overlap_frames" not in row
    assert [row["guide_frame_count"] for row in value["segments"]] == [0, 21 if mode == "continuation_21" else 0]
    assert [row["picture_id"] for row in value["segments"]] == ["pic-0", "pic-1"]


@pytest.mark.parametrize("pictures", [0, 1, 3])
def test_picture_count_must_match_video_count_without_automatic_reuse(pictures):
    value = PLAN.build_plan(upstream_clips(project(100, pictures=pictures), [(0, 40), (40, 100)]))
    assert not value["validation"]["ready"]
    assert "picture_count_mismatch" in codes(value)
    if pictures == 1:
        assert value["segments"][1]["picture_id"] is None


def test_left_to_right_video_and_picture_order_owns_pairing():
    source = upstream_clips(project(100, pictures=2), [(0, 40), (40, 100)])
    source["video_track"][0]["timeline_in_seconds"] = 10
    source["picture_track"][0]["order"] = 3
    value = PLAN.build_plan(source)
    assert [(row["clip_id"], row["picture_id"]) for row in value["segments"]] == [("clip-1", "pic-1"), ("clip-0", "pic-0")]
    assert "sequential_sources" in codes(value, "warnings")


def test_fixed_native_history_short_source_is_not_fabricated():
    value = PLAN.build_plan(upstream_clips(project(12, pictures=2), [(0, 4), (4, 12)]), settings("continuation_21"))
    assert value["segments"][1]["guide_frame_count"] == 4
    assert value["target_frame_count"] == 12


@pytest.mark.parametrize("fps", [24, 30, 30000 / 1001, 29.97])
def test_workflow_fps_is_authoritative_and_frozen_in_plan(fps):
    source = project(300)
    source["video_track"][0]["source_out_seconds"] = 100 / fps
    value = PLAN.build_plan(source, fps=fps)
    assert value["validation"]["ready"]
    assert value["fps"] == pytest.approx(fps)
    assert value["fps_origin"] == "workflow"
    assert value["media_project"]["project_clock"]["fps"] == 24
    assert value["target_frame_count"] == 100
    assert PLAN.normalize_plan(value) == value


def test_source_fps_then_project_clock_only_when_original_clock_unlinked():
    source = project(300)
    assert PLAN.build_plan(source)["fps"] == 30
    source["assets"][0]["probe"]["fps"] = None
    value = PLAN.build_plan(source)
    assert value["fps"] == 24 and value["fps_origin"] == "project"
    assert "source_fps_unknown" in codes(value, "warnings")


@pytest.mark.parametrize("key", ["source_in_seconds", "source_out_seconds"])
def test_off_grid_cut_keeps_user_seconds_and_maps_only_the_vhs_frame_window(key):
    source = project(300)
    source["video_track"][0][key] = .123 if key == "source_in_seconds" else 9.123
    value = PLAN.build_plan(source, fps=30)
    assert "source_grid_conflict" not in codes(value)
    assert value["media_project"]["video_track"][0][key] == source["video_track"][0][key]
    row = value["segments"][0]
    assert row["load_start_frame"] == round(source["video_track"][0]["source_in_seconds"] * 30)
    assert row["load_end_frame"] == round(source["video_track"][0]["source_out_seconds"] * 30)
    assert row["frame_count"] == row["load_end_frame"] - row["load_start_frame"]


def test_probe_float_noise_does_not_change_rate_or_repeat_estimated_frame_warnings():
    rate = 30.00000108303253
    source = upstream_clips(project(356, pictures=2, audio=True, fps=rate), [(0, 114), (114, 356)])
    for track in ("video_track", "audio_track"):
        source[track][0].update(source_in_seconds=0, source_out_seconds=3.8)
        source[track][1].update(source_in_seconds=3.8, source_out_seconds=11.840726)
    source["assets"][0]["probe"].update(frame_count=355, frame_count_exact=False, vfr=None)
    source = CONTRACT.normalize_project(source)
    value = PLAN.build_plan(source, {**settings(), "mask_enabled": True, "mask_tasks": {
        "clip-0": {"asset_id": "video", "source_frame": 113, "prompt": "shirt"},
        "clip-1": {"asset_id": "video", "source_frame": 155, "prompt": "shirt"},
    }})
    assert value["validation"]["ready"]
    assert value["fps"] == 30
    assert [row["frame_count"] for row in value["segments"]] == [114, 241]
    assert [(row["mask_frame_min"] + 1, row["mask_frame_max"] + 1) for row in value["segments"]] == [(1, 114), (115, 355)]
    assert [row["mask_task"]["local_index"] for row in value["segments"]] == [113, 41]
    assert "fps_resampled" not in codes(value, "warnings")
    assert [row["code"] for row in value["validation"]["warnings"]].count("estimated_frames") == 1


def test_mixed_fps_reports_resampling_to_original_workflow_rate():
    source = upstream_clips(project(300, pictures=2), [(0, 100), (100, 300)])
    source["assets"].append(asset("video", "other", 600, 60))
    source["video_track"][1]["asset_id"] = "other"
    value = PLAN.build_plan(source, fps=30)
    assert value["validation"]["ready"]
    assert "fps_resampled" in codes(value, "warnings")


def test_live_source_changes_rebuild_without_saved_snapshot():
    source = project(300)
    first = PLAN.build_plan(source)
    source["video_track"][0]["source_out_seconds"] = 299 / 30
    second = PLAN.build_plan(source, first["settings"])
    assert second["target_frame_count"] == 299
    assert first["plan_fingerprint"] != second["plan_fingerprint"]
    assert set(second["settings"]) == {"schema_version", "seam_mode", "mask_enabled", "mask_tasks"}


@pytest.mark.parametrize("value", [{"overlap_frames": 8}, {"schema_version": 2}, {"seam_mode": "continue"}, {"fps": 24}, {"segments": []}])
def test_old_or_unknown_controls_are_not_retained(value):
    with pytest.raises(PLAN.AnimatePlanError):
        PLAN.build_plan(project(), value)


@pytest.mark.parametrize("fps", [0, -1, True, "30", float("nan"), float("inf"), 241])
def test_invalid_workflow_clock_rejected(fps):
    with pytest.raises(PLAN.AnimatePlanError):
        PLAN.build_plan(project(), fps=fps)


def test_plan_fingerprint_rejects_changed_route_or_clock():
    value = PLAN.build_plan(project(), fps=30)
    value["segments"][0]["picture_id"] = "changed"
    with pytest.raises(PLAN.AnimatePlanError):
        PLAN.normalize_plan(value)
    value = PLAN.build_plan(project(300), fps=30)
    value["fps"] = 24
    with pytest.raises(PLAN.AnimatePlanError):
        PLAN.normalize_plan(value)
