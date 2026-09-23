import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zf_animate_once_builder", ROOT / "tools" / "add_animate_once.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
REAL_SOURCE_VALUE = os.environ.get("ZV_ANIMATE_SOURCE_WORKFLOW")
REAL_SOURCE = Path(REAL_SOURCE_VALUE) if REAL_SOURCE_VALUE else None


def small_source():
    """The original attachment boundaries and representative preserved branches."""
    rows = [
        (62, "VHS_LoadVideo", [], [("IMAGE", "IMAGE"), ("frame_count", "INT"), ("audio", "AUDIO"), ("video_info", "VHS_VIDEOINFO")], ["original.mp4", 30]),
        (49, "LoadImage", [], [("IMAGE", "IMAGE")], ["original.png"]),
        (197, "SetNode", [("IMAGE", "IMAGE")], [], ["SP图像"]),
        (203, "SetNode", [("INT", "INT")], [], ["SP帧计数"]),
        (202, "SetNode", [("AUDIO", "AUDIO")], [], ["音频"]),
        (204, "SetNode", [("VHS_VIDEOINFO", "VHS_VIDEOINFO")], [], ["视频信息"]),
        (208, "SetNode", [("IMAGE", "IMAGE")], [], ["TU图像"]),
        (936, "GetNode", [], [("INT", "INT")], ["帧率预设"]),
        (934, "SetNode", [("INT", "INT")], [], ["帧率预设"]),
        (430, "INTConstant", [], [("value", "INT")], [30]),
        (432, "SimpleMath+", [("a", "*")], [("INT", "INT"), ("FLOAT", "FLOAT")], ["a*1"]),
        (759, "GetNode", [], [("INT", "INT")], ["SP缩放宽"]),
        (758, "GetNode", [], [("INT", "INT")], ["SP缩放高"]),
        (200, "SetNode", [("INT", "INT")], [], ["SP缩放宽"]),
        (201, "SetNode", [("INT", "INT")], [], ["SP缩放高"]),
        (534, "INTConstant", [], [("value", "INT")], [720]),
        (535, "INTConstant", [], [("value", "INT")], [1280]),
        (41, "GetNode", [], [("IMAGE", "IMAGE")], ["SP图像"]),
        (216, "GetNode", [], [("IMAGE", "IMAGE")], ["TU图像"]),
        (61, "GetNode", [], [("INT", "INT")], ["SP帧计数"]),
        (938, "GetNode", [], [("IMAGE", "IMAGE")], ["过渡SP"]),
        (937, "SetNode", [("IMAGE", "IMAGE")], [], ["过渡SP"]),
        (912, "VHS_LoadVideo", [], [("IMAGE", "IMAGE")], [""]),
        (789, "WanAnimatePlus AnimateEmbeds", [("ref_images", "IMAGE"), ("pose_images", "IMAGE"), ("transition_video", "IMAGE"), ("num_frames", "INT"), ("frame_window_size", "INT")], [("image_embeds", "WANVIDIMAGE_EMBEDS")], [832, 480, 81, True, 77]),
        (59, "WanVideoContextOptions", [], [("context_options", "WANVIDCONTEXT")], ["static_standard", 81, 4, 32, True, False, "linear"]),
        (790, "WanAnimatePlus SamplerSettings", [("image_embeds", "WANVIDIMAGE_EMBEDS"), ("context_options", "WANVIDCONTEXT")], [("sampler_inputs", "SAMPLER_ARGS")], [8, 1, 8]),
        (792, "WanAnimatePlus SamplerFromSettings", [("sampler_inputs", "SAMPLER_ARGS")], [("samples", "LATENT")], []),
        (793, "WanAnimatePlus Decode", [("samples", "LATENT")], [("images", "IMAGE")], [False, 272, 272, 144, 128, "default"]),
        (700, "ImageFromBatch", [("image", "IMAGE"), ("batch_index", "INT"), ("length", "INT")], [("IMAGE", "IMAGE")], [4, 1]),
        (685, "INTConstant", [], [("value", "INT")], [6]),
        (687, "SetNode", [("IMAGE", "IMAGE")], [], ["有效提取"]),
        (886, "GetNode", [], [("IMAGE", "IMAGE")], ["有效提取"]),
        (885, "VHS_VideoCombine", [("images", "IMAGE")], [("Filenames", "VHS_FILENAMES")], {"filename_prefix": "old_result"}),
        (887, "DuckHideNode", [("images", "IMAGE")], [("duck_image", "IMAGE")], ["unchanged"]),
        (882, "SaveImage", [("images", "IMAGE")], [], ["old_image"]),
        (969, "easy showAnything", [("anything", "*")], [("output", "*")], ["not in the loop"]),
        (831, "PurgeVRAM_UTK", [("anything", "*")], [("anything", "*")], [True, True]),
        (881, "LoadImage", [], [("IMAGE", "IMAGE")], ["old-independent-image.png"]),
        (880, "SaveImage", [("images", "IMAGE")], [], ["old_independent_output"]),
        (304, "CR Text", [], [("text", "*")], ["shirt"]),
        (305, "SetNode", [("*", "*")], [], ["替换词"]),
        (522, "GetNode", [], [("*", "*")], ["替换词"]),
        (835, "GoogleTranslateTextNode", [("text", "STRING")], [("text", "STRING")], []),
        (433, "SimpleMath+", [], [("INT", "INT")], ["414"]),
        (523, "ImageFromBatch", [("image", "IMAGE"), ("batch_index", "INT")], [("IMAGE", "IMAGE")], [0, 1]),
        (374, "SetNode", [("IMAGE", "IMAGE")], [], ["SP运行"]),
        (375, "GetNode", [], [("IMAGE", "IMAGE")], ["SP运行"]),
        (712, "ImpactConditionalBranch", [], [("*", "*")], []),
        (513, "SAM3_Detect", [("image", "IMAGE"), ("text", "STRING")], [("masks", "MASK")], []),
        (504, "Masks Add", [("masks_a", "MASK")], [("MASKS", "MASK")], []),
        (367, "SeCVideoSegmentation", [("frames", "IMAGE"), ("input_mask", "MASK"), ("annotation_frame_idx", "INT")], [("masks", "MASK")], []),
        (370, "BlockifyMask", [("masks", "MASK")], [("mask", "MASK")], []),
        (371, "DrawMaskOnImage", [("image", "IMAGE"), ("mask", "MASK")], [("images", "IMAGE")], []),
        (19, "SetNode", [("MASK", "MASK")], [("MASK", "MASK")], ["抠出"]),
        (40, "SetNode", [("IMAGE", "IMAGE")], [("IMAGE", "IMAGE")], ["背景绘制抠出"]),
        (10, "GetNode", [], [("MASK", "MASK")], ["抠出"]),
        (43, "GetNode", [], [("IMAGE", "IMAGE")], ["背景绘制抠出"]),
        (834, "PurgeVRAM_UTK", [("anything", "*")], [("anything", "*")], [True, True]),
    ]
    nodes = [BUILDER.make_node(identifier, kind, kind, [identifier * 2, identifier], inputs, outputs, values=values)
             for identifier, kind, inputs, outputs, values in rows]
    next(row for row in nodes if row["id"] == 789)["inputs"].extend([
        {"name": "mask", "type": "MASK", "link": None}, {"name": "bg_images", "type": "IMAGE", "link": None}])
    links = [
        (241, 62, "IMAGE", 197, "IMAGE"), (248, 62, "frame_count", 203, "INT"),
        (249, 62, "audio", 202, "AUDIO"), (250, 62, "video_info", 204, "VHS_VIDEOINFO"),
        (268, 49, "IMAGE", 208, "IMAGE"), (1227, 938, "IMAGE", 789, "transition_video"),
        (1226, 912, "IMAGE", 937, "IMAGE"), (1223, 432, "INT", 934, "INT"),
        (548, 430, "value", 432, "a"),
        (702, 534, "value", 200, "INT"), (703, 535, "value", 201, "INT"),
        (1052, 216, "IMAGE", 789, "ref_images"), (1053, 41, "IMAGE", 789, "pose_images"),
        (1059, 61, "INT", 789, "num_frames"), (1060, 61, "INT", 789, "frame_window_size"),
        (1049, 789, "image_embeds", 790, "image_embeds"), (1062, 59, "context_options", 790, "context_options"),
        (1065, 790, "sampler_inputs", 792, "sampler_inputs"), (1064, 792, "samples", 793, "samples"),
        (927, 793, "images", 700, "image"), (928, 685, "value", 700, "batch_index"),
        (929, 61, "INT", 700, "length"), (912, 700, "IMAGE", 687, "IMAGE"),
        (1169, 886, "IMAGE", 885, "images"), (1172, 886, "IMAGE", 887, "images"),
        (1168, 887, "duck_image", 882, "images"), (1261, 430, "value", 969, "anything"),
        (1262, 793, "images", 831, "anything"),
        (1263, 881, "IMAGE", 880, "images"),
        (681, 304, "text", 305, "*"), (1117, 522, "*", 835, "text"),
        (686, 433, "INT", 523, "batch_index"), (558, 433, "INT", 367, "annotation_frame_idx"),
        (687, 375, "IMAGE", 523, "image"), (600, 41, "IMAGE", 374, "IMAGE"),
        (602, 375, "IMAGE", 367, "frames"), (683, 523, "IMAGE", 513, "image"),
        (674, 835, "text", 513, "text"), (689, 513, "masks", 504, "masks_a"),
        (665, 504, "MASKS", 367, "input_mask"), (452, 367, "masks", 370, "masks"),
        (443, 375, "IMAGE", 371, "image"), (444, 370, "mask", 371, "mask"),
        (449, 370, "mask", 19, "MASK"), (446, 371, "images", 40, "IMAGE"),
        (1114, 371, "images", 834, "anything"), (1056, 10, "MASK", 789, "mask"),
        (1055, 43, "IMAGE", 789, "bg_images"),
    ]
    by_id = {node["id"]: node for node in nodes}
    result_links = []
    for identifier, source, output_name, target, input_name in links:
        source_node, target_node = by_id[source], by_id[target]
        output_index = next(i for i, row in enumerate(source_node["outputs"]) if row["name"] == output_name)
        input_index = next(i for i, row in enumerate(target_node["inputs"]) if row["name"] == input_name)
        source_node["outputs"][output_index]["links"].append(identifier)
        target_node["inputs"][input_index]["link"] = identifier
        result_links.append([identifier, source, output_index, target, input_index, target_node["inputs"][input_index]["type"]])
    return {"version": 0.4, "nodes": nodes, "links": result_links,
            "groups": [{"id": 8, "title": "用户原组", "bounding": [0, 0, 2000, 1200]}],
            "extra": {"original_property": {"keep": True}, "ds": {"scale": 0.4, "offset": [500, 200]}}}


