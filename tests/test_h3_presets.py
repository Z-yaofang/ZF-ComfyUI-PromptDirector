"""H3-V2-02 portable references, transactional storage, and real HTTP routes."""
import copy
import importlib
import json
import subprocess
import sys
from pathlib import Path
import runpy
import sqlite3
import types

import pytest

H = runpy.run_path(str(Path(__file__).with_name("test_h3_v2.py")))
I, C, S, R, N = (H[key] for key in ("I", "C", "S", "R", "N"))
contract_registry_for_synthetic_inputs = H["contract_registry_for_synthetic_inputs"]
PACKAGE = H["H"]["PACKAGE"]
P = importlib.import_module(PACKAGE + ".h3_focus.presets")
DB = importlib.import_module(PACKAGE + ".h3_focus.preset_store")
REF = importlib.import_module(PACKAGE + ".h3_focus.references")
HTTP = importlib.import_module(PACKAGE + ".h3_focus.preset_server")


def fresh(pictures=1, videos=0, audios=0, paired=False, prefix=""):
    project = H["source"](pictures, videos, audios, soundtracks=paired)
    if prefix:
        identifiers = {row["item_id"] for row in I.media_inventory(project)}
        text = json.dumps(project)
        for identifier in identifiers: text = text.replace('"' + identifier + '"', '"' + prefix + identifier + '"')
        project = C.normalize_project(json.loads(text))
    return project


def confirmed(project, **text):
    state = I.empty_interview(); state.update(text)
    return H["aligned"](project, state)


def template(text="自由叙述：图一，数字1，0:02秒"):
    return P.capture_template(I.empty_interview() | {"intent": text}, fresh(0))


def test_reference_picture_keeps_source_after_adding_first_frame_and_sorting():
    old = fresh(1); preset = P.capture_template(confirmed(old, intent="保留 <Picture 1> 的人物，图一和0:02不重写"), old)
    new = fresh(2, prefix="new_")
    current = I.empty_interview(); current["bindings"]["new_p2"] = {"item_id": "new_p2", "participates": True, "banks": ["first_frame"]}
    loaded = P.apply_template(preset, current, new)
    assert loaded["state"]["intent"] == "保留 <Picture 2> 的人物，图一和0:02不重写"
    assert loaded["notices"][0]["code"] == "extra_slots"
    saved = H["aligned"](new, loaded["state"])
    new["picture_track"][0]["order"] = 10
    # The anchor stays first; source new_p1 is tracked by ID, not stale ordinal.
    again = I.compile_interview(saved, C.normalize_project(new))
    assert again["state"]["reference_texts"]["intent"]["definitions"][0]["source"]["item_id"] == "new_p1"
    assert "图一和0:02不重写" in again["state"]["intent"]
    assert I.compile_interview(json.loads(I.dumps(again["state"])), C.normalize_project(new))["state"]["intent"] == again["state"]["intent"]


def test_live_reference_sort_edit_and_export_refresh_typed_slot():
    project = fresh(2); state = confirmed(project, intent="<Picture 1> 的人物")
    state = I.compile_interview(state, project)["state"]
    project["picture_track"][0]["order"] = 9; project = C.normalize_project(project)
    state["intent"] = "改写剧情，<Picture 1> 的人物在0:02说话"
    state = I.compile_interview(state, project)["state"]
    assert state["intent"] == "改写剧情，<Picture 2> 的人物在0:02说话"
    state = H["aligned"](project, state)
    portable = P.capture_template(state, project)
    assert portable["fields"]["intent"]["definitions"][0]["source"] == {"kind": "picture", "slot": 2, "bank": "ref_images"}
    state["intent"] = "只保留自由文本，不再引用"; state = I.compile_interview(state, project)["state"]
    assert state["reference_texts"]["intent"]["definitions"] == []


def test_video_soundtrack_and_independent_audio_never_swap_when_pair_changes():
    old = fresh(0, 1, 1, paired=True)
    state = confirmed(old, intent="<Audio 1> 保留视频原声，<Audio 2> 模仿独立台词")
    state["media_roles"]["va1"] = ["voice_reference"]
    state["media_purposes"]["va1"] = "<Audio 1> 保留原声声线"
    preset = P.capture_template(state, old)
    pair = preset["slots"][0]["soundtrack"]
    assert pair["expected"] and pair["roles"] == ["voice_reference"] and pair["purpose"]["definitions"][0]["source"]["kind"] == "video"
    new = fresh(0, 1, 1, paired=True, prefix="new_")
    new["video_track"][0]["source_audio_enabled"] = False; new = C.normalize_project(new)
    result = P.apply_template(preset, I.empty_interview(), new)
    assert "<H3待绑定:r1> 保留视频原声，<Audio 1> 模仿独立台词" == result["state"]["intent"]
    assert not result["validation"]["ready"]
    assert any(row["code"] == "unresolved_reference" for row in result["validation"]["errors"])
    assert result["state"]["media_roles"]["new_va1"] == ["voice_reference"]
    assert any(row["code"] == "unused_purpose" for row in result["validation"]["warnings"])
    new["video_track"][0]["source_audio_enabled"] = True; new = C.normalize_project(new)
    restored = I.compile_interview(result["state"], new)["state"]
    assert restored["intent"] == state["intent"]
    assert restored["media_purposes"]["new_va1"] == state["media_purposes"]["va1"]


