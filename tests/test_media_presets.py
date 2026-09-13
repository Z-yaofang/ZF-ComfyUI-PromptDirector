import copy
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zv_preset_test", ROOT / "media_evidence" / "__init__.py", submodule_search_locations=[str(ROOT / "media_evidence")])
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
C = importlib.import_module(SPEC.name + ".contract")
P = importlib.import_module(SPEC.name + ".presets")
S = importlib.import_module(SPEC.name + ".preset_store")


def window_project(preset_id="builtin.generic", seconds=17):
    p = C.empty_project()
    p["processing_window"]["end_seconds"] = seconds
    p["processing_preset"] = P.builtin(preset_id)
    return p


def test_new_project_is_v2_generic_and_17_seconds_is_valid():
    p = C.empty_project()
    assert p["schema_version"] == 2 and p["processing_preset"] == P.builtin()
    out = C.normalize_project(window_project())
    assert not out["validation"]["errors"]
    assert out["preset_compatibility"]["compatible"]
    assert out["processing_window"]["frame_count"] == 408


def test_v1_migration_preserves_range_and_maps_to_h3_snapshot():
    p = window_project()
    p["schema_version"] = 1
    del p["processing_preset"]
    original = copy.deepcopy(p)
    out = C.normalize_project(p)
    assert p == original and out["schema_version"] == 2
    assert out["processing_preset"] == P.builtin("builtin.minimax-h3.single")
    assert out["processing_window"]["end_seconds"] == 17
    assert not out["validation"]["errors"] and not out["preset_compatibility"]["compatible"]
    assert "408" in str(out["preset_compatibility"]["issues"])


def test_explicit_v2_requires_snapshot_and_recomputes_all_derived_validation():
    p = window_project("builtin.minimax-h3.single")
    p.update(validation={"errors": [], "warnings": []}, preset_compatibility={"compatible": True, "untrusted": True})
    p["processing_window"]["frame_count"] = 1
    out = C.normalize_project(p)
    assert out["processing_window"]["frame_count"] == 408
    assert not out["preset_compatibility"]["compatible"]
    assert C.normalize_project(out) == out
    del p["processing_preset"]
    with pytest.raises(C.ProjectError):
        C.normalize_project(p)


def test_long_task_keeps_real_segment_constraints_and_reports_rules_only():
    out = C.normalize_project(window_project("builtin.minimax-h3.segmented", 90))
    assert not out["validation"]["errors"] and out["preset_compatibility"]["compatible"]
    assert out["preset_compatibility"]["segment_count"] == 7
    assert out["preset_compatibility"]["rules_only"] is True
    rules = out["processing_preset"]["snapshot"]["rules"]
    assert out["processing_preset"]["preset_version"] == 2
    assert rules["max_seconds"] is None and rules["max_frames"] == 360
    assert rules["segment_max_seconds"] == 15 and rules["overlap_frames"] == 48
    assert rules["overlap_alignment"] == "h3_guide"
    assert out["preset_compatibility"]["requested_overlap_frames"] == 48
    assert out["preset_compatibility"]["effective_overlap_frames"] == 39
    assert out["preset_compatibility"]["segment_stride_frames"] == 321
    short = C.normalize_project(window_project("builtin.minimax-h3.segmented", 1))
    assert not short["preset_compatibility"]["compatible"]
    assert not short["validation"]["errors"]


@pytest.mark.parametrize("requested,actual", [(1, 1), (4, 1), (5, 5), (12, 5), (22, 22), (48, 39)])
def test_h3_guide_aligns_requested_overlap_down_before_planning(requested, actual):
    project = window_project("builtin.minimax-h3.segmented", 28)
    project["processing_preset"]["snapshot"]["rules"]["overlap_frames"] = requested
    assert not P.rule_errors(project["processing_preset"]["snapshot"])
    out = C.normalize_project(project)
    result = out["preset_compatibility"]
    assert result["compatible"] and result["frame_count"] == 672
    assert result["requested_overlap_frames"] == requested
    assert result["effective_overlap_frames"] == actual
    assert result["segment_stride_frames"] == 360 - actual
    assert result["segment_count"] == 2
    assert out["processing_preset"]["snapshot"]["rules"]["overlap_frames"] == requested


def test_segment_count_uses_effective_overlap_and_exact_is_model_independent():
    project = window_project("builtin.minimax-h3.segmented", 28)
    result = C.normalize_project(project)["preset_compatibility"]
    assert result["segment_count"] == 2  # Using requested 48 would incorrectly require 3.
    rules = project["processing_preset"]["snapshot"]["rules"]
    rules.update(overlap_alignment="exact", overlap_frames=12)
    result = C.normalize_project(project)["preset_compatibility"]
    assert result["compatible"] and result["effective_overlap_frames"] == 12
    assert result["segment_stride_frames"] == 348
    rules["overlap_frames"] = 0
    result = C.normalize_project(project)["preset_compatibility"]
    assert result["effective_overlap_frames"] == 0 and result["segment_stride_frames"] == 360


