import copy
import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "zf_h3_reference_detection_tests"
root_package = types.ModuleType(PACKAGE)
root_package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, root_package)

D = importlib.import_module(PACKAGE + ".h3_focus.reference_detection")


def node(class_type, **inputs):
    return {"class_type": class_type, "inputs": inputs}


def base_prompt():
    return {
        "172": node("ZVH3InterviewFormV2", media_project=["165", 0]),
        "165": node("ZVUniversalMediaEvidenceDesk", project_data="{}"),
        "176": node("ZVPictureOutlet", media_project=["165", 0], item_id="picture-stable"),
        "177": node("ZVVideoOutlet", media_project=["165", 0], clip_id="video-stable"),
        "178": node("ZVAudioOutlet", media_project=["165", 0], clip_id="audio-stable"),
        "190": node("TextRelay", text=["172", 1]),
        "146": node(
            "ZFPromptDirectorLocalLLM",
            prompt=["190", 0],
            image1=["176", 0],
            video_frames=["177", 0],
        ),
        # A later LLM still has the interview in its ancestry, but must not be
        # mistaken for Stage1 merely because it uses the same node class.
        "147": node("ZFPromptDirectorLocalLLM", prompt=["146", 0]),
        "7": node(
            "MiniMaxH3AudioConditioningT8",
            prompt=["147", 0],
            **{
                "ref_images.ref_image_0": ["176", 0],
                "ref_videos.ref_video_0": ["177", 0],
                "ref_video_audios.ref_video_audio_0": ["177", 1],
                "add_source_as_reference": True,
            },
        ),
        "14": node(
            "MiniMaxH3AudioConditioningT8",
            prompt=["147", 0],
            **{
                "ref_images.ref_image_0": ["176", 0],
                "ref_videos.ref_video_0": ["177", 0],
                "ref_video_audios.ref_video_audio_0": ["177", 1],
                "add_source_as_reference": True,
            },
        ),
        # This conditioning belongs to another prompt chain and is ignored.
        "99": node(
            "MiniMaxH3AudioConditioningT8",
            prompt="unrelated",
            **{"ref_images.ref_image_0": ["178", 0]},
        ),
    }


def fixed_hub_prompt():
    prompt = {
        "172": node("ZVH3InterviewFormV2", media_project=["165", 0]),
        "165": node("ZVUniversalMediaEvidenceDesk", project_data="{}"),
        "180": node("ZVH3ReferenceOutlet", reference_plan=["172", 6]),
        "146": node("ZFPromptDirectorLocalLLM", prompt=["172", 1]),
    }
    hub_inputs = {
        "first_frame": ["180", 0],
        "last_frame": ["180", 1],
        **{
            f"ref_images.ref_image_{index}": ["180", 2 + index]
            for index in range(9)
        },
        **{
            f"ref_videos.ref_video_{index}": ["180", 11 + index]
            for index in range(3)
        },
        **{
            f"ref_video_audios.ref_video_audio_{index}": ["180", 14 + index]
            for index in range(3)
        },
        "drive_audio": ["180", 17],
        "final_audio": ["180", 18],
        **{
            f"ref_audios.ref_audio_{index}": ["180", 19 + index]
            for index in range(3)
        },
        "add_source_as_reference": True,
        "prompt_primary_audio_ordinal": 0,
    }
    stage_inputs = {
        **{f"image{index + 1}": ["180", index] for index in range(11)},
        "video_frames": ["180", 11],
        "video_frames2": ["180", 12],
        "video_frames3": ["180", 13],
    }
    prompt["146"]["inputs"].update(stage_inputs)
    prompt["7"] = node(
        "MiniMaxH3AudioConditioningT8", prompt=["146", 0], **copy.deepcopy(hub_inputs)
    )
    prompt["14"] = node(
        "MiniMaxH3AudioConditioningT8", prompt=["146", 0], **copy.deepcopy(hub_inputs)
    )
    return prompt


def test_detects_only_the_interview_chain_and_matches_current_dense_order():
    result = D.detect_reference_wiring(base_prompt(), "172")
    assert result["errors"] == []
    assert result["conditioning_count"] == 2
    assert [row["binding_id"] for row in result["pictures"]] == ["picture-stable"]
    assert [row["binding_id"] for row in result["videos"]] == ["video-stable"]
    assert result["videos"][0]["soundtrack"] == {
        "binding_id": "video-stable",
        "outlet_type": "ZVVideoOutlet",
        "output_slot": 1,
    }
    assert [(row["role"], row["binding_id"]) for row in result["audios"]] == [
        ("video_soundtrack", "video-stable")
    ]
    assert result["stage1"]["node_count"] == 1
    assert [row["binding_id"] for row in result["stage1"]["pictures"]] == ["picture-stable"]
    assert [row["binding_id"] for row in result["stage1"]["videos"]] == ["video-stable"]


