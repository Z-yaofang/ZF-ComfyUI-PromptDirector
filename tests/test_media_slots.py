import copy
import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("zf_slot_fixtures", ROOT / "tests/media_outlet_smoke.py")
SMOKE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = SMOKE
spec.loader.exec_module(SMOKE)
C = SMOKE.C
SLOTS = importlib.import_module(SMOKE.SPEC.name + ".slot_nodes")
OLD = importlib.import_module(SMOKE.SPEC.name + ".outlet_nodes")
RUNTIME = importlib.import_module(SMOKE.SPEC.name + ".runtime")


def add_slots(project):
    p = copy.deepcopy(project)
    p["outlet_slots"] = {"version": 1, "items": [
        dict(slot_id="picture-port", kind="picture", ordinal=7, binding_id="red"),
        dict(slot_id="video-port", kind="video", ordinal=2, binding_id="voiced"),
        dict(slot_id="audio-port", kind="audio", ordinal=3, binding_id="independent"),
    ]}
    return p


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    directory = tmp_path_factory.mktemp("slot-outlets")
    store, project = SMOKE.imported_project(directory)
    return directory, store, add_slots(project)


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_projects_normalize_without_forced_slots(version):
    p = C.empty_project()
    p.pop("outlet_slots")
    p["schema_version"] = version
    result = C.normalize_project(p)
    assert result["schema_version"] == 2 and "outlet_slots" not in result


@pytest.mark.parametrize("damage", ["version", "bool_version", "unknown", "slot_unknown", "duplicate_id", "duplicate_ordinal", "kind", "empty_id", "path_id", "ordinal_bool", "ordinal_zero", "empty_binding", "binding_array", "limit"])
def test_slot_schema_strictly_rejects_invalid_snapshots(damage):
    p = add_slots(C.empty_project())
    data = p["outlet_slots"]
    row = data["items"][0]
    if damage == "version": data["version"] = 2
    elif damage == "bool_version": data["version"] = True
    elif damage == "unknown": data["x"] = 1
    elif damage == "slot_unknown": row["x"] = 1
    elif damage == "duplicate_id": data["items"][1]["slot_id"] = row["slot_id"]
    elif damage == "duplicate_ordinal": data["items"].append({**row, "slot_id": "another"})
    elif damage == "kind": row["kind"] = "timeline"
    elif damage == "empty_id": row["slot_id"] = ""
    elif damage == "path_id": row["slot_id"] = "../outside"
    elif damage == "ordinal_bool": row["ordinal"] = True
    elif damage == "ordinal_zero": row["ordinal"] = 0
    elif damage == "empty_binding": row["binding_id"] = ""
    elif damage == "binding_array": row["binding_id"] = []
    elif damage == "limit": data["items"] = [row] * 257
    with pytest.raises(C.ProjectError): C.normalize_project(p)


def test_slot_identity_label_and_binding_survive_track_reorder_and_json(media):
    _, _, p = media
    before = SLOTS.resolve_slot(p, "picture-port", "picture")
    p = copy.deepcopy(p)
    p["picture_track"].reverse()
    for i, item in enumerate(p["picture_track"]): item["order"] = i + 1
    after = SLOTS.resolve_slot(json.loads(json.dumps(p)), "picture-port", "picture")
    assert before == after and after["label"] == "图片7" and after["binding_id"] == "red"