@pytest.fixture(params=["small", "original"])
def source(request):
    if request.param == "small":
        return small_source()
    if REAL_SOURCE is None or not REAL_SOURCE.is_file():
        pytest.skip("set ZV_ANIMATE_SOURCE_WORKFLOW to audit the user's original graph")
    return json.loads(REAL_SOURCE.read_text(encoding="utf-8-sig"))


def nodes_by_id(workflow):
    return {node["id"]: node for node in workflow["nodes"]}


def logic_without_link_metadata(node):
    value = copy.deepcopy(node)
    value.pop("order", None)
    value.pop("mode", None)
    for port in value.get("inputs", []):
        port.pop("link", None)
    for port in value.get("outputs", []):
        port.pop("links", None)
    return value


def input_source(workflow, identifier, name):
    node = nodes_by_id(workflow)[identifier]
    link_id = next(port["link"] for port in node["inputs"] if port["name"] == name)
    link = next(row for row in workflow["links"] if row[0] == link_id)
    parent = nodes_by_id(workflow)[link[1]]
    return parent["id"], parent["outputs"][link[2]]["name"]


def test_preserves_every_original_node_widget_position_group_and_nonentry_link(source):
    original = copy.deepcopy(source)
    result = BUILDER.build(source)
    assert source == original
    before, after = nodes_by_id(source), nodes_by_id(result)
    metadata = result["extra"]["zv_animate_once"]
    assert set(before).issubset(after)
    assert result["groups"][:-1] == source["groups"]
    for key, value in source.get("extra", {}).items():
        if key != "ds":
            assert result["extra"][key] == value
    assert metadata["original_view"] == source.get("extra", {}).get("ds")
    view = result["extra"]["ds"]
    desk = after[metadata["new_node_ids"]["desk"]]
    assert (desk["pos"][0] + view["offset"][0]) * view["scale"] == pytest.approx(70)
    assert (desk["pos"][1] + view["offset"][1]) * view["scale"] == pytest.approx(90)
    for identifier, node in before.items():
        expected = logic_without_link_metadata(node)
        if identifier in (78, 109) and after[identifier].get("mode", 0) == 2:
            for field in ("widgets_values", "widgets_values_named"):
                if isinstance(expected.get(field), dict):
                    expected[field].pop("videopreview", None)
        assert logic_without_link_metadata(after[identifier]) == expected
        if str(identifier) in metadata["original_modes"]:
            assert node["type"] in BUILDER.OUTPUT_TYPES
            assert node.get("mode", 0) == metadata["original_modes"][str(identifier)] == 0
            assert after[identifier]["mode"] == 2
        else:
            assert after[identifier].get("mode", 0) == node.get("mode", 0)
    preserved_links = {row[0]: row for row in result["links"]}
    replaced = {row[2] for row in (*BUILDER.REPLACEMENTS, *BUILDER.MASK_REPLACEMENTS)}
    for link in source["links"]:
        mask_preview_image = link[3] == 284 and before[284]["inputs"][link[4]]["name"] == "images"
        if link[0] not in replaced and not mask_preview_image:
            assert preserved_links[link[0]] == link
    assert metadata["original_links"] == [next(row for row in source["links"] if row[0] == identifier)
                                          for identifier in (241, 248, 249, 250, 268, 1227)]
    BUILDER.Editor(result).validate()


