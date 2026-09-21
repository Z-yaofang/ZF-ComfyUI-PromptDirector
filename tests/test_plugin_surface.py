"""Check the published node/UI boundary without importing ComfyUI or models."""

import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RETIRED_NODES = {
    "ZVH3InterviewForm", "ZVH3FocusCompiler", "ZVPictureSlotOutlet",
    "ZVVideoSlotOutlet", "ZVAudioSlotOutlet", "ZFBlueprintParser", "ZFSinglePromptTask",
}


def source(path):
    return (ROOT / path).read_text(encoding="utf-8-sig")


def assigned(body, name):
    return next(
        node.value for node in body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )


def js_string(text, name):
    match = re.search(rf'\bconst\s+{name}\s*=\s*[\"\']([^\"\']+)[\"\']', text)
    assert match, f"Missing string constant: {name}"
    return match.group(1)


def test_registered_nodes_and_display_names_have_one_current_surface():
    body = ast.parse(source("nodes.py")).body
    tables = []
    for name in ("NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"):
        mapping = assigned(body, name)
        keys = [ast.literal_eval(key) for key in mapping.keys]
        assert len(keys) == len(set(keys)), f"Duplicate keys in {name}"
        assert not RETIRED_NODES.intersection(keys), f"Retired node registered in {name}"
        tables.append(set(keys))
    assert tables[0] == tables[1]
    assert {"ZVH3InterviewFormV2", "ZVH3ReverseStage", "ZVH3ReferenceOutlet"} <= tables[0]


def test_frontend_extensions_have_unique_registration_names():
    owners = {}
    for path in sorted((ROOT / "web").glob("*.js")):
        text = path.read_text(encoding="utf-8-sig")
        registrations = re.findall(
            r'app\.registerExtension\(\s*\{\s*name\s*:\s*(?:[\"\']([^\"\']+)[\"\']|([A-Za-z_$][\w$]*))',
            text,
        )
        assert len(registrations) == text.count("app.registerExtension("), path.name
        for literal, variable in registrations:
            name = literal or js_string(text, variable)
            assert name not in owners, f"{name} is registered by {owners.get(name)} and {path.name}"
            owners[name] = path.name
    assert owners.get("ZV.H3InterviewForm") == "h3_interview.js"


def test_frontend_does_not_attach_retired_nodes():
    for path in sorted((ROOT / "web").glob("*.js")):
        strings = set(re.findall(r'[\"\']([A-Za-z][A-Za-z0-9_]*)[\"\']', path.read_text(encoding="utf-8-sig")))
        assert not RETIRED_NODES.intersection(strings), path.name


def test_h3_form_ui_and_backend_share_current_contract():
    ui = source("web/h3_interview.js")
    form_name = js_string(ui, "NAME")
    assert form_name == "ZVH3InterviewFormV2"
    form = next(
        node for node in ast.parse(source("h3_focus/node.py")).body
        if isinstance(node, ast.ClassDef) and node.name == form_name
    )
    outputs = ast.literal_eval(assigned(form.body, "RETURN_NAMES"))
    output_types = ast.literal_eval(assigned(form.body, "RETURN_TYPES"))
    assert outputs == (
        "user_prompt", "material_context_json", "duration_seconds", "interview_json",
        "human_report", "ready", "reference_plan",
    )
    assert output_types == ("STRING", "STRING", "FLOAT", "STRING", "STRING", "BOOLEAN", "ZV_H3_REFERENCE_PLAN")
    input_types = next(node for node in form.body if isinstance(node, ast.FunctionDef) and node.name == "INPUT_TYPES")
    required = next(node for node in ast.walk(input_types) if isinstance(node, ast.Dict) and any(isinstance(key, ast.Constant) and key.value == "media_project" for key in node.keys))
    assert {ast.literal_eval(key) for key in required.keys} == {"media_project", "interview_json"}
    assert 'item.name === "interview_json"' in ui
    assert 'input.name === "media_project"' in ui
    assert re.search(rf'endpoint\.slot\s*===\s*{outputs.index("reference_plan")}\b', ui)
    assert re.search(rf'distanceToOutput\(node,\s*interviewNode\.id,\s*{outputs.index("material_context_json")}\)', ui)
    interview_body = ast.parse(source("h3_focus/interview.py")).body
    assert js_string(ui, "VERSION") == ast.literal_eval(assigned(interview_body, "SCHEMA_VERSION"))
    detection_body = ast.parse(source("h3_focus/reference_detection.py")).body
    assert form_name == ast.literal_eval(assigned(detection_body, "INTERVIEW_CLASS"))
    assert js_string(ui, "H3_REFERENCE_HUB") == ast.literal_eval(assigned(detection_body, "HUB_CLASS"))
