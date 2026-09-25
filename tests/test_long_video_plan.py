import copy
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest
import jsonschema


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "zf_long_video_testpkg"
package = importlib.util.module_from_spec(importlib.util.spec_from_loader(PACKAGE, loader=None, is_package=True))
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
SPEC = importlib.util.spec_from_file_location(PACKAGE + ".long_video", ROOT / "long_video" / "__init__.py", submodule_search_locations=[str(ROOT / "long_video")])
LONG_VIDEO = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LONG_VIDEO
SPEC.loader.exec_module(LONG_VIDEO)
PLAN = importlib.import_module(SPEC.name + ".plan")
CONTRACT = importlib.import_module(PACKAGE + ".media_evidence.contract")
OUTLET = importlib.import_module(PACKAGE + ".media_evidence.outlet")


def asset(kind, identifier, seconds=None):
    digest_char = {"video": "a", "audio": "b", "picture": "c"}[kind]
    return {
        "asset_id": identifier, "name": identifier, "kind": kind,
        "source_handle": "originals/" + (digest_char * 32) + {"video": ".mp4", "audio": ".wav", "picture": ".png"}[kind],
        "probe": {
            "size_bytes": 1000, "duration_seconds": seconds, "width": None if kind == "audio" else 320,
            "height": None if kind == "audio" else 180, "fps": 30 if kind == "video" else None,
            "frame_count": int(seconds * 30) if kind == "video" else None, "frame_count_exact": kind == "video",
            "vfr": False if kind == "video" else None, "has_audio": kind != "picture",
            "sample_rate": 48000 if kind != "picture" else None, "channels": 2 if kind != "picture" else None, "codec": "fixture",
        },
    }


def project(frames=672):
    seconds = frames / 24
    value = CONTRACT.empty_project()
    value["assets"] = [asset("video", "video", seconds), asset("picture", "picture")]
    value["picture_track"] = [{"item_id": "picture-item", "asset_id": "picture", "order": 1}]
    value["video_track"] = [{
        "clip_id": "video-clip", "asset_id": "video", "timeline_in_seconds": 0,
        "source_in_seconds": 0, "source_out_seconds": seconds, "source_audio_enabled": False, "audio_link_id": None,
    }]
    return CONTRACT.normalize_project(value)


def settings(**changes):
    value = PLAN.default_settings()
    value.update(changes)
    return value


def codes(plan):
    return {row["code"] for row in plan["validation"]["errors"]}


def test_auto_source_plan_uses_effective_overlap_and_exact_tail_trim():
    result = PLAN.build_segment_plan(project(), settings())
    assert result["validation"]["ready"]
    assert result["target_frame_count"] == 672
    assert result["requested_overlap_frames"] == 48
    assert result["effective_overlap_frames"] == 39
    assert [(row["start_frame"], row["end_frame"]) for row in result["segments"]] == [(0, 360), (321, 681)]
    assert result["segments"][1]["overlap_frames"] == 39
    assert result["segments"][1]["tail_padding_frames"] == 9
    assert sum(row["output_frame_count"] for row in result["segments"]) == 672
    assert result["segments"][0]["model_padding"] == {"adapter": "h3", "requested_frames": 360, "model_length": 362, "predicted_final_frames": 362, "actual_final_frames": None}


