import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "flow_nodes.py"
SPEC = importlib.util.spec_from_file_location("zf_prompt_director_flow_nodes", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_any_filter_distinguishes_none_empty_text_zero_and_false():
    node = MODULE.ZFPromptDirectorAnyFilter()

    assert node.filter_value(value=[])[0] == [None]
    assert node.filter_value(value=[None])[0] == [None]
    assert node.filter_value(value=["  "])[0] == [None]
    assert node.filter_value(value=[0])[0] == [0]
    assert node.filter_value(value=[False])[0] == [False]


def test_any_filter_can_emit_empty_text_or_remove_literal_content():
    node = MODULE.ZFPromptDirectorAnyFilter()

    empty = node.filter_value(
        condition=node.CONDITION_ALWAYS,
        output_action=node.OUTPUT_EMPTY_TEXT,
        value=["保留也应被截断"],
    )
    removed = node.filter_value(
        condition=node.CONDITION_CONTAINS,
        output_action=node.OUTPUT_REMOVE,
        filter_content="测试\nABC",
        case_sensitive=False,
        value=["这是测试 abc 文本"],
    )

    assert empty[0] == [""]
    assert removed[0] == ["这是  文本"]


def test_text_selector_requests_and_returns_only_selected_route():
    node = MODULE.ZFPromptDirectorMultiTextSelector()

    assert node.check_lazy_status(4, 3, text_1=None, text_3=None) == ["text_3"]
    assert node.select(4, 3, text_1="第一路", text_3="第三路") == ("第三路", 3)
    assert node.select(4, 0, text_1="第一路") == ("", 0)


def test_text_selector_clamps_saved_route_to_visible_inputs():
    node = MODULE.ZFPromptDirectorMultiTextSelector()

    assert node.select(4, 99, text_4="第四路") == ("第四路", 4)
    assert node.select(0, -5, text_1="第一路") == ("第一路", 1)


def test_new_nodes_have_prompt_director_specific_registration_ids():
    root = MODULE_PATH.parent
    nodes_source = (root / "nodes.py").read_text(encoding="utf-8")
    frontend_source = (root / "web" / "multi_text_selector.js").read_text(encoding="utf-8")

    assert '"ZFPromptDirectorAnyFilter": ZFPromptDirectorAnyFilter' in nodes_source
    assert '"ZFPromptDirectorMultiTextSelector": ZFPromptDirectorMultiTextSelector' in nodes_source
    assert 'const NODE_NAME = "ZFPromptDirectorMultiTextSelector"' in frontend_source
    assert "ZFAnyFilter\"" not in frontend_source
    assert "ZFMultiTextSwitch\"" not in frontend_source