@pytest.mark.parametrize("kind,cls,old_cls,binding", [
    ("picture", SLOTS.ZVPictureSlotOutlet, OLD.ZVPictureOutlet, "red"),
    ("video", SLOTS.ZVVideoSlotOutlet, OLD.ZVVideoOutlet, "voiced"),
    ("audio", SLOTS.ZVAudioSlotOutlet, OLD.ZVAudioOutlet, "independent"),
])
def test_real_slot_outputs_match_legacy_nodes_and_add_slot_manifest(media, monkeypatch, kind, cls, old_cls, binding):
    import torch
    directory, store, p = media
    monkeypatch.setattr(RUNTIME, "_store", store)
    before = copy.deepcopy(p)
    actual = cls().export_media(p, kind + "-port")
    legacy = old_cls().export_media(p, binding)
    if kind == "audio": assert torch.equal(actual[0]["waveform"], legacy[0]["waveform"])
    else: assert torch.equal(actual[0], legacy[0])
    if kind == "video":
        assert torch.equal(actual[1]["waveform"], legacy[1]["waveform"])
        assert actual[1]["sample_rate"] == 44100
        assert actual[1]["waveform"].shape[-1] == actual[0].shape[0] / 10 * 44100
    manifest = SMOKE.assert_private_manifest(actual[-2], directory)
    assert manifest["outlet_slot"]["slot_id"] == kind + "-port"
    assert manifest["outlet_slot"]["binding_id"] == binding
    assert p == before
    assert cls.RETURN_TYPES == old_cls.RETURN_TYPES
    assert list(cls.INPUT_TYPES()["required"]) == ["media_project", "slot_id"]
    assert "slot_id" not in old_cls.INPUT_TYPES()["required"]


@pytest.mark.parametrize("damage", ["empty", "deleted", "wrong_kind", "wrong_slot", "linked_audio"])
def test_missing_slots_never_decode_or_retarget(media, monkeypatch, damage):
    _, _, p = media
    p = copy.deepcopy(p)
    cls, slot_id = SLOTS.ZVPictureSlotOutlet, "picture-port"
    if damage == "empty": p["outlet_slots"]["items"][0]["binding_id"] = None
    elif damage == "deleted": p["picture_track"] = [i for i in p["picture_track"] if i["item_id"] != "red"]
    elif damage == "wrong_kind": p["outlet_slots"]["items"][0]["binding_id"] = "voiced"
    elif damage == "wrong_slot": slot_id = "unknown"
    elif damage == "linked_audio":
        cls, slot_id = SLOTS.ZVAudioSlotOutlet, "audio-port"
        p["outlet_slots"]["items"][2]["binding_id"] = "original"
    monkeypatch.setattr(SLOTS, "_export", lambda *args: pytest.fail("Invalid slot reached media execution"))
    with pytest.raises(SLOTS.OutletError, match="未指定|不存在|关联视频"):
        cls().export_media(p, slot_id)


def test_slot_swap_keeps_interface_and_real_source_selection(media, monkeypatch):
    import torch
    _, store, p = media
    p = copy.deepcopy(p)
    monkeypatch.setattr(RUNTIME, "_store", store)
    first = SLOTS.ZVPictureSlotOutlet().export_media(p, "picture-port")[0]
    p["outlet_slots"]["items"][0]["binding_id"] = "green"
    second = SLOTS.ZVPictureSlotOutlet().export_media(p, "picture-port")[0]
    assert first.shape != second.shape or not torch.equal(first, second)
    assert p["outlet_slots"]["items"][0]["ordinal"] == 7


def test_video_slot_inherits_the_desk_output_canvas(media, monkeypatch):
    _, store, p = media
    p = copy.deepcopy(p)
    p["output_canvas"] = {"width": 64, "height": 96}
    monkeypatch.setattr(RUNTIME, "_store", store)
    frames = SLOTS.ZVVideoSlotOutlet().export_media(p, "video-port")[0]
    assert tuple(frames.shape[1:3]) == (96, 64)


def test_slot_nodes_are_registered_with_exact_new_names():
    spec = importlib.util.spec_from_file_location("zf_slot_registration", ROOT / "tests/test_prompt_layers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("ZVPictureSlotOutlet", "ZVVideoSlotOutlet", "ZVAudioSlotOutlet"):
        cls = module.MODULE.NODE_CLASS_MAPPINGS[name]
        assert cls.__name__ == name
        assert cls.INPUT_TYPES()["required"]["slot_id"][0] == "STRING"
        assert len(cls.RETURN_TYPES) in (3, 4)
