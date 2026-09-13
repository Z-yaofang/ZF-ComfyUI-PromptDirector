import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "zf_h3_reference_outlet_tests"
root_package = types.ModuleType(PACKAGE)
root_package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, root_package)

I = importlib.import_module(PACKAGE + ".h3_focus.interview")
P = importlib.import_module(PACKAGE + ".h3_focus.reference_plan")
N = importlib.import_module(PACKAGE + ".h3_focus.outlet_node")
C = importlib.import_module(PACKAGE + ".media_evidence.contract")
PRESETS = importlib.import_module(PACKAGE + ".media_evidence.presets")
OUTLET = importlib.import_module(PACKAGE + ".media_evidence.outlet")
DECODE = importlib.import_module(PACKAGE + ".media_evidence.outlet_decode")
RUNTIME = importlib.import_module(PACKAGE + ".media_evidence.runtime")


def asset(identifier, kind):
    suffix = {"picture": "png", "video": "mp4", "audio": "wav"}[kind]
    return {
        "asset_id": identifier,
        "name": f"{identifier}.{suffix}",
        "source_handle": "originals/" + (identifier[-1] * 32) + "." + suffix,
        "kind": kind,
        "probe": {
            "size_bytes": 100,
            "duration_seconds": None if kind == "picture" else 20,
            "width": None if kind == "audio" else 720,
            "height": None if kind == "audio" else 1280,
            "fps": 30 if kind == "video" else None,
            "frame_count": 600 if kind == "video" else None,
            "frame_count_exact": kind == "video",
            "vfr": False if kind == "video" else None,
            "has_audio": kind != "picture",
            "sample_rate": 48000 if kind != "picture" else None,
            "channels": 2 if kind != "picture" else None,
            "codec": "fixture",
        },
    }


def complete_local_socket_project():
    value = C.empty_project()
    value["processing_preset"] = PRESETS.builtin("builtin.minimax-h3.single")
    value["processing_window"] = {"start_seconds": 0, "end_seconds": 6, "fps": 24}
    value["output_canvas"] = {"width": 640, "height": 1152}
    for index in range(1, 12):
        item = asset(f"picture{index}", "picture")
        value["assets"].append(item)
        value["picture_track"].append({"item_id": f"p{index}", "asset_id": item["asset_id"], "order": index})
    for index in range(1, 4):
        item = asset(f"video{index}", "video")
        value["assets"].append(item)
        value["video_track"].append({
            "clip_id": f"v{index}", "asset_id": item["asset_id"],
            "timeline_in_seconds": 0, "source_in_seconds": 0, "source_out_seconds": 6,
            "source_audio_enabled": True, "audio_link_id": f"va{index}",
        })
        value["audio_track"].append({
            "clip_id": f"va{index}", "asset_id": item["asset_id"],
            "timeline_in_seconds": 0, "source_in_seconds": 0, "source_out_seconds": 6,
            "origin": "video_source", "enabled": True,
            "linked_video_clip_id": f"v{index}", "source_video_clip_id": f"v{index}",
        })
    for index in range(1, 5):
        item = asset(f"audio{index}", "audio")
        value["assets"].append(item)
        value["audio_track"].append({
            "clip_id": f"a{index}", "asset_id": item["asset_id"],
            "timeline_in_seconds": 0, "source_in_seconds": 0, "source_out_seconds": 6,
            "origin": "standalone", "enabled": True,
            "linked_video_clip_id": None, "source_video_clip_id": None,
        })
    return C.normalize_project(value)


def complete_state():
    state = I.empty_interview()
    roles = {"p1": ["first_frame"], "p2": ["last_frame"]}
    roles.update({f"p{index}": ["style_reference"] for index in range(3, 12)})
    roles.update({f"v{index}": ["motion_reference"] for index in range(1, 4)})
    roles["a1"] = ["speech_lipsync"]
    roles.update({f"a{index}": ["voice_reference"] for index in range(2, 5)})
    bindings = {f"p{i}": {"item_id": f"p{i}", "participates": True, "banks": ["first_frame" if i == 1 else "last_frame" if i == 2 else "ref_images"]} for i in range(1, 12)}
    bindings.update({f"v{i}": {"item_id": f"v{i}", "participates": True, "banks": ["ref_videos"]} for i in range(1, 4)})
    bindings.update({f"a{i}": {"item_id": f"a{i}", "participates": True, "banks": ["drive_audio" if i == 1 else "ref_audios"]} for i in range(1, 5)})
    state.update(intent="本地固定插槽结构测试，组合不符合官方源数量与总时长限制。", media_roles=roles, bindings=bindings)
    return state