def test_reuses_original_fps_size_and_final_crop_without_rebuilding_preprocess(source):
    result = BUILDER.build(source)
    ids = result["extra"]["zv_animate_once"]["new_node_ids"]
    assert input_source(result, ids["plan"], "fps") == (936, "INT")
    assert next(port["type"] for port in nodes_by_id(result)[ids["plan"]]["inputs"] if port["name"] == "fps") == "INT,FLOAT"
    assert input_source(result, ids["entry"], "width") == (759, "INT")
    assert input_source(result, ids["entry"], "height") == (758, "INT")
    assert input_source(result, ids["recorder"], "frames") == (700, "IMAGE")
    for target, name, _old, source_name, _type in BUILDER.REPLACEMENTS:
        assert input_source(result, target, name) == (ids["entry"], source_name)
    for name in ("num_frames", "frame_window_size"):
        assert input_source(result, 789, name) == input_source(source, 789, name)
    assert input_source(result, 790, "context_options") == input_source(source, 790, "context_options")
    for name in ("image", "batch_index", "length"):
        assert input_source(result, 700, name) == input_source(source, 700, name)
    assert {nodes_by_id(result)[identifier]["type"] for identifier in ids.values()} == {
        "ZVUniversalMediaEvidenceDesk", "ZVAnimateSegmentDesk", "StartLoop", "ZVAnimateExecutionEntry",
        "ZVAnimateSegmentRecorder", "EndLoop", "ZVAnimateExecutionEnd", "SaveVideo", "PreviewAny", "Note",
        "ZVAnimateMaskFrame", "ZVAnimateMaskSeed", "ZVAnimateMaskGate",
        "ZVAnimateFinalComparison",
    }