def test_t8_real_order_includes_keyframes_and_compresses_sparse_ports():
    prompt = base_prompt()
    prompt.update({
        "201": node("ZVPictureOutlet", item_id="first"),
        "202": node("ZVPictureOutlet", item_id="last"),
        "203": node("ZVPictureOutlet", item_id="ref-zero"),
        "204": node("ZVPictureOutlet", item_id="ref-five"),
        "205": node("ZVVideoOutlet", clip_id="video-two"),
        "206": node("ZVAudioOutlet", clip_id="drive"),
        "207": node("ZVAudioOutlet", clip_id="ref-audio-two"),
    })
    dense_inputs = {
        "first_frame": ["201", 0],
        "last_frame": ["202", 0],
        "ref_images.ref_image_5": ["204", 0],
        "ref_images.ref_image_0": ["203", 0],
        "ref_videos.ref_video_2": ["205", 0],
        "ref_video_audios.ref_video_audio_2": ["205", 1],
        "drive_audio": ["206", 0],
        "add_source_as_reference": True,
        "ref_audios.ref_audio_2": ["207", 0],
    }
    prompt["7"]["inputs"] = {"prompt": ["147", 0], **dense_inputs}
    # Different sparse socket suffixes in HIGH still produce the same dense
    # runtime mapping and therefore are not a LOW/HIGH mismatch.
    high_inputs = copy.deepcopy(dense_inputs)
    high_inputs["ref_images.ref_image_1"] = high_inputs.pop("ref_images.ref_image_0")
    high_inputs["ref_images.ref_image_8"] = high_inputs.pop("ref_images.ref_image_5")
    high_inputs["ref_videos.ref_video_1"] = high_inputs.pop("ref_videos.ref_video_2")
    high_inputs["ref_video_audios.ref_video_audio_1"] = high_inputs.pop(
        "ref_video_audios.ref_video_audio_2"
    )
    high_inputs["ref_audios.ref_audio_0"] = high_inputs.pop("ref_audios.ref_audio_2")
    prompt["14"]["inputs"] = {"prompt": ["147", 0], **high_inputs}
    prompt["146"]["inputs"].update(
        image1=["201", 0],
        image2=["202", 0],
        image3=["203", 0],
        image4=["204", 0],
        video_frames=["205", 0],
    )

    result = D.detect_reference_wiring(prompt, 172)
    assert result["errors"] == []
    assert [(row["ordinal"], row["role"], row["binding_id"]) for row in result["pictures"]] == [
        (1, "first_frame", "first"),
        (2, "last_frame", "last"),
        (3, "reference_image", "ref-zero"),
        (4, "reference_image", "ref-five"),
    ]
    assert [(row["ordinal"], row["binding_id"]) for row in result["videos"]] == [
        (1, "video-two")
    ]
    assert [(row["ordinal"], row["role"], row["binding_id"]) for row in result["audios"]] == [
        (1, "video_soundtrack", "video-two"),
        (2, "drive_audio", "drive"),
        (3, "reference_audio", "ref-audio-two"),
    ]


def test_stage1_accepts_keyframes_plus_all_nine_reference_images():
    prompt = base_prompt()
    picture_ids = [f"picture-{index}" for index in range(1, 12)]
    for offset, binding_id in enumerate(picture_ids, start=201):
        prompt[str(offset)] = node("ZVPictureOutlet", item_id=binding_id)

    h3_inputs = {
        "prompt": ["147", 0],
        "first_frame": ["201", 0],
        "last_frame": ["202", 0],
        "ref_videos.ref_video_0": ["177", 0],
        "ref_video_audios.ref_video_audio_0": ["177", 1],
        "add_source_as_reference": True,
    }
    h3_inputs.update(
        {
            f"ref_images.ref_image_{index}": [str(203 + index), 0]
            for index in range(9)
        }
    )
    prompt["7"]["inputs"] = copy.deepcopy(h3_inputs)
    prompt["14"]["inputs"] = copy.deepcopy(h3_inputs)
    prompt["146"]["inputs"] = {
        "prompt": ["190", 0],
        "video_frames": ["177", 0],
        **{
            f"image{index}": [str(200 + index), 0]
            for index in range(1, 12)
        },
    }

    result = D.detect_reference_wiring(prompt, "172")
    assert result["errors"] == []
    assert [row["binding_id"] for row in result["pictures"]] == picture_ids
    assert [row["binding_id"] for row in result["stage1"]["pictures"]] == picture_ids


def test_low_high_and_stage1_order_mismatches_are_reported():
    prompt = base_prompt()
    prompt["179"] = node("ZVPictureOutlet", item_id="other-picture")
    prompt["14"]["inputs"]["ref_images.ref_image_0"] = ["179", 0]
    prompt["146"]["inputs"]["image1"] = ["179", 0]
    result = D.detect_reference_wiring(prompt, "172")
    codes = {row["code"] for row in result["errors"]}
    assert "conditioning_mapping_mismatch" in codes
    assert "stage1_picture_mapping_mismatch" in codes


