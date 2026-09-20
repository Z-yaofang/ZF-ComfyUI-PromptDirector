"""Current H3 interview mechanical boundaries, with no GPU generation."""

import copy
import hashlib
import importlib
import json
import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT / "tests/test_h3_interview.py"))
I, N, C, P, RP, D = (H[key] for key in ("I", "N", "C", "P", "RP", "D"))
R = importlib.import_module(H["PACKAGE"] + ".h3_focus.routing")
S = importlib.import_module(H["PACKAGE"] + ".h3_focus.server")
O = importlib.import_module(H["PACKAGE"] + ".h3_focus.outlet_node")
OUT = importlib.import_module(H["PACKAGE"] + ".media_evidence.outlet")
DEC = importlib.import_module(H["PACKAGE"] + ".media_evidence.outlet_decode")
RUN = importlib.import_module(H["PACKAGE"] + ".media_evidence.runtime")
WORKFLOW = ROOT / "tests/fixtures/h3_focus_interview_topology.json"
contract_registry_for_synthetic_inputs = H["contract_registry_for_synthetic_inputs"]


def source(pictures=1, videos=1, audios=1, seconds=2, soundtracks=False, target=5):
    value = C.empty_project()
    value["processing_preset"] = P.builtin("builtin.minimax-h3.single")
    value["processing_window"] = {"start_seconds": 0, "end_seconds": target, "fps": 24}
    value["output_canvas"] = {"width": 640, "height": 1152}
    for kind, count in (("picture", pictures), ("video", videos), ("audio", audios)):
        for index in range(1, count + 1):
            asset = H["asset"](f"{kind}{index}", kind)
            value["assets"].append(asset)
            item_id = f"{kind[0]}{index}"
            if kind == "picture":
                value["picture_track"].append({"item_id": item_id, "asset_id": asset["asset_id"], "order": index})
            else:
                item = {"clip_id": item_id, "asset_id": asset["asset_id"], "timeline_in_seconds": 0, "source_in_seconds": 0, "source_out_seconds": seconds}
                if kind == "video":
                    item.update(source_audio_enabled=soundtracks, audio_link_id=f"va{index}" if soundtracks else None)
                    if soundtracks:
                        value["audio_track"].append({"clip_id": f"va{index}", "asset_id": asset["asset_id"], "timeline_in_seconds": 0, "source_in_seconds": 0, "source_out_seconds": seconds, "origin": "video_source", "enabled": True, "linked_video_clip_id": item_id, "source_video_clip_id": item_id})
                else:
                    item.update(origin="standalone", enabled=True, linked_video_clip_id=None, source_video_clip_id=None)
                value[kind + "_track"].append(item)
    return C.normalize_project(value)


def aligned(project, state=None):
    result = S.plan_interview({"state": state or I.empty_interview(), "media_project": project, "align": True, "conditioning_count": 1})
    state = result["state"]
    state["reference_detection"] = result["snapshot"]
    state["alignment"] = result["alignment_context"]
    return state


def signature(result):
    return [(row["kind"], row["item_id"], row["origin"], row["call_label"]) for row in result["call_references"]]


def codes(result):
    return {row["code"] for row in result["validation"]["errors"]}


@pytest.mark.parametrize("snapshot", [False, True])
@pytest.mark.parametrize("roles", [{}, {"p1": ["first_frame", "last_frame", "style_reference", "subject_identity"], "a1": ["speech_lipsync", "audio_reuse"]}])
def test_fresh_custom_and_changed_semantics_have_identical_plan(snapshot, roles):
    project = source(soundtracks=True)
    state = aligned(project) if snapshot else I.empty_interview()
    before = I.compile_interview(state, project)
    state["media_roles"] = roles
    state["media_purposes"] = {"p1": "一项图片定义多个 <Subject 1> 与 <Subject 2>；自由编辑、转场和续写"}
    after = I.compile_interview(state, project)
    assert after["validation"]["ready"]
    assert signature(before) == signature(after)
    assert RP.planned_detection(before) == RP.planned_detection(after)
    assert N.ZVH3InterviewFormV2().build(project, I.dumps(state))[6]["routes"] == RP.build_reference_plan(project, before)["routes"]
    if snapshot:
        assert N.ZVH3InterviewFormV2().build(project, I.dumps(state), prompt=H["fixed_hub_prompt"](), unique_id="172")[6]["ready"]