def test_empty_new_desk_fixed_choices_loop_cache_and_previous_result_wiring(source):
    result = BUILDER.build(source)
    ids = result["extra"]["zv_animate_once"]["new_node_ids"]
    nodes = nodes_by_id(result)
    project = json.loads(nodes[ids["desk"]]["widgets_values"][0])
    expected = BUILDER.empty_project()
    expected["project_clock"]["fps"] = expected["processing_window"]["fps"] = nodes[430]["widgets_values"][0]
    assert project == expected
    assert json.loads(nodes[ids["plan"]]["widgets_values"][0]) == {"schema_version": 1, "seam_mode": "hard_cut", "mask_enabled": False, "mask_tasks": {}}
    assert nodes[ids["start"]]["widgets_values_named"]["cache_iterations"] is False
    assert nodes[ids["end"]]["widgets_values_named"]["accumulate"] is False
    for target in ("entry", "recorder"):
        assert input_source(result, ids[target], "previous_result") == (ids["start"], "current_iteration_value")
    for name in ("output_value", "next_iteration_value"):
        assert input_source(result, ids["end"], name) == (ids["recorder"], "run_result")
    assert input_source(result, ids["finish"], "run_result") == (ids["end"], "outputs")
    assert input_source(result, ids["report"], "source") == (ids["finish"], "report")
    assert nodes[ids["report"]]["mode"] == 2
    assert nodes[ids["save"]]["mode"] == 0
    assert input_source(result, ids["recorder"], "source_audio") == (ids["entry"], "source_audio")
    assert "少 1 帧" in nodes[ids["note"]]["widgets_values"][0]


def test_only_loop_dependent_preview_outputs_are_muted():
    result = BUILDER.build(small_source())
    assert result["extra"]["zv_animate_once"]["original_modes"] == {"880": 0, "882": 0, "885": 0}
    assert nodes_by_id(result)[969]["mode"] == 0
    assert nodes_by_id(result)[887]["mode"] == 0
    metadata = result["extra"]["zv_animate_once"]
    assert metadata["purge_terminations"] == {"terminations.termination0": 831, "terminations.termination1": 834}
    assert nodes_by_id(result)[831]["mode"] == 0
    assert input_source(result, metadata["new_node_ids"]["end"], "terminations.termination0") == (831, "anything")
    assert all(not port["name"].startswith("dependency")
               for port in nodes_by_id(result)[metadata["new_node_ids"]["recorder"]]["inputs"])


