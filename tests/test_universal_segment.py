import importlib
import json
from pathlib import Path
import sys
import types
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
PACKAGE = "zf_universal_segment_testpkg"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
MODULE = importlib.import_module(PACKAGE + ".universal_segment")


def test_h3_delegates_existing_plan_and_preserves_downstream_port():
    settings = MODULE.default_settings()
    settings["h3"]["segment_frames"] = 210
    plan = {"segments": [{"segment_id": "one"}, {"segment_id": "two"}], "fps": 24}
    with mock.patch.object(MODULE.ZVLongVideoSegmentDesk, "build", return_value=(plan, "H3 ready")) as build:
        result = MODULE.ZVUniversalSegmentDesk().build({"source": "fixture"}, "H3", json.dumps(settings))
    assert result[0] is plan
    assert result[1] == "H3 ready"
    assert result[3:] == (2, 24.0)
    assert json.loads(build.call_args.args[1]) == settings["h3"]
    assert MODULE.ZVUniversalSegmentDesk.RETURN_TYPES[0] == "ZV_SEGMENT_PLAN"
    first_change = MODULE.ZVUniversalSegmentDesk.IS_CHANGED(target_mode="H3")
    second_change = MODULE.ZVUniversalSegmentDesk.IS_CHANGED(target_mode="H3")
    assert first_change != second_change


def test_animate_delegates_existing_plan_without_h3_limit():
    settings = MODULE.default_settings()
    settings["animate"]["seam_mode"] = "continuation_21"
    plan = {"segments": [{"segment_id": "one"}], "fps": 30}
    with mock.patch.object(MODULE.ZVAnimateSegmentDesk, "build", return_value=(plan, 1, 30.0, "Animate ready")) as build:
        result = MODULE.ZVUniversalSegmentDesk().build({"source": "fixture"}, "Animate", json.dumps(settings), fps=30)
    assert result[1:] == ("Animate ready", plan, 1, 30.0)
    assert json.loads(build.call_args.args[1]) == settings["animate"]
    assert build.call_args.kwargs == {"fps": 30}
    assert MODULE.ZVUniversalSegmentDesk.IS_CHANGED(target_mode="Animate") != MODULE.ZVUniversalSegmentDesk.IS_CHANGED(target_mode="Animate")


def test_raw_existing_settings_can_be_used_in_a_test_copy():
    settings = MODULE.default_settings()["h3"]
    with mock.patch.object(MODULE.ZVLongVideoSegmentDesk, "build", return_value=({"segments": [], "fps": 24}, "ready")) as build:
        MODULE.ZVUniversalSegmentDesk().build({}, "H3", json.dumps(settings))
    assert json.loads(build.call_args.args[1]) == settings


def test_h3_adapter_builds_the_existing_execution_plan_shape():
    contract = importlib.import_module(PACKAGE + ".media_evidence.contract")
    runtime = importlib.import_module(PACKAGE + ".media_evidence.runtime")
    project = contract.empty_project()
    project["assets"] = [
        {"asset_id": "video", "name": "video.mp4", "kind": "video", "source_handle": "originals/" + "a" * 32 + ".mp4",
         "probe": {"size_bytes": 1000, "duration_seconds": 12, "width": 320, "height": 180, "fps": 24,
                   "frame_count": 288, "frame_count_exact": True, "vfr": False, "has_audio": False,
                   "sample_rate": None, "channels": None, "codec": "fixture"}},
    ]
    project["video_track"] = [{"clip_id": "clip", "asset_id": "video", "timeline_in_seconds": 0,
                               "source_in_seconds": 0, "source_out_seconds": 12,
                               "source_audio_enabled": False, "audio_link_id": None}]
    settings = MODULE.default_settings()
    # This legacy fixture checks real source-clock slicing, not the new H3 default.
    settings["h3"]["mode"] = "source_auto"
    settings["h3"].update(segment_frames=210, overlap_frames=39)
    store = types.SimpleNamespace(canonical=contract.normalize_project)
    with mock.patch.object(runtime, "get_store", return_value=store):
        plan, report, _inactive, count, fps = MODULE.ZVUniversalSegmentDesk().build(project, "H3", json.dumps(settings))
        settings["h3"].update(overlap_frames=0, overlap_alignment="exact")
        hard_cut = MODULE.ZVUniversalSegmentDesk().build(project, "H3", json.dumps(settings))[0]
        settings["h3"].update(overlap_frames=32, overlap_alignment="h3_guide")
        aligned = MODULE.ZVUniversalSegmentDesk().build(project, "H3", json.dumps(settings))[0]
    assert plan["validation"]["ready"], report
    assert count == len(plan["segments"]) == 2
    assert fps == 24.0
    assert plan["segments"][1]["overlap_frames"] == 39
    assert hard_cut["segments"][1]["seam"] == "hard_cut"
    assert hard_cut["segments"][1]["overlap_frames"] == 0
    assert aligned["effective_overlap_frames"] == 22
