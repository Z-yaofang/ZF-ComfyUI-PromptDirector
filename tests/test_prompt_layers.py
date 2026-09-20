import importlib.util
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "zf_prompt_director_prompt_layer_tests"


def _load_nodes_module():
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules.setdefault(PACKAGE_NAME, package)

    comfy_execution = types.ModuleType("comfy_execution")
    graph = types.ModuleType("comfy_execution.graph")
    graph.ExecutionBlocker = type("ExecutionBlocker", (), {})
    comfy_execution.graph = graph

    module_name = f"{PACKAGE_NAME}.nodes"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "nodes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    stubs = {"comfy_execution": comfy_execution, "comfy_execution.graph": graph}
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec.loader.exec_module(module)
    finally:
        # Restore only these stubs; unloading newly imported native modules
        # (for example torch) makes subsequent test collection unsafe.
        for name, original in previous.items():
            if original is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


MODULE = _load_nodes_module()


def test_registration_loader_preserves_existing_host_graph_modules(monkeypatch):
    host = types.ModuleType("comfy_execution")
    graph = types.ModuleType("comfy_execution.graph")
    host.graph = graph
    monkeypatch.setitem(sys.modules, "comfy_execution", host)
    monkeypatch.setitem(sys.modules, "comfy_execution.graph", graph)
    _load_nodes_module()
    assert sys.modules["comfy_execution"] is host
    assert sys.modules["comfy_execution.graph"] is graph
    assert host.graph is graph


def test_video_nodes_register_only_new_zv_ids_and_socket():
    for node_id in ("ZVUniversalMediaEvidenceDesk", "ZVProcessingWindowOutlet", "ZVH3InterviewFormV2", "ZVH3ReverseStage"):
        cls = getattr(MODULE, node_id)
        assert MODULE.NODE_CLASS_MAPPINGS[node_id] is cls
        assert cls.__name__ == node_id
        assert list(MODULE.NODE_CLASS_MAPPINGS.values()).count(cls) == 1
    for old_id in ("ZFUniversalMediaEvidenceDesk", "ZFH3FocusCompiler", "ZVH3FocusCompiler", "ZVH3InterviewForm", "ZVPictureSlotOutlet", "ZVVideoSlotOutlet", "ZVAudioSlotOutlet", "ZFBlueprintParser", "ZFSinglePromptTask"):
        assert old_id not in MODULE.NODE_CLASS_MAPPINGS
        assert old_id not in MODULE.NODE_DISPLAY_NAME_MAPPINGS
        assert not hasattr(MODULE, old_id)
    assert MODULE.ZVUniversalMediaEvidenceDesk.RETURN_TYPES == ("ZV_MEDIA_PROJECT", "STRING", "ZV_ORIGINAL_SOURCES")
    assert MODULE.ZVUniversalMediaEvidenceDesk.RETURN_NAMES == ("media_project", "project_json", "原素材来源")


def test_video_nodes_use_zv_display_names_and_categories():
    expected = {
        "ZVUniversalMediaEvidenceDesk": ("ZV 通用素材取证台", "ZV/视频创作/素材取证"),
        "ZVProcessingWindowOutlet": ("ZV 处理窗口参数出口", "ZV/视频创作/素材取证"),
        "ZVH3InterviewFormV2": ("ZV H3 采访表 · 收集对齐整理", "ZV/视频创作/H3"),
        "ZVH3ReverseStage": ("ZV H3 独立反推阶段", "ZV/视频创作/H3"),
    }
    for node_id, (display_name, category) in expected.items():
        assert MODULE.NODE_DISPLAY_NAME_MAPPINGS[node_id] == display_name
        assert MODULE.NODE_CLASS_MAPPINGS[node_id].CATEGORY == category