def test_zero_media_pure_text_does_not_require_recipe_or_semantic_content():
    project = source(0, 0, 0)
    result = I.compile_interview(I.empty_interview(), project)
    assert result["validation"]["ready"] and result["validation"]["effective_mode"] == "T2VA"
    assert signature(result) == []
    assert N.ZVH3InterviewFormV2().build(project, I.dumps(I.empty_interview()), prompt=H["fixed_hub_prompt"](), unique_id="172")[5]


@pytest.mark.parametrize("banks,mode", [(["first_frame"], "I2VA"), (["last_frame"], "L2VA"), (["first_frame", "last_frame"], "FL2VA"), (["first_frame", "ref_images"], "Hybrid")])
def test_explicit_one_picture_banks_determine_mode(banks, mode):
    project = source(1, 0, 0)
    state = I.empty_interview(); state["bindings"]["p1"] = {"item_id": "p1", "participates": True, "banks": banks}
    result = I.compile_interview(state, project)
    assert result["validation"]["ready"] and result["validation"]["effective_mode"] == mode
    assert result["validation"]["mixed_sources"] == len(banks)
    assert result["validation"]["local_extension"] == (mode == "Hybrid")


@pytest.mark.parametrize("kind,limit", [("picture", 9), ("video", 3), ("audio", 3)])
def test_each_actual_bank_boundary_and_overflow(kind, limit):
    kwargs = {"pictures": 0, "videos": 0, "audios": 0, kind + "s": limit}
    assert I.compile_interview(I.empty_interview(), source(**kwargs))["validation"]["ready"]
    kwargs[kind + "s"] += 1
    assert "media_limit" in codes(I.compile_interview(I.empty_interview(), source(**kwargs)))


@pytest.mark.parametrize("pictures,valid", [(6, True), (7, False)])
def test_mixed_12_and_13_count_clips_not_roles_names_or_paired_channels(pictures, valid):
    project = source(pictures, 3, 3, seconds=2, soundtracks=True)
    # Deliberately same names/handles: actual distinct clip/item inputs still count.
    state = I.empty_interview(); state["media_roles"] = {"p1": ["subject_identity", "style_reference", "keyframe"]}
    result = I.compile_interview(state, project)
    assert result["validation"]["ready"] == valid
    assert result["validation"]["mixed_sources"] == pictures + 6
    assert result["validation"]["counts"]["ref_video_audios"] == 3
    assert [row["call_label"] for row in result["call_references"] if row["kind"] == "audio"] == [f"<Audio {i}>" for i in range(1, 7)]
    assert result["validation"]["local_extension"]
    assert ("mixed_sources" in codes(result)) == (not valid)


def test_seventh_audio_channel_is_explicit_local_drive_without_independent_overflow():
    project = source(1, 3, 4, seconds=2, soundtracks=True)
    state = I.empty_interview(); state["bindings"]["a1"] = {"item_id": "a1", "participates": True, "banks": ["drive_audio"]}
    result = I.compile_interview(state, project)
    assert result["validation"]["ready"] and result["validation"]["counts"]["ref_audios"] == 3
    assert [row["call_label"] for row in result["call_references"] if row["kind"] == "audio"][-1] == "<Audio 7>"
    assert result["validation"]["local_extension"]


@pytest.mark.parametrize("kind", ["video", "audio"])
@pytest.mark.parametrize("seconds,valid", [(1, False), (2, True), (15, True), (16, False)])
def test_selected_reference_segment_lengths(kind, seconds, valid):
    project = source(0, int(kind == "video"), int(kind == "audio"), seconds=seconds)
    result = I.compile_interview(I.empty_interview(), project)
    assert result["validation"]["ready"] == valid


@pytest.mark.parametrize("kind", ["video", "audio"])
@pytest.mark.parametrize("seconds,valid", [(5, True), (6, False)])
def test_reference_class_total_15_boundary_is_separate(kind, seconds, valid):
    result = I.compile_interview(I.empty_interview(), source(0, 3 if kind == "video" else 0, 3 if kind == "audio" else 0, seconds=seconds, soundtracks=kind == "video"))
    assert result["validation"]["ready"] == valid
    assert ("reference_total_seconds" in codes(result)) == (not valid)


@pytest.mark.parametrize("target,valid", [(2, False), (4, True), (15, True), (16, False)])
def test_official_output_range_is_separate_from_reference_minimum(target, valid):
    result = I.compile_interview(I.empty_interview(), source(0, 0, 0, target=target))
    assert result["validation"]["ready"] == valid
    if target == 15:
        assert result["validation"]["local_output"] == {"requested_frames": 360, "requested_seconds": 15, "model_length": 362, "predicted_final_frames": 362, "actual_final_frames": None}


