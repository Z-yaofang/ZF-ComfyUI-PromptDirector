import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("h3_reverse_pipeline_test_target", ROOT / "h3_focus" / "reverse_pipeline.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def context(mode="Ref2VA", materials=None, duration=10.0):
    return json.dumps({
        "schema_version": "zv-h3-material-context-v1",
        "mode": mode,
        "duration_seconds": duration,
        "target_fps": 24,
        "target_frames": round(duration * 24),
        "materials": materials or [],
    }, ensure_ascii=False)


def build(stage, **kwargs):
    values = {
        "user_prompt": "生成10秒视频，人物使用图1，只参考视频1的运镜。",
        "material_context_json": context(),
        "material_evidence": "<Picture 1>：已查看人物参考图。<Video 1>：观察到向右平移。未听取音频。",
        "chinese_user_prompt": "生成10秒视频。图1提供人物身份，视频1只提供向右平移的运镜参考。",
    }
    values.update(kwargs)
    return R.build_stage_prompts(stage, **values)


def test_stage_one_only_collects_evidence_not_planning_or_formatting():
    system, task = build("素材理解")
    assert "使用中文输出" in system
    assert "不负责导演规划" in system
    assert "未听取音频" in system
    assert "subject_definitions" not in system
    assert "integrated_multimodal_description" not in system
    assert set(json.loads(task)) == {"采访表整理的用户提示词", "素材对齐信息"}


def test_stage_two_outputs_chinese_intent_without_final_format_rules():
    system, task = build("中文意图整理")
    assert "其他正文必须中文" in system
    assert "不要输出“未指定”清单" in system
    assert "素材理解" in json.loads(task)["第一阶段素材理解结果"] or "已查看" in json.loads(task)["第一阶段素材理解结果"]
    assert "subject_definitions" not in system
    assert "integrated_multimodal_description" not in system
    assert "不要擅自选择" in system
    assert "不要把自己补出的内容说成用户已确认" in system
    assert "第二阶段中文用户提示词" not in json.loads(task)


def test_final_receives_both_aligned_evidence_and_chinese_user_prompt():
    _, task = build("H3提示词生成")
    payload = json.loads(task)
    assert set(payload) == {"采访表整理的用户提示词", "素材对齐信息", "第一阶段素材理解结果", "第二阶段中文用户提示词"}
    assert "只提供向右平移" in payload["第二阶段中文用户提示词"]
    assert "只参考视频1" in payload["采访表整理的用户提示词"]
    assert "未听取音频" in payload["第一阶段素材理解结果"]


@pytest.mark.parametrize("stage", R.STAGES)
def test_user_and_quoted_content_is_not_rewritten(stage):
    source = '让角色说：“No, 我不走！”\n招牌："营业中"。\n空白项不新增要求。'
    _, task = build(stage, user_prompt=source)
    assert json.loads(task)["采访表整理的用户提示词"] == source


@pytest.mark.parametrize("stage", R.STAGES)
def test_system_override_is_exact_without_hidden_preset_append(stage):
    override = "  我的自定义反推规则。\n允许任意我选择的格式。  "
    system, _ = build(stage, system_prompt=override, material_context_json=context("custom-mode"))
    assert system == override


@pytest.mark.parametrize("stage", R.STAGES)
def test_blank_override_selects_stage_preset(stage):
    system, _ = build(stage, system_prompt=" \n ")
    assert system.strip()
    if stage == "素材理解":
        assert system == R.EVIDENCE_SYSTEM
    elif stage == "中文意图整理":
        assert system == R.INTENT_SYSTEM
    else:
        assert system.startswith(R.FINAL_SYSTEM)


@pytest.mark.parametrize("mode", R.MODES)
def test_final_preset_is_selected_by_actual_mode(mode):
    system, _ = build("H3提示词生成", material_context_json=context(mode, duration=8.25))
    assert f"SELECTED MODE: {mode}. Target duration: 8.25 seconds." in system
    if mode in ("Ref2VA", "Hybrid"):
        assert "subject_definitions\nsummary\nretention_analysis\ndetailed_description\noverall_soundscape\nnon_diegetic_music" in system
        assert "Use this exact first line" not in system
        assert "Use this first line" not in system
    else:
        assert "subject_definitions" not in system
        assert "retention_analysis" not in system
        assert "integrated_multimodal_description:" in system
    if mode in ("FL2VA", "L2VA"):
        assert "8.25-second mark" in system
    if mode == "T2VA":
        assert "There is no picture-alignment instruction" in system
    if mode == "Hybrid":
        assert "local T8" in system


def test_roles_and_clocks_are_data_not_fixed_picture_or_target_timing_rules():
    materials = [{
        "call_label": "<Picture 1>", "kind": "picture", "origin": "reference",
        "route": "ref_images", "roles": ["style"], "role_labels": ["风格参考"],
        "purpose": "只取水彩质感，不参考人物。",
    }, {
        "call_label": "<Video 2>", "kind": "video", "origin": "reference",
        "route": "ref_videos", "roles": ["camera"],
        "source_in_seconds": 0.0, "source_out_seconds": 5.167,
        "timeline_in_seconds": 14.042, "timeline_out_seconds": 19.209,
        "purpose": "参考运镜",
    }]
    for stage in R.STAGES:
        system, task = build(stage, material_context_json=context(materials=materials))
        assert json.loads(task)["素材对齐信息"]["materials"] == materials
        assert "source_in_seconds" in system or "源素材时间" in system
        assert "timeline_in_seconds" in system or "素材台位置" in system
        assert "图1管人物" not in system
        assert "撑伞" not in system


def test_final_can_enrich_underspecified_requests_but_not_replace_them():
    system, _ = build("H3提示词生成")
    assert "Develop unspecified execution details" in system
    assert "without changing the requested subject, purpose, relationships or ending" in system
    assert "Do not invent observed facts" in system


@pytest.mark.parametrize("stage", R.STAGES)
@pytest.mark.parametrize("seam,guide", [
    ("overlap", {"source_segment_id": "segment-1", "frame_count": 48, "local_end_seconds": 2.0}),
    ("hard_cut", None),
])
def test_long_video_continuity_is_material_context_not_interview_system_rules(stage, seam, guide):
    value = json.loads(context())
    value["long_video"] = {"segment_index": 1, "seam": seam, "incoming_guide": guide}
    system, task = build(stage, material_context_json=json.dumps(value))
    assert json.loads(task)["素材对齐信息"]["long_video"] == value["long_video"]
    assert "hard_cut" in system
    assert "Picture/Video" in system
    assert "guide" in system


@pytest.mark.parametrize("stage", ["中文意图整理", "H3提示词生成"])
def test_later_stages_require_actual_stage_one_dependency(stage):
    with pytest.raises(ValueError, match="material_evidence"):
        build(stage, material_evidence=" ")


def test_stage_three_requires_chinese_prompt_dependency():
    with pytest.raises(ValueError, match="chinese_user_prompt"):
        build("H3提示词生成", chinese_user_prompt="")


def test_empty_media_still_supports_text_only_stage_one():
    system, task = build("素材理解", material_context_json=context("T2VA"), material_evidence="", chinese_user_prompt="")
    assert json.loads(task)["素材对齐信息"]["materials"] == []
    assert "无素材" in system


@pytest.mark.parametrize("value", ["broken", "[]", "{}", '{"materials":{}}'])
def test_bad_context_is_reported_as_a_wiring_error(value):
    with pytest.raises(ValueError, match="素材对齐信息"):
        build("素材理解", material_context_json=value)


def test_unknown_mode_not_silently_coerced_to_reference_mode():
    with pytest.raises(ValueError, match="已确定的 H3 模式"):
        build("H3提示词生成", material_context_json=context("auto"))


@pytest.mark.parametrize("duration", [0, -1, None, "10", True])
def test_builtin_final_preset_requires_real_duration(duration):
    with pytest.raises(ValueError, match="duration_seconds"):
        build("H3提示词生成", material_context_json=json.dumps({"mode": "T2VA", "duration_seconds": duration, "materials": []}))


def test_node_interface_and_optional_input_order():
    node = R.ZVH3ReverseStage()
    inputs = node.INPUT_TYPES()
    assert list(inputs["required"]) == ["stage", "user_prompt", "material_context_json", "system_prompt"]
    assert list(inputs["optional"]) == ["material_evidence", "chinese_user_prompt"]
    assert inputs["required"]["user_prompt"][1]["forceInput"]
    assert inputs["required"]["system_prompt"][1]["default"] == ""
    assert node.RETURN_NAMES == ("system_prompt", "user_task")
    assert node.RETURN_TYPES == ("STRING", "STRING")
    assert node.build("素材理解", "用户原话", context()) == R.build_stage_prompts("素材理解", "用户原话", context())