def test_new_extra_soundtrack_moves_only_independent_audio_reference():
    old = fresh(0, 1, 1)
    preset = P.capture_template(confirmed(old, dialogue="严格按 <Audio 1> 说话"), old)
    new = fresh(0, 1, 1, paired=True, prefix="x_")
    before = copy.deepcopy(new)
    result = P.apply_template(preset, I.empty_interview(), new)
    assert result["state"]["dialogue"] == "严格按 <Audio 2> 说话"
    assert new == before and new["video_track"][0]["source_audio_enabled"]
    assert any(row["code"] == "soundtrack_difference" for row in result["notices"])


def test_same_picture_multiple_banks_and_drive_selectors_are_distinct():
    project = fresh(1, 0, 1); state = I.empty_interview()
    state["bindings"] = {"p1": {"item_id": "p1", "participates": True, "banks": ["first_frame", "ref_images"]}, "a1": {"item_id": "a1", "participates": True, "banks": ["drive_audio"]}}
    state["intent"] = "<Picture 1> 开场，<Picture 2> 定身份，<Audio 1> 驱动"
    preset = P.capture_template(H["aligned"](project, state), project)
    assert [row["source"]["bank"] for row in preset["fields"]["intent"]["definitions"]] == ["first_frame", "ref_images", "drive_audio"]
    assert P.apply_template(preset, I.empty_interview(), fresh(1, 0, 1, prefix="z_"))["state"]["intent"] == state["intent"]


def test_missing_slot_stays_visible_then_binds_once_and_extra_material_is_kept():
    old = fresh(2); preset = P.capture_template(confirmed(old, intent="<Picture 2> 定主体"), old)
    new = fresh(1, prefix="m_"); result = P.apply_template(preset, I.empty_interview(), new)
    assert "<H3待绑定:r1>" in result["state"]["intent"] and not result["validation"]["ready"]
    assert any(row["code"] == "missing_slot" for row in result["notices"])
    extended = fresh(2, prefix="m_"); bound = I.compile_interview(result["state"], extended)["state"]
    assert bound["intent"] == "<Picture 2> 定主体"
    assert bound["reference_texts"]["intent"]["definitions"][0]["source"]["item_id"] == "m_p2"


def test_semantic_load_does_not_invalidate_mechanics_or_change_project():
    project = fresh(); current = confirmed(project, intent="旧文本")
    updated = copy.deepcopy(current); updated["intent"] = "新自由叙述"; updated["media_roles"]["p1"] = ["style_reference"]
    preset = P.capture_template(updated, project); before = copy.deepcopy(project)
    result = P.apply_template(preset, current, project)
    assert not result["mechanical_changed"] and result["state"]["reference_detection"] == current["reference_detection"]
    assert result["state"]["alignment"] == current["alignment"] and project == before
    assert result["state"]["intent"] == "新自由叙述"


def test_template_has_no_media_identity_paths_names_preview_or_project_settings():
    project = fresh(1, 1, 1, paired=True)
    preset = P.capture_template(confirmed(project, intent="参考 <Picture 1>"), project)
    text = json.dumps(preset)
    for forbidden in ["item_id", "asset_id", "clip_id", "source_handle", "originals/", "preview", "cache", "alignment", "reference_detection", "processing_window", "output_canvas", "processing_preset", ".mp4", ".png"]:
        assert forbidden not in text
    assert set(preset["fields"]) == set(I.TEXT_FIELDS)


@pytest.mark.parametrize("case", ["unknown", "duplicate", "missing", "unused", "bank", "id", "slot", "literal", "malformed"])
def test_malicious_or_incomplete_token_contract_is_rejected(case):
    project = fresh(); preset = P.capture_template(confirmed(project, intent="<Picture 1>"), project)
    entry = preset["fields"]["intent"]
    if case == "unknown": entry["extra"] = True
    if case == "duplicate": entry["definitions"] *= 2
    if case == "missing": entry["definitions"] = []
    if case == "unused": entry["text"] = "自由叙述"
    if case == "bank": entry["definitions"][0]["source"]["bank"] = "arbitrary"
    if case == "id": entry["definitions"][0]["source"]["item_id"] = "old"
    if case == "slot": entry["definitions"][0]["source"]["slot"] = 9
    if case == "literal": entry["text"] = "<Picture 1>"
    if case == "malformed": entry["text"] = "{{h3:unknown}}"
    with pytest.raises(P.PresetError): P.validate_template(preset)


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e400}', '[' * 20 + '0' + ']' * 20, 'x' * (P.MAX_BYTES + 1)], ids=["duplicate", "nan", "inf", "overflow", "depth", "size"])
def test_json_size_depth_duplicate_keys_and_nonfinite_are_rejected(text):
    with pytest.raises(P.PresetError): P.strict_json(text)


def test_explicit_reference_requires_confirmed_nonstale_unique_source_to_save():
    project = fresh(); state = I.empty_interview(); state["intent"] = "<Picture 1>"
    with pytest.raises(P.PresetError): P.capture_template(state, project)
    state = confirmed(project, intent="<Picture 1>")
    changed = copy.deepcopy(project); changed["output_canvas"]["width"] = 704
    with pytest.raises(P.PresetError): P.capture_template(state, C.normalize_project(changed))
    state["intent"] = "<Picture 9>"
    with pytest.raises(P.PresetError): P.capture_template(state, project)