def test_mask_gate_controls_both_plus_inputs_and_cleanup_while_seed_indices_match(source):
    result = BUILDER.build(source)
    ids = result["extra"]["zv_animate_once"]["new_node_ids"]
    assert input_source(result, 523, "batch_index") == input_source(result, 367, "annotation_frame_idx") == (ids["mask_frame"], "annotation_frame_idx")
    assert input_source(result, ids["mask_frame"], "front_padding") == (712, "*")
    assert input_source(result, 835, "text") == (ids["mask_frame"], "mask_prompt")
    assert input_source(result, 367, "input_mask") == (ids["mask_seed"], "validated_seed")
    assert input_source(result, ids["mask_seed"], "mask") == (504, "MASKS")
    assert input_source(result, ids["mask_seed"], "reference_image") == (523, "IMAGE")
    assert input_source(result, 19, "MASK") == (ids["mask_gate"], "mask")
    assert input_source(result, 40, "IMAGE") == input_source(result, 834, "anything") == (ids["mask_gate"], "bg_images")
    prompt = resolved_prompt(result)
    assert prompt["789"]["inputs"]["mask"] == [str(ids["mask_gate"]), 0]
    assert prompt["789"]["inputs"]["bg_images"] == [str(ids["mask_gate"]), 1]
    assert prompt["834"]["inputs"]["anything"] == [str(ids["mask_gate"]), 1]
    # Model/cleanup roots must not reach detection through a second, ungated path.
    pending = [key for key, node in prompt.items() if node["class_type"] in BUILDER.OUTPUT_TYPES | {"SaveVideo"}]
    reached = set()
    while pending:
        key = pending.pop()
        if key in reached:
            continue
        reached.add(key)
        for name, value in prompt[key]["inputs"].items():
            if key == str(ids["mask_gate"]) and name in {"mask", "bg_images"}:
                continue
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                pending.append(value[0])
    assert reached.isdisjoint({"367", "513", "523", "835", str(ids["mask_frame"]), str(ids["mask_seed"])})


def test_rejects_double_application_or_changed_attachment_boundary(source):
    with pytest.raises(BUILDER.WorkflowBuildError):
        BUILDER.build(BUILDER.build(source))
    broken = copy.deepcopy(source)
    nodes_by_id(broken)[197]["widgets_values"] = ["not the video input"]
    with pytest.raises(BUILDER.WorkflowBuildError, match="#197"):
        BUILDER.build(broken)


def test_cli_never_overwrites_original_or_existing_file(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(small_source()), encoding="utf-8")
    before = source.read_bytes()
    with pytest.raises(SystemExit):
        BUILDER.main([str(source), str(source)])
    assert source.read_bytes() == before
    output = tmp_path / "exists.json"
    output.write_text("existing user data", encoding="utf-8")
    with pytest.raises(SystemExit):
        BUILDER.main([str(source), str(output)])
    assert output.read_text(encoding="utf-8") == "existing user data"


def test_initial_grid_follows_original_fps_and_rejects_unverified_formulas():
    source = small_source()
    nodes_by_id(source)[430]["widgets_values"] = [25]
    result = BUILDER.build(source)
    ids = result["extra"]["zv_animate_once"]["new_node_ids"]
    project = json.loads(nodes_by_id(result)[ids["desk"]]["widgets_values"][0])
    assert project["project_clock"]["fps"] == project["processing_window"]["fps"] == 25
    assert input_source(result, ids["plan"], "fps") == (936, "INT")
    for identifier, values in ((432, ["a*2"]), (430, [0]), (430, ["30"])):
        broken = copy.deepcopy(source)
        nodes_by_id(broken)[identifier]["widgets_values"] = values
        with pytest.raises(BUILDER.WorkflowBuildError, match="无法静态对齐"):
            BUILDER.build(broken)


def resolved_prompt(workflow):
    """Resolve same-graph Set/Get and bypass ports before host loop validation."""
    nodes = nodes_by_id(workflow)
    links = {row[0]: row for row in workflow["links"]}
    setters = {node["widgets_values"][0]: node for node in nodes.values()
               if node["type"] == "SetNode" and node.get("widgets_values")}

    def resolve_input(node, slot, visited):
        link = links.get(node["inputs"][slot].get("link"))
        return resolve_output(nodes[link[1]], link[2], visited) if link else None

    def resolve_output(node, slot, visited):
        marker = node["id"], slot
        assert marker not in visited, marker
        visited = visited | {marker}
        if node.get("mode", 0) == 2:
            return None
        if node.get("mode", 0) == 4:
            type_ = node["outputs"][slot]["type"]
            for index, port in enumerate(node.get("inputs", [])):
                if port["type"] in (type_, "*"):
                    return resolve_input(node, index, visited)
            return None
        if node["type"] == "GetNode":
            setter = setters.get(node["widgets_values"][0])
            return resolve_input(setter, slot, visited) if setter else None
        return [str(node["id"]), slot]

    result = {}
    for node in nodes.values():
        if node.get("mode", 0) in (2, 4) or node["type"] in {"GetNode", "SetNode", "Note", "MarkdownNote"} or node["type"].startswith("Fast Groups"):
            continue
        inputs = dict(node.get("widgets_values_named", {}))
        for index, port in enumerate(node.get("inputs", [])):
            value = resolve_input(node, index, set())
            if value is not None:
                inputs[port["name"]] = value
        result[str(node["id"])] = {"class_type": node["type"], "inputs": inputs}
    return result