def test_local_socket_structure_is_preserved_but_oversized_combination_is_not_ready():
    project = complete_local_socket_project()
    compiled = I.compile_interview(complete_state(), project)
    assert not compiled["validation"]["ready"]
    assert {"mixed_sources", "reference_total_seconds"} <= {row["code"] for row in compiled["validation"]["errors"]}
    plan = P.build_reference_plan(project, compiled)
    routes = plan["routes"]
    assert routes["first_frame"] == "p1" and routes["last_frame"] == "p2"
    assert routes["ref_images"] == [f"p{index}" for index in range(3, 12)]
    assert routes["ref_videos"] == ["v1", "v2", "v3"]
    assert routes["ref_video_audios"] == ["v1", "v2", "v3"]
    assert routes["drive_audio"] == "a1"
    assert routes["ref_audios"] == ["a2", "a3", "a4"]
    assert plan["limits"] == {
        "ref_images": 9, "ref_videos": 3, "ref_video_audios": 3,
        "ref_audios": 3, "drive_audios": 1,
    }
    assert plan["selection_preset"] == {"pictures": 6, "videos": 3, "audios": 3}
    audio_calls = [row for row in compiled["call_references"] if row["kind"] == "audio"]
    assert [row["origin"] for row in audio_calls] == [
        "video_soundtrack", "video_soundtrack", "video_soundtrack",
        "drive_audio", "standalone", "standalone", "standalone",
    ]


def test_reference_image_ten_exceeds_official_ref_image_bank_not_anchor_bank():
    project = complete_local_socket_project()
    state = complete_state()
    state["bindings"]["p2"]["banks"] = ["last_frame", "ref_images"]
    compiled = I.compile_interview(state, project)
    errors = compiled["validation"]["errors"]
    assert any(row["code"] == "media_limit" and "ref_images" in row["message"] for row in errors)


def test_node_contract_matches_official_fixed_socket_order():
    assert N.ZVH3ReferenceOutlet.INPUT_TYPES()["required"] == {
        "reference_plan": ("ZV_H3_REFERENCE_PLAN",)
    }
    assert N.ZVH3ReferenceOutlet.RETURN_NAMES == (
        "first_frame", "last_frame",
        *(f"ref_image_{index}" for index in range(1, 10)),
        *(f"ref_video_{index}" for index in range(1, 4)),
        *(f"ref_video_audio_{index}" for index in range(1, 4)),
        "drive_audio", "final_audio",
        *(f"ref_audio_{index}" for index in range(1, 4)),
        "reference_plan_json", "report",
    )
    assert len(N.ZVH3ReferenceOutlet.RETURN_TYPES) == len(N.ZVH3ReferenceOutlet.RETURN_NAMES) == 24