def test_library_crud_rename_pagination_restart_import_export_and_cas(tmp_path):
    library = DB.InterviewLibrary(tmp_path); body = template()
    a = library.create("动作", body); b = library.create("文戏", body)
    assert len(library.listing(limit=1)["presets"]) == 1
    assert len(library.listing(library.listing(limit=1)["next_cursor"], 1)["presets"]) == 1
    changed = library.update(a["preset_id"], 1, "新动作")
    assert changed["preset_version"] == 2 and changed["template"] == body
    with pytest.raises(P.PresetError, match="已被修改"): library.delete(a["preset_id"], 1)
    assert DB.InterviewLibrary(tmp_path).get(a["preset_id"])["name"] == "新动作"
    package = library.export([a["preset_id"], b["preset_id"]]); imported = library.import_collection(package)
    assert all(item["preset_id"] not in {a["preset_id"], b["preset_id"]} for item in imported)
    assert imported[0]["name"].startswith("新动作（副本")
    assert all(item["template"] == body for item in imported)
    library.delete(a["preset_id"], 2)
    with pytest.raises(P.PresetError): library.get(a["preset_id"])
    assert library.get(b["preset_id"])["preset_version"] == 1


def test_library_users_paths_corruption_and_readonly_transaction_failure(tmp_path, monkeypatch):
    alice, bob = tmp_path / "alice", tmp_path / "bob"; alice.mkdir(); bob.mkdir()
    library = DB.InterviewLibrary(alice); item = library.create("安全", template())
    assert DB.InterviewLibrary(bob).listing()["presets"] == []
    with pytest.raises(P.PresetError): DB.InterviewLibrary(bob).get(item["preset_id"])
    with pytest.raises(P.PresetError): library.get("../../media")
    other = tmp_path / "other"; other.mkdir(); linked = tmp_path / "linked"
    if sys.platform == "win32":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(other)], capture_output=True)
        assert result.returncode == 0
    else: linked.symlink_to(other, target_is_directory=True)
    linked_library = DB.InterviewLibrary(linked)
    assert linked_library.listing()["presets"] == []
    assert linked_library.create("可信根", template())["name"] == "可信根"
    assert (other / "zf_h3_interview" / "presets.sqlite3").is_file()
    retarget = tmp_path / "retarget"; retarget.mkdir()
    linked.rmdir() if sys.platform == "win32" else linked.unlink()
    if sys.platform == "win32":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(retarget)], capture_output=True)
        assert result.returncode == 0
    else: linked.symlink_to(retarget, target_is_directory=True)
    with pytest.raises(P.PresetError, match="指向已改变"): linked_library.listing()
    internal_root = tmp_path / "internal-root"; internal_root.mkdir()
    internal_target = internal_root / "target"; internal_target.mkdir()
    internal_directory = internal_root / "zf_h3_interview"
    if sys.platform == "win32":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(internal_directory), str(internal_target)], capture_output=True)
        assert result.returncode == 0
    else: internal_directory.symlink_to(internal_target, target_is_directory=True)
    with pytest.raises(P.PresetError, match="reparse"): DB.InterviewLibrary(internal_root).listing()
    escape_root = tmp_path / "escape-root"; escape_root.mkdir()
    escape_target = tmp_path / "escape-target"; escape_target.mkdir()
    escape_directory = escape_root / "zf_h3_interview"
    if sys.platform == "win32":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(escape_directory), str(escape_target)], capture_output=True)
        assert result.returncode == 0
    else: escape_directory.symlink_to(escape_target, target_is_directory=True)
    with pytest.raises(P.PresetError, match="reparse"): DB.InterviewLibrary(escape_root).listing()
    original_connect = DB.sqlite3.connect
    def readonly(path, **kwargs): return original_connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, **kwargs)
    monkeypatch.setattr(DB.sqlite3, "connect", readonly)
    with pytest.raises(P.PresetError): library.update(item["preset_id"], 1, "不能写")
    monkeypatch.setattr(DB.sqlite3, "connect", original_connect)
    assert library.get(item["preset_id"])["name"] == "安全"
    data = library.path.read_bytes(); library.path.write_bytes(b"corrupt DB")
    with pytest.raises(P.PresetError): library.listing()
    assert library.path.read_bytes() == b"corrupt DB"
    library.path.write_bytes(data)


def test_library_rejects_dangling_sidecar_link_before_resolving_target(tmp_path):
    library = DB.InterviewLibrary(tmp_path); library.listing()
    target = tmp_path / "missing-sidecar-target"; target.mkdir()
    sidecar = library.directory / "presets.sqlite3-wal"
    if sys.platform == "win32":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(sidecar), str(target)], capture_output=True)
        assert result.returncode == 0
    else: sidecar.symlink_to(target, target_is_directory=True)
    target.rmdir()
    with pytest.raises(P.PresetError, match="reparse"):
        library.listing()


def test_import_failure_is_atomic_and_unknown_id_cannot_overwrite(tmp_path):
    library = DB.InterviewLibrary(tmp_path); a = library.create("原条目", template())
    package = {"schema_version": "zv-h3-interview-library-v1", "presets": [{"name": "合法", "template": template()}, {"name": "非法", "template": {}}]}
    with pytest.raises(P.PresetError): library.import_collection(package)
    assert len(library.listing()["presets"]) == 1
    package["presets"] = [{"name": "原条目", "template": template(), "preset_id": a["preset_id"]}]
    with pytest.raises(P.PresetError): library.import_collection(package)
    assert library.get(a["preset_id"])["preset_version"] == 1