def test_video_soundtrack_requires_same_video_outlet_and_same_suffix():
    prompt = base_prompt()
    prompt["188"] = node("ZVVideoOutlet", clip_id="wrong-video")
    prompt["7"]["inputs"]["ref_video_audios.ref_video_audio_0"] = ["188", 1]
    prompt["14"]["inputs"]["ref_video_audios.ref_video_audio_0"] = ["188", 1]
    prompt["7"]["inputs"]["ref_video_audios.ref_video_audio_2"] = ["177", 1]
    prompt["14"]["inputs"]["ref_video_audios.ref_video_audio_2"] = ["177", 1]
    result = D.detect_reference_wiring(prompt, "172")
    codes = {row["code"] for row in result["errors"]}
    assert {"video_soundtrack_pair_mismatch", "orphan_video_soundtrack"} <= codes


def test_direct_outlet_type_output_slot_and_binding_are_validated():
    prompt = base_prompt()
    prompt["176"]["inputs"]["item_id"] = ["190", 0]
    prompt["146"]["inputs"]["video_frames"] = ["177", 1]
    result = D.detect_reference_wiring(prompt, "172")
    codes = {row["code"] for row in result["errors"]}
    assert "missing_stable_binding" in codes
    assert "wrong_outlet_output" in codes


def test_compare_detection_ignores_saved_errors_but_rejects_actual_errors_or_drift():
    actual = D.detect_reference_wiring(base_prompt(), "172")
    compact = D.detection_snapshot(actual)
    assert compact == {
        "version": 1,
        "pictures": [{"item_id": "picture-stable", "source_kind": "picture", "source_port": "image", "origin": "reference"}],
        "videos": [{"item_id": "video-stable", "source_kind": "video", "source_port": "frames", "origin": "reference"}],
        "audios": [{"item_id": "video-stable", "source_kind": "video", "source_port": "original_audio", "origin": "video_soundtrack"}],
        "stage1": {"pictures": ["picture-stable"], "videos": ["video-stable"]},
        "conditioning_count": 2,
    }
    assert D.compare_detection(compact, actual)["match"]
    saved = copy.deepcopy(actual)
    saved["errors"] = [{"code": "old_frontend_warning"}]
    assert D.compare_detection(saved, actual) == {
        "match": True,
        "differences": [],
        "errors": [],
    }

    drifted = copy.deepcopy(actual)
    drifted["pictures"][0]["binding_id"] = "changed"
    compared = D.compare_detection(saved, drifted)
    assert not compared["match"]
    assert [row["field"] for row in compared["differences"]] == ["pictures"]

    broken = D.detect_reference_wiring(base_prompt(), "missing")
    compared = D.compare_detection(saved, broken)
    assert not compared["match"] and compared["errors"]


def test_fixed_hub_audit_requires_the_complete_semantic_fanout():
    prompt = fixed_hub_prompt()
    result = D.validate_reference_hub_wiring(prompt, "172")
    assert result == {
        "hub_count": 1,
        "conditioning_count": 2,
        "stage1_count": 1,
        "errors": [],
    }

    prompt["14"]["inputs"]["first_frame"] = ["180", 1]
    prompt["14"]["inputs"]["add_source_as_reference"] = False
    prompt["14"]["inputs"]["prompt_primary_audio_ordinal"] = 1
    prompt["146"]["inputs"].pop("image11")
    broken = D.validate_reference_hub_wiring(prompt, 172)
    codes = [row["code"] for row in broken["errors"]]
    assert "fixed_hub_wiring" in codes
    assert codes.count("fixed_hub_audio_numbering") == 2
    assert any(row.get("input_name") == "image11" for row in broken["errors"])


def test_fixed_hub_stage_only_partial_branch_is_valid_but_conditioning_needs_stage1():
    prompt = fixed_hub_prompt()
    prompt.pop("7")
    prompt.pop("14")
    stage_only = D.validate_reference_hub_wiring(prompt, "172")
    assert stage_only["conditioning_count"] == 0
    assert stage_only["stage1_count"] == 1
    assert stage_only["errors"] == []

    prompt = fixed_hub_prompt()
    prompt.pop("146")
    # Keep the T8 nodes in the interview ancestry while removing Stage①.
    prompt["7"]["inputs"]["prompt"] = ["172", 3]
    prompt["14"]["inputs"]["prompt"] = ["172", 3]
    missing = D.validate_reference_hub_wiring(prompt, "172")
    assert any(row["code"] == "fixed_hub_stage1_missing" for row in missing["errors"])
