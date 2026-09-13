import copy
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("zf_h3_focus_testcore", ROOT / "h3_focus" / "__init__.py", submodule_search_locations=[str(ROOT / "h3_focus")])
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
CONTRACT = importlib.import_module(SPEC.name + ".contract")
NODE = importlib.import_module(SPEC.name + ".node").ZVH3FocusCompiler


def fixture(mode="t2va"):
    return json.loads((ROOT / "tests" / "fixtures" / "h3_focus" / f"{mode}.json").read_text(encoding="utf-8"))


def codes(plan):
    return {error["code"] for error in CORE.validate_plan(plan)["errors"]}


def reference_plan(pictures=0, videos=0, audios=0, seconds=2, profile="local_t8"):
    plan = fixture()
    plan["mode"] = "Ref2VA"
    plan["profile"] = profile
    tasks, labels = [], []
    for kind, count in (("picture", pictures), ("video", videos), ("audio", audios)):
        for index in range(1, count + 1):
            label = f"<{kind.title()} {index}>"
            asset = {
                "asset_id": f"{kind}-{index}", "kind": kind, "ordinal": index, "official_label": label,
                "source": {"handle": f"uploads/{kind}-{index}", "clock_id": "main", "clock_offset_seconds": 0},
                "probe": {}, "role": {"picture": "keyframe", "video": "structure_reference", "audio": "audio_reference"}[kind],
                "selected": True, "selected_window": None, "definition": "is a reference for the cup scene.",
                "retention": {"relationship": "reference" if kind == "audio" else "weak_reference", "placement": "", "details": "Its broad qualities guide the scene."},
            }
            task = {"picture": "keyframe completion", "video": "reference generation", "audio": "audio reference"}[kind]
            if task not in tasks:
                tasks.append(task)
            if kind != "picture":
                asset["probe"] = {"duration_seconds": 120, "fps": 30, "frame_count": 3600} if kind == "video" else {"duration_seconds": 120, "sample_rate": 48000, "sample_count": 5760000}
                asset["selected_window"] = {"in_seconds": 0, "out_seconds": seconds}
                if kind == "video":
                    asset["model_input"] = {"fps": 24, "frame_count": int(seconds * 24)}
            plan["media_assets"].append(asset)
            labels.append(label)
    plan["ref2va"] = {"task_types": tasks, "summary": "The cup scene uses " + ", ".join(labels) + "."}
    return plan


def add_gap(plan, path="/shots/0/action", required=True):
    CONTRACT.pointer_set(plan, path, "")
    plan["gaps"].append({"id": "gap-action", "path": path, "required": required, "value_type": "string", "context": "Describe the cup motion.", "status": "pending"})
    return plan


def segmented(strategy="uniform_edit"):
    plan = reference_plan(videos=1)
    plan["duration_seconds"] = 20
    plan["segmentation"] = {
        "strategy": strategy, "clock": "source_seconds", "clock_id": "main",
        "global_prompt": "Keep the cup blue.", "shared_lock_paths": ["/style"], "segments": [],
    }
    plan["locks"] = [{"path": "/style", "value": plan["style"]}]
    for i in range(2):
        window = {"in_seconds": i * 10, "out_seconds": (i + 1) * 10}
        plan["segmentation"]["segments"].append({
            "id": f"segment-{i + 1}", "order": i + 1, "source_window": window,
            "local_prompt": ("The cup turns." if i == 0 else "The cup stops.") if strategy == "narrative" else "",
            "selections": [{"asset_id": "video-1", "timing": "synchronized", "window": dict(window), "model_input": {"fps": 24, "frame_count": 240}}],
        })
    return plan


@pytest.mark.parametrize("mode", ["t2va", "i2va", "fl2va", "l2va", "ref2va"])
def test_five_modes_compile_deterministically_with_exact_headings(mode):
    plan = fixture(mode)
    before = copy.deepcopy(plan)
    result = CORE.compile_plan(plan)
    assert result["ready"], result["validation"]
    assert CORE.compile_plan(plan) == result
    assert plan == before
    heading_pattern = r"^([a-z_]+):$" if mode == "ref2va" else r"^([a-z_]+): "
    headings = re.findall(heading_pattern, result["final_prompt"], re.M)
    assert headings == (["subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music"] if mode == "ref2va" else ["integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"])
    assert "[Shot 1] At" not in result["final_prompt"]
    assert "SLOT:" not in result["final_prompt"]
    if mode in ("i2va", "fl2va", "l2va"):
        assert result["final_prompt"].splitlines()[1] == ""


