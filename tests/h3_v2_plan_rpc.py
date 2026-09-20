"""Browser bridge: neutral temporary CPU fixtures; planning reads caches only."""

import copy
import hashlib
import json
import runpy
import sys
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT / "tests/test_h3_v2.py"))
I, C, S, R = (H[key] for key in ("I", "C", "S", "R"))
import importlib
P = importlib.import_module(H["H"]["PACKAGE"] + ".h3_focus.presets")
DB = importlib.import_module(H["H"]["PACKAGE"] + ".h3_focus.preset_store")
MEDIA_ROOT = ROOT.parents[1] / "input/zf_media_evidence"
NEUTRAL_DIRECTORY = tempfile.TemporaryDirectory(prefix="h3-v2-neutral-")
NEUTRAL_ROOT = None
NEUTRAL_HANDLES = set()
NEUTRAL_PROJECT = None
LIBRARY_ROOT = Path(NEUTRAL_DIRECTORY.name) / "user"
LIBRARY_ROOT.mkdir()


def cached_path(handle, variant):
    if not isinstance(handle, str) or not handle.startswith("originals/"):
        raise ValueError("Invalid source handle")
    suffix = {"thumbnail": ".jpg", "proxy": ".mp4", "audio": ".m4a", "peaks": ".json"}
    root = NEUTRAL_ROOT if handle in NEUTRAL_HANDLES else MEDIA_ROOT
    path = root / handle if variant == "original" else root / "cache" / (hashlib.sha256((handle + variant + "v1").encode()).hexdigest() + suffix[variant])
    path = path.resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Existing cache missing; test never creates previews")
    return str(path)


def fixture():
    global NEUTRAL_ROOT, NEUTRAL_HANDLES, NEUTRAL_PROJECT
    if NEUTRAL_PROJECT is not None:
        return copy.deepcopy(NEUTRAL_PROJECT)
    media = runpy.run_path(str(ROOT / "tests/media_outlet_smoke.py"))
    store, generated = media["imported_project"](Path(NEUTRAL_DIRECTORY.name))
    image, video, audio = generated["assets"][0], generated["assets"][3], generated["assets"][4]
    for asset, variants in [(image, ["thumbnail"]), (video, ["thumbnail", "proxy", "audio", "peaks"]), (audio, ["audio", "peaks"])]:
        for variant in variants: store.preview(asset["source_handle"], variant)
    NEUTRAL_ROOT = store.root
    NEUTRAL_HANDLES = {asset["source_handle"] for asset in (image, video, audio)}
    project = H["source"](2, 1, 1, soundtracks=True)
    project["assets"] = list({asset["asset_id"]: asset for asset in (image, video, audio)}.values())
    for row in project["picture_track"]: row["asset_id"] = image["asset_id"]
    project["video_track"][0]["asset_id"] = video["asset_id"]
    for row in project["audio_track"]: row["asset_id"] = video["asset_id"] if row["linked_video_clip_id"] else audio["asset_id"]
    NEUTRAL_PROJECT = C.normalize_project(project)
    return copy.deepcopy(NEUTRAL_PROJECT)


def vectors():
    results = []
    for pictures, videos, audios in [(0, 0, 0), (1, 0, 0), (2, 0, 0), (9, 0, 0), (10, 0, 0), (6, 3, 3), (7, 3, 3), (1, 3, 4)]:
        for soundtrack in [False, True]:
            project = H["source"](pictures, videos, audios, soundtracks=soundtrack)
            state = I.empty_interview()
            if audios == 4: state["bindings"]["a1"] = {"item_id": "a1", "participates": True, "banks": ["drive_audio"]}
            result = S.plan_interview({"state": state, "media_project": project, "align": True, "conditioning_count": 2})
            results.append({"project": project, "state": result["state"], "mode": result["validation"]["effective_mode"], "snapshot": result["snapshot"], "context": result["alignment_context"]})
    for banks in [["first_frame"], ["last_frame"], ["first_frame", "last_frame"], ["first_frame", "ref_images"]]:
        project = H["source"](1, 0, 0)
        state = I.empty_interview(); state["bindings"]["p1"] = {"item_id": "p1", "participates": True, "banks": banks}
        result = S.plan_interview({"state": state, "media_project": project, "align": True, "conditioning_count": 2})
        results.append({"project": project, "state": result["state"], "mode": result["validation"]["effective_mode"], "snapshot": result["snapshot"], "context": result["alignment_context"]})
    return results


def execute(request):
    if request["action"] == "presets":
        library = DB.InterviewLibrary(LIBRARY_ROOT)
        method, path = request["method"], request["path"]
        try:
            value = P.strict_json(request["body"]) if request.get("body") else None
            if method == "GET" and not path:
                body = library.listing()
            elif method == "POST" and not path:
                body = library.create(value["name"], P.capture_template(value["state"], value["media_project"]))
            elif path == "/export": body = library.export(value["preset_ids"])
            elif path == "/import": body = {"presets": library.import_collection(value)}
            else:
                identifier = path.split("/")[1]
                if path.endswith("/apply"):
                    saved = library.get(identifier); body = P.apply_template(saved["template"], value["state"], value["media_project"])
                    body["preset"] = {key:saved[key] for key in ("name", "preset_id", "preset_version")}
                elif method == "GET": body = library.get(identifier)
                elif method == "DELETE": library.delete(identifier, value["preset_version"]); body = {"deleted": True}
                else:
                    template = P.capture_template(value["state"], value["media_project"]) if method == "PUT" else None
                    body = library.update(identifier, value["preset_version"], value["name"], template)
            return {"status": 200, "body": body}
        except P.PresetError as error: return {"status": error.status, "body": {"error": {"code": error.code, "message": error.message}}}
    if request["action"] == "plan": return S.plan_interview(request["value"])
    if request["action"] == "fixture": return fixture()
    if request["action"] == "preview": return cached_path(request["handle"], request["variant"])
    if request["action"] == "normalize": return C.normalize_project(request["value"])
    if request["action"] == "vectors": return vectors()
    if request["action"] == "workflow":
        graph = json.loads(H["WORKFLOW"].read_text(encoding="utf-8"))
        nodes = {node["id"]: node for node in graph["nodes"]}
        project = fixture()
        # Exercise the distributed topology with generated neutral media only.
        nodes[165]["widgets_values"][0] = json.dumps(project)
        return {"graph": graph, "state": I.normalize_interview(json.loads(nodes[172]["widgets_values"][0])), "project": project}
    raise ValueError("Unknown test action")


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8"); sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        request = json.loads(line)
        try:
            print(json.dumps({"id": request["id"], "result": execute(request)}, ensure_ascii=False), flush=True)
        except Exception as error:
            print(json.dumps({"id": request["id"], "error": str(error)}, ensure_ascii=False), flush=True)