def test_three_tracks_are_integer_mapped_and_sliced_with_stable_ids():
    value = project(240)
    value["assets"].append(asset("audio", "audio", 10))
    value["audio_track"] = [{"clip_id": "audio-clip", "asset_id": "audio", "timeline_in_seconds": 1.25, "source_in_seconds": .5, "source_out_seconds": 8.5, "origin": "standalone", "enabled": True, "linked_video_clip_id": None, "source_video_clip_id": None}]
    value = CONTRACT.normalize_project(value)
    result = PLAN.build_segment_plan(value, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact"))
    assert result["source_tracks"]["pictures"][0]["item_id"] == "picture-item"
    assert result["source_tracks"]["audio"][0]["timeline_in_frame"] == 30
    assert result["source_tracks"]["audio"][0]["source_in_frame"] == 12
    slices = result["segments"][0]["source_slices"]
    assert slices["video"][0]["clip_id"] == "video-clip"
    assert slices["audio"][0]["clip_id"] == "audio-clip"
    assert slices["audio"][0]["segment_in_frame"] == 30


def test_frozen_snapshot_survives_local_split_and_upstream_change_is_stale():
    upstream = project(240)
    baseline = PLAN.project_fingerprint(upstream)
    frozen = copy.deepcopy(upstream)
    frozen["video_track"] = [
        {**frozen["video_track"][0], "clip_id": "left", "source_out_seconds": 5},
        {**frozen["video_track"][0], "clip_id": "right", "timeline_in_seconds": 5, "source_in_seconds": 5},
    ]
    first = PLAN.build_segment_plan(upstream, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact", source_snapshot=frozen, source_fingerprint=baseline))
    assert not first["stale"] and [row["clip_id"] for row in first["source_tracks"]["video"]] == ["left", "right"]
    changed = copy.deepcopy(upstream)
    changed["video_track"][0]["source_out_seconds"] = 9
    stale = PLAN.build_segment_plan(changed, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact", source_snapshot=frozen, source_fingerprint=baseline))
    assert stale["stale"] and "source_stale" in codes(stale) and not stale["validation"]["ready"]
    refreshed = PLAN.build_segment_plan(changed, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact", source_snapshot=frozen, source_fingerprint=baseline, refresh_sources=True))
    assert not refreshed["stale"] and [row["clip_id"] for row in refreshed["source_tracks"]["video"]] == ["video-clip"]


def test_manual_overlap_hard_cut_and_gap_are_distinct():
    manual = settings(mode="source_manual", overlap_frames=0, overlap_alignment="exact", segments=[
        {"segment_id": "a", "start_frame": 0, "end_frame": 120},
        {"segment_id": "b", "start_frame": 120, "end_frame": 240},
    ])
    touching = PLAN.build_segment_plan(project(240), manual)
    assert touching["validation"]["ready"] and touching["segments"][1]["seam"] == "hard_cut"
    manual["segments"][1]["start_frame"] = 110
    overlap = PLAN.build_segment_plan(project(240), manual)
    assert overlap["validation"]["ready"] and overlap["segments"][1]["seam"] == "guide" and overlap["segments"][1]["overlap_frames"] == 10
    manual["segments"][1]["start_frame"] = 121
    gap = PLAN.build_segment_plan(project(240), manual)
    assert "segment_gap" in codes(gap) and not gap["validation"]["ready"]


def test_manual_segments_are_sorted_by_start_frame_without_changing_ids():
    manual = settings(mode="source_manual", overlap_frames=0, overlap_alignment="exact", segments=[
        {"segment_id": "later", "start_frame": 120, "end_frame": 240},
        {"segment_id": "earlier", "start_frame": 0, "end_frame": 120},
    ])
    result = PLAN.build_segment_plan(project(240), manual)
    assert result["validation"]["ready"]
    assert [row["segment_id"] for row in result["segments"]] == ["earlier", "later"]


def test_source_video_hole_is_an_error_even_when_segments_cover_the_axis():
    value = project(240)
    clip = value["video_track"][0]
    value["video_track"] = [
        {**clip, "clip_id": "left", "source_out_seconds": 4},
        {**clip, "clip_id": "right", "timeline_in_seconds": 5, "source_in_seconds": 5},
    ]
    result = PLAN.build_segment_plan(value, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact", range_start_frame=0, range_end_frame=240))
    assert "video_gap" in codes(result) and not result["validation"]["ready"]


def test_generation_count_mode_needs_no_source_video_and_one_segment_works():
    empty = CONTRACT.normalize_project(CONTRACT.empty_project())
    one = PLAN.build_segment_plan(empty, settings(mode="generation_count", segment_frames=120, overlap_frames=22, overlap_alignment="h3_guide", segment_count=1))
    assert one["validation"]["ready"] and one["target_frame_count"] == 120 and one["segments"][0]["seam"] == "first"
    three = PLAN.build_segment_plan(empty, settings(mode="generation_count", segment_frames=120, overlap_frames=22, overlap_alignment="h3_guide", segment_count=3))
    assert three["effective_overlap_frames"] == 22
    assert three["target_frame_count"] == 120 + 2 * (120 - 22)
    assert [row["overlap_frames"] for row in three["segments"]] == [0, 22, 22]


def test_generation_manual_supports_dragged_windows_without_video():
    empty = CONTRACT.normalize_project(CONTRACT.empty_project())
    result = PLAN.build_segment_plan(empty, settings(mode="generation_manual", overlap_frames=0, overlap_alignment="exact", segments=[
        {"segment_id": "second", "start_frame": 100, "end_frame": 200},
        {"segment_id": "first", "start_frame": 0, "end_frame": 120},
    ]))
    assert result["validation"]["ready"]
    assert result["target_frame_count"] == 200
    assert [row["segment_id"] for row in result["segments"]] == ["first", "second"]
    assert result["segments"][1]["overlap_frames"] == 20
    assert result["segments"][0]["model_padding"]["adapter"] == "none"


def test_source_seconds_keep_fractional_endpoint_in_segment_project():
    value = project(360)
    value["assets"][0]["probe"].update(duration_seconds=14.487, frame_count=435)
    value["video_track"][0]["source_out_seconds"] = 14.487
    value = CONTRACT.normalize_project(value)
    result = PLAN.build_segment_plan(value, settings(segment_frames=360, overlap_frames=0, overlap_alignment="exact"))
    local = PLAN.segment_project(result, result["segments"][0]["segment_id"])
    assert local["video_track"][0]["source_out_seconds"] == 14.487


def test_unused_preload_asset_does_not_expire_frozen_tracks():
    upstream = project(240)
    baseline = PLAN.project_fingerprint(upstream)
    changed = copy.deepcopy(upstream)
    changed["assets"].append(asset("picture", "unused"))
    result = PLAN.build_segment_plan(changed, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact", source_snapshot=upstream, source_fingerprint=baseline))
    assert not result["stale"] and result["validation"]["ready"]


def test_revision_and_stale_ignore_non_task_pool_window_and_project_clock():
    original = project(240)
    first = PLAN.build_segment_plan(original, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact"))
    changed = copy.deepcopy(original)
    changed["assets"].append(asset("picture", "unused"))
    changed["processing_window"].update(start_seconds=40, end_seconds=42, fps=30)
    changed["project_clock"]["fps"] = 60
    fresh = PLAN.build_segment_plan(changed, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact"))
    frozen = PLAN.build_segment_plan(changed, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact", source_snapshot=first["media_project"], source_fingerprint=first["source_fingerprint"]))
    assert fresh["revision"] == first["revision"]
    assert fresh["snapshot_fingerprint"] == first["snapshot_fingerprint"]
    assert not frozen["stale"] and frozen["revision"] == first["revision"]


def test_revision_changes_for_frozen_track_edits_not_unused_pool_edits():
    original = project(240)
    first = PLAN.build_segment_plan(original, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact"))
    frozen = copy.deepcopy(first["media_project"])
    frozen["video_track"][0]["source_out_seconds"] = 9
    edited = PLAN.build_segment_plan(original, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact", source_snapshot=frozen, source_fingerprint=first["source_fingerprint"]))
    assert not edited["stale"]
    assert edited["snapshot_fingerprint"] != first["snapshot_fingerprint"]
    assert edited["revision"] != first["revision"]


def test_segment_project_uses_current_media_contract_with_local_clock():
    source = project()
    result = PLAN.build_segment_plan(source, settings())
    local = PLAN.segment_project(result, result["segments"][1]["segment_id"])
    assert not local["validation"]["errors"]
    assert local["processing_window"]["start_frame"] == 0
    assert local["processing_window"]["frame_count"] == 360
    assert local["video_track"][0]["timeline_in_seconds"] == 0
    assert local["video_track"][0]["source_in_seconds"] == 321 / 24
    assert local["picture_track"][0]["item_id"] == "picture-item"
    assert "outlet_slots" not in local


def test_fractional_source_end_matches_real_outlet_frame_rounding():
    value = project(360)
    value["assets"][0]["probe"].update(duration_seconds=14.487, frame_count=435)
    value["video_track"][0]["source_out_seconds"] = 14.487
    result = PLAN.build_segment_plan(value, settings(segment_frames=360, overlap_frames=0, overlap_alignment="exact"))
    local = PLAN.segment_project(result, result["segments"][0]["segment_id"])
    outlet = OUTLET.build_outlet_plan(local, "video", "video-clip")
    assert result["source_tracks"]["video"][0]["timeline_out_frame"] == 348
    assert outlet["items"][0]["frame_count"] == 348
    assert outlet["items"][0]["requested_source_window"]["end_seconds"] == 14.487


def test_plan_is_deterministic_and_matches_schema_shape():
    first = PLAN.build_segment_plan(project(), settings())
    second = PLAN.build_segment_plan(project(), settings())
    assert first == second
    schema = json.loads((ROOT / "schemas" / "zv-segment-plan-v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(first, schema)


@pytest.mark.parametrize("change", [
    {"fps": 0}, {"segment_frames": 0}, {"overlap_frames": -1}, {"segment_count": 0},
    {"overlap_alignment": "unknown"}, {"mode": "unknown"}, {"refresh_sources": 1}, {"schema_version": True}, {"unknown": 1},
])
def test_bad_settings_are_rejected(change):
    with pytest.raises(PLAN.SegmentPlanError):
        PLAN.build_segment_plan(project(), settings(**change))


def test_auto_segment_count_is_bounded_before_allocation():
    with pytest.raises(PLAN.SegmentPlanError, match="Invalid long-video"):
        PLAN.build_segment_plan(project(PLAN.MAX_SEGMENTS + 1), settings(segment_frames=1, overlap_frames=0, overlap_alignment="exact"))


def test_automatic_ids_follow_timeline_order_and_fallback_stays_unique():
    manual = settings(mode="source_manual", overlap_frames=0, overlap_alignment="exact", segments=[
        {"segment_id": "later", "start_frame": 120, "end_frame": 240},
        {"segment_id": "earlier", "start_frame": 0, "end_frame": 120},
    ])
    arranged = PLAN.build_segment_plan(project(240), manual)
    automatic = PLAN.build_segment_plan(project(240), {**manual, "mode": "source_auto", "segment_frames": 120})
    assert [row["segment_id"] for row in arranged["segments"]] == ["earlier", "later"]
    assert [row["segment_id"] for row in automatic["segments"]] == ["earlier", "later"]
    colliding = PLAN.build_segment_plan(project(240), {
        **manual, "mode": "source_auto", "segment_frames": 120,
        "segments": [{"segment_id": "segment-0002", "start_frame": 0, "end_frame": 120}, {}],
    })
    assert [row["segment_id"] for row in colliding["segments"]] == ["segment-0002", "segment-0003"]


def test_unused_asset_order_and_old_processing_window_do_not_block_task():
    upstream = project(240)
    upstream["assets"].insert(0, asset("picture", "unused"))
    upstream["processing_window"].update(start_seconds=20, end_seconds=10)
    first = PLAN.build_segment_plan(upstream, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact"))
    reordered = copy.deepcopy(upstream)
    reordered["assets"].reverse()
    second = PLAN.build_segment_plan(reordered, settings(segment_frames=120, overlap_frames=0, overlap_alignment="exact"))
    assert first["validation"]["ready"] and second["validation"]["ready"]
    assert first["source_fingerprint"] == second["source_fingerprint"]


def test_generation_manual_rejects_empty_explicit_range():
    result = PLAN.build_segment_plan(CONTRACT.empty_project(), settings(
        mode="generation_manual", overlap_frames=0, overlap_alignment="exact",
        range_start_frame=20, range_end_frame=20,
        segments=[{"segment_id": "one", "start_frame": 20, "end_frame": 40}],
    ))
    assert not result["validation"]["ready"]
    assert "source_range" in codes(result)


def test_old_snapshot_without_source_fingerprint_requires_refresh():
    with pytest.raises(PLAN.SegmentPlanError) as caught:
        PLAN.build_segment_plan(project(240), settings(source_snapshot=project(240), source_fingerprint=None))
    assert caught.value.issues[0]["code"] == "missing_fingerprint"


@pytest.mark.parametrize("frames,expected", [
    (361, [(0, 352), (313, 673)]),
    (365, [(0, 356), (317, 677)]),
    (368, [(0, 359), (320, 680)]),
    (369, [(0, 360), (321, 681)]),
    (370, [(0, 360), (321, 681)]),
])
def test_h3_source_auto_rebalances_short_final_reference_without_changing_target(frames, expected):
    result = PLAN.build_segment_plan(project(frames), settings())
    assert result["validation"]["ready"], result["validation"]["errors"]
    assert [(row["start_frame"], row["end_frame"]) for row in result["segments"]] == expected
    assert sum(row["output_frame_count"] for row in result["segments"]) == frames
    assert all(
        source_slice["timeline_out_frame"] - source_slice["timeline_in_frame"] >= 48
        for row in result["segments"] for source_slice in row["source_slices"]["video"]
    )


def test_h3_source_auto_reports_too_short_whole_source_and_cross_source_slice():
    short = PLAN.build_segment_plan(project(47), settings())
    assert not short["validation"]["ready"]
    assert "h3_reference_video_frames" in codes(short)

    split = project(120)
    original = split["video_track"][0]
    split["video_track"] = [
        {**original, "clip_id": "tiny", "source_out_seconds": 30 / 24},
        {**original, "clip_id": "rest", "timeline_in_seconds": 30 / 24,
         "source_in_seconds": 30 / 24, "source_out_seconds": 120 / 24},
    ]
    split = CONTRACT.normalize_project(split)
    result = PLAN.build_segment_plan(split, settings(segment_frames=120))
    assert not result["validation"]["ready"]
    assert "h3_reference_video_frames" in codes(result)


class NormalizeStore:
    def canonical(self, value):
        return CONTRACT.normalize_project(value)


def test_refresh_sources_skips_unavailable_old_snapshot_in_api_and_node(monkeypatch):
    class ExpiredSnapshotStore(NormalizeStore):
        def canonical(self, value):
            canonical = super().canonical(value)
            if any(row["asset_id"] == "expired" for row in canonical["assets"]):
                canonical["validation"] = {
                    "ready": False,
                    "errors": [{"path": "/assets/0", "code": "source_unavailable", "message": "old file missing"}],
                    "warnings": [],
                }
            return canonical

    old = project()
    old["assets"][0]["asset_id"] = "expired"
    old["video_track"][0]["asset_id"] = "expired"
    stale_settings = settings(source_snapshot=old, source_fingerprint=PLAN.project_fingerprint(old))
    server = importlib.import_module(SPEC.name + ".server")
    runtime = importlib.import_module(PACKAGE + ".media_evidence.runtime")
    store = ExpiredSnapshotStore()
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setattr(runtime, "get_store", lambda: store)

    with pytest.raises(PLAN.SegmentPlanError) as caught:
        server.prepare_plan({"media_project": project(), "settings": stale_settings})
    assert caught.value.issues[0]["code"] == "source_unavailable"

    refresh_settings = {**stale_settings, "refresh_sources": True}
    refreshed = server.prepare_plan({"media_project": project(), "settings": refresh_settings})
    assert refreshed["validation"]["ready"]
    assert not refreshed["stale"]
    assert {row["asset_id"] for row in refreshed["media_project"]["assets"]} == {"video", "picture"}

    missing_current = project()
    missing_current["validation"] = {
        "ready": False,
        "errors": [{"path": "/assets/0", "code": "source_unavailable", "message": "current file missing"}],
        "warnings": [],
    }
    with pytest.raises(PLAN.SegmentPlanError) as caught:
        server.prepare_plan({"media_project": missing_current, "settings": refresh_settings})
    assert caught.value.issues[0]["code"] == "source_unavailable"

    node_module = importlib.import_module(SPEC.name + ".plan_node")
    node_plan, report = node_module.ZVLongVideoSegmentDesk().build(project(), json.dumps(refresh_settings))
    assert node_plan["validation"]["ready"]
    assert "可执行" in report


def test_canonical_project_preserves_referenced_source_error_and_ignores_unused_pool_error():
    referenced = project(240)
    referenced["validation"] = {"ready": False, "errors": [{
        "path": "/assets/0", "code": "source_unavailable", "message": "forged client detail",
    }], "warnings": []}
    with pytest.raises(PLAN.SegmentPlanError) as caught:
        PLAN.canonical_task_project(referenced, NormalizeStore())
    assert caught.value.issues[0]["code"] == "source_unavailable"
    assert "forged" not in caught.value.issues[0]["message"]

    unused = project(240)
    unused["assets"].append(asset("picture", "unused"))
    unused["validation"] = {"ready": False, "errors": [{
        "path": "/assets/2", "code": "source_unavailable", "message": "unused missing",
    }], "warnings": []}
    canonical = PLAN.canonical_task_project(unused, NormalizeStore())
    assert not canonical["validation"]["errors"]
    assert {row["asset_id"] for row in canonical["assets"]} == {"video", "picture"}


def test_plan_node_turns_non_object_settings_and_bad_snapshot_into_blockers(monkeypatch):
    node_module = importlib.import_module(SPEC.name + ".plan_node")
    runtime = importlib.import_module(PACKAGE + ".media_evidence.runtime")
    monkeypatch.setattr(runtime, "get_store", lambda: NormalizeStore())

    class Blocker:
        def __init__(self, message):
            self.message = message

    core = types.ModuleType("comfy_execution")
    core.__path__ = []
    graph = types.ModuleType("comfy_execution.graph_utils")
    graph.ExecutionBlocker = Blocker
    monkeypatch.setitem(sys.modules, "comfy_execution", core)
    monkeypatch.setitem(sys.modules, "comfy_execution.graph_utils", graph)

    node = node_module.ZVLongVideoSegmentDesk()
    for raw in (
        "[]",
        json.dumps({**settings(), "source_snapshot": {"schema_version": 2}, "source_fingerprint": "a" * 64}),
    ):
        blocked, message = node.build(project(240), raw)
        assert isinstance(blocked, Blocker)
        assert isinstance(message, str) and message