@pytest.mark.parametrize("mode,action,alignment", [
    ("t2va", "The cup slowly turns.", ""),
    ("i2va", "The cup begins in the position shown in <Picture 1> and slowly turns.",
     "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."),
    ("fl2va", "The cup turns from the position in <Picture 1> into the position in <Picture 2>.",
     "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 6.00-second mark of the target video."),
    ("l2va", "The cup turns into the position shown in <Picture 1>.",
     "How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 6.00-second mark of the target video."),
])
def test_base_prompt_matches_exact_same_line_field_format(mode, action, alignment):
    expected_core = (
        "integrated_multimodal_description: [Shot 1] Live-action. "
        "A close shot frames a ceramic cup. The cup has a blue rim. "
        "A plain wooden table fills the frame. " + action + " The camera remains still.\n\n"
        "overall_soundscape: Quiet room tone continues.\n\n"
        "non_diegetic_music: N/A"
    )
    expected = alignment + "\n\n" + expected_core if alignment else expected_core
    result = CORE.compile_plan(fixture(mode))
    assert result["ready"], result["validation"]
    assert result["final_prompt"] == expected


def test_exact_base_alignment_lines_use_actual_final_shot_and_two_decimals():
    expected = {
        "i2va": "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.",
        "fl2va": "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 2) aligns with the 6.25-second mark of the target video.",
        "l2va": "How the reference pictures align with the target video — <Picture 1> (from [Shot 2]) aligns with the 6.25-second mark of the target video.",
    }
    for mode, line in expected.items():
        plan = fixture(mode)
        plan["duration_seconds"] = 6.25
        plan["shots"].append({**copy.deepcopy(plan["shots"][0]), "id": "shot-b", "order": 2, "cut_seconds": 3.5})
        result = CORE.compile_plan(plan)
        assert result["ready"]
        assert result["final_prompt"].splitlines()[0] == line
        assert "[Shot 2] At 00:03.500," in result["final_prompt"]


def test_aliases_normalize_without_translating_or_changing_literal_text():
    assert CONTRACT.normalize_labels("【图1】 【图片1】 【视频2】 【音频3】 【主体4】 【人物4】") == "<Picture 1> <Picture 1> <Video 2> <Audio 3> <Subject 4> <Subject 4>"
    plan = fixture("i2va")
    plan["shots"][0]["action"] = "The cup in 【图1】 slowly rotates."
    plan["shots"][0]["dialogue"] = [{"speaker_id": "S1", "source": "An off-screen narrator", "delivery": "says:", "language": "中文", "text": "请看【图片1】！", "after": ""}]
    plan["shots"][0]["visible_text"] = [{"description": "A sign reads", "text": "【图1】营业中！"}]
    result = CORE.compile_plan(plan)
    assert result["ready"]
    assert "The cup in <Picture 1> slowly rotates." in result["final_prompt"]
    assert "<d>[中文] 请看【图片1】！</d>" in result["final_prompt"]
    assert '"【图1】营业中！"' in result["final_prompt"]
    assert result["plan"]["shots"][0]["action"] == plan["shots"][0]["action"]


def test_labels_survive_reorder_deletion_and_new_allocation():
    plan = CORE.normalize_plan(reference_plan(pictures=3))
    old = {a["asset_id"]: a["official_label"] for a in plan["media_assets"]}
    plan["media_assets"].reverse()
    plan["media_assets"] = [a for a in plan["media_assets"] if a["asset_id"] != "picture-2"]
    added = copy.deepcopy(plan["media_assets"][0])
    added.update(asset_id="new-picture", selected=False)
    added.pop("official_label")
    added.pop("ordinal")
    plan["media_assets"].append(added)
    result = CORE.normalize_plan(plan)
    assert {a["asset_id"]: a["official_label"] for a in result["media_assets"] if a["asset_id"] in old} == {k: v for k, v in old.items() if k != "picture-2"}
    assert result["media_assets"][-1]["official_label"] == "<Picture 4>"