def validate_native_loop(workflow):
    comfy_value = os.environ.get("ZV_COMFY_ROOT")
    if not comfy_value:
        pytest.skip("set ZV_COMFY_ROOT for actual ComfyUI loop validation")
    comfy = str(Path(comfy_value).resolve())
    if comfy not in sys.path:
        sys.path.insert(0, comfy)
    validate_loops = importlib.import_module("comfy_execution.validation").validate_loops
    prompt = resolved_prompt(workflow)
    ids = workflow["extra"]["zv_animate_once"]["new_node_ids"]
    outputs = {identifier for identifier, node in prompt.items()
               if node["class_type"] in BUILDER.OUTPUT_TYPES | {"SaveVideo"}}
    assert validate_loops(prompt, outputs, prompt, {str(ids["start"])}, {str(ids["end"])}) == {
        str(ids["start"]): str(ids["end"]),
    }


def test_host_native_loop_validator_accepts_all_preserved_output_roots(source):
    validate_native_loop(BUILDER.build(source))


def with_bypassed_video_outputs():
    editor = BUILDER.Editor(small_source())
    for identifier in (78, 109):
        node = BUILDER.make_node(identifier, "VHS_VideoCombine", "原流预览", [identifier, 0],
                                 [("images", "IMAGE")], [("Filenames", "VHS_FILENAMES")])
        node["mode"] = 4
        editor.add(node)
        editor.wire(886, "IMAGE", identifier, "images", "IMAGE")
    return editor.finish()


def with_rgthree_pose_switch():
    editor = BUILDER.Editor(small_source())
    editor.add(BUILDER.make_node(644, "SDPoseDrawKeypoints", "原姿态绘制", [0, 0],
                                 [("keypoints", "POSE_KEYPOINT")], [("IMAGE", "IMAGE")]))
    editor.add(BUILDER.make_node(554, "Any Switch (rgthree)", "原姿态切换", [0, 0],
                                 [("any_02", "IMAGE")], [("输出", "IMAGE")]))
    editor.wire(644, "IMAGE", 554, "any_02", "IMAGE")
    editor.wire(554, "输出", 789, "pose_images", "IMAGE", replace=True)
    return editor.finish()


def test_dynamic_pose_switch_is_explicitly_anchored_inside_loop():
    result = BUILDER.build(with_rgthree_pose_switch())
    ids = result["extra"]["zv_animate_once"]["new_node_ids"]
    port = result["extra"]["zv_animate_once"]["pose_termination"]
    assert port.startswith("terminations.termination")
    assert input_source(result, ids["end"], port) == (644, "IMAGE")
    repaired = BUILDER.repair_loop_outputs(result)
    assert input_source(repaired, ids["end"], repaired["extra"]["zv_animate_once"]["pose_termination"]) == (644, "IMAGE")
    assert BUILDER.repair_loop_outputs(repaired) == repaired


def test_final_save_visible_by_old_outputs_without_stale_video_preview():
    source = with_bypassed_video_outputs()
    source["groups"].append({"id": 10, "title": "浏览效果", "bounding": [-7992, 4425, 2033, 1699]})
    for identifier in (78, 109):
        node = nodes_by_id(source)[identifier]
        node["mode"] = 0
        node["widgets_values"] = {"filename_prefix": f"old-{identifier}", "videopreview": {"filename": "second.mp4"}}
        node["widgets_values_named"] = {"filename_prefix": f"old-{identifier}", "videopreview": {"filename": "second.mp4"}}
    original = copy.deepcopy(source)

    result = BUILDER.build(source)
    ids = result["extra"]["zv_animate_once"]["new_node_ids"]
    nodes = nodes_by_id(result)
    assert source == original
    assert nodes[ids["save"]]["pos"] == [-5891, 4500]
    assert nodes[ids["save"]]["size"] == [460, 600]
    assert nodes[ids["save"]]["title"] == f"完整成片保存（来自 #{ids['finish']}）"
    assert input_source(result, ids["save"], "video") == (ids["finish"], "video")
    assert input_source(result, ids["comparison"], "video") == (ids["save"], "video")
    assert {port["name"] for port in nodes[ids["comparison"]]["inputs"]} == {"animate_plan", "video"}
    assert input_source(result, ids["comparison_save"], "video") == (ids["comparison"], "comparison_video")
    assert nodes[ids["comparison_save"]]["pos"][0] > nodes[ids["save"]]["pos"][0]
    for identifier in (78, 109):
        assert nodes[identifier]["mode"] == 2
        assert nodes[identifier]["widgets_values"] == {"filename_prefix": f"old-{identifier}"}
        assert nodes[identifier]["widgets_values_named"] == {"filename_prefix": f"old-{identifier}"}

    repaired = BUILDER.repair_loop_outputs(result)
    assert nodes_by_id(repaired)[ids["save"]] == nodes[ids["save"]]
    assert BUILDER.repair_loop_outputs(repaired) == repaired