def test_portrait_registers_only_zi_id_with_unchanged_output_contract():
    cls = MODULE.ZIPortraitPromptGenerator
    assert MODULE.NODE_CLASS_MAPPINGS["ZIPortraitPromptGenerator"] is cls
    assert list(MODULE.NODE_CLASS_MAPPINGS.values()).count(cls) == 1
    assert cls.__name__ == "ZIPortraitPromptGenerator"
    assert cls.CATEGORY == "ZI/图片创作/人像提示词"
    assert MODULE.NODE_DISPLAY_NAME_MAPPINGS["ZIPortraitPromptGenerator"] == "ZI 人像提示词生成器"
    assert "ZFPortraitPromptGenerator" not in MODULE.NODE_CLASS_MAPPINGS
    assert "ZFPortraitPromptGenerator" not in MODULE.NODE_DISPLAY_NAME_MAPPINGS
    assert not hasattr(MODULE, "ZFPortraitPromptGenerator")
    assert cls.RETURN_TYPES == ("STRING", "STRING", "STRING")
    assert cls.RETURN_NAMES == ("portrait_prompt", "selection_json", "status")
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")
    assert 'const NODE_NAME = "ZIPortraitPromptGenerator"' in source
    assert 'const EXTENSION_NAME = "ZI.PromptDirector.PortraitGenerator"' in source
    assert "ZFPortraitPromptGenerator" not in source


def _build(**overrides):
    values = {
        "enabled": True,
        "user_prompt": "一名女孩坐在明亮教室的讲台上读书",
        "theme": "【人物资产】\n青春校园人物与整洁教室。\n\n【边界】\n保持日常、端庄的年龄表达，不把人物成人化。",
        "width": 1024,
        "height": 1024,
        "count": 1,
        "selection_json": MODULE.DEFAULT_SELECTION_JSON,
        "image_model_level": MODULE.MODEL_LEVELS[1],
    }
    values.update(overrides)
    return MODULE.ZFPromptDirector().build(**values)


def test_user_prompt_remains_highest_priority_and_world_boundary_is_silent():
    system_prompt, tasks, original, *_ = _build()
    task = tasks[0]

    assert original == "一名女孩坐在明亮教室的讲台上读书"
    assert "用户提示拥有最高内容优先级" in system_prompt
    assert "先完整写清用户明确内容" in task
    assert original in task
    assert "青春校园人物与整洁教室" in task

    assert "【边界】" not in task
    assert "不把人物成人化" not in task
    assert "【本次世界观边界（内部控制，只执行不复述）】" in system_prompt
    assert "不把人物成人化" in system_prompt


def test_empty_user_prompt_keeps_theme_creation_and_variation_logic():
    system_prompt, tasks, original, enabled, _, _, creation_mode, *_ = _build(
        user_prompt="",
        count=2,
    )

    assert original == ""
    assert enabled is True
    assert creation_mode == "主题创作"
    assert "用户提示为空时" in system_prompt
    assert len(tasks) == 2
    for task in tasks:
        assert "（空；本图采用主题创作模式）" in task
        assert "青春校园人物与整洁教室" in task
        assert "【本图变化方向】" in task
        assert "用途与视觉方法主导" in task


def test_expression_and_text_controls_no_longer_enter_writer_tasks():
    system_prompt, tasks, *_ = _build()
    task = tasks[0]

    assert "【本次表达完整性（内部控制，不得成文）】" in system_prompt
    assert "【文字与内部标签纪律】" in system_prompt
    assert "关键边界可以使用一句简短约束" not in system_prompt

    for leaked_fragment in (
        "【成文密度】",
        "【文字限制】",
        "除非用户核心明确要求出现文字",
        "每只手一个明确任务",
        "世界观名称不得变成标题",
    ):
        assert leaked_fragment not in task


def test_storyboard_keeps_story_logic_without_control_layer_echo():
    selection = json.dumps(
        [
            {
                "purpose": "storyboard_sequence",
                "visual": "geometric_panel_grid",
                "enabled": True,
                "strength": 1.0,
            }
        ],
        ensure_ascii=False,
    )
    system_prompt, tasks, _, _, _, _, creation_mode, *_ = _build(
        count=4,
        selection_json=selection,
    )
    task = tasks[0]

    assert creation_mode.startswith("故事分镜")
    assert len(tasks) == 1
    assert "有效分镜4格" in task
    assert "用户提示构成故事铁案" in task
    assert "【连续性资产】" in task
    assert "【成文密度】" not in task
    assert "【文字限制】" not in task
    assert "【本次表达完整性（内部控制，不得成文）】" in system_prompt