def test_model_visible_reference_clipping_and_48_to_39_are_reported_not_rejected():
    for seconds, exported, visible in [(2, 48, 39), (15, 360, 124)]:
        result = I.compile_interview(I.empty_interview(), source(0, 1, 0, seconds=seconds, target=5))
        assert result["validation"]["ready"]
        row = result["validation"]["model_visible_references"][0]
        assert (row["export_frames"], row["model_frames"]) == (exported, visible)
        assert f"{visible} 帧" in result["human_report"] and "实际 length 未核实" in result["human_report"]


@pytest.mark.parametrize("mutation", ["participation", "bank", "order", "source", "soundtrack", "window", "canvas", "delete"])
def test_mechanical_changes_expire_alignment_before_execution(mutation):
    project = source(2, 1, 1, soundtracks=True); state = aligned(project)
    if mutation == "participation": state["bindings"]["p1"]["participates"] = False
    if mutation == "bank": state["bindings"]["p1"]["banks"] = ["first_frame"]
    if mutation == "order": project["picture_track"][0]["order"] = 9
    if mutation == "source": project["video_track"][0]["source_in_seconds"] = .5
    if mutation == "soundtrack":
        project["video_track"][0].update(source_audio_enabled=False, audio_link_id=None); project["audio_track"] = [row for row in project["audio_track"] if row["clip_id"] != "va1"]
    if mutation == "window": project["processing_window"]["end_seconds"] = 6
    if mutation == "canvas": project["output_canvas"]["width"] = 672
    if mutation == "delete": project["picture_track"].pop()
    project = C.normalize_project(project)
    assert "alignment_stale" in codes(I.compile_interview(state, project))
    with pytest.raises(RuntimeError, match="对齐已过期"):
        N.ZVH3InterviewFormV2().build(project, I.dumps(state), prompt=H["fixed_hub_prompt"](), unique_id="172")


def test_renaming_asset_does_not_expire_mechanical_alignment():
    project = source(); state = aligned(project); project["assets"][0]["name"] = "用户自己改名.png"
    assert I.compile_interview(state, project)["validation"]["ready"]


@pytest.mark.parametrize("label", ["<Picture 0>", "<Picture 2>", "<Video 2>", "<Audio 9>"])
def test_explicit_missing_number_blocks_execution_with_correct_range(label):
    state = I.empty_interview(); state["intent"] = label
    result = I.compile_interview(state, source())
    assert "missing_prompt_reference" in codes(result)
    assert "本次有效编号" in next(row["message"] for row in result["validation"]["errors"] if row["code"] == "missing_prompt_reference")


@pytest.mark.parametrize("payload", [
    {"schema_version": "zv-h3-interview-v1"},
    {"schema_version": "zv-h3-interview-v1", "media_roles": {"p1": ["first_frame"]}},
])
def test_retired_interview_schema_is_rejected_without_migration(payload):
    with pytest.raises(I.InterviewError):
        I.normalize_interview(payload)


def test_current_form_drops_retired_metadata_without_creating_routes():
    state = I.empty_interview()
    state.update(recipe="i2va", migration={"from": "zv-h3-interview-v1"}, intent="保留原文")
    normalized = I.normalize_interview(state)
    assert "recipe" not in normalized and "migration" not in normalized
    assert normalized["intent"] == "保留原文"
    assert normalized["bindings"] == {}


def test_snapshot_without_context_is_blocked_before_execution():
    project = source(1, 0, 0)
    state = I.empty_interview(); state["reference_detection"] = H["detection"](pictures=("p1",), stage1_pictures=("p1",))
    assert "alignment_missing" in codes(I.compile_interview(state, project))
    with pytest.raises(RuntimeError, match="机械对齐上下文"):
        N.ZVH3InterviewFormV2().build(project, json.dumps(state), prompt=H["fixed_hub_prompt"](), unique_id="172")