def test_repair_adds_post_loop_comparison_without_mutating_legacy_copy():
    editor = BUILDER.Editor(BUILDER.build(small_source()))
    ids = editor.workflow["extra"]["zv_animate_once"]["new_node_ids"]
    editor.remove_nodes((ids.pop("comparison"), ids.pop("comparison_save")))
    legacy = editor.finish()
    original = copy.deepcopy(legacy)
    repaired = BUILDER.repair_loop_outputs(legacy)
    assert legacy == original
    repaired_ids = repaired["extra"]["zv_animate_once"]["new_node_ids"]
    assert input_source(repaired, repaired_ids["comparison"], "video") == (repaired_ids["save"], "video")
    assert {port["name"] for port in nodes_by_id(repaired)[repaired_ids["comparison"]]["inputs"]} == {"animate_plan", "video"}
    assert input_source(repaired, repaired_ids["comparison_save"], "video") == (repaired_ids["comparison"], "comparison_video")
    assert BUILDER.repair_loop_outputs(repaired) == repaired


def test_repair_removes_old_comparison_edge_back_to_loop():
    editor = BUILDER.Editor(BUILDER.build(small_source()))
    ids = editor.workflow["extra"]["zv_animate_once"]["new_node_ids"]
    compare = editor.nodes[ids["comparison"]]
    compare["inputs"].insert(1, {"name": "run_result", "type": "ZV_ANIMATE_RUN", "link": None})
    for link in editor.links:
        if link[3] == ids["comparison"] and link[4] >= 1:
            link[4] += 1
    editor.wire(ids["end"], "outputs", ids["comparison"], "run_result", "ZV_ANIMATE_RUN")
    draft = editor.finish()
    repaired = BUILDER.repair_loop_outputs(draft)
    assert {port["name"] for port in nodes_by_id(repaired)[ids["comparison"]]["inputs"]} == {"animate_plan", "video"}
    assert input_source(repaired, ids["comparison"], "video") == (ids["save"], "video")
    assert not any(link[1] == ids["end"] and link[3] == ids["comparison"] for link in repaired["links"])
    assert BUILDER.repair_loop_outputs(repaired) == repaired


def test_old_video_outputs_are_muted_and_not_loop_roots():
    result = BUILDER.build(with_bypassed_video_outputs())
    ids = result["extra"]["zv_animate_once"]["new_node_ids"]
    nodes = nodes_by_id(result)
    for identifier in (78, 109):
        assert nodes[identifier]["mode"] == 4
        assert not any(link[1] == identifier and link[3] == ids["end"] for link in result["links"])
    assert nodes[ids["report"]]["mode"] == 2
    validate_native_loop(result)


def test_repair_mutes_reported_escape_and_preserves_user_edits():
    editor = BUILDER.Editor(BUILDER.build(with_bypassed_video_outputs()))
    ids = editor.workflow["extra"]["zv_animate_once"]["new_node_ids"]
    for identifier in (78, 109):
        editor.nodes[identifier]["mode"] = 0
    for port in editor.nodes[ids["end"]]["inputs"]:
        port["name"] = port["name"].removeprefix("terminations.")
    editor.nodes[ids["end"]]["inputs"].append({"name": "terminations.termination0", "type": "*", "link": None})
    editor.nodes[ids["desk"]]["widgets_values"] = ["user material data stays untouched"]
    editor.nodes[789]["pos"] = [-50, 100]
    broken = editor.finish()
    broken["links"].reverse()
    original = copy.deepcopy(broken)
    # These re-enabled legacy previews are independent output roots again.
    with pytest.raises(Exception, match="reaches 109, 78 without passing through End Loop"):
        validate_native_loop(broken)
    repaired = BUILDER.repair_loop_outputs(broken)
    assert broken == original
    before, after = nodes_by_id(broken), nodes_by_id(repaired)
    assert before.keys() == after.keys()
    for identifier in before:
        if identifier not in (78, 109):
            assert before[identifier]["mode"] == after[identifier]["mode"]
        if identifier not in (ids["end"], ids["note"]):
            assert logic_without_link_metadata(before[identifier]) == logic_without_link_metadata(after[identifier])
    assert after[78]["mode"] == after[109]["mode"] == 2
    ports = after[ids["end"]]["inputs"]
    assert len({port["name"] for port in ports}) == len(ports)
    assert all(port["name"].startswith("terminations.") for port in ports if port["name"].startswith("termination"))
    old_links = {link[0]: link for link in broken["links"]}
    for link in repaired["links"]:
        if link[0] in old_links:
            assert link[:4] == old_links[link[0]][:4]
            assert link[5] == old_links[link[0]][5]
            if link[3] != ids["end"]:
                assert link == old_links[link[0]]
    assert BUILDER.repair_loop_outputs(repaired) == repaired
    validate_native_loop(repaired)