def test_backend_decodes_each_stable_binding_once_and_leaves_unused_slots_empty(monkeypatch):
    project = {"output_canvas": {"width": 640, "height": 1152}, "validation": {"errors": []}}
    plan = P.empty_reference_plan()
    plan.update(ready=True, media_project=project, reference_selection="legacy_window_intersection")
    plan["routes"].update({
        "first_frame": "p1", "ref_images": ["p1", "p2"],
        "ref_videos": ["v1"], "ref_video_audios": ["v1"],
        "drive_audio": "a1", "ref_audios": ["a2"],
    })

    class Store:
        def canonical(self, value):
            return value

    calls = []

    def build(_project, kind, binding, target_width=None, target_height=None):
        calls.append((kind, binding, target_width, target_height))
        return {"kind": kind, "binding": binding}

    def execute(_store, outlet_plan):
        kind, binding = outlet_plan["kind"], outlet_plan["binding"]
        manifest, report = {"kind": kind, "binding": binding}, f"{kind}:{binding}"
        if kind == "video":
            return f"video:{binding}", f"soundtrack:{binding}", manifest, report
        return f"{kind}:{binding}", None, manifest, report

    monkeypatch.setattr(RUNTIME, "get_store", lambda: Store())
    monkeypatch.setattr(OUTLET, "require_valid_project", lambda _project: None)
    monkeypatch.setattr(OUTLET, "build_outlet_plan", build)
    monkeypatch.setattr(DECODE, "execute_outlet", execute)

    output = N.ZVH3ReferenceOutlet().export_references(plan)
    assert len(output) == 24
    assert output[0] == "picture:p1" and output[1] is None
    assert output[2:5] == ("picture:p1", "picture:p2", None)
    assert output[11:14] == ("video:v1", None, None)
    assert output[14:17] == ("soundtrack:v1", None, None)
    assert output[17:19] == ("audio:a1", "audio:a1")
    assert output[19:22] == ("audio:a2", None, None)
    assert calls.count(("picture", "p1", None, None)) == 1
    assert ("video", "v1", None, None) in calls


def test_unready_plan_fails_before_accessing_media_store(monkeypatch):
    monkeypatch.setattr(RUNTIME, "get_store", lambda: (_ for _ in ()).throw(AssertionError("store accessed")))
    plan = P.empty_reference_plan(errors=[{"message": "请选择素材用途"}])
    try:
        N.ZVH3ReferenceOutlet().export_references(plan)
        raise AssertionError("unready plan accepted")
    except P.ReferencePlanError as exc:
        assert "请选择素材用途" in str(exc)


def test_unready_recipe_or_window_error_does_not_mislead_user_to_redetect(monkeypatch):
    monkeypatch.setattr(RUNTIME, "get_store", lambda: (_ for _ in ()).throw(AssertionError("store accessed")))
    plan = P.empty_reference_plan(errors=[{
        "path": "/media_roles/v1",
        "code": "reference_video_frames",
        "message": "Video 1 与处理窗口的有效交集只有 30 帧",
    }])
    try:
        N.ZVH3ReferenceOutlet().export_references(plan)
        raise AssertionError("unready plan accepted")
    except P.ReferencePlanError as exc:
        message = str(exc)
        assert "修正上述机械错误" in message
        assert "语义用途可留空" in message


def test_plan_rejects_duplicate_same_numbered_video_soundtrack():
    plan = P.empty_reference_plan()
    plan.update(ready=True, media_project={})
    plan["routes"].update({
        "ref_videos": ["v1", "v2"],
        "ref_video_audios": ["v1", "v1"],
    })
    try:
        P.normalize_reference_plan(plan)
        raise AssertionError("duplicate soundtrack route was accepted")
    except P.ReferencePlanError as exc:
        assert "不能重复" in str(exc)


def test_fixed_hub_rejects_combined_video_memory_before_any_decode(monkeypatch):
    project = {"output_canvas": None, "validation": {"errors": []}}
    plan = P.empty_reference_plan()
    plan.update(ready=True, media_project=project, reference_selection="legacy_window_intersection")
    plan["routes"]["ref_videos"] = ["v1", "v2", "v3"]

    class Store:
        def canonical(self, value):
            return value

    def build(_project, kind, binding, target_width=None, target_height=None):
        assert kind == "video"
        return {
            "kind": kind,
            "binding": binding,
            "items": [{
                "kind": "video",
                "output_width": 1080,
                "output_height": 1920,
                "frame_count": 360,
                "sample_count": None,
            }],
            "original_audio": None,
        }

    monkeypatch.setattr(RUNTIME, "get_store", lambda: Store())
    monkeypatch.setattr(OUTLET, "require_valid_project", lambda _project: None)
    monkeypatch.setattr(OUTLET, "build_outlet_plan", build)
    monkeypatch.setattr(
        DECODE,
        "execute_outlet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("decode started")),
    )

    try:
        N.ZVH3ReferenceOutlet().export_references(plan)
        raise AssertionError("combined memory limit was not enforced")
    except P.ReferencePlanError as exc:
        assert "合计超过 12 GiB" in str(exc)