def test_subject_is_not_a_file_and_can_have_multiple_physical_sources():
    plan = fixture("ref2va")
    second = copy.deepcopy(plan["media_assets"][0])
    second.update(asset_id="picture-2", ordinal=2, official_label="<Picture 2>")
    plan["media_assets"].append(second)
    plan["subjects"][0]["source_asset_ids"].append("picture-2")
    plan["subjects"][0]["definition"] = "is the cup shown in <Picture 1> and <Picture 2>."
    result = CORE.compile_plan(plan)
    assert result["ready"]
    assert len(result["plan"]["subjects"]) == 1 and len(result["plan"]["media_assets"]) == 2
    assert "<Subject 1>" in result["final_prompt"]
    assert "<Picture 1> is" not in result["final_prompt"]
    plan["subjects"][0]["source_asset_ids"] = ["cup"]
    assert "subject_source" in codes(plan)


@pytest.mark.parametrize("mode,count", [("t2va", 0), ("i2va", 1), ("fl2va", 2), ("l2va", 1)])
def test_base_modes_serialize_their_physical_assets(mode, count):
    saved = json.loads(CORE.serialize_plan(fixture(mode)))
    assert len(saved["media_assets"]) == count
    assert saved["schema_version"] == "h3-focus-plan-v1"


def test_patch_rejects_locked_unknown_structural_and_wrong_type_paths():
    plan = add_gap(fixture())
    plan["locks"] = [{"path": "/style", "value": plan["style"]}]
    patch = {"/style": "Changed.", "/unknown": "No.", "/mode": "Ref2VA", "/shots/0/action": 17}
    changed, report = CORE.apply_llm_patch(plan, patch)
    assert {x["reason"] for x in report["rejected"]} == {"locked_path", "unknown_path", "structural_path_not_patchable", "type_mismatch"}
    assert not report["accepted"]
    assert changed["style"] == plan["style"]


def test_required_gap_controls_derived_ready_and_accepts_exact_json_patch():
    plan = add_gap(fixture())
    plan["ready"] = True
    assert not CORE.compile_plan(plan)["ready"]
    patch = [{"op": "replace", "path": "/shots/0/action", "value": "The cup stops turning."}]
    result = CORE.compile_plan(plan, patch)
    assert result["ready"], result["validation"]
    assert result["plan"]["gaps"][0]["status"] == "resolved"
    assert len(result["reverse_tasks"]["patch_report"]["accepted"]) == 1
    assert "The cup stops turning." in result["final_prompt"]
    again, report = CORE.apply_llm_patch(result["plan"], {"/shots/0/action": "Rewrite."})
    assert report["rejected"][0]["reason"] == "unauthorized_gap"


def test_optional_gap_can_be_explicitly_skipped_and_required_cannot():
    plan = add_gap(fixture(), "/shots/0/sound", False)
    plan["gaps"][0]["status"] = "skipped"
    assert CORE.validate_plan(plan)["ready"]
    plan["gaps"][0]["required"] = True
    assert "required_gap" in codes(plan)


def test_locking_parent_blocks_child_patch_and_snapshot_detects_edits():
    plan = add_gap(fixture())
    plan["locks"] = [{"path": "/shots/0", "value": copy.deepcopy(plan["shots"][0])}]
    changed, report = CORE.apply_llm_patch(plan, {"/shots/0/action": "Turn."})
    assert report["rejected"][0]["reason"] == "locked_path"
    plan["shots"][0]["camera"] = "Changed camera."
    assert "lock_changed" in codes(plan)


@pytest.mark.parametrize("cut", [-1, 0, 6, 8, 0.0001])
def test_invalid_shot_times_block_compilation(cut):
    plan = fixture()
    plan["shots"].append({**copy.deepcopy(plan["shots"][0]), "id": "shot-b", "order": 2, "cut_seconds": cut})
    assert not CORE.compile_plan(plan)["ready"] if cut >= 0 else not CORE.validate_plan(plan)["ready"]


def test_shot_sorting_uses_explicit_order_and_rejects_decreasing_cuts():
    plan = fixture()
    plan["shots"].append({**copy.deepcopy(plan["shots"][0]), "id": "shot-b", "order": 2, "cut_seconds": 4})
    plan["shots"].append({**copy.deepcopy(plan["shots"][0]), "id": "shot-c", "order": 3, "cut_seconds": 3})
    assert "shot_time" in codes(plan)
    plan["shots"][-1]["cut_seconds"] = 5
    plan["shots"].reverse()
    assert CORE.compile_plan(plan)["ready"]