@pytest.mark.parametrize("alignment,requested", [("exact", 48), ("h3_guide", 56), ("h3_guide", 0), ("unknown", 12), (None, 12)])
def test_overlap_strategy_and_effective_segment_minimum_are_validated(alignment, requested):
    snapshot = P.builtin("builtin.minimax-h3.segmented")["snapshot"]
    snapshot["rules"].update(overlap_alignment=alignment, overlap_frames=requested)
    assert P.rule_errors(snapshot)


def test_single_window_has_no_requested_effective_overlap_or_stride():
    for preset_id in ("builtin.generic", "builtin.minimax-h3.single"):
        result = C.normalize_project(window_project(preset_id))["preset_compatibility"]
        assert all(result[key] is None for key in ("requested_overlap_frames", "effective_overlap_frames", "segment_stride_frames"))


def test_old_v2_snapshot_defaults_to_exact_without_upgrading_frozen_identity():
    project = window_project("builtin.minimax-h3.segmented", 28)
    project["processing_preset"]["preset_version"] = 1
    rules = project["processing_preset"]["snapshot"]["rules"]
    rules["overlap_frames"] = 12
    del rules["overlap_alignment"]
    before = copy.deepcopy(project)
    assert P.rule_errors(project["processing_preset"]["snapshot"])
    migrated = P.normalize_snapshot(project["processing_preset"]["snapshot"])
    assert migrated["rules"]["overlap_alignment"] == "exact"
    out = C.normalize_project(project)
    assert project == before and out["processing_preset"]["preset_version"] == 1
    assert out["processing_preset"]["preset_id"] == "builtin.minimax-h3.segmented"
    assert out["processing_preset"]["snapshot"] == migrated
    assert out["preset_compatibility"]["effective_overlap_frames"] == 12
    assert out["preset_compatibility"]["segment_stride_frames"] == 348
    assert C.normalize_project(out) == out


def test_old_library_is_migrated_in_memory_without_rewriting_and_save_uses_full_snapshot(tmp_path):
    store = S.PresetLibrary(tmp_path)
    legacy = P.builtin("builtin.minimax-h3.segmented")
    legacy.update(preset_id="user." + "a" * 32, preset_version=7)
    legacy["snapshot"]["rules"]["overlap_frames"] = 12
    del legacy["snapshot"]["rules"]["overlap_alignment"]
    store.directory.mkdir(parents=True)
    store.path.write_text(json.dumps({"schema_version": 1, "presets": [legacy]}), encoding="utf-8")
    original_bytes = store.path.read_bytes()
    migrated = store.listing()["users"][0]
    assert store.path.read_bytes() == original_bytes
    assert migrated["preset_id"] == legacy["preset_id"] and migrated["preset_version"] == 7
    assert migrated["snapshot"]["rules"]["overlap_alignment"] == "exact"
    assert migrated["snapshot"]["rules"]["overlap_frames"] == 12
    assert store.read() == [migrated] and store.path.read_bytes() == original_bytes
    saved = store.save(legacy["snapshot"], legacy["preset_id"], 7)
    assert saved["preset_version"] == 8 and saved["snapshot"] == migrated["snapshot"]
    assert store.listing()["users"] == [saved]
    assert json.loads(store.path.read_text(encoding="utf-8"))["presets"] == [saved]


def test_stricter_frame_seconds_cap_is_derived_without_changing_snapshot():
    p = window_project("builtin.minimax-h3.single", 12)
    p["processing_preset"]["snapshot"]["rules"].update(max_seconds=10, max_frames=360)
    out = C.normalize_project(p)
    assert out["processing_preset"] == p["processing_preset"]
    assert out["preset_compatibility"]["effective_max_frames"] == 240
    assert out["preset_compatibility"]["effective_max_seconds"] == 10
    assert not out["preset_compatibility"]["compatible"]


def test_unaligned_range_cannot_hide_excess_duration_in_rounded_frame_count():
    p = window_project("builtin.minimax-h3.single", 10.01)
    p["processing_preset"]["snapshot"]["rules"].update(max_frames=240, align_to_grid=False)
    out = C.normalize_project(p)
    assert out["preset_compatibility"]["frame_count"] == 240
    assert not out["preset_compatibility"]["compatible"]
    assert out["processing_window"]["end_seconds"] == 10.01


@pytest.mark.parametrize("change", [
    {"min_frames": 400}, {"max_seconds": -1}, {"target_fps": float("nan")}, {"target_fps": float("inf")},
    {"min_frames": 1.5}, {"target_fps": None}, {"target_fps": .5}, {"overlap_frames": -1}, {"max_frames": 0},
    {"max_seconds": 1}, {"target_fps": True}, {"align_to_grid": "yes"}, {"unexpected": 1},
])
def test_invalid_user_rules_cannot_be_saved(tmp_path, change):
    snapshot = P.builtin("builtin.minimax-h3.single")["snapshot"]
    snapshot["rules"].update(change)
    with pytest.raises(S.PresetError):
        S.PresetLibrary(tmp_path).save(snapshot)
    assert not (tmp_path / "zf_media_evidence" / "processing_presets.json").exists()


