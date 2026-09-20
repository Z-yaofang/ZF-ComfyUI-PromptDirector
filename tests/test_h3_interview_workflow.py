import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import prepare_h3_workflow as preparation


def source_workflow():
    return json.loads((ROOT / "tests/fixtures/h3_focus_interview_topology.json").read_text(encoding="utf-8"))


def input_origin(workflow, node_id, name):
    nodes = {node["id"]: node for node in workflow["nodes"]}
    slot = next(i for i, port in enumerate(nodes[node_id]["inputs"]) if port["name"] == name)
    edge = next(edge for edge in workflow["links"] if edge[3:5] == [node_id, slot])
    return edge[1], nodes[edge[1]]["outputs"][edge[2]]["name"]


def test_preparation_keeps_source_data_and_nodes_verbatim():
    source = source_workflow()
    form = next(node for node in source["nodes"] if node["type"] == "ZVH3InterviewFormV2")
    form["widgets_values"] = ['{"user_text":"随意内容：不要补填空项。","unknown_future_field":"保留"}']
    original = copy.deepcopy(source)
    result = preparation.build(source)
    assert source == original
    assert result["nodes"] == source["nodes"]
    assert result["links"] == source["links"]
    assert not any(node["type"] == "ZVH3InterviewForm" for node in result["nodes"])


def test_three_stages_have_independent_systems_and_original_form_context():
    result = preparation.build(source_workflow())
    metadata = result["extra"]["zv_interview_v2"]
    nodes = {node["id"]: node for node in result["nodes"]}
    form_id, llms = metadata["form_id"], metadata["llm_ids"]
    for index, stage_id in enumerate(metadata["reverse_stage_ids"]):
        assert nodes[stage_id]["widgets_values"] == [preparation.STAGES[index], ""]
        for port in ("user_prompt", "material_context_json"):
            assert input_origin(result, stage_id, port) == (form_id, port)
        role, prompt = ("system_prompt", "custom_prompt") if index == 1 else ("role", "prompt")
        assert input_origin(result, llms[index], role) == (stage_id, "system_prompt")
        assert input_origin(result, llms[index], prompt) == (stage_id, "user_task")
        if index:
            assert input_origin(result, stage_id, "material_evidence") == (llms[0], "response")
    assert input_origin(result, metadata["reverse_stage_ids"][2], "chinese_user_prompt") == (llms[1], "output")
    assert not any(n["type"] == "StringFunction|pysssss" for n in result["nodes"])


def test_final_stage_sees_same_real_visuals_and_unloads():
    result = preparation.build(source_workflow())
    first_id, _, final_id = result["extra"]["zv_interview_v2"]["llm_ids"]
    nodes = {node["id"]: node for node in result["nodes"]}
    assert nodes[final_id]["type"] == "ZFPromptDirectorLocalLLM"
    visuals = [port["name"] for port in nodes[first_id]["inputs"] if port["type"] == "IMAGE" and port.get("link")]
    assert visuals
    for name in visuals:
        assert input_origin(result, first_id, name) == input_origin(result, final_id, name)
    assert nodes[final_id]["widgets_values_named"]["force_offload"] is True
    assert nodes[final_id]["widgets_values_named"]["skip_error"] is False


def test_prompt_only_mutes_every_non_preview_ancestor():
    source = source_workflow()
    result = preparation.build(source, prompt_only=True)
    required = set(result["extra"]["zv_interview_v2"]["preview_ids"])
    assert len(required) == 4
    while True:
        expanded = required | {edge[1] for edge in result["links"] if edge[3] in required}
        if expanded == required:
            break
        required = expanded
    assert len(result["nodes"]) == len(source["nodes"])
    for node in result["nodes"]:
        if node["id"] not in required:
            assert node["mode"] == 2
        if node["type"] in ("SamplerCustomAdvanced", "MiniMaxH3AVDecodeT8", "VHS_VideoCombine"):
            assert node["id"] not in required


def test_rejects_missing_stage():
    source = source_workflow()
    stage = next(node for node in source["nodes"] if node["type"] == "ZVH3ReverseStage")
    stage["widgets_values"][0] = "unknown"
    with pytest.raises(preparation.WorkflowBuildError, match="三个独立阶段"):
        preparation.build(source)


def test_cli_creates_only_new_files_and_refuses_overwrite(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(source_workflow(), ensure_ascii=False), encoding="utf-8")
    before = source.read_bytes()
    output, prompt = tmp_path / "full.json", tmp_path / "prompt-only.json"
    command = [sys.executable, str(ROOT / "tools/prepare_h3_workflow.py"), str(source),
               "--output", str(output), "--prompt-only-output", str(prompt)]
    run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert run.returncode == 0, run.stderr
    assert source.read_bytes() == before
    output_bytes = output.read_bytes()
    assert subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace").returncode != 0
    assert output.read_bytes() == output_bytes