def process_create(root, index):
    library = DB.InterviewLibrary(root)
    library.create(f"进程{index}", template())


def test_multiprocess_creates_do_not_lose_entries(tmp_path):
    DB.InterviewLibrary(tmp_path).listing()
    code = "import runpy,sys; h=runpy.run_path(sys.argv[1]);h['process_create'](sys.argv[2],int(sys.argv[3]))"
    processes = [subprocess.Popen([sys.executable, "-c", code, str(Path(__file__)), str(tmp_path), str(index)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for index in range(4)]
    for process in processes:
        output, error = process.communicate(timeout=20)
        assert process.returncode == 0, error.decode("utf-8", errors="replace")
    assert len(DB.InterviewLibrary(tmp_path).listing()["presets"]) == 4


def test_fresh_form_defaults_to_materials_and_explicit_exclusion_keeps_zero():
    project = fresh(1, 1, 1)
    empty = I.empty_interview()
    candidate = I.compile_interview(empty, project)
    assert len(candidate["call_references"]) == 3
    with pytest.raises(RuntimeError, match="检测"):
        N.ZVH3InterviewFormV2().build(project, json.dumps(empty), prompt=H["H"]["fixed_hub_prompt"](), unique_id="172")
    empty["bindings"] = {
        row["item_id"]: {"item_id": row["item_id"], "participates": False, "banks": [R.DEFAULT_BANK[row["kind"]]]}
        for row in I.media_inventory(project)
    }
    empty["alignment"] = I.compile_interview(empty, project)["alignment_context"]
    empty["reference_detection"] = H["H"]["detection"]()
    compiled = I.compile_interview(empty, project)
    assert compiled["call_references"] == [] and compiled["validation"]["effective_mode"] == "T2VA"
    assert all(not binding["participates"] for binding in compiled["state"]["bindings"].values())
    assert I.compile_interview(compiled["state"], project)["state"] == compiled["state"]


def test_pending_slot_and_absent_soundtrack_semantics_survive_workflow_reload():
    old = fresh(0, 1, 0, paired=True)
    state = confirmed(old); state["media_roles"]["va1"] = ["voice_reference"]; state["media_purposes"]["va1"] = "原声声线保持"
    preset = P.capture_template(state, old)
    loaded = P.apply_template(preset, I.empty_interview(), fresh(0, 0, 0))
    assert loaded["state"]["preset_pending"] and loaded["validation"]["ready"]
    restored = json.loads(I.dumps(loaded["state"]))
    silent = fresh(0, 1, 0, prefix="later_")
    result = I.compile_interview(restored, silent)
    assert result["state"]["preset_pending"][0]["item_id"] == "later_v1"
    voiced = fresh(0, 1, 0, paired=True, prefix="later_")
    completed = I.compile_interview(result["state"], voiced)
    assert not completed["state"]["preset_pending"]
    assert completed["state"]["media_purposes"]["later_va1"] == "原声声线保持"
    assert completed["state"]["media_roles"]["later_va1"] == ["voice_reference"]


def pending_voice_setup(extra_paired=True):
    old = fresh(0, 1, 0, paired=True)
    state = confirmed(old, intent="<Video 1> 与 <Audio 1> 同源")
    state["media_purposes"]["v1"] = "<Video 1> 保留画面"
    state["media_purposes"]["va1"] = "use <Audio 1> own voice with <Video 1>"
    preset = P.capture_template(state, old)
    loaded = P.apply_template(preset, I.empty_interview(), fresh(0, 1, 0, prefix="x_"))["state"]
    reordered = fresh(0, 2, 0, paired=True, prefix="x_")
    reordered["video_track"][0]["timeline_in_seconds"] = 1
    first = reordered["video_track"][0]
    first["source_audio_enabled"] = False; first["audio_link_id"] = None
    reordered["audio_track"] = [row for row in reordered["audio_track"] if row["clip_id"] != "x_va1"]
    if not extra_paired:
        reordered["video_track"][1]["source_audio_enabled"] = False; reordered["video_track"][1]["audio_link_id"] = None
        reordered["audio_track"] = []
    return loaded, C.normalize_project(reordered)


def assert_voice_source(result, video_id, pair_id, audio_label, video_label):
    assert result["state"]["media_purposes"][pair_id] == f"use {audio_label} own voice with {video_label}"
    entries = [result["state"]["reference_texts"][key] for key in ("intent", "purpose:" + video_id, "purpose:" + pair_id)]
    assert {definition["source"]["item_id"] for entry in entries for definition in entry["definitions"]} == {video_id}
    assert not result["state"]["preset_pending"]
    assert result["validation"]["ready"] and not result["validation"]["errors"]


def test_pending_soundtrack_reorder_then_restore_keeps_every_reference_source():
    loaded, reordered = pending_voice_setup()
    waiting = I.compile_interview(json.loads(I.dumps(loaded)), reordered)["state"]
    voiced = fresh(0, 2, 0, paired=True, prefix="x_"); voiced["video_track"][0]["timeline_in_seconds"] = 1
    voiced = C.normalize_project(voiced)
    state = H["aligned"](voiced, json.loads(I.dumps(waiting)))
    result = I.compile_interview(state, voiced)
    assert_voice_source(result, "x_v1", "x_va1", "<Audio 2>", "<Video 2>")


@pytest.mark.parametrize("extra_paired", [False, True])
def test_pending_soundtrack_export_before_restore_uses_current_video_slot(tmp_path, extra_paired):
    loaded, reordered = pending_voice_setup(extra_paired)
    # Global missing audio is actually sent, so clear only that field to save a usable template.
    loaded["intent"] = "自由叙述"; loaded["reference_texts"].pop("intent")
    state = H["aligned"](reordered, loaded)
    exported = P.capture_template(state, reordered)
    slots = {slot["slot"]: slot for slot in exported["slots"] if slot["kind"] == "video"}
    assert slots[1]["soundtrack"]["purpose"] == {"text": "", "definitions": []}
    assert slots[2]["soundtrack"]["purpose"]["text"] == "use {{h3:r1}} own voice with {{h3:r2}}"
    assert {definition["source"]["slot"] for definition in slots[2]["soundtrack"]["purpose"]["definitions"]} == {2}
    library = DB.InterviewLibrary(tmp_path); saved = library.create("待补声", exported)
    collection = library.export([saved["preset_id"]])
    assert "item_id" not in json.dumps(collection)
    imported = library.import_collection(P.strict_json(json.dumps(collection)))[0]["template"]
    new = fresh(0, 2, 0, paired=True, prefix="new_")
    result = P.apply_template(imported, I.empty_interview(), new)
    state = H["aligned"](new, result["state"])
    result = I.compile_interview(state, new)
    assert result["state"]["media_purposes"]["new_va2"] == "use <Audio 2> own voice with <Video 2>"
    assert {definition["source"]["item_id"] for definition in result["state"]["reference_texts"]["purpose:new_va2"]["definitions"]} == {"new_v2"}
    assert result["state"]["media_purposes"].get("new_va1", "") == ""


def test_pending_soundtrack_save_after_restore_and_reload_keeps_sources():
    loaded, reordered = pending_voice_setup()
    waiting = I.compile_interview(loaded, reordered)["state"]
    voiced = fresh(0, 2, 0, paired=True, prefix="x_"); voiced["video_track"][0]["timeline_in_seconds"] = 1
    voiced = C.normalize_project(voiced)
    result = I.compile_interview(H["aligned"](voiced, waiting), voiced)
    exported = P.capture_template(result["state"], voiced)
    own = next(slot for slot in exported["slots"] if slot["kind"] == "video" and slot["slot"] == 2)
    assert {definition["source"]["slot"] for definition in own["soundtrack"]["purpose"]["definitions"]} == {2}
    new = fresh(0, 2, 0, paired=True, prefix="new_")
    loaded = P.apply_template(exported, I.empty_interview(), new)
    result = I.compile_interview(H["aligned"](new, loaded["state"]), new)
    assert_voice_source(result, "new_v2", "new_va2", "<Audio 2>", "<Video 2>")


def test_pending_cross_references_bind_when_available_then_survive_second_reorder():
    old = fresh(2, 1, 1, paired=True)
    state = confirmed(old, intent="<Picture 2> <Video 1> <Audio 1> <Audio 2>")
    state["media_purposes"]["va1"] = "<Picture 2> <Video 1> <Audio 1> <Audio 2>"
    preset = P.capture_template(state, old)
    silent = fresh(1, 1, 1, prefix="x_")
    result = P.apply_template(preset, I.empty_interview(), silent)
    pending = result["state"]["preset_pending"][-1]
    assert pending["reference_texts"]["soundtrack"]["definitions"][0]["source"]["item_id"] is None
    assert "<H3待绑定:r1>" in result["state"]["intent"] and not result["validation"]["ready"]
    complete = fresh(2, 1, 1, prefix="x_")
    state = I.compile_interview(result["state"], complete)["state"]
    pair_waiting = next(row for row in state["preset_pending"] if row["soundtrack_only"])
    assert pair_waiting["reference_texts"]["soundtrack"]["definitions"][0]["source"]["item_id"] == "x_p2"
    voiced = fresh(2, 2, 1, paired=True, prefix="x_")
    voiced["picture_track"][0]["order"] = 9; voiced["video_track"][0]["timeline_in_seconds"] = 1
    voiced = C.normalize_project(voiced)
    result = I.compile_interview(H["aligned"](voiced, json.loads(I.dumps(state))), voiced)
    for key in ("intent", "purpose:x_va1"):
        assert [definition["source"]["item_id"] for definition in result["state"]["reference_texts"][key]["definitions"]] == ["x_p2", "x_v1", "x_v1", "x_a1"]
        text = result["state"]["intent"] if key == "intent" else result["state"]["media_purposes"]["x_va1"]
        assert text == "<Picture 1> <Video 2> <Audio 2> <Audio 3>"
    assert result["validation"]["ready"]


def test_pending_bound_source_removed_does_not_switch_to_other_legal_slot():
    loaded, reordered = pending_voice_setup()
    reordered["video_track"] = [row for row in reordered["video_track"] if row["clip_id"] != "x_v1"]
    result = I.compile_interview(loaded, C.normalize_project(reordered))
    pending = result["state"]["preset_pending"][0]
    assert pending["item_id"] == "x_v1"
    assert {definition["source"]["item_id"] for definition in pending["reference_texts"]["soundtrack"]["definitions"]} == {"x_v1"}
    assert "<H3待绑定:" in result["state"]["intent"] and not result["validation"]["ready"]
    assert result["state"]["media_purposes"].get("x_va2", "") == ""
    state = result["state"]; state["intent"] = "自由叙述"; state["reference_texts"].pop("intent")
    with pytest.raises(P.PresetError): P.capture_template(H["aligned"](C.normalize_project(reordered), state), C.normalize_project(reordered))


@pytest.mark.parametrize("case", ["missing_runtime", "extra_runtime", "wrong_source", "wrong_id", "wrong_text"])
def test_pending_runtime_reference_contract_rejects_invalid_state(case):
    state, _ = pending_voice_setup(); pending = state["preset_pending"][0]
    if case == "missing_runtime": pending.pop("reference_texts")
    if case == "extra_runtime": pending["reference_texts"]["unknown"] = pending["reference_texts"]["purpose"]
    entry = pending.get("reference_texts", {}).get("soundtrack")
    if case == "wrong_source": entry["definitions"][0]["source"]["slot"] = 2
    if case == "wrong_id": entry["definitions"][0]["source"]["item_id"] = "../../escape"
    if case == "wrong_text": entry["text"] += " changed"
    with pytest.raises(I.InterviewError): I.normalize_interview(state)


def test_extra_purpose_live_bindings_are_kept_when_loading_fewer_slots():
    project = fresh(2)
    current = confirmed(project); current["media_purposes"]["p2"] = "保留 <Picture 2>"
    current = I.compile_interview(current, project)["state"]
    preset = P.capture_template(I.empty_interview(), fresh(1))
    loaded = P.apply_template(preset, current, project)
    assert loaded["state"]["reference_texts"]["purpose:p2"]["definitions"][0]["source"]["item_id"] == "p2"
    project["picture_track"][0]["order"] = 9
    again = I.compile_interview(loaded["state"], C.normalize_project(project))
    assert again["state"]["media_purposes"]["p2"] == "保留 <Picture 1>"


def test_failed_user_reference_edit_is_never_replaced_by_old_rendered_text():
    project = fresh(); state = I.compile_interview(confirmed(project, intent="<Picture 1> 的人物"), project)["state"]
    state["intent"] = "用户新编辑 <Picture 9> 不得覆盖"
    result = I.compile_interview(state, project)
    assert result["state"]["intent"] == state["intent"] and not result["validation"]["ready"]
    again = I.compile_interview(json.loads(I.dumps(result["state"])), project)
    assert again["state"]["intent"] == state["intent"]


def process_update(root, identifier):
    library = DB.InterviewLibrary(root)
    try:
        library.update(identifier, 1, "并发改名")
        print("updated")
    except P.PresetError as error: print(error.status)


def test_multiprocess_updates_use_cas_not_last_writer_wins(tmp_path):
    library = DB.InterviewLibrary(tmp_path); item = library.create("初始", template())
    code = "import runpy,sys;h=runpy.run_path(sys.argv[1]);h['process_update'](sys.argv[2],sys.argv[3])"
    processes = [subprocess.Popen([sys.executable, "-c", code, str(Path(__file__)), str(tmp_path), item["preset_id"]], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
    results = []
    for process in processes:
        output, error = process.communicate(timeout=20)
        assert process.returncode == 0, error
        results.append(output.decode().strip())
    assert results.count("updated") == 1 and results.count("409") == 2
    assert library.get(item["preset_id"])["preset_version"] == 2


def test_registered_http_crud_user_isolation_and_planning_no_media_decode(tmp_path, monkeypatch):
    import asyncio
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    media = runpy.run_path(str(Path(__file__).with_name("media_outlet_smoke.py")))
    store, project = media["imported_project"](tmp_path / "media")
    project["processing_preset"] = H["P"].builtin("builtin.minimax-h3.single")
    project["processing_window"] = {"start_seconds": 0, "end_seconds": 5, "fps": 24}
    for row in project["video_track"] + project["audio_track"]: row["source_out_seconds"] = row["source_in_seconds"] + 2
    project = C.normalize_project(project)
    alice, bob = tmp_path / "alice", tmp_path / "bob"; alice.mkdir(); bob.mkdir()
    server = types.ModuleType("server")
    def user_path(request, file, create_dir=False):
        assert file is None and create_dir is False
        return {"alice":alice,"bob":bob}[request.headers.get("X-Test-User", "alice")]
    server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(user_manager=types.SimpleNamespace(get_request_user_filepath=user_path)))
    monkeypatch.setitem(sys.modules, "server", server)
    monkeypatch.setattr(HTTP, "get_interview_library", DB.get_interview_library)
    monkeypatch.setattr(HTTP, "get_store", lambda: store)
    def no_worker(*args): raise AssertionError("Preset routes may not probe/decode")
    monkeypatch.setattr(store, "worker", no_worker)
    async def run():
        routes = web.RouteTableDef(); HTTP.register_preset_routes(routes); app = web.Application(); app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            payload = {"name": "中性演示", "state": I.empty_interview(), "media_project": project}
            response = await client.post(HTTP.PREFIX, json=payload); assert response.status == 201; saved = await response.json(); identifier = saved["preset_id"]
            response = await client.get(HTTP.PREFIX); assert response.status == 200 and len((await response.json())["presets"]) == 1
            response = await client.get(HTTP.PREFIX + "/" + identifier, headers={"X-Test-User": "bob"}); assert response.status == 404
            response = await client.get(HTTP.PREFIX, headers={"X-Test-User": "bob"}); assert response.status == 200 and (await response.json())["presets"] == []
            response = await client.patch(HTTP.PREFIX + "/" + identifier, json={"name": "新名称", "preset_version": 1}); assert response.status == 200
            response = await client.delete(HTTP.PREFIX + "/" + identifier, json={"preset_version": 1}); assert response.status == 409
            response = await client.post(HTTP.PREFIX + "/" + identifier + "/apply", json={"state": I.empty_interview(), "media_project": project}); assert response.status == 200
            response = await client.post(HTTP.PREFIX + "/export", json={"preset_ids": [identifier]}); package = await response.json(); assert response.status == 200
            response = await client.post(HTTP.PREFIX + "/import", json=package); assert response.status == 201
            response = await client.post(HTTP.PREFIX, data='{"name":"x","name":"y"}'); assert response.status == 400
            response = await client.delete(HTTP.PREFIX + "/" + identifier, json={"preset_version": 2}, headers={"Origin": "https://untrusted.example"}); assert response.status == 403
            response = await client.delete(HTTP.PREFIX + "/" + identifier, json={"preset_version": 2}); assert response.status == 200
    asyncio.run(run())


@pytest.mark.parametrize("text", ["Picture 99、Audio 99、Video 99", "图一，数字1，0:02秒", "<picture 99>、<Picture 1 >、< Picture 1>"])
def test_only_full_exact_explicit_labels_are_bound_or_hard_checked(text):
    project = fresh(0); state = I.empty_interview() | {"intent": text}
    assert I.compile_interview(state, project)["validation"]["ready"]
    preset = P.capture_template(state, project)
    assert preset["fields"]["intent"] == {"text": text, "definitions": []}


def test_sql_failure_after_first_import_insert_rolls_back_all(tmp_path):
    library = DB.InterviewLibrary(tmp_path); library.create("原条目", template())
    with sqlite3.connect(library.path) as db:
        db.execute("CREATE TRIGGER failure BEFORE INSERT ON presets WHEN NEW.name='第二条' BEGIN SELECT RAISE(ABORT,'test transaction failure'); END")
    package = {"schema_version":"zv-h3-interview-library-v1","presets":[{"name":"第一条","template":template()},{"name":"第二条","template":template()}]}
    with pytest.raises(P.PresetError): library.import_collection(package)
    assert [item["name"] for item in library.listing()["presets"]] == ["原条目"]


def test_more_than_old_128_entries_and_metadata_pagination_are_supported(tmp_path):
    library = DB.InterviewLibrary(tmp_path)
    package = {"schema_version":"zv-h3-interview-library-v1","presets":[{"name":f"预设{index}","template":template()} for index in range(129)]}
    library.import_collection(package)
    first=library.listing(limit=100);second=library.listing(cursor=first["next_cursor"],limit=100)
    assert len(first["presets"])==100 and len(second["presets"])==29 and second["next_cursor"] is None
    assert all("template" not in item for item in first["presets"])


@pytest.mark.parametrize("case", ["directory_junction", "database_hardlink", "empty_library", "damaged_template"])
def test_library_path_and_damaged_entries_are_refused_without_rebuild(tmp_path, case):
    library = DB.InterviewLibrary(tmp_path); item=library.create("原条目",template())
    if case == "directory_junction":
        separate=tmp_path.parent/(tmp_path.name+'-outside');separate.mkdir()
        junction=tmp_path/'junction'
        if sys.platform=='win32':
            result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(separate)],capture_output=True);assert result.returncode==0
        else:junction.symlink_to(separate,target_is_directory=True)
        library.directory=junction;library.path=junction/'presets.sqlite3'
    elif case == "database_hardlink":
        other=tmp_path/'hardlink.sqlite3';other.hardlink_to(library.path)
    elif case == "empty_library": library.path.write_bytes(b'')
    else:
        with sqlite3.connect(library.path) as db:db.execute('UPDATE presets SET template=? WHERE preset_id=?',('{"invalid":true}',item['preset_id']))
    before=library.path.read_bytes() if library.path.exists() else None
    with pytest.raises(P.PresetError):library.get(item['preset_id'])
    assert (library.path.read_bytes() if library.path.exists() else None)==before


def test_pending_expansion_keeps_long_user_text_and_state_can_be_reloaded():
    project=fresh(0,1,1,paired=True);state=confirmed(project,intent='x'*11989+'<Audio 1>')
    preset=P.capture_template(state,project)
    project['video_track'][0]['source_audio_enabled']=False;project=C.normalize_project(project)
    result=P.apply_template(preset,I.empty_interview(),project)
    assert result['state']['intent'].startswith('x'*11989) and '<H3待绑定:' in result['state']['intent']
    assert I.compile_interview(json.loads(I.dumps(result['state'])),project)['state']['intent']==result['state']['intent']


def test_runtime_state_resource_limit_is_checked_even_for_object_requests():
    state=I.empty_interview();state['media_purposes']={f'p{index}':'x'*12000 for index in range(30)}
    with pytest.raises(I.InterviewError) as error:I.normalize_interview(state)
    assert error.value.issues[0]['code']=='json_size'


def test_export_aggregate_size_limit_rejects_oversized_batch_without_mutation(tmp_path):
    library=DB.InterviewLibrary(tmp_path);large=template();
    for field in large['fields'].values():field['text']='x'*12000
    saved=[library.create(f'模板{index}',large) for index in range(16)]
    with pytest.raises(P.PresetError,match='2 MiB'):library.export([item['preset_id'] for item in saved])
    assert len(library.listing()['presets'])==16


@pytest.mark.parametrize('case',['oversized_token','duplicate_pending','wrong_pending_kind','invalid_roles','float_slot','foreign_id','stale_delete'])
def test_remaining_contract_and_cas_edges_are_explicit(tmp_path,case):
    if case=='stale_delete':
        library=DB.InterviewLibrary(tmp_path);item=library.create('旧版本',template());library.update(item['preset_id'],1,'新版本')
        with pytest.raises(P.PresetError) as error:library.delete(item['preset_id'],1)
        assert error.value.status==409 and library.get(item['preset_id'])['name']=='新版本'
        return
    project=fresh();preset=P.capture_template(confirmed(project,intent='<Picture 1>'),project)
    if case=='oversized_token':preset['fields']['intent']['definitions'][0]['token']='r'+'9'*100
    if case=='invalid_roles':preset['slots'][0]['roles']=[{'unknown':True}]
    if case=='float_slot':preset['slots'][0]['slot']=1.5
    if case=='foreign_id':preset['slots'][0]['asset_id']='old'
    if case in {'duplicate_pending','wrong_pending_kind'}:
        state=I.empty_interview();pending={'slot':preset['slots'][0],'item_id':'p1','soundtrack_only':case=='wrong_pending_kind'};state['preset_pending']=[pending,pending] if case=='duplicate_pending' else [pending]
        with pytest.raises(I.InterviewError):I.normalize_interview(state)
    else:
        with pytest.raises(P.PresetError):P.validate_template(preset)


@pytest.mark.parametrize('first',['get','export','delete','business_failure'])
def test_first_missing_id_or_business_failure_does_not_poison_new_library(tmp_path,monkeypatch,first):
    library=DB.InterviewLibrary(tmp_path);identifier='h3.'+'a'*32
    with pytest.raises(P.PresetError):
        if first=='get':library.get(identifier)
        elif first=='export':library.export([identifier])
        elif first=='delete':library.delete(identifier,1)
        else:
            def fail(*args):raise P.PresetError('test_failure','首次业务失败')
            with monkeypatch.context() as patch:patch.setattr(library,'insert',fail);library.create('首次保存',template())
    assert library.listing()['presets']==[]
    assert library.create('之后可用',template())['preset_version']==1


@pytest.mark.parametrize('paired',[False,True])
def test_confirmed_then_inactive_purpose_binding_can_save_export_load_and_reenable(tmp_path,paired):
    project=fresh(2) if not paired else fresh(0,1,1,paired=True)
    owner='p2' if not paired else 'va1';label='<Picture 2>' if not paired else '<Audio 1>'
    state=confirmed(project);state['media_purposes'][owner]='保留 '+label
    state=I.compile_interview(state,project)['state']
    if paired:project['video_track'][0]['source_audio_enabled']=False;project=C.normalize_project(project)
    else:state['bindings']['p2']['participates']=False
    state=H['aligned'](project,state);result=I.compile_interview(state,project)
    assert result['validation']['ready'] and any(row['code']=='unused_purpose' for row in result['validation']['warnings'])
    portable=P.capture_template(result['state'],project);library=DB.InterviewLibrary(tmp_path);entry=library.create('停用用途',portable)
    exported=library.export([entry['preset_id']]);imported=library.import_collection(exported)[0]['template']
    new=fresh(2,prefix='new_') if not paired else fresh(0,1,1,paired=True,prefix='new_')
    if paired:new['video_track'][0]['source_audio_enabled']=False;new=C.normalize_project(new)
    loaded=P.apply_template(imported,I.empty_interview(),new)
    assert loaded['validation']['ready'] and '<H3待绑定:' in loaded['state']['media_purposes']['new_'+owner]
    if paired:new['video_track'][0]['source_audio_enabled']=True;new=C.normalize_project(new)
    else:loaded['state']['bindings']['new_p2']['participates']=True
    active=I.compile_interview(loaded['state'],new)
    assert active['state']['media_purposes']['new_'+owner]=='保留 '+label


def process_update_or_delete(root,identifier,operation):
    library=DB.InterviewLibrary(root)
    try:
        if operation=='delete':library.delete(identifier,1)
        else:library.update(identifier,1,'并发更新')
        print(operation)
    except P.PresetError as error:print(error.status)


def test_concurrent_update_and_delete_cas_preserves_unrelated_entries(tmp_path):
    library=DB.InterviewLibrary(tmp_path);target=library.create('目标',template());other=library.create('其它条目',template())
    code="import runpy,sys;h=runpy.run_path(sys.argv[1]);h['process_update_or_delete'](sys.argv[2],sys.argv[3],sys.argv[4])"
    processes=[subprocess.Popen([sys.executable,'-c',code,str(Path(__file__)),str(tmp_path),target['preset_id'],operation],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for operation in ['update','delete']]
    outcomes=[]
    for process in processes:
        output,error=process.communicate(timeout=20);assert process.returncode==0,error;outcomes.append(output.decode().strip())
    assert sum(value in {'update','delete'} for value in outcomes)==1
    assert any(value in {'409','404'} for value in outcomes)
    assert library.get(other['preset_id'])['name']=='其它条目'