@pytest.mark.parametrize("change", [{"segment_min_seconds": 16}, {"segment_max_seconds": None}, {"overlap_frames": 56}, {"max_seconds": 1}])
def test_auto_segment_conflicts_rejected(change):
    snapshot = P.builtin("builtin.minimax-h3.segmented")["snapshot"]
    snapshot["rules"].update(change)
    assert P.rule_errors(snapshot)


def test_empty_name_and_unknown_snapshot_fields_rejected(tmp_path):
    for change in [{"name": "  "}, {"strategy": "unlimited_h3"}, {"path": "../../outside.json"}]:
        snapshot = P.builtin()["snapshot"]
        snapshot.update(change)
        with pytest.raises(S.PresetError):
            S.PresetLibrary(tmp_path).save(snapshot)


def test_library_stable_id_versions_restart_and_project_snapshot_isolation(tmp_path):
    store = S.PresetLibrary(tmp_path)
    first = store.save(P.builtin("builtin.minimax-h3.single")["snapshot"])
    assert first["preset_id"].startswith("user.") and first["preset_version"] == 1
    project = window_project(); project["processing_preset"] = first
    old = C.normalize_project(project)
    edited = copy.deepcopy(first["snapshot"]); edited["name"] = "我的长片段规则"; edited["rules"].update(max_frames=720, max_seconds=30)
    second = store.save(edited, first["preset_id"], first["preset_version"])
    assert second["preset_id"] == first["preset_id"] and second["preset_version"] == 2
    assert S.PresetLibrary(tmp_path).listing()["users"] == [second]
    assert C.normalize_project(json.loads(json.dumps(old))) == old
    with pytest.raises(S.PresetError, match="已被修改"):
        store.save(edited, first["preset_id"], 1)
    with pytest.raises(S.PresetError):
        store.delete(first["preset_id"], 1)
    store.delete(second["preset_id"], 2)
    assert S.PresetLibrary(tmp_path).listing()["users"] == []
    assert C.normalize_project(old) == old


@pytest.mark.parametrize("preset_id", ["builtin.generic", "builtin.minimax-h3.single", "../escape", "C:/outside.json"])
def test_builtins_and_arbitrary_ids_cannot_be_written_or_deleted(tmp_path, preset_id):
    store = S.PresetLibrary(tmp_path)
    with pytest.raises(S.PresetError):
        store.save(P.builtin()["snapshot"], preset_id, 1)
    with pytest.raises(S.PresetError):
        store.delete(preset_id, 1)
    assert not list(tmp_path.iterdir())


def test_corrupt_library_is_not_overwritten_and_user_roots_are_isolated(tmp_path):
    alice, bob = S.PresetLibrary(tmp_path / "alice"), S.PresetLibrary(tmp_path / "bob")
    alice.save(P.builtin()["snapshot"])
    assert bob.listing()["users"] == []
    alice.path.write_text('{"invalid":true}', encoding="utf-8")
    before = alice.path.read_bytes()
    with pytest.raises(S.PresetError):
        alice.save(P.builtin()["snapshot"])
    assert alice.path.read_bytes() == before


def test_storage_path_escape_is_rejected_before_io(tmp_path):
    store = S.PresetLibrary(tmp_path / "user")
    store.path = tmp_path / "outside.json"
    with pytest.raises(S.PresetError):
        store.save(P.builtin()["snapshot"])
    assert not store.path.exists()


def test_host_current_user_api_determines_library_root(tmp_path, monkeypatch):
    calls = []
    class Manager:
        def get_request_user_filepath(self, request, file, create_dir):
            calls.append((request, file, create_dir))
            return str(tmp_path / request.user)
    monkeypatch.setitem(sys.modules, "server", types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(user_manager=Manager()))))
    runtime = importlib.import_module(SPEC.name + ".runtime")
    request = types.SimpleNamespace(user="alice")
    store = runtime.get_preset_library(request)
    assert store.path == (tmp_path / "alice" / "zf_media_evidence" / "processing_presets.json").resolve()
    assert calls == [(request, None, False)]


def test_generic_still_enforces_positive_range_and_twelve_hour_limit():
    p = window_project(seconds=0)
    assert any(e["code"] == "window_range" for e in C.normalize_project(p)["validation"]["errors"])
    p["processing_window"]["end_seconds"] = 43201
    with pytest.raises(C.ProjectError):
        C.normalize_project(p)


def test_all_builtins_match_published_schema_and_are_valid():
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(S.PRESET_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(C.SCHEMA)
    for preset in P.BUILTIN_PRESETS:
        assert not P.rule_errors(preset["snapshot"])
        jsonschema.validate(preset, S.PRESET_SCHEMA)
        p = C.empty_project(); p["processing_preset"] = copy.deepcopy(preset)
        jsonschema.validate(C.normalize_project(p), C.SCHEMA)
