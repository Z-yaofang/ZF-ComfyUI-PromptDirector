"""Form V2 API/physical routing integration; no model execution."""
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT / "tests/test_h3_v2.py"))
D, S, I = (H[key] for key in ("D", "S", "I"))
F = runpy.run_path(str(ROOT / "tests/test_h3_reference_detection.py"))


def v2_prompt():
    prompt = F["fixed_hub_prompt"]()
    prompt["172"]["class_type"] = "ZVH3InterviewFormV2"
    prompt["180"]["inputs"]["reference_plan"] = ["172", 6]
    prompt["190"] = F["node"]("ZVH3ReverseStage", stage="素材理解", user_prompt=["172", 0], material_context_json=["172", 1])
    prompt["146"]["inputs"]["prompt"] = ["190", 1]
    prompt["146"]["inputs"]["role"] = ["190", 0]
    return prompt


def test_v2_reference_plan_slot_and_independent_stage_are_recognized():
    result = D.validate_reference_hub_wiring(v2_prompt(), "172")
    assert result["hub_count"] == 1
    assert result["stage1_count"] == 1
    assert not result["errors"]


def test_v2_does_not_silently_accept_old_slot():
    prompt = v2_prompt()
    prompt["180"]["inputs"]["reference_plan"] = ["172", 8]
    assert D.validate_reference_hub_wiring(prompt, "172")["hub_count"] == 0


def test_api_returns_exact_pure_form_output_and_no_reverse_instructions():
    project = H["source"](0, 0, 0)
    state = I.empty_interview()
    state["intent"] = "主角转身。不要添加对白。"
    result = S.plan_interview({"state": state, "media_project": project, "align": True})
    compiled = I.compile_interview(result["state"], project)
    assert result["user_prompt"] == compiled["user_prompt"]
    assert state["intent"] in result["user_prompt"]
    assert "未指定" not in result["user_prompt"]
    assert not {"system_prompt", "stage1_task", "stage2_prefix", "stage3_prefix"}.intersection(result)
    assert json.loads(result["material_context_json"])["mode"] == "T2VA"


def test_v2_plan_endpoint_uses_fixed_hub_not_old_output_route():
    project = H["source"](0, 0, 0)
    result = S.plan_interview({"state": I.empty_interview(), "media_project": project, "align": True,
        "prompt": v2_prompt(), "interview_id": "172"})
    assert result["wiring"]["hub_count"] == 1
    assert not result["wiring"]["errors"]