def test_active_outputs_never_read_old_media_loaders(source):
    prompt = resolved_prompt(BUILDER.build(source))
    pending = [identifier for identifier, node in prompt.items()
               if node["class_type"] in BUILDER.OUTPUT_TYPES | {"SaveVideo"}]
    reached = set()
    while pending:
        identifier = pending.pop()
        if identifier in reached:
            continue
        reached.add(identifier)
        node = prompt[identifier]
        assert node["class_type"] not in BUILDER.MATERIAL_LOADER_TYPES, identifier
        pending.extend(value[0] for value in node["inputs"].values()
                       if isinstance(value, list) and len(value) == 2 and str(value[0]) in prompt)


def with_mask_previews():
    editor = BUILDER.Editor(small_source())
    editor.add(BUILDER.make_node(284, "VHS_VideoCombine", "遮罩背景预览", [300, 500],
                               [("images", "IMAGE")], [("Filenames", "VHS_FILENAMES")],
                               values={"save_output": False, "filename_prefix": "original-mask"}))
    editor.add(BUILDER.make_node(515, "ImageAndMaskPreview", "旧种子预览", [0, 500],
                               [("image", "IMAGE"), ("mask", "MASK")], [("composite", "IMAGE")]))
    editor.wire(371, "images", 284, "images", "IMAGE")
    editor.wire(523, "IMAGE", 515, "image", "IMAGE")
    editor.wire(513, "masks", 515, "mask", "MASK")
    return editor.finish()


def assert_safe_mask_previews(workflow):
    ids = workflow["extra"]["zv_animate_once"]["new_node_ids"]
    nodes = nodes_by_id(workflow)
    assert nodes[284]["mode"] == 2
    assert nodes[515]["mode"] == 2
    assert input_source(workflow, 284, "images") == (ids["mask_gate"], "bg_images")
    assert input_source(workflow, ids["mask_seed"], "reference_image") == (523, "IMAGE")
    assert not any(link[1] == 284 and link[3] == ids["end"] for link in workflow["links"])
    # Only the lazy gate may pull in the mask path, even with video preview enabled.
    prompt = resolved_prompt(workflow)
    pending = [key for key, node in prompt.items() if node["class_type"] in BUILDER.OUTPUT_TYPES | {"SaveVideo"}]
    reached = set()
    while pending:
        key = pending.pop()
        if key in reached:
            continue
        reached.add(key)
        for name, value in prompt[key]["inputs"].items():
            if key == str(ids["mask_gate"]) and name in {"mask", "bg_images"}:
                continue
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in prompt:
                pending.append(value[0])
    assert reached.isdisjoint({"367", "513", "523", "515", str(ids["mask_seed"])})


def test_new_workflow_keeps_mask_previews_behind_global_gate():
    workflow = BUILDER.build(with_mask_previews())
    assert_safe_mask_previews(workflow)
    validate_native_loop(workflow)


def test_restore_mask_previews_preserves_materials_parameters_and_loop():
    editor = BUILDER.Editor(BUILDER.build(with_mask_previews()))
    ids = editor.workflow["extra"]["zv_animate_once"]["new_node_ids"]
    editor.nodes[284]["mode"] = 2
    editor.wire(371, "images", 284, "images", "IMAGE", replace=True)
    editor.nodes[ids["desk"]]["widgets_values"] = ["user material data"]
    old = editor.finish()
    before = copy.deepcopy(old)
    result = BUILDER.restore_mask_previews(old)
    assert old == before
    for identifier, node in nodes_by_id(old).items():
        if identifier not in {284, 515, ids["mask_seed"], ids["note"], ids["end"]}:
            assert logic_without_link_metadata(nodes_by_id(result)[identifier]) == logic_without_link_metadata(node)
    assert nodes_by_id(result)[284]["widgets_values"] == nodes_by_id(old)[284]["widgets_values"]
    assert_safe_mask_previews(result)
    assert BUILDER.restore_mask_previews(result) == result
    validate_native_loop(result)
