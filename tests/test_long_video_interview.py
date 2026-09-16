import copy
import importlib
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "zf_long_interview_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
P = importlib.import_module(PACKAGE + ".long_video.plan")
I = importlib.import_module(PACKAGE + ".long_video.interview")
C = importlib.import_module(PACKAGE + ".media_evidence.contract")


def source():
    value = C.empty_project()
    value["assets"] = [
        {"asset_id": "video", "name": "source.mp4", "kind": "video", "source_handle": "originals/" + "a" * 32 + ".mp4", "probe": {"size_bytes": 100, "duration_seconds": 30, "width": 720, "height": 1280, "fps": 24, "frame_count": 720, "frame_count_exact": True, "vfr": False, "has_audio": False, "sample_rate": None, "channels": None, "codec": "fixture"}},
        {"asset_id": "image", "name": "person.png", "kind": "picture", "source_handle": "originals/" + "b" * 32 + ".png", "probe": {"size_bytes": 100, "duration_seconds": None, "width": 720, "height": 1280, "fps": None, "frame_count": None, "frame_count_exact": False, "vfr": None, "has_audio": False, "sample_rate": None, "channels": None, "codec": "png"}},
    ]
    value["video_track"] = [{"clip_id": "v1", "asset_id": "video", "timeline_in_seconds": 0, "source_in_seconds": 0, "source_out_seconds": 28, "source_audio_enabled": False, "audio_link_id": None}]
    value["picture_track"] = [{"item_id": "p1", "asset_id": "image", "order": 1}]
    return C.normalize_project(value)


def test_align_all_then_exclude_is_physical_and_invalidates_snapshot():
    plan = P.build_segment_plan(source(), P.default_settings())
    state = I.empty_segment_interview()
    state["global"] = {"intent": "人物模仿对应视频片段动作。", "media_roles": {"p1": ["subject_identity"], "v1": ["motion_reference"]}}
    original = copy.deepcopy(plan)
    result = I.compile_segment_interview(plan, state, align=True)
    assert result["ready"], result["errors"]
    assert len(result["segments"]) == 2
    assert result["segments"][1]["reference_plan"]["routes"]["ref_images"] == ["p1"]
    state = result["state"]
    second = plan["segments"][1]["segment_id"]
    state["segments"][second] = {"bindings": {"p1": {"item_id": "p1", "participates": False, "banks": ["ref_images"]}}}
    stale = I.compile_segment_interview(plan, state)
    assert not stale["ready"] and any(x["code"] == "alignment_stale" for x in stale["errors"])
    aligned = I.compile_segment_interview(plan, state, align=True)
    assert aligned["ready"], aligned["errors"]
    assert aligned["segments"][0]["reference_plan"]["routes"]["ref_images"] == ["p1"]
    assert aligned["segments"][1]["reference_plan"]["routes"]["ref_images"] == []
    assert all(x["item_id"] != "p1" for x in aligned["segments"][1]["call_references"])
    assert "person.png" not in aligned["segments"][1]["stage1_task"]
    assert plan == original


def test_timing_change_and_text_change_require_realign():
    plan = P.build_segment_plan(source(), P.default_settings())
    aligned = I.compile_segment_interview(plan, I.empty_segment_interview(), align=True)
    assert aligned["ready"], aligned["errors"]
    settings = {**P.default_settings(), "segment_frames": 320}
    changed_plan = P.build_segment_plan(source(), settings)
    assert not I.compile_segment_interview(changed_plan, aligned["state"])["ready"]
    changed = copy.deepcopy(aligned["state"])
    changed["global"]["must_keep"] = "保持站立"
    assert not I.compile_segment_interview(plan, changed)["ready"]
    assert I.compile_segment_interview(plan, changed, align=True)["ready"]


def test_generation_has_no_fake_media_and_roundtrip_is_stable():
    plan = P.build_segment_plan(C.empty_project(), {**P.default_settings(), "mode": "generation_count", "segment_frames": 124, "segment_count": 3})
    result = I.compile_segment_interview(plan, {**I.empty_segment_interview(), "global": {"intent": "城市晨光。"}}, align=True)
    assert result["ready"], result["errors"]
    assert all(not s["call_references"] for s in result["segments"])
    restored = I.compile_segment_interview(plan, json.dumps(result["state"]))
    assert restored["ready"] and result["fingerprint"] == restored["fingerprint"]


def test_global_and_local_text_keep_both_constraints():
    combined = I.merged_interview({"must_keep": "保持躺姿", "music": "不加配乐"}, {"must_keep": "保持人物服装", "intent": "抬起右手"})
    assert combined["must_keep"] == "保持躺姿\n保持人物服装"
    assert combined["music"] == "不加配乐"
    with pytest.raises(ValueError):
        I.parse_segment_interview({"schema_version": 1, "global": {"sam_prompt": "clothes"}})


def test_compiled_media_name_changes_execution_fingerprint_after_refresh():
    plan = P.build_segment_plan(source(), P.default_settings())
    first = I.compile_segment_interview(plan, I.empty_segment_interview(), align=True)
    changed_source = source()
    changed_source["assets"][0]["name"] = "renamed-source.mp4"
    changed_plan = P.build_segment_plan(changed_source, {**P.default_settings(), "refresh_sources": True})
    second = I.compile_segment_interview(changed_plan, first["state"])
    assert second["fingerprint"] != first["fingerprint"]
    assert not second["ready"] and any(row["code"] == "alignment_stale" for row in second["errors"])


def test_fingerprint_ignores_asset_pool_order_and_project_clock():
    original = source()
    plan = P.build_segment_plan(original, P.default_settings())
    first = I.compile_segment_interview(plan, I.empty_segment_interview(), align=True)
    changed = source()
    changed["assets"].reverse()
    changed["project_clock"]["fps"] = 60
    changed["assets"].append({
        "asset_id": "unused", "name": "unused.png", "kind": "picture",
        "source_handle": "originals/" + "c" * 32 + ".png",
        "probe": {"size_bytes": 10, "duration_seconds": None, "width": 16, "height": 16,
                  "fps": None, "frame_count": None, "frame_count_exact": False, "vfr": None,
                  "has_audio": False, "sample_rate": None, "channels": None, "codec": "png"},
    })
    changed_plan = P.build_segment_plan(changed, P.default_settings())
    second = I.compile_segment_interview(changed_plan, first["state"])
    assert changed_plan["revision"] == plan["revision"]
    assert second["ready"], second["errors"]
    assert second["fingerprint"] == first["fingerprint"]


@pytest.mark.parametrize("frames", [361, 365, 368, 369, 370])
def test_rebalanced_short_source_tail_compiles_for_h3(frames):
    value = source()
    seconds = frames / 24
    value["assets"][0]["probe"].update(
        duration_seconds=seconds, frame_count=frames, fps=24, frame_count_exact=True,
    )
    value["video_track"][0]["source_out_seconds"] = seconds
    plan = P.build_segment_plan(C.normalize_project(value), P.default_settings())
    result = I.compile_segment_interview(plan, I.empty_segment_interview(), align=True)
    assert result["ready"], result["errors"]
    assert result["segments"][-1]["reference_plan"]["media_project"]["video_track"][0]["project_frame_count"] >= 48