@pytest.mark.parametrize("window", [{"in_seconds": 1}, {"out_seconds": 2}, {"in_seconds": -1, "out_seconds": 1}, {"in_seconds": 2, "out_seconds": 1}, {"in_seconds": 119, "out_seconds": 121}, {"in_seconds": 0, "out_seconds": 2, "in_frame": 0}])
def test_invalid_source_windows_are_rejected(window):
    plan = reference_plan(videos=1)
    plan["media_assets"][0]["selected_window"] = window
    assert not CORE.validate_plan(plan)["ready"]


def test_frame_and_sample_boundaries_use_source_clock_not_model_fps():
    plan = reference_plan(videos=1, audios=1)
    plan["media_assets"][0]["selected_window"].update(in_frame=0, out_frame=60)
    plan["media_assets"][1]["selected_window"].update(in_sample=0, out_sample=96000)
    assert CORE.validate_plan(plan)["ready"]
    plan["media_assets"][0]["selected_window"]["out_frame"] = 48
    assert "boundary_clock" in codes(plan)


def test_local_and_cloud_limits_apply_to_selected_input_windows():
    local = reference_plan(videos=2, seconds=10)
    assert CORE.validate_plan(local)["ready"]
    local["profile"] = "cloud_strict"
    assert "cloud_duration_limit" in codes(local)
    local["profile_limits"] = {"video_total_seconds": 21}
    assert CORE.validate_plan(local)["ready"]
    audio = reference_plan(audios=2, seconds=10, profile="cloud_strict")
    assert "cloud_duration_limit" in codes(audio)


@pytest.mark.parametrize("kind,limit", [("pictures", 9), ("videos", 3), ("audios", 3)])
def test_local_asset_count_boundaries(kind, limit):
    assert CORE.validate_plan(reference_plan(**{kind: limit}))["ready"]
    assert "local_asset_limit" in codes(reference_plan(**{kind: limit + 1}))


@pytest.mark.parametrize("frames,fps", [(47, 24), (361, 24), (48, 30)])
def test_local_requires_actual_24fps_input_frame_count(frames, fps):
    plan = reference_plan(videos=1)
    plan["media_assets"][0]["model_input"] = {"fps": fps, "frame_count": frames}
    assert "local_video_frames" in codes(plan)


def test_long_library_asset_is_valid_but_fake_short_model_count_is_not():
    plan = reference_plan(videos=1)
    assert CORE.validate_plan(plan)["ready"]
    library = copy.deepcopy(plan["media_assets"][0])
    library.update(asset_id="library", ordinal=8, official_label="<Video 8>", selected=False, selected_window=None)
    plan["media_assets"].append(library)
    assert CORE.validate_plan(plan)["ready"]
    plan["media_assets"][0]["selected_window"]["out_seconds"] = 60
    assert "model_window_mismatch" in codes(plan)


def test_paired_video_audio_has_independent_label_and_synchronized_window():
    plan = reference_plan(videos=1, audios=1)
    video, audio = plan["media_assets"]
    audio.update(ordinal=7, official_label="<Audio 7>", source_video_asset_id=video["asset_id"], source=dict(video["source"]))
    video.update(audio_enabled=True, paired_audio_asset_id=audio["asset_id"])
    video["probe"]["has_audio"] = True
    plan["ref2va"]["summary"] = "The scene uses <Video 1> and <Audio 7>."
    assert CORE.validate_plan(plan)["ready"]
    audio["selected_window"] = {"in_seconds": 1, "out_seconds": 3}
    assert "paired_window" in codes(plan)


@pytest.mark.parametrize("strategy", ["uniform_edit", "narrative"])
def test_long_segment_prompt_layers_and_source_clock(strategy):
    plan = segmented(strategy)
    result = CORE.compile_plan(plan)
    assert result["ready"], result["validation"]
    layers = result["validation"]["segment_prompt_layers"]
    assert len(layers) == 2 and layers[0]["shared_prompt"] == "Keep the cup blue."
    if strategy == "narrative":
        assert layers[0]["local_prompt"] != layers[1]["local_prompt"]
        plan["segmentation"]["segments"][1]["local_prompt"] = ""
        assert "local_prompt" in codes(plan)
    plan["segmentation"]["segments"][0]["selections"][0]["window"]["in_seconds"] = 1
    assert "synchronized_clock" in codes(plan)


