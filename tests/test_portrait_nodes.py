import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location("zf_portrait_nodes_tests", ROOT / "portrait_nodes.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _generate(*args, **kwargs):
    """Return the first prompt plus scalar metadata for single-prompt behavior tests."""
    prompts, selection_json, status = MODULE.ZIPortraitPromptGenerator().generate(*args, **kwargs)
    return prompts[0], None, selection_json, status


def _option(field_id, adult=None):
    field = MODULE.PORTRAIT_FIELD_BY_ID[field_id][1]
    return next(
        item
        for item in field["options"]
        if item.get("text") and item.get("value") not in ("", "不启用")
        and (adult is None or bool(item.get("adult")) is adult)
    )


def _option_by_value(field_id, value):
    field = MODULE.PORTRAIT_FIELD_BY_ID[field_id][1]
    return next(item for item in field["options"] if item.get("value") == value)


def _state(
    selected=None,
    overrides=None,
    adult_content=False,
    section_enabled=None,
    option_overrides=None,
    locked=None,
    section_locked=None,
    section_lock_items=None,
    auto_random=False,
    excluded_options=None,
):
    return json.dumps(
        {
            "version": 6,
            "adult_content": adult_content,
            "auto_random": auto_random,
            "selected": selected or {},
            "enabled": {},
            "overrides": overrides or {},
            "pinned": {},
            "locked": locked or {},
            "section_locked": section_locked or {},
            "section_lock_items": section_lock_items or {},
            "section_enabled": section_enabled or {},
            "option_overrides": option_overrides or {},
            "excluded_options": excluded_options or {},
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


def test_main_sections_follow_the_portrait_decision_order():
    sections = MODULE.PORTRAIT_CATALOG["sections"]
    assert [(section["id"], section["title"]) for section in sections[:9]] == [
        ("shooting_light", "拍摄与光影"),
        ("subject", "人物主体"),
        ("person_detail", "人物细节"),
        ("hair", "发型与头饰"),
        ("styling_expression", "妆造表达"),
        ("wear_state", "穿着状态"),
        ("clothing", "服装"),
        ("accessories", "配饰"),
        ("clothing_expression", "服装表现"),
    ]
    assert [len(section["fields"]) for section in sections[:9]] == [8, 7, 12, 9, 7, 1, 15, 6, 7]
    all_ids = [field["id"] for section in sections for field in section["fields"]]
    assert len(all_ids) == len(set(all_ids)) == 111


def test_legacy_pose_selection_migrates_to_the_new_action_group():
    legacy_state = _state(selected={"sfwSimPick": "I023"})
    prompt, _, selection_json, _ = _generate(legacy_state)
    migrated = json.loads(selection_json)

    assert "原地旋转中定格" in prompt
    assert migrated["version"] == 7
    assert migrated["selected"]["actionSpinning"] == "I023"
    assert "sfwSimPick" not in migrated["selected"]

    posture_state = _state(selected={"sfwSimPick": "F001"})
    posture_prompt, _, posture_selection, _ = _generate(posture_state)
    posture_migrated = json.loads(posture_selection)
    assert "站立，双腿并拢" in posture_prompt
    assert posture_migrated["selected"]["postureStanding"] == "F001"


def test_legacy_section_lock_snapshots_only_existing_selections():
    lens = _option("lens")
    legacy = json.loads(_state(selected={"lens": lens["value"]}, section_locked={"camera": True}))
    legacy["version"] = 4
    _, _, selection_json, _ = _generate(json.dumps(legacy, ensure_ascii=False))
    migrated = json.loads(selection_json)

    assert migrated["version"] == 7
    assert migrated["section_lock_items"]["lens"] is True
    assert "viewpoint" not in migrated["section_lock_items"]


def test_portrait_prompt_works_without_reverse_analysis():
    lens = _option("lens")
    age = _option("age")
    scene = _option("scene")
    state = _state(selected={"lens": lens["value"], "age": age["value"], "scene": scene["value"]})

    prompt, _, selection_json, status = _generate(state)

    assert lens["text"] in prompt
    assert scene["text"] in prompt
    assert json.loads(selection_json)["adult_content"] is False
    assert "已生成 1 条提示词" in status
    assert "成人内容关闭" in status


def test_portrait_prompt_uses_html_style_prose_without_section_headers():
    lens = _option_by_value("lens", "广角")
    viewpoint = _option_by_value("viewpoint", "平视正面")
    device = _option_by_value("device", "手机自拍")
    main_light = _option_by_value("mainLight", "自然光")
    tone = _option_by_value("colorTone", "中性白")
    cloth_item = _option_by_value("clothItem", "上下装｜白色棉质衬衫")
    scene = _option_by_value("scene", "卧室")
    composition = _option_by_value("comp", "三分法")
    state = _state(
        selected={
            "lens": lens["value"],
            "viewpoint": viewpoint["value"],
            "shotSize": "半身",
            "device": device["value"],
            "mainLight": main_light["value"],
            "colorTone": tone["value"],
            "temperament": "清纯",
            "age": "24岁轻熟女",
            "race": "欧美",
            "skin": "冷白皮",
            "texture": "哑光质感",
            "face": "瓜子脸",
            "clothCat": "上下装",
            "clothItem": cloth_item["value"],
            "scene": scene["value"],
            "comp": composition["value"],
            "compPos": "居于画面中央",
        },
    )

    prompt = _generate(state)[0]

    assert "拍摄与光影：" not in prompt
    assert "人物主体：" not in prompt
    assert "服装：" not in prompt
    assert lens["text"] in prompt
    assert viewpoint["text"] in prompt
    assert "取半身景别" in prompt
    assert f"画面以{device['text']}呈现" in prompt
    assert "人物为清纯的24岁轻熟女，欧美，冷白皮哑光质感，瓜子脸" in prompt
    assert f"上身穿着{cloth_item['text']}" in prompt
    assert scene["text"] in prompt
    assert f"{composition['text']}，人物居于画面中央" in prompt


def test_prompt_omits_selector_metadata_and_keeps_full_option_descriptions():
    cloth_item = _option_by_value("clothItem", "连衣裙｜白色缎面吊带长裙")
    state = _state(
        selected={
            "stylePreset": "法式优雅",
            "clothCat": "连衣裙",
            "clothItem": cloth_item["value"],
        },
    )

    prompt = _generate(state)[0]

    assert "stylePreset" not in prompt
    assert "主件类别" not in prompt
    assert "法式优雅" not in prompt
    assert f"身着{cloth_item['text']}" in prompt


def test_adult_prompt_does_not_inject_a_policy_prefix():
    wear_state = _option("nsfwState")
    age = _option_by_value("age", "24岁轻熟女")
    state = _state(
        selected={"nsfwState": wear_state["value"], "age": age["value"]},
        adult_content=True,
    )

    prompt = _generate(state, adult_content=True)[0]

    assert prompt.startswith(f"{wear_state['text']}。")
    assert "成年人物" not in prompt
    assert "明确的成年人物" not in prompt
    assert "穿着状态：" not in prompt


def test_prompt_keeps_a_space_between_english_and_chinese_sentences():
    posture = _option("postureStanding")
    scene = _option_by_value("scene", "卧室")
    state = _state(
        selected={"postureStanding": posture["value"], "scene": scene["value"]},
        overrides={"postureStanding": "standing still."},
    )

    prompt = _generate(state)[0]

    assert f"standing still. {scene['text']}" in prompt


def test_adult_material_is_excluded_while_switch_is_off():
    adult_field = next(field for _, field in MODULE.PORTRAIT_FIELDS if field.get("adult") and field.get("options"))
    adult_option = next(item for item in adult_field["options"] if item.get("text") and item.get("value") != "不启用")
    state = _state(selected={adult_field["id"]: adult_option["value"]}, adult_content=True)

    prompt, *_ = _generate(
        state,
        adult_content=False,
    )

    assert adult_option["text"] not in prompt


def test_adult_mode_keeps_user_text_without_local_age_policy_rewriting():
    adult_field = next(field for _, field in MODULE.PORTRAIT_FIELDS if field.get("adult") and field.get("options"))
    adult_option = next(item for item in adult_field["options"] if item.get("text") and item.get("value") != "不启用")
    selected = {adult_field["id"]: adult_option["value"], "age": _option("age")["value"]}
    safe_state = _state(selected=selected, adult_content=True)

    prompt, _, _, status = _generate(
        safe_state,
        adult_content=True,
    )
    assert adult_option["text"] in prompt
    assert _option("age")["text"] in prompt
    assert "明确的成年人物" not in prompt
    assert "成人内容开启" in status

    custom_state = _state(
        selected=selected,
        overrides={"age": "16岁"},
        adult_content=True,
    )
    custom_prompt, _, custom_selection, custom_status = _generate(
        custom_state,
        adult_content=True,
    )
    assert adult_option["text"] in custom_prompt
    assert "16岁" in custom_prompt
    assert json.loads(custom_selection)["adult_content"] is True
    assert "成人内容开启" in custom_status


def test_reference_analysis_is_optional_material_not_a_random_dependency():
    state = _state(selected={"lens": _option("lens")["value"]})
    prompt_without_reference, *_ = _generate(state)
    prompt_with_reference, *_ = _generate(
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


def test_portrait_node_outputs_a_prompt_list_without_world_asset():
    node = MODULE.ZIPortraitPromptGenerator
    prompts, selection_json, status = node().generate(_state())

    assert node.RETURN_NAMES == ("portrait_prompt", "selection_json", "status")
    assert node.OUTPUT_IS_LIST == (True, False, False)
    assert isinstance(prompts, list) and len(prompts) == 1
    assert json.loads(selection_json)["version"] == 7
    assert "已生成 1 条提示词" in status


def test_quantity_three_generates_unique_prompts_and_preserves_locks():
    node = MODULE.ZIPortraitPromptGenerator
    quantity = node.INPUT_TYPES()["required"]["quantity"][1]
    lens = _option("lens")
    state = _state(
        selected={"lens": lens["value"]},
        locked={"lens": True},
    )

    prompts, selection_json, status = node().generate(state, seed=1234, quantity=3)

    assert quantity["default"] == 1
    assert quantity["min"] == 1 and quantity["max"] == 100
    assert len(prompts) == len(set(prompts)) == 3
    assert all(lens["text"] in prompt for prompt in prompts)
    assert json.loads(selection_json)["locked"]["lens"] is True
    assert "已生成 3 条提示词" in status


def test_asset_catalog_does_not_export_pose_cancelling_policy_clauses():
    serialized = json.dumps(MODULE.PORTRAIT_CATALOG, ensure_ascii=False)
    forbidden = (
        "避开私密部位",
        "避开敏感部位",
        "避开私处",
        "不露点",
        "保留最后遮挡",
        "仅留极简遮挡",
    )

    assert not any(term in serialized for term in forbidden)


def test_disabling_a_section_removes_it_from_current_prompt():
    lens = _option("lens")
    state = _state(
        selected={"lens": lens["value"]},
        section_enabled={"shooting_light": False},
    )
    prompt, *_ = _generate(state)

    assert lens["text"] not in prompt


def test_frontend_uses_pinned_rows_and_has_no_result_chip_summary():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")

    assert "zf-pg-chips" not in source
    assert "●" in source and "○" in source
    assert "＋ 添加项目" in source
    assert "本段随机" in source
    assert "本段锁定" in source
    assert 'disabled ? "本段启用" : "本段排除"' in source
    assert "本项锁定" in source
    assert 'makeButton("解锁所有")' in source
    assert '"自动随机：开"' in source and '"自动随机：关"' in source
    assert 'makeButton("清空所有")' not in source
    assert "临时启用或停用这一项" not in source


def test_frontend_layers_adult_material_onto_the_complete_normal_recipe():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")

    assert 'if (!standardLocked && !lingerieLocked) family = "standard"' in source
    assert "Boolean(field.adult) === Boolean(state.adult_content)" in source
    assert 'const degreeIds = state.adult_content\n              ? ["nsfwExposure"]' in source
    assert "completeAdultComposition" in source
    assert "保留完整人物与画面素材" in source
    assert "不再混抽常规姿态或服装" not in source


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


def test_frontend_keeps_locked_choices_pinned_and_recovers_older_states():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")

    assert "recoveredLockedPin" in source
    assert "if (willLock) state.pinned[field.id] = true;" in source
    assert "state.pinned[item.id] = true;" in source
    assert "本项已锁定并固定到节点首页" in source

    adult_toggle_block = source[source.index('adultToggle.addEventListener("change"'):]
    adult_toggle_block = adult_toggle_block[:adult_toggle_block.index("renderHome();")]
    assert "delete state.pinned[adultField.id]" not in adult_toggle_block


def test_option_edit_changes_current_prompt_and_saved_state():
    lens = _option("lens")
    key = f"lens::{lens['value']}"
    customized = "自定义镜头资产描述"
    state = _state(
        selected={"lens": lens["value"]},
        option_overrides={key: customized},
    )

    prompt, _, selection_json, _ = _generate(state)

    assert customized in prompt
    assert json.loads(selection_json)["option_overrides"][key] == customized


def test_portrait_node_display_name_is_model_agnostic():
    source = (ROOT / "nodes.py").read_text(encoding="utf-8")

    assert '"ZIPortraitPromptGenerator": "ZI 人像提示词生成器"' in source
    assert '"ZIPortraitPromptGenerator": "ZI K2' not in source


def test_age_label_is_concise_and_manual_override_still_round_trips():
    field = MODULE.PORTRAIT_FIELD_BY_ID["age"][1]
    assert field["label"] == "年纪身份" and field["editable"] is True
    catalog = (ROOT / "data" / "portrait_generator_v12.json").read_text(encoding="utf-8")
    assert "（可手动输入）" not in catalog
    value = "28岁的陶艺师"
    prompt, _, selection_json, _ = _generate(_state(overrides={"age": value}))
    assert value in prompt
    assert json.loads(selection_json)["overrides"]["age"] == value


def test_v6_state_adds_empty_exclusions_and_upgrades_to_v7():
    old = json.loads(_state())
    old.pop("excluded_options")
    assert old["version"] == 6
    result = json.loads(_generate(json.dumps(old))[2])
    assert result["version"] == 7 and result["excluded_options"] == {}
    assert json.loads(MODULE.DEFAULT_PORTRAIT_STATE)["version"] == 7


@pytest.mark.parametrize("lock_key", [None, "locked", "section_lock_items"])
def test_excluded_selected_option_does_not_output_and_preserves_asset_edit(lock_key):
    lens = _option("lens")
    key = f"lens::{lens['value']}"
    exclusions = {key: True, "unknown::preserved": False}
    args = {lock_key: {"lens": True}} if lock_key else {}
    state = _state(selected={"lens": lens["value"]}, option_overrides={key: "EXCLUDED_ASSET_TEXT"}, excluded_options=exclusions, **args)
    prompt, _, saved, _ = _generate(state)
    saved = json.loads(saved)
    assert "EXCLUDED_ASSET_TEXT" not in prompt and lens["text"] not in prompt
    assert saved["excluded_options"] == exclusions
    assert saved["option_overrides"][key] == "EXCLUDED_ASSET_TEXT"
    if lock_key:
        assert saved[lock_key]["lens"] is True and saved["selected"]["lens"] == lens["value"]
    else:
        assert "lens" not in saved["selected"]


def test_single_field_random_skips_excluded_options_and_restore_makes_them_usable():
    field = MODULE.PORTRAIT_FIELD_BY_ID["lens"][1]
    allowed = _option("lens")
    excluded = {f"lens::{item['value']}": True for item in field["options"] if item['value'] != allowed['value']}
    state = MODULE._parse_state(_state(excluded_options=excluded))
    for seed in range(20):
        assert MODULE._choose_random(state, "lens", MODULE.random.Random(seed), False)['value'] == allowed['value']
    state['excluded_options'][f"lens::{allowed['value']}"] = True
    assert MODULE._choose_random(state, "lens", MODULE.random.Random(1), False) is None
    assert 'lens' not in state['selected']
    del state['excluded_options'][f"lens::{allowed['value']}"]
    assert MODULE._choose_random(state, "lens", MODULE.random.Random(1), False)['value'] == allowed['value']


@pytest.mark.parametrize("auto_random,quantity", [(True, 1), (False, 8)])
def test_auto_and_batch_random_never_output_excluded_lens(auto_random, quantity):
    field = MODULE.PORTRAIT_FIELD_BY_ID['lens'][1]
    allowed = _option('lens')
    excluded = {f"lens::{item['value']}": True for item in field['options'] if item['value'] != allowed['value']}
    edits = {key: 'EXCLUDED_RANDOM_SENTINEL' for key in excluded}
    state = _state(selected={'lens': allowed['value']}, auto_random=auto_random, excluded_options=excluded, option_overrides=edits)
    prompts, saved, _ = MODULE.ZIPortraitPromptGenerator().generate(state, quantity=quantity)
    assert all('EXCLUDED_RANDOM_SENTINEL' not in prompt and allowed['text'] in prompt for prompt in prompts)
    assert json.loads(saved)['excluded_options'] == excluded


@pytest.mark.parametrize("adult", [False, True])
def test_all_random_branches_filter_excluded_options(adult):
    excluded = {f"{field['id']}::{option['value']}": True for _, field in MODULE.PORTRAIT_FIELDS for index, option in enumerate(field['options']) if index % 2 == 0}
    for seed in range(12):
        state = MODULE._parse_state(_state(excluded_options=excluded))
        MODULE._randomize_state(state, MODULE.random.Random(seed), adult)
        if adult:
            MODULE._ensure_adult_selection(state, MODULE.random.Random(seed))
        assert all(not MODULE._is_excluded(state, field_id, value) for field_id, value in state['selected'].items())


def test_all_options_excluded_stably_skip_every_random_branch():
    excluded = {f"{field['id']}::{option['value']}": True for _, field in MODULE.PORTRAIT_FIELDS for option in field['options']}
    prompts, saved, _ = MODULE.ZIPortraitPromptGenerator().generate(_state(auto_random=True, excluded_options=excluded), adult_content=True, quantity=4)
    assert len(prompts) == 4 and len(set(prompts)) == 1
    assert json.loads(saved)['selected'] == {} and json.loads(saved)['excluded_options'] == excluded


@pytest.mark.parametrize("field_id,category_id", [('clothItem', 'clothCat'), ('lingerieItem', 'lingerieCat')])
def test_excluding_whole_current_group_does_not_fall_back_to_another_group(field_id, category_id):
    field = MODULE.PORTRAIT_FIELD_BY_ID[field_id][1]
    group = next(option['group'] for option in field['options'] if option.get('group'))
    state = MODULE._parse_state(_state())
    category = group if category_id == 'clothCat' else MODULE._lingerie_category_for_group(group, state)
    state['selected'][category_id] = category
    state['excluded_options'] = {f"{field_id}::{option['value']}": True for option in field['options'] if option.get('group') == group}
    assert MODULE._usable_options(field, state, True) == []


@pytest.mark.parametrize("field_id,category_id", [('clothItem', 'clothCat'), ('lingerieItem', 'lingerieCat')])
def test_locked_item_does_not_reintroduce_excluded_derived_category(field_id, category_id):
    field = MODULE.PORTRAIT_FIELD_BY_ID[field_id][1]
    option = next(option for option in field['options'] if option.get('group'))
    state = MODULE._parse_state(_state(selected={field_id: option['value']}, locked={field_id: True}))
    category = option['group'] if category_id == 'clothCat' else MODULE._lingerie_category_for_group(option['group'], state)
    state['excluded_options'][f'{category_id}::{category}'] = True
    MODULE._randomize_state(state, MODULE.random.Random(4), True)
    assert state['selected'][field_id] == option['value']
    assert state['selected'].get(category_id) != category


def test_frontend_exclusions_are_visible_persistent_and_guarded():
    source = (ROOT / 'web' / 'portrait_generator.js').read_text(encoding='utf-8')
    assert 'version: 7' in source and 'state.version = 7' in source and 'excluded_options: {}' in source
    assert 'const matches = displayableOptions(field, state)' in source
    assert 'return displayableOptions(field, state).filter((item) => !isExcluded' in source
    toggle = source[source.index('exclude.addEventListener("click"'):source.index('card.append(value, description, exclude)')]
    assert 'event.stopPropagation()' in toggle and 'exclude.addEventListener("dblclick"' in toggle
    assert 'current && isFieldLocked(field.id)' in toggle and 'delete state.selected[field.id]' in toggle
    assert 'option_overrides' not in toggle
    assert source.count('if (isExcluded(field, state, item.value) || card.classList.contains') == 2
    restore = source[source.index('restoreOptions.addEventListener("click"'):source.index('search.addEventListener("input"')]
    assert 'displayableOptions(field, state)' in restore and 'searchTerm' not in restore and 'state.selected' not in restore
    assert 'makeButton("＋ 一键添加")' in source and 'restoreOptions.disabled =' in source
    repair = source[source.index('repair.addEventListener("click"'):source.index('const advanced =')]
    assert 'excluded_options' not in repair


def test_editor_is_prepended_in_its_own_row_with_visible_wrapping_actions():
    source = (ROOT / 'web' / 'portrait_generator.js').read_text(encoding='utf-8')
    assert 'options.prepend(editorCard)' in source and 'options.scrollTop = 0' in source
    assert '.zf-pg-options{grid-row:3;' in source
    assert '.zf-pg-option-editor{grid-column:1/-1;position:relative;z-index:2;background:' in source
    assert '.zf-pg-option-edit-actions{display:flex;flex-wrap:wrap;' in source


def test_unlock_all_only_removes_locks_and_keeps_selections():
    source = (ROOT / "web" / "portrait_generator.js").read_text(encoding="utf-8")
    block = source[source.index('const unlockAll = makeButton("解锁所有")'):]
    block = block[:block.index('const autoRandom =')]

    assert "state.locked = {}" in block
    assert "state.section_locked = {}" in block
    assert "state.section_lock_items = {}" in block
    assert "state.selected = {}" not in block
    assert "state.overrides = {}" not in block


def test_auto_random_changes_every_execution_without_outfit_or_movement_conflicts():
    state = _state(adult_content=True, auto_random=True)
    results = [
        json.loads(_generate(state, adult_content=True)[2])
        for _ in range(80)
    ]

    assert len({item["seed"] for item in results}) > 70
    assert len({tuple(sorted(item["selected"].items())) for item in results}) > 70
    for item in results:
        selected = item["selected"]
        standard = any(selected.get(field_id) for field_id in MODULE.STANDARD_CLOTHING_FIELD_IDS)
        lingerie = any(selected.get(field_id) for field_id in MODULE.LINGERIE_FIELD_IDS)
        assert not (standard and lingerie)
        assert sum(bool(selected.get(field_id)) for field_id in MODULE.MOVEMENT_FIELD_IDS) == 1
        assert sum(bool(selected.get(field_id)) for field_id in MODULE.CLOTHING_DEGREE_FIELD_IDS) <= 1
        movement_id = next(field_id for field_id in MODULE.MOVEMENT_FIELD_IDS if selected.get(field_id))
        assert MODULE.PORTRAIT_FIELD_BY_ID[movement_id][1].get("adult") is True
        assert selected.get("nsfwState")
        assert selected.get("nsfwLowerBody")
        assert selected.get("nsfwBreastDetail")
        if selected["nsfwState"] not in MODULE.NO_CLOTHING_STATES:
            assert standard
            assert not lingerie
            assert selected.get("nsfwExposure")


def test_enabling_adult_mode_guarantees_adult_output_without_pressing_random():
    prompt, _, selection_json, status = _generate(
        _state(adult_content=True),
        adult_content=True,
    )
    state = json.loads(selection_json)
    adult_ids = {
        field["id"]
        for _, field in MODULE.PORTRAIT_FIELDS
        if field.get("adult")
    }

    assert any(state["selected"].get(field_id) for field_id in adult_ids)
    assert state["selected"].get("lens")
    assert state["selected"].get("age")
    assert state["selected"].get("hairLen")
    assert state["selected"].get("scene")
    assert state["selected"].get("comp")
    assert "成人内容开启" in status
    assert "成年人物" not in prompt


def test_regular_auto_random_never_selects_adult_fields():
    state = _state(auto_random=True)
    adult_ids = {
        field["id"]
        for _, field in MODULE.PORTRAIT_FIELDS
        if field.get("adult")
    }

    for _ in range(30):
        result = json.loads(_generate(state)[2])["selected"]
        assert not any(result.get(field_id) for field_id in adult_ids)


def test_auto_random_preserves_locked_outfit_and_does_not_add_another_family():
    cloth_item = _option("clothItem")
    selected = {
        "clothCat": cloth_item["group"],
        "clothItem": cloth_item["value"],
    }
    state = _state(selected=selected, locked={"clothItem": True}, auto_random=True)

    for _ in range(30):
        result = json.loads(_generate(state)[2])["selected"]
        assert result["clothItem"] == cloth_item["value"]
        assert result["clothCat"] == cloth_item["group"]
        assert not any(result.get(field_id) for field_id in MODULE.LINGERIE_FIELD_IDS)
        assert result.get("nsfwState") not in MODULE.NO_CLOTHING_STATES


def test_auto_random_preserves_locked_regular_posture_in_prompt():
    posture = _option("postureStanding")
    state = _state(
        selected={"postureStanding": posture["value"]},
        locked={"postureStanding": True},
        auto_random=True,
    )

    for _ in range(30):
        prompt, _, selection_json, _ = _generate(state)
        result = json.loads(selection_json)
        assert result["selected"]["postureStanding"] == posture["value"]
        assert result["locked"]["postureStanding"] is True
        assert posture["text"] in prompt
        assert sum(bool(result["selected"].get(field_id)) for field_id in MODULE.MOVEMENT_FIELD_IDS) == 1


def test_auto_random_preserves_locked_adult_posture_in_prompt():
    posture = _option("adultPostureSupine")
    state = _state(
        selected={"adultPostureSupine": posture["value"]},
        locked={"adultPostureSupine": True},
        adult_content=True,
        auto_random=True,
    )

    for _ in range(30):
        prompt, _, selection_json, _ = _generate(
            state,
            adult_content=True,
        )
        result = json.loads(selection_json)
        assert result["selected"]["adultPostureSupine"] == posture["value"]
        assert result["locked"]["adultPostureSupine"] is True
        assert posture["text"] in prompt
        assert sum(bool(result["selected"].get(field_id)) for field_id in MODULE.MOVEMENT_FIELD_IDS) == 1


def test_no_clothing_state_removes_unlocked_outfit_and_expression_fields():
    state = _state(
        selected={
            "nsfwState": "仅剩配饰",
            "clothCat": _option("clothCat")["value"],
            "clothItem": _option("clothItem")["value"],
            "lingerieCat": _option("lingerieCat")["value"],
            "lingerieItem": _option("lingerieItem")["value"],
            "clothTransparency": _option("clothTransparency")["value"],
        },
        adult_content=True,
    )

    result = json.loads(_generate(state, adult_content=True)[2])["selected"]
    assert result["nsfwState"] == "仅剩配饰"
    assert not any(result.get(field_id) for field_id in MODULE.STANDARD_CLOTHING_FIELD_IDS)
    assert not any(result.get(field_id) for field_id in MODULE.LINGERIE_FIELD_IDS)
    assert not any(result.get(field_id) for field_id in MODULE.CLOTHING_EXPRESSION_FIELD_IDS)


def test_existing_multiple_movement_selections_are_reduced_to_one():
    state = _state(
        selected={
            "postureStanding": _option("postureStanding")["value"],
            "actionWalking": _option("actionWalking")["value"],
        },
    )

    result = json.loads(_generate(state)[2])["selected"]
    assert sum(bool(result.get(field_id)) for field_id in MODULE.MOVEMENT_FIELD_IDS) == 1
