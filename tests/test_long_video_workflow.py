import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests" / "fixtures" / "h3_focus_interview_topology.json"
EXAMPLE = ROOT / "docs" / "examples" / "H3焦点访谈_长视频分段.json"
MASK_EXAMPLE = ROOT / "docs" / "examples" / "H3焦点访谈_长视频蒙版.json"
SPEC = importlib.util.spec_from_file_location(
    "zf_long_video_workflow_builder", ROOT / "tools" / "build_long_video_workflow.py",
)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def source_workflow(path=SOURCE):
    path = Path(path)
    assert path.is_file(), f"missing H3 source workflow: {path}"
    return json.loads(path.read_text(encoding="utf-8-sig"))


def one(workflow, kind):
    found = [node for node in workflow["nodes"] if node["type"] == kind]
    assert len(found) == 1, (kind, len(found))
    return found[0]


def input_link(workflow, node, name):
    port = next(row for row in node["inputs"] if row["name"] == name)
    return next(row for row in workflow["links"] if row[0] == port["link"])


def output_name(workflow, link):
    node = next(row for row in workflow["nodes"] if row["id"] == link[1])
    return node, node["outputs"][link[2]]["name"]


def prompt_from_ui(workflow):
    links = {row[0]: row for row in workflow["links"]}
    result = {}
    for node in workflow["nodes"]:
        inputs = {}
        for port in node.get("inputs", []):
            if port.get("link") in links:
                link = links[port["link"]]
                inputs[port["name"]] = [str(link[1]), link[2]]
        for name, value in (node.get("widgets_values_named") or {}).items():
            inputs.setdefault(name, value)
        result[str(node["id"])] = {"class_type": node["type"], "inputs": inputs}
    return result


def test_builder_rewrites_real_h3_graph_with_dynamic_ids_and_named_ports():
    source = source_workflow()
    original = copy.deepcopy(source)
    result = BUILDER.build(source)
    assert source == original
    BUILDER.Editor(result).validate()

    source_max = max(node["id"] for node in source["nodes"])
    new_ids = result["extra"]["zv_long_video"]["new_node_ids"]
    assert min(new_ids.values()) > source_max
    assert len(new_ids.values()) == len(set(new_ids.values()))
    assert not ({"ZVH3InterviewFormV2", "ZVProcessingWindowOutlet", "VHS_VideoCombine", "easy showAnything", "PreviewAny"}
                & {node["type"] for node in result["nodes"]})

    start, end = one(result, "StartLoop"), one(result, "EndLoop")
    assert [row["name"] for row in start["inputs"]] == [
        "mode", "mode.num_iterations", "cache_iterations", "parent_iteration", "initial_iteration_value",
    ]
    assert start["widgets_values"] == ["simple", 3, False]
    assert start["widgets_values_named"]["cache_iterations"] is False
    assert [row["name"] for row in end["inputs"]] == ["output_value", "next_iteration_value", "accumulate"]
    assert end["widgets_values"] == [False]
    assert end["widgets_values_named"]["accumulate"] is False

    entry = one(result, "ZVLongVideoExecutionEntry")
    assert [port["name"] for port in entry["outputs"]] == [
        "segment_context", "reference_plan", "user_prompt", "material_context_json", "duration_seconds",
        "frame_count", "model_length", "model_adapter", "has_guide", "guide_frames", "guide_audio",
        "guide_frame_idx", "segment_id", "report",
    ]
    stages = [node for node in result["nodes"] if node["type"] == "ZVH3ReverseStage"]
    assert len(stages) == 3
    for stage in stages:
        for port in ("user_prompt", "material_context_json"):
            source_node, output = output_name(result, input_link(result, stage, port))
            assert (source_node["id"], output) == (entry["id"], port)
    outlet = one(result, "ZVH3ReferenceOutlet")
    reference_source, reference_output = output_name(result, input_link(result, outlet, "reference_plan"))
    assert reference_source["id"] == entry["id"] and reference_output == "reference_plan"

    recorder = one(result, "ZVLongVideoSegmentRecorder")
    final_source, final_output = output_name(result, input_link(result, recorder, "final_audio"))
    generated_source, generated_output = output_name(result, input_link(result, recorder, "generated_audio"))
    assert final_source["id"] == outlet["id"] and final_output == "final_audio"
    assert generated_source["type"] == "MiniMaxH3AVDecodeT8" and generated_output == "generated_audio"
    assert not [node for node in result["nodes"] if node["type"] == "ZVH3MaskedSegmentLatent"]

    conditionings = [node for node in result["nodes"] if node["type"] == "MiniMaxH3AudioConditioningT8"]
    assert len(conditionings) == 2
    for conditioning in conditionings:
        assert conditioning["widgets_values_named"]["task_type"] == "auto"
        source_node, source_output = output_name(result, input_link(result, conditioning, "length"))
        assert source_node["id"] == entry["id"] and source_output == "model_length"
    assert len([node for node in result["nodes"] if node["type"] == "MiniMaxH3AddGuide"]) == 2
    assert len([node for node in result["nodes"] if node["type"] == "ComfySwitchNode"]) == 2

    desk = one(result, "ZVUniversalMediaEvidenceDesk")
    project = json.loads(desk["widgets_values"][0])
    assert project["assets"] == project["picture_track"] == project["video_track"] == project["audio_track"] == []
    assert result["extra"]["zv_long_video"]["mask_status"].startswith("mask clock/bundle/slice protocol only")
    mask_slice = one(result, "ZVSegmentMaskSlice")
    assert all(not (row.get("links") or []) for row in mask_slice["outputs"])
    mask_source, mask_output = output_name(result, input_link(result, mask_slice, "segment_index"))
    assert mask_source["id"] == start["id"] and mask_output == "iteration_index"
    note_text = "\n".join(node["widgets_values"][0] for node in result["nodes"] if node["type"] == "Note")
    assert "整条长视频不受单次 15 秒上限约束" in note_text
    assert "source_auto" in note_text and "没有接入当前普通生成路径" in note_text and "SAM3、SeC" in note_text
    assert "final_audio" in note_text and "generated_audio" in note_text
    assert "44100 Hz/2 ch" in note_text and "缺失音频补同钟静音" in note_text
    assert all(node["widgets_values_named"]["text"] == node["widgets_values"][0]
               for node in result["nodes"] if node["type"] == "Note")