def test_segment_limits_are_per_invocation_and_missing_shared_lock_is_rejected():
    plan = segmented()
    plan["profile"] = "cloud_strict"
    assert CORE.validate_plan(plan)["ready"]
    plan["segmentation"]["shared_lock_paths"] = ["/non_diegetic_music"]
    assert "shared_lock" in codes(plan)


@pytest.mark.parametrize("key", ["shell_command", "cut_command", "api_key", "translation_key"])
def test_unsafe_unknown_fields_cannot_be_serialized_or_echoed_by_node(key):
    plan = fixture()
    plan[key] = "private-value"
    with pytest.raises(CORE.ContractError):
        CORE.serialize_plan(plan)
    output = NODE().compile(json.dumps(plan))
    assert output[0] == "{}" and output[-1] is False
    assert "private-value" not in " ".join(str(v) for v in output)


def test_shell_payload_is_rejected_as_data_without_execution_or_echo():
    plan = add_gap(fixture())
    value = 'ffmpeg -i "$(bad)" output.mp4'
    changed, report = CORE.apply_llm_patch(plan, {"/shots/0/action": value})
    assert report["rejected"][0]["reason"] == "unsafe_payload"
    assert value not in json.dumps(report)
    assert changed["shots"][0]["action"] == ""


def test_unknown_labels_retention_and_task_roles_block_ref_compilation():
    plan = fixture("ref2va")
    plan["subjects"][0]["retention"]["relationship"] = "fully_copy"
    assert "retention_kind" in codes(plan)
    plan = fixture("ref2va")
    plan["shots"][0]["action"] = "<Subject 9> turns."
    assert "undefined_label" in codes(plan)
    plan = fixture("ref2va")
    plan["ref2va"]["task_types"] = ["video editing"]
    assert "task_roles" in codes(plan)


def test_auto_mode_and_manual_override_keep_persisted_frame_labels():
    plan = fixture("l2va")
    plan["mode"] = "auto"
    assert CORE.compile_plan(plan)["plan"]["effective_mode"] == "L2VA"
    plan["mode_override"] = "I2VA"
    assert "mode_assets" in codes(plan)
    plan["media_assets"][0]["role"] = "first_frame"
    assert CORE.compile_plan(plan)["ready"]
    plan["media_assets"][0].update(ordinal=5, official_label="<Picture 5>")
    assert "mode_assets" in codes(plan)


def test_patch_does_not_introduce_new_validation_errors_or_allow_non_replace_ops():
    plan = add_gap(fixture())
    result = CORE.compile_plan(plan, {"/shots/0/action": "<Subject 8> turns."})
    assert result["reverse_tasks"]["patch_report"]["rejected"][0]["reason"] == "validation_regression"
    assert not result["ready"]
    _, report = CORE.apply_llm_patch(plan, [{"op": "remove", "path": "/locks", "value": []}])
    assert not report["accepted"]


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '[}', 'null'])
def test_node_handles_invalid_json_without_importing_comfyui(raw):
    assert NODE().compile(raw)[-1] is False


def test_node_outputs_and_registration_do_not_change_existing_interfaces():
    node = NODE()
    result = node.compile(json.dumps(fixture()))
    assert len(result) == 6 and result[-1] is True
    assert NODE.RETURN_TYPES[-1] == "BOOLEAN"
    assert json.loads(result[0])["ready"] is True
    source = (ROOT / "nodes.py").read_text(encoding="utf-8")
    assert '"ZVH3FocusCompiler": ZVH3FocusCompiler' in source
    assert '"ZFPromptDirectorLocalLLM": ZFPromptDirectorLocalLLM' in source


def test_bundled_schema_rejects_unknown_nested_fields_without_external_library():
    assert not CONTRACT.schema_errors(fixture("ref2va"))
    plan = fixture("ref2va")
    plan["media_assets"][0]["source"]["absolute_path"] = "not-persisted"
    assert "unknown_field" in codes(plan)