def test_actual_snapshot_mode_drives_conditioning_audit():
    project = source(1, 0, 0); state = I.empty_interview()
    state["bindings"]["p1"] = {"item_id": "p1", "participates": True, "banks": ["first_frame"]}
    state["reference_detection"] = H["detection"](pictures=("p1",), stage1_pictures=("p1",))
    state["alignment"] = I.compile_interview({**state, "reference_detection": None}, project)["alignment_context"]
    assert I.compile_interview(state, project)["validation"]["effective_mode"] == "Ref2VA"
    prompt = {"172": {"class_type": "ZVH3InterviewFormV2", "inputs": {}}, "7": {"class_type": D.T8_CLASS, "inputs": {"prompt": ["172", 3], "task_type": "I2VA", "length": 124}}}
    with pytest.raises(RuntimeError, match="实际素材模式为 Ref2VA"):
        N.ZVH3InterviewFormV2().build(project, json.dumps(state), prompt=prompt, unique_id="172")


def test_detect_rpc_uses_actual_refs_not_conflicting_binding_mode():
    project = source(1, 0, 0); state = I.empty_interview()
    state["bindings"]["p1"] = {"item_id": "p1", "participates": True, "banks": ["first_frame"]}
    prompt = {"172": {"class_type": "ZVH3InterviewFormV2", "inputs": {"media_project": ["165", 0]}}, "165": {"class_type": "ZVUniversalMediaEvidenceDesk", "inputs": {}}, "176": {"class_type": "ZVPictureOutlet", "inputs": {"item_id": "p1"}}, "146": {"class_type": "ZFPromptDirectorLocalLLM", "inputs": {"prompt": ["172", 1], "image1": ["176", 0]}}, "7": {"class_type": D.T8_CLASS, "inputs": {"prompt": ["172", 3], "ref_images.ref_image_0": ["176", 0], "task_type": "Ref2VA", "length": 120}}}
    result = S.plan_interview({"state": state, "media_project": project, "prompt": prompt, "interview_id": "172", "align": True})
    assert result["validation"]["ready"] and result["validation"]["effective_mode"] == "Ref2VA"
    assert result["validation"]["conditioning"]["model_length"] == 124
    assert result["state"]["reference_detection"]["pictures"][0]["origin"] == "reference"


def test_literal_length_is_normalized_by_real_t8_grid_before_comparison():
    prompt = H["fixed_hub_prompt"](); prompt["7"]["inputs"]["length"] = 360
    proof = D.validate_conditioning_settings(prompt, "172", effective_mode="Ref2VA", project_frame_count=360)
    assert proof["length_verified"] and proof["model_length"] == 362 and not proof["errors"]


@pytest.mark.parametrize("case", ["inactive", "deleted", "active", "paired"])
def test_only_sent_media_purposes_can_block_missing_number(case):
    project = source(1, 1, 0, soundtracks=True); state = I.empty_interview()
    key = "p1"
    if case == "deleted": key = "deleted"
    if case == "inactive": state["bindings"]["p1"] = {"item_id": "p1", "participates": False, "banks": ["ref_images"]}
    if case == "paired": key = project["audio_track"][0]["clip_id"]
    state["media_purposes"][key] = "按 <Picture 9> 处理"
    result = I.compile_interview(state, project)
    assert ("missing_prompt_reference" in codes(result)) == (case in {"active", "paired"})
    assert ("unused_purpose" in {row["code"] for row in result["validation"]["warnings"]}) == (case in {"inactive", "deleted"})


@pytest.mark.parametrize("kind", ["literal", "same_project", "unknown", "different", "mismatch"])
def test_actual_length_proof_literals_same_source_and_unknown_chains(kind):
    prompt = H["fixed_hub_prompt"](); prompt["14"] = copy.deepcopy(prompt["7"])
    for key in ["7", "14"]: prompt[key]["inputs"]["length"] = 362
    if kind in {"same_project", "unknown"}:
        prompt["171"] = {"class_type": "ZVProcessingWindowOutlet", "inputs": {"media_project": ["165", 0]}}
        prompt["30"] = {"class_type": "ComfyMathExpression", "inputs": {"values.a": ["171", 4], "expression": "max(5, round(a)) + (5 - (max(5, round(a)) % 17)) % 17" if kind == "same_project" else "a+2"}}
        for key in ["7", "14"]: prompt[key]["inputs"]["length"] = ["30", 1]
    if kind == "different":
        for key in ["7", "14"]: prompt[key]["inputs"]["length"] = 124
    if kind == "mismatch": prompt["14"]["inputs"]["length"] = 124
    proof = D.validate_conditioning_settings(prompt, "172", effective_mode="Ref2VA", project_frame_count=360)
    assert proof["length_verified"] == (kind != "unknown" and kind != "mismatch")
    assert bool(proof["errors"]) == (kind in {"different", "mismatch"})
    if kind in {"literal", "same_project"}: assert proof["model_length"] == 362
    if kind == "unknown": assert proof["warnings"][0]["code"] == "conditioning_length_unverified"