def test_mask_mode_activates_only_the_explicit_c1_adapter_path():
    result = BUILDER.build(source_workflow(), mask_mode=True)
    BUILDER.Editor(result).validate()

    adapter = one(result, "ZVH3MaskedSegmentLatent")
    high_restore = one(result, "ZVH3MaskedLatentRestore")
    compose = one(result, "ZVH3MaskedFrameCompose")
    recorder = one(result, "ZVLongVideoSegmentRecorder")
    final_source, final_output = output_name(result, input_link(result, recorder, "final_audio"))
    assert final_source["id"] == adapter["id"] and final_output == "final_audio"
    frame_source, frame_output = output_name(result, input_link(result, recorder, "frames"))
    assert frame_source["id"] == compose["id"] and frame_output == "frames"

    conditionings = [node for node in result["nodes"] if node["type"] == "MiniMaxH3AudioConditioningT8"]
    for conditioning in conditionings:
        source, output = output_name(result, input_link(result, conditioning, "length"))
        assert source["id"] == adapter["id"] and output == "model_length"

    low = next(node for node in conditionings if node["title"].startswith("LOW"))
    low_guide = next(
        node for node in result["nodes"]
        if node["type"] == "MiniMaxH3AddGuide" and node["title"].startswith("LOW")
    )
    source, output = output_name(result, input_link(result, low_guide, "latent"))
    assert source["id"] == adapter["id"] and output == "av_latent"
    assert not any(
        link[1] == low["id"] and low["outputs"][link[2]]["name"] == "av_latent"
        for link in result["links"]
    )

    source, output = output_name(result, input_link(result, adapter, "source_audio"))
    assert source["type"] == "ZVSegmentVideoMaskSource" and output == "source_audio"
    source, output = output_name(result, input_link(result, adapter, "masked_segments"))
    assert source["type"] == "ZVMaskedSegmentBundle" and output == "masked_segments"
    source, output = output_name(result, input_link(result, high_restore, "source_latent"))
    assert source["id"] == adapter["id"] and output == "av_latent"
    source, output = output_name(result, input_link(result, high_restore, "av_latent"))
    assert source["type"] == "MiniMaxH3TwoPassLatentReconcileT8Advanced" and output == "av_latent"
    mixer = one(result, "MiniMaxH3TwoPassDetailMixerT8Advanced")
    source, output = output_name(result, input_link(result, mixer, "av_latent"))
    assert source["id"] == high_restore["id"] and output == "av_latent"
    sampler_latents = [
        output_name(result, input_link(result, node, "latent_image"))
        for node in result["nodes"] if node["type"] == "SamplerCustomAdvanced"
    ]
    assert sum(source["id"] == high_restore["id"] and output == "av_latent"
               for source, output in sampler_latents) == 1
    source, output = output_name(result, input_link(result, compose, "generated_frames"))
    assert source["type"] == "MiniMaxH3AVDecodeT8" and output == "frames"
    for port, expected_output in (("source_frames", "model_frames"), ("model_mask", "model_mask")):
        source, output = output_name(result, input_link(result, compose, port))
        assert source["id"] == adapter["id"] and output == expected_output
    for port, expected_node, expected_output in (
        ("mask_source_evidence", adapter, "clock_evidence_json"),
        ("mask_high_evidence", high_restore, "evidence_json"),
        ("mask_compose_evidence", compose, "evidence_json"),
    ):
        source, output = output_name(result, input_link(result, recorder, port))
        assert source["id"] == expected_node["id"] and output == expected_output
    assert result["extra"]["zv_long_video"]["mask_status"].startswith("C1 full-frame")
    note_text = "\n".join(node["widgets_values"][0] for node in result["nodes"] if node["type"] == "Note")
    assert "H3 nested AV latent" in note_text
    assert BUILDER.build_masked(source_workflow()) == result