def test_reordered_array_cannot_redirect_a_saved_gap_or_user_lock():
    plan = add_gap(fixture())
    second = {**copy.deepcopy(plan["shots"][0]), "id": "shot-b", "order": 2, "cut_seconds": 3}
    plan["shots"].append(second)
    saved = CORE.normalize_plan(plan)
    assert saved["gaps"][0]["target_id"] == "shot-a"
    saved["shots"].reverse()
    assert "stale_binding" in codes(saved)
    changed, report = CORE.apply_llm_patch(saved, {"/shots/0/action": "The cup moves."})
    assert report["rejected"][0]["reason"] == "stale_gap_binding"
    assert changed["shots"][0]["action"] == ""
    plan["locks"] = [{"path": "/shots/0/camera", "value": plan["shots"][0]["camera"]}]
    saved = CORE.normalize_plan(plan)
    saved["shots"].reverse()
    _, report = CORE.apply_llm_patch(saved, {"/shots/0/action": "The cup moves."})
    assert report["rejected"][0]["reason"] == "stale_lock_binding"


def test_non_english_prose_is_reported_without_guessing_or_translation():
    plan = fixture()
    plan["shots"][0]["action"] = "杯子缓慢旋转。"
    result = CORE.compile_plan(plan)
    assert result["final_prompt"] == "" and not result["ready"]
    assert "prose_language" in codes(plan)
    assert result["plan"]["shots"][0]["action"] == "杯子缓慢旋转。"


def test_nonexistent_shots_and_malformed_labels_in_retention_are_rejected():
    plan = fixture("ref2va")
    plan["subjects"][0]["retention"]["placement"] = "appears in [Shot 8]"
    assert "unknown_shot" in codes(plan)
    plan["subjects"][0]["definition"] = "is the cup in <Picture 0>."
    assert "label_format" in codes(plan)


def test_editing_summary_is_supplied_verbatim_and_requires_fixed_sentence():
    plan = reference_plan(videos=1)
    plan["media_assets"][0]["role"] = "video_edit"
    plan["ref2va"]["task_types"] = ["video editing"]
    assert "editing_summary" in codes(plan)
    plan["ref2va"]["summary"] = "The target video is an edited version of <Video 1>. The cup turns blue."
    result = CORE.compile_plan(plan)
    assert result["ready"]
    assert "[video editing] The target video is an edited version of <Video 1>." in result["final_prompt"]


def test_lyrics_crossing_cuts_and_visible_text_are_preserved_exactly():
    plan = fixture()
    plan["shots"][0]["dialogue"] = [{"speaker_id": "S1", "source": "A singer", "delivery": "sings:", "language": "中文", "text": "风起<scenetrans>", "after": "The voice continues seamlessly across the cut."}]
    second = {**copy.deepcopy(plan["shots"][0]), "id": "shot-b", "order": 2, "cut_seconds": 3}
    second["dialogue"][0]["text"] = "<scenetrans>归来<cutoff>"
    second["dialogue"][0]["after"] = "The phrase is cut off by the video ending."
    plan["shots"].append(second)
    result = CORE.compile_plan(plan)
    assert result["ready"]
    assert "<d>[中文] 风起<scenetrans></d>" in result["final_prompt"]
    assert "<d>[中文] <scenetrans>归来<cutoff></d>" in result["final_prompt"]
    assert result["final_prompt"].count("A singer (S1)") == 2


def test_paired_audio_does_not_consume_standalone_audio_budget():
    plan = reference_plan(videos=1, audios=4)
    video, audio = plan["media_assets"][:2]
    video.update(audio_enabled=True, paired_audio_asset_id=audio["asset_id"])
    video["probe"]["has_audio"] = True
    audio.update(source_video_asset_id=video["asset_id"], source=dict(video["source"]))
    assert CORE.validate_plan(plan)["ready"]


def test_node_rejects_secrets_inside_lock_snapshot_without_echoing_value():
    plan = fixture()
    plan["locks"] = [{"path": "/style", "value": {"api_key": "private-lock-secret"}}]
    output = NODE().compile(json.dumps(plan))
    assert output[-1] is False and output[0] == "{}"
    assert "private-lock-secret" not in str(output)


def test_invalid_patch_json_is_reported_without_losing_the_valid_plan():
    result = CORE.compile_plan(fixture(), '{"bad"')
    assert result["ready"]
    assert result["reverse_tasks"]["patch_report"]["rejected"][0]["reason"] == "invalid_json"


def test_missing_probe_and_segment_holes_are_not_reported_ready():
    plan = reference_plan(videos=1)
    plan["media_assets"][0]["probe"] = {}
    assert "probe_required" in codes(plan)
    plan = segmented()
    plan["segmentation"]["segments"][1]["source_window"]["in_seconds"] = 11
    assert "segment_hole" in codes(plan)
