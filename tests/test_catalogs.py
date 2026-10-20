import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _read_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_catalog_ids_and_recommendations_are_consistent():
    purposes = _read_json("purposes.json")
    visuals = _read_json("visual_methods.json")
    recommendations = _read_json("purpose_visual_recommendations.json")

    purpose_ids = [item["id"] for item in purposes]
    visual_ids = [item["id"] for item in visuals]
    assert len(purpose_ids) == len(set(purpose_ids)) == 32
    assert len(visual_ids) == len(set(visual_ids)) == 41
    assert set(recommendations) == set(purpose_ids)
    for purpose_id, recommended in recommendations.items():
        assert recommended, purpose_id
        assert len(recommended) == len(set(recommended)), purpose_id
        assert set(recommended) <= set(visual_ids), purpose_id


def test_character_reference_sheet_is_production_oriented():
    purposes = {item["id"]: item for item in _read_json("purposes.json")}
    purpose = purposes["character_reference_sheet"]
    combined = "".join(purpose["material_focus"]) + purpose["prompt"] + purpose["detail_prompt"]

    for phrase in ("正面", "侧面", "背面", "统一比例", "中立姿态"):
        assert phrase in combined


def test_template_rules_extend_existing_methods_without_new_duplicates():
    visuals = {item["id"]: item for item in _read_json("visual_methods.json")}
    sheet = "".join(visuals["encyclopedia_sheet"].values())
    split = "".join(visuals["geometric_panel_grid"].values())
    system_prompt = (ROOT / "nodes.py").read_text(encoding="utf-8")

    assert "标准视图" in sheet and "低透视畸变" in sheet
    assert "双侧分屏" in split and "分界轴" in split
    assert "只采用一套相互兼容的景别与机位" in system_prompt


def test_recommendation_guide_covers_every_purpose_and_its_top_choices():
    purposes = _read_json("purposes.json")
    visuals = {item["id"]: item["name"] for item in _read_json("visual_methods.json")}
    recommendations = _read_json("purpose_visual_recommendations.json")
    guide = (ROOT / "docs" / "用途与创意推荐说明书.md").read_text(encoding="utf-8")

    for purpose in purposes:
        assert purpose["name"] in guide
        for visual_id in recommendations[purpose["id"]][:3]:
            assert visuals[visual_id] in guide


def test_material_update_provenance_and_thumbnail_assets():
    import re
    import xml.etree.ElementTree as ET

    manifest = _read_json("material_sources.json")
    visuals = {item["id"]: item for item in _read_json("visual_methods.json")}
    sources = {item["id"]: item for item in manifest["sources"]}
    assert manifest["catalog_counts"]["visual_methods"] == len(visuals)
    assert manifest["catalog_counts"]["purposes"] == len(_read_json("purposes.json"))
    assert len({entry["visual_id"] for entry in manifest["entries"]}) == len(manifest["entries"])
    for entry in manifest["entries"]:
        visual = visuals[entry["visual_id"]]
        assert entry["source_id"] in sources
        assert entry["source_indices_zero_based"]
        assert len(entry["source_indices_zero_based"]) == len(entry["source_text_sha256"])
        assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in entry["source_text_sha256"])
        thumbnail = ROOT / "web" / "thumbnails" / visual["thumbnail"]
        assert thumbnail.is_file()
        if thumbnail.suffix == ".svg":
            svg = ET.parse(thumbnail).getroot()
            assert svg.tag == "{http://www.w3.org/2000/svg}svg"
            assert not list(svg.iter("{http://www.w3.org/2000/svg}script"))
            assert all(not key.lower().startswith("on") for element in svg.iter() for key in element.attrib)

    for entry in manifest.get("daily_adaptations", []):
        assert entry["target_catalog"] == "visual_methods"
        visual = visuals[entry["target_id"]]
        source = sources[entry["source_id"]]
        assert source["zip_crc_verified"] is True
        assert re.fullmatch(r"[0-9a-f]{64}", source["file_sha256"])
        indices = entry["source_paragraph_indices_zero_based"]
        assert indices and len(indices) == len(set(indices))
        assert all(isinstance(index, int) and index >= 0 for index in indices)
        assert len(indices) == len(entry["source_text_sha256"])
        assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in entry["source_text_sha256"])
        assert entry["adaptation"] in visual[entry["target_field"]]
