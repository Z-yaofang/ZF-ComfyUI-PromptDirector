import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location("zf_portrait_nodes_tests", ROOT / "portrait_nodes.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _option(field_id, adult=None):
    field = MODULE.PORTRAIT_FIELD_BY_ID[field_id][1]
    return next(
        item
        for item in field["options"]
        if item.get("text") and item.get("value") not in ("", "不启用")
        and (adult is None or bool(item.get("adult")) is adult)
    )


def _state(
    selected=None,
    overrides=None,
    adult_content=False,
    section_enabled=None,
    option_overrides=None,
    locked=None,
    section_locked=None,
    section_lock_items=None,
):
    return json.dumps(
        {
            "version": 5,
            "adult_content": adult_content,
            "selected": selected or {},
            "enabled": {},
            "overrides": overrides or {},
            "pinned": {},
            "locked": locked or {},
            "section_locked": section_locked or {},
            "section_lock_items": section_lock_items or {},
            "section_enabled": section_enabled or {},
            "option_overrides": option_overrides or {},
        },
        ensure_ascii=False,
    )


def test_catalog_contains_editable_normal_and_adult_fields():
    fields = [field for _, field in MODULE.PORTRAIT_FIELDS]
    assert len(fields) >= 90
    assert all(field.get("editable") for field in fields)
    assert any(field.get("adult") for field in fields)
    assert any(not field.get("adult") for field in fields)


def test_pose_and_action_are_real_sections_without_mode_or_custom_pages():
    sections = {section["id"]: section for section in MODULE.PORTRAIT_CATALOG["sections"]}
    assert "pose" not in sections
    assert {"posture", "action"}.issubset(sections)
    assert [field["label"] for field in sections["posture"]["fields"] if not field.get("adult")] == [
        "仰卧", "俯卧", "侧卧", "跪姿", "坐姿", "站姿", "蹲姿", "悬空", "特殊姿态",
    ]
    assert [field["label"] for field in sections["action"]["fields"] if not field.get("adult")] == [
        "姿态转换", "行走与步伐", "跳跃动作", "旋转动作",
    ]
    removed_ids = {
        "personCustom", "nsfwCustom1", "nsfwCustom2",
        "sfwSimMode", "sfwSimCoreCat", "sfwSimCat", "sfwSimPick",
        "simMode", "simCoreCat", "simCat", "simPick",
    }
    assert removed_ids.isdisjoint(MODULE.PORTRAIT_FIELD_BY_ID)
    assert MODULE.PORTRAIT_FIELD_BY_ID["race"][1]["label"] == "人种"


def test_legacy_pose_selection_migrates_to_the_new_action_group():
    legacy_state = _state(selected={"sfwSimPick": "I023"})
    prompt, _, selection_json, _ = MODULE.ZFPortraitPromptGenerator().generate(legacy_state)
    migrated = json.loads(selection_json)

    assert "原地旋转中定格" in prompt
    assert migrated["version"] == 5
    assert migrated["selected"]["actionSpinning"] == "I023"
    assert "sfwSimPick" not in migrated["selected"]

    posture_state = _state(selected={"sfwSimPick": "F001"})
    posture_prompt, _, posture_selection, _ = MODULE.ZFPortraitPromptGenerator().generate(posture_state)
    posture_migrated = json.loads(posture_selection)
    assert "站立，双腿并拢" in posture_prompt
    assert posture_migrated["selected"]["postureStanding"] == "F001"


def test_legacy_section_lock_snapshots_only_existing_selections():
    lens = _option("lens")
    legacy = json.loads(_state(selected={"lens": lens["value"]}, section_locked={"camera": True}))
    legacy["version"] = 4
    _, _, selection_json, _ = MODULE.ZFPortraitPromptGenerator().generate(json.dumps(legacy, ensure_ascii=False))
    migrated = json.loads(selection_json)

    assert migrated["version"] == 5
    assert migrated["section_lock_items"]["lens"] is True
    assert "viewpoint" not in migrated["section_lock_items"]


def test_portrait_prompt_and_world_asset_work_without_reverse_analysis():
    lens = _option("lens")
    age = _option("age")
    scene = _option("scene")
    state = _state(selected={"lens": lens["value"], "age": age["value"], "scene": scene["value"]})

    prompt, world_asset, selection_json, status = MODULE.ZFPortraitPromptGenerator().generate(state)

    assert lens["text"] in prompt
    assert scene["text"] in prompt
    assert "【人物资产库｜常规】" in world_asset
    assert scene["text"] in world_asset
    assert json.loads(selection_json)["adult_content"] is False
    assert "成人内容关闭" in status


def test_adult_material_is_excluded_while_switch_is_off():
    adult_field = next(field for _, field in MODULE.PORTRAIT_FIELDS if field.get("adult") and field.get("options"))
    adult_option = next(item for item in adult_field["options"] if item.get("text") and item.get("value") != "不启用")
    state = _state(selected={adult_field["id"]: adult_option["value"]}, adult_content=True)

    prompt, world_asset, *_ = MODULE.ZFPortraitPromptGenerator().generate(
        state,
        adult_content=False,
    )

    assert adult_option["text"] not in prompt
    assert adult_option["text"] not in world_asset
    assert "【成人扩展边界】" not in world_asset


def test_adult_mode_requires_adult_context_and_blocks_minor_override():
    adult_field = next(field for _, field in MODULE.PORTRAIT_FIELDS if field.get("adult") and field.get("options"))
    adult_option = next(item for item in adult_field["options"] if item.get("text") and item.get("value") != "不启用")
    selected = {adult_field["id"]: adult_option["value"], "age": _option("age")["value"]}
    safe_state = _state(selected=selected, adult_content=True)

    prompt, world_asset, _, status = MODULE.ZFPortraitPromptGenerator().generate(
        safe_state,
        adult_content=True,
    )
    assert adult_option["text"] in prompt
    assert "明确的成年人物" in prompt
    assert adult_option["text"] in world_asset
    assert "【成人扩展边界】" in world_asset
    assert "成人内容开启" in status

    blocked_state = _state(
        selected=selected,
        overrides={"age": "16岁"},
        adult_content=True,
    )
    blocked_prompt, blocked_asset, blocked_selection, blocked_status = MODULE.ZFPortraitPromptGenerator().generate(
        blocked_state,
        adult_content=True,
    )
    assert adult_option["text"] not in blocked_prompt
    assert "【成人扩展边界】" not in blocked_asset
    assert json.loads(blocked_selection)["adult_content"] is False
    assert "未参与输出" in blocked_status


def test_reference_analysis_is_optional_material_not_a_random_dependency():
    state = _state(selected={"lens": _option("lens")["value"]})
    prompt_without_reference, *_ = MODULE.ZFPortraitPromptGenerator().generate(state)
    prompt_with_reference, *_ = MODULE.ZFPortraitPromptGenerator().generate(
        state,
        reference_analysis=json.dumps(
            {
                "image_overview": "窗边半身人像",
                "lighting_and_atmosphere": "柔和侧光",
            },
            ensure_ascii=False,
        ),
    )
    assert prompt_without_reference
    assert "窗边半身人像" in prompt_with_reference
    assert "柔和侧光" in prompt_with_reference


def test_frontend_repair_only_clears_overrides():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")
    repair_block = source[source.index('const repair = makeButton("节点修复")'):]
    repair_block = repair_block[:repair_block.index("const advanced =")]
    assert "state.overrides = {}" in repair_block
    assert "state.option_overrides = {}" in repair_block
    assert "state.selected = {}" not in repair_block
    assert "state.pinned = {}" not in repair_block
    assert "state.locked = {}" not in repair_block
    assert "state.section_lock_items = {}" not in repair_block


def test_world_asset_is_the_complete_catalog_and_does_not_depend_on_random_selection():
    empty_asset = MODULE.ZFPortraitPromptGenerator().generate(_state())[1]
    selected_asset = MODULE.ZFPortraitPromptGenerator().generate(
        _state(selected={"lens": _option("lens")["value"], "scene": _option("scene")["value"]})
    )[1]

    assert empty_asset == selected_asset
    assert len(empty_asset) > 25000
    assert "镜头类型（必选）" in empty_asset
    assert "场景（必选）" in empty_asset
    assert "服装与配饰" in empty_asset


def test_adult_toggle_adds_the_complete_adult_asset_catalog():
    adult_field = next(field for _, field in MODULE.PORTRAIT_FIELDS if field.get("adult") and field.get("options"))
    adult_option = next(item for item in adult_field["options"] if item.get("value") not in ("", "不启用"))
    regular_asset = MODULE.ZFPortraitPromptGenerator().generate(_state(), adult_content=False)[1]
    adult_asset = MODULE.ZFPortraitPromptGenerator().generate(
        _state(adult_content=True),
        adult_content=True,
    )[1]

    assert "【人物资产库｜成人扩展】" not in regular_asset
    assert "【人物资产库｜成人扩展】" in adult_asset
    assert adult_option["text"] in adult_asset
    assert len(adult_asset) > len(regular_asset)


def test_disabling_a_section_only_removes_it_from_current_prompt():
    lens = _option("lens")
    state = _state(
        selected={"lens": lens["value"]},
        section_enabled={"camera": False},
    )
    prompt, world_asset, *_ = MODULE.ZFPortraitPromptGenerator().generate(state)

    assert lens["text"] not in prompt
    assert lens["text"] in world_asset


def test_frontend_uses_pinned_rows_and_has_no_result_chip_summary():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")

    assert "zf-pg-chips" not in source
    assert "●" in source and "○" in source
    assert "＋ 添加项目" in source
    assert "本段随机" in source
    assert "本段锁定" in source
    assert "本段不启用" in source
    assert "本项锁定" in source
    assert "临时启用或停用这一项" not in source


def test_asset_cards_are_edited_in_place_and_saved_explicitly():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")

    assert 'card.addEventListener("dblclick"' in source
    assert 'makeButton("确认保存"' in source
    assert "state.option_overrides[key] = editor.value" in source
    assert "可人工修改本项输出" not in source


def test_modal_preserves_option_and_tab_scroll_positions():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")

    assert 'tabsLeft: overlay.querySelector(".zf-pg-field-tabs")?.scrollLeft' in source
    assert 'optionsTop: overlay.querySelector(".zf-pg-options")?.scrollTop' in source
    assert "nextTabs.scrollLeft = previousView.tabsLeft" in source
    assert "nextOptions.scrollTop = previousView.optionsTop" in source
    assert "options.scrollTop = preservedTop" in source


def test_clear_is_undoable_and_locks_protect_selected_cards():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")

    assert 'canUndoClear ? "撤销清除"' in source
    assert 'lastCleared = {' in source
    assert 'lockBadge.textContent = "🔒 已锁定"' in source
    assert 'if (isFieldLocked(field.id))' in source
    assert 'if (state.section_locked[section.id])' in source
    assert "尚未选择的分类仍会继续随机" in source


def test_option_edit_changes_current_prompt_and_complete_asset_library():
    lens = _option("lens")
    key = f"lens::{lens['value']}"
    customized = "自定义镜头资产描述"
    state = _state(
        selected={"lens": lens["value"]},
        option_overrides={key: customized},
    )

    prompt, world_asset, selection_json, _ = MODULE.ZFPortraitPromptGenerator().generate(state)

    assert customized in prompt
    assert customized in world_asset
    assert lens["text"] not in world_asset
    assert json.loads(selection_json)["option_overrides"][key] == customized


def test_portrait_node_display_name_is_model_agnostic():
    source = (ROOT / "nodes.py").read_text(encoding="utf-8")

    assert '"ZFPortraitPromptGenerator": "ZF 人像提示词与人物资产"' in source
    assert '"ZFPortraitPromptGenerator": "ZF K2' not in source