def test_soundtrack_muted_detached_and_invalid_pairing():
    project = source(0, 1, 0, soundtracks=True)
    assert I.compile_interview(I.empty_interview(), project)["validation"]["counts"]["ref_video_audios"] == 1
    project["video_track"][0].update(source_audio_enabled=False, audio_link_id=None)
    project["audio_track"][0].update(linked_video_clip_id=None, origin="standalone")
    result = I.compile_interview(I.empty_interview(), C.normalize_project(project))
    assert result["validation"]["counts"]["ref_audios"] == 1 and result["validation"]["mixed_sources"] == 2
    project["audio_track"][0]["enabled"] = False
    assert I.compile_interview(I.empty_interview(), C.normalize_project(project))["validation"]["counts"]["ref_audios"] == 0
    project["video_track"][0].update(source_audio_enabled=True, audio_link_id="missing")
    assert "soundtrack_pair" in codes(I.compile_interview(I.empty_interview(), C.normalize_project(project)))


@pytest.mark.parametrize("task,mode,drive,error", [("Ref2VA — 参考生音视频", "Ref2VA", False, False), ("Ref2VA", "T2VA", False, True), ("auto", "FL2VA", False, False), ("Hybrid", "Hybrid", True, False)])
def test_actual_conditioning_task_settings_accept_display_labels(task, mode, drive, error):
    prompt = H["fixed_hub_prompt"](); prompt["7"]["inputs"]["task_type"] = task
    errors = D.validate_reference_hub_wiring(prompt, "172", effective_mode=mode, has_drive_audio=drive)["errors"]
    assert bool(errors) == error


def test_audio_modes_dynamic_task_and_low_high_mismatch_are_actionable():
    prompt = H["fixed_hub_prompt"](); prompt["7"]["inputs"]["audio_mode"] = "lock_source"
    assert any(row["code"] == "conditioning_audio_mode" for row in D.validate_reference_hub_wiring(prompt, "172", effective_mode="Ref2VA")["errors"])
    prompt["14"] = copy.deepcopy(prompt["7"]); prompt["14"]["inputs"]["audio_mode"] = "native"
    assert any(row["code"] == "conditioning_audio_mismatch" for row in D.validate_reference_hub_wiring(prompt, "172", effective_mode="Ref2VA", has_drive_audio=True)["errors"])
    prompt["7"]["inputs"]["task_type"] = ["165", 0]
    assert any(row["code"] == "conditioning_task" for row in D.validate_reference_hub_wiring(prompt, "172", effective_mode="Ref2VA", has_drive_audio=True)["errors"])


def test_h3_export_selected_reference_outside_gen_and_ordinary_outlet_unchanged(monkeypatch):
    project = source(0, 1, 1, soundtracks=True)
    project["processing_window"] = {"start_seconds": 10, "end_seconds": 15, "fps": 24}
    project = C.normalize_project(project)
    with pytest.raises(OUT.OutletError, match="没有交集"):
        OUT.build_outlet_plan(project, "video", "v1")
    plan = RP.build_reference_plan(project, I.compile_interview(I.empty_interview(), project))
    assert plan["ready"]
    original = copy.deepcopy(project); prepared = []
    class Store:
        def canonical(self, value): return value
    monkeypatch.setattr(RUN, "get_store", lambda: Store())
    def execute(store, row):
        prepared.append(row)
        return ("frames", "paired", {}, "") if row["kind"] == "video" else ("audio", None, {}, "")
    monkeypatch.setattr(DEC, "execute_outlet", execute)
    output = O.ZVH3ReferenceOutlet().export_references(plan)
    assert output[11] == "frames" and output[14] == "paired" and output[19] == "audio"
    assert {row["items"][0]["output_duration_seconds"] for row in prepared} == {2}
    assert prepared[0]["items"][0]["frame_count"] == 48
    assert project == original and len(output) == 24


def test_template_model_has_no_real_bindings_paths_cache_sizes_or_snapshots():
    project = source(soundtracks=True); state = aligned(project)
    template = R.reusable_template(state, I.media_inventory(project))
    encoded = json.dumps(template)
    for forbidden in ["item_id", "asset_id", "source_handle", "alignment", "detection", "canvas", "width", "height", "processing_window", "originals/"]:
        assert forbidden not in encoded
    assert [row["kind"] for row in template["slots"]] == ["picture", "video", "audio"]