def test_generated_graph_has_one_output_root_and_closed_loop_protocol():
    result = BUILDER.build(source_workflow())
    prompt = prompt_from_ui(result)
    assert not any(row["class_type"] == "easy showAnything" for row in prompt.values())
    assert {node_id for node_id, row in prompt.items() if row["class_type"] == "SaveVideo"} == {
        str(one(result, "SaveVideo")["id"]),
    }

    setup, start = one(result, "ZVLongVideoExecutionSetup"), one(result, "StartLoop")
    entry, recorder = one(result, "ZVLongVideoExecutionEntry"), one(result, "ZVLongVideoSegmentRecorder")
    end, finish = one(result, "EndLoop"), one(result, "ZVLongVideoExecutionEnd")
    checks = (
        (start, "mode.num_iterations", setup, "segment_count"),
        (entry, "iteration_index", start, "iteration_index"),
        (entry, "previous_result", start, "current_iteration_value"),
        (recorder, "previous_result", start, "current_iteration_value"),
        (end, "output_value", recorder, "run_result"),
        (end, "next_iteration_value", recorder, "run_result"),
        (finish, "run_result", end, "outputs"),
    )
    for target, target_input, expected_source, expected_output in checks:
        source, output = output_name(result, input_link(result, target, target_input))
        assert source["id"] == expected_source["id"] and output == expected_output


def test_optional_host_loop_validator_integration():
    comfy_value = os.environ.get("ZV_COMFY_ROOT")
    if not comfy_value:
        pytest.skip("set ZV_COMFY_ROOT to run the host comfy_execution loop validator")
    comfy = Path(comfy_value).resolve()
    real_source = os.environ.get("ZV_H3_REAL_SOURCE_WORKFLOW")
    source_path = Path(real_source).resolve() if real_source else SOURCE
    if str(comfy) not in sys.path:
        sys.path.insert(0, str(comfy))
    previous = {
        key: value for key, value in tuple(sys.modules.items())
        if key == "comfy_execution" or key.startswith("comfy_execution.")
    }
    for key in previous:
        sys.modules.pop(key, None)
    try:
        validate_loops = importlib.import_module("comfy_execution.validation").validate_loops
    finally:
        for key in tuple(sys.modules):
            if key == "comfy_execution" or key.startswith("comfy_execution."):
                sys.modules.pop(key, None)
        sys.modules.update(previous)

    result = BUILDER.build(source_workflow(source_path))
    prompt = prompt_from_ui(result)
    starts = {node_id for node_id, row in prompt.items() if row["class_type"] == "StartLoop"}
    ends = {node_id for node_id, row in prompt.items() if row["class_type"] == "EndLoop"}
    # The copied workflow removes the five easy showAnything output roots; its
    # only active root is the final SaveVideo.
    outputs = {node_id for node_id, row in prompt.items() if row["class_type"] == "SaveVideo"}
    assert not any(row["class_type"] == "easy showAnything" for row in prompt.values())
    assert validate_loops(prompt, outputs, prompt, starts, ends) == {
        str(one(result, "StartLoop")["id"]): str(one(result, "EndLoop")["id"]),
    }


def test_builder_rejects_schema_drift_and_cli_refuses_overwrite(tmp_path):
    broken = source_workflow()
    conditioning = next(node for node in broken["nodes"] if node["type"] == "MiniMaxH3AudioConditioningT8")
    next(row for row in conditioning["inputs"] if row["name"] == "length")["name"] = "old_length"
    with pytest.raises(BUILDER.WorkflowBuildError, match="length"):
        BUILDER.build(broken)

    broken_size = source_workflow()
    desk = one(broken_size, "ZVUniversalMediaEvidenceDesk")
    width = next(row for row in desk["inputs"] if row["name"] == "width")
    width["link"] = None
    broken_size["links"] = [row for row in broken_size["links"] if row[0] != 376]
    with pytest.raises(BUILDER.WorkflowBuildError, match="素材台 width"):
        BUILDER.build(broken_size)

    broken_scale = source_workflow()
    scale = next(node for node in broken_scale["nodes"] if node["type"] == "ImpactFloat")
    scale["widgets_values"] = [1.5]
    scale["widgets_values_named"]["value"] = 1.5
    with pytest.raises(BUILDER.WorkflowBuildError, match="同画布 1x"):
        BUILDER.build(broken_scale, mask_mode=True)

    output = tmp_path / "exists.json"
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        BUILDER.main([str(SOURCE), str(output)])
    assert output.read_text(encoding="utf-8") == "{}"


def test_committed_example_is_deterministic_and_contains_no_media_handles():
    expected = BUILDER.build(source_workflow())
    actual = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert actual == expected
    text = EXAMPLE.read_text(encoding="utf-8")
    assert "originals/" not in text and "source_handle" not in text

    masked_expected = BUILDER.build(source_workflow(), mask_mode=True)
    masked_actual = json.loads(MASK_EXAMPLE.read_text(encoding="utf-8"))
    assert masked_actual == masked_expected
    masked_text = MASK_EXAMPLE.read_text(encoding="utf-8")
    assert "originals/" not in masked_text and "source_handle" not in masked_text