def test_actual_user_workflow_preserves_current_fields_and_full_links_read_only():
    if not WORKFLOW.exists(): pytest.skip("User's workflow not on this host")
    digest = hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()
    graph = json.loads(WORKFLOW.read_text(encoding="utf-8")); ids = {row["id"] for row in graph["nodes"]}
    assert len(ids) == len(graph["nodes"]) and graph["links"]
    assert len({link[0] for link in graph["links"]}) == len(graph["links"])
    assert all(link[1] in ids and link[3] in ids for link in graph["links"])
    nodes = {row["id"]: row for row in graph["nodes"]}
    old = json.loads(nodes[172]["widgets_values"][0]); original = copy.deepcopy(old)
    project = C.normalize_project(json.loads(nodes[165]["widgets_values"][0]))
    state = I.compile_interview(old, project)["state"]
    assert all(state[key] == value for key, value in old.items() if key not in {"schema_version", "recipe", "migration"})
    assert old == original and "recipe" not in state and "migration" not in state
    assert I.normalize_interview(state) == state
    links = {row[0]: row for row in graph["links"]}
    assert [(links[input["link"]][1], links[input["link"]][2]) for input in nodes[165]["inputs"] if input["name"] in {"width", "height"}] == [(29, 0), (29, 1)]
    assert len(nodes[182]["outputs"]) == 24
    assert hashlib.sha256(WORKFLOW.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("field,value,code", [("fps", 30, "h3_fps"), ("start_seconds", .02, "h3_grid"), ("frame_count", 119, "h3_grid")])
def test_output_frame_grid_and_clock_errors(field, value, code):
    project = source(0, 0, 0); project["processing_window"][field] = value
    assert code in codes(I.compile_interview(I.empty_interview(), project))


def test_h3_fixed_outlet_real_cpu_decode_and_planning_reuses_registry_without_decode(tmp_path, monkeypatch):
    import torch
    media = runpy.run_path(str(ROOT / "tests/media_outlet_smoke.py"))
    store, project = media["imported_project"](tmp_path)
    project["processing_preset"] = P.builtin("builtin.minimax-h3.single")
    project["processing_window"] = {"start_seconds": 20, "end_seconds": 25, "fps": 24}
    project["output_canvas"] = {"width": 64, "height": 96}
    for item in project["video_track"] + project["audio_track"]:
        item["source_out_seconds"] = item["source_in_seconds"] + 2
    project = C.normalize_project(project)
    originals = {asset["source_handle"]: hashlib.sha256(store.resolve(asset["source_handle"]).read_bytes()).hexdigest() for asset in project["assets"]}
    def no_worker(*args): raise AssertionError("Planning may not probe or decode")
    monkeypatch.setattr(store, "worker", no_worker)
    monkeypatch.setattr(S, "get_store", lambda: store)
    # Test the registered HTTP route, including registry hydration, not a UI mock.
    import asyncio
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    async def request():
        routes = web.RouteTableDef(); S.register_interview_routes(routes)
        app = web.Application(); app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/zf-prompt-director/h3-interview/plan", json={"state": I.empty_interview(), "media_project": project, "align": True})
            assert response.status == 200
            return await response.json()
    result = asyncio.run(request())
    assert result["validation"]["ready"]
    state = result["state"]; state["reference_detection"] = result["snapshot"]; state["alignment"] = result["alignment_context"]
    plan = RP.build_reference_plan(project, I.compile_interview(state, project))
    monkeypatch.setattr(RUN, "get_store", lambda: store)
    output = O.ZVH3ReferenceOutlet().export_references(plan)
    assert len(output) == 24
    assert output[0] is None and output[1] is None
    for frames in output[11:13]:
        assert tuple(frames.shape) == (48, 96, 64, 3) and frames.dtype == torch.float32 and frames.device.type == "cpu"
    assert output[13] is None and output[15] is None
    assert tuple(output[14]["waveform"].shape) == (1, 2, 88200)
    assert tuple(output[19]["waveform"].shape) == (1, 2, 88200)
    assert output[14]["sample_rate"] == output[19]["sample_rate"] == 44100
    assert "模型可见 39 帧" in output[23]
    assert all(hashlib.sha256(store.resolve(handle).read_bytes()).hexdigest() == digest for handle, digest in originals.items())
