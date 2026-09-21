"""CPU smoke through the installed Comfy executor and native loop expansion.

Only the expensive generation/cleanup body is synthetic. Entry (including actual
VHS decoding), disk recording, loop carry and final encoded assembly are real.
Run with the Comfy Python runtime; this script never starts a server or GPU job.
"""

import asyncio
import copy
from fractions import Fraction
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[1]
COMFY = ROOT.parents[1]
sys.path.insert(0, str(COMFY))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import av
import torch
import nodes
import execution
import folder_paths
import server
from comfy_extras import nodes_loop

package = types.ModuleType("zf_animate_native_smoke")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
RUNTIME = importlib.import_module(package.__name__ + ".animate_video.nodes")
PLAN = importlib.import_module(package.__name__ + ".animate_video.plan")
MASKING = importlib.import_module(package.__name__ + ".animate_video.masking")
spec = importlib.util.spec_from_file_location("animate_media_fixtures", ROOT / "tests" / "media_outlet_smoke.py")
MEDIA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MEDIA)
vhs_package = types.ModuleType("animate_actual_vhs")
vhs_package.__path__ = [str(COMFY / "custom_nodes" / "ComfyUI-VideoHelperSuite" / "videohelpersuite")]
sys.modules[vhs_package.__name__] = vhs_package


class Server:
    client_id = None
    last_node_id = None
    sockets_metadata = {}
    prompt_queue = None
    def send_sync(self, *args, **kwargs):
        pass
    def send_progress_text(self, text, node_id):
        pass


server.PromptServer.instance = Server()
VHS = importlib.import_module(vhs_package.__name__ + ".load_video_nodes").LoadVideoUpload
STATE = {}


class PlanSource:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}
    RETURN_TYPES = ("ZV_ANIMATE_PLAN", "INT")
    FUNCTION = "get"
    def get(self):
        return STATE["plan"], 3


class OriginalBody:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"context": ("ZV_ANIMATE_CONTEXT",), "source": ("IMAGE",),
            "transition": ("IMAGE",), "picture": ("IMAGE",), "mask": ("MASK",), "background": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "generate"
    def generate(self, context, source, transition, picture, mask, background):
        index = context["index"]
        assert index == len(STATE["generated"]), "native loop executed out of order"
        assert len(source) == (24, 8, 16)[index]
        assert len(picture) == 1
        if STATE["mask_enabled"]:
            assert mask.shape == source.shape[:3] and background is not None
        else:
            assert mask is None and background is None
        if index and STATE["mode"] == "continuation_21":
            assert torch.equal(transition, STATE["generated"][-1][-21:])
        else:
            assert transition is None
        count = (23, 7, 16)[index]  # Simulate the original graph's actual crop.
        frames = torch.linspace(.1 + index * .2, .2 + index * .2, count).reshape(-1, 1, 1, 1).expand(-1, 24, 32, 3).clone()
        STATE["generated"].append(frames)
        STATE["transitions"].append(0 if transition is None else len(transition))
        return (frames,)


class OriginalMaskDetect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"context": ("ZV_ANIMATE_CONTEXT",), "source": ("IMAGE",), "index": ("INT",), "text": ("STRING",)}}
    RETURN_TYPES = ("MASK",)
    FUNCTION = "detect"
    def detect(self, context, source, index, text):
        assert STATE["mask_enabled"], "disabled mask branch was executed"
        assert index == 2 and text == f"target {context['index']}"
        STATE["mask_calls"].append(context["index"])
        return (torch.ones(1, source.shape[1], source.shape[2]),)


class OriginalMaskTrack:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("IMAGE",), "seed": ("MASK",)}}
    RETURN_TYPES = ("MASK", "IMAGE")
    FUNCTION = "track"
    def track(self, source, seed):
        assert STATE["mask_enabled"], "disabled tracking branch was executed"
        return seed.repeat(len(source), 1, 1), source


class OriginalCleanup:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"frames": ("IMAGE",), "slot": ("INT",)}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "cleanup"
    OUTPUT_NODE = True
    def cleanup(self, frames, slot):
        STATE["cleanup"].append((len(STATE["generated"]) - 1, slot))
        return (frames,)


class Capture:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",), "count": ("INT",), "report": ("STRING",), "result": ("ZV_ANIMATE_RUN",)}}
    RETURN_TYPES = ()
    FUNCTION = "capture"
    OUTPUT_NODE = True
    def capture(self, video, count, report, result):
        STATE["final"] = video, count, report, result
        return ()


def source_project(original):
    project = copy.deepcopy(original)
    clip = next(row for row in project["video_track"] if row["source_audio_enabled"])
    sound = next(row for row in project["audio_track"] if row["clip_id"] == clip["audio_link_id"])
    picture = project["picture_track"][0]
    project["video_track"], project["audio_track"], project["picture_track"] = [], [], []
    for index, (start, end) in enumerate(((0, 24), (24, 32), (32, 48))):
        project["video_track"].append({**clip, "clip_id": f"clip-{index}", "audio_link_id": f"sound-{index}",
            "timeline_in_seconds": start / 24, "source_in_seconds": start / 24, "source_out_seconds": end / 24})
        project["audio_track"].append({**sound, "clip_id": f"sound-{index}", "linked_video_clip_id": f"clip-{index}",
            "source_video_clip_id": f"clip-{index}", "timeline_in_seconds": start / 24,
            "source_in_seconds": start / 24, "source_out_seconds": end / 24})
        project["picture_track"].append({**picture, "item_id": f"picture-{index}", "order": index + 1})
    return project


def graph():
    value = {
        "plan": {"class_type": "AnimateSmokePlan", "inputs": {}},
        "start": {"class_type": "StartLoop", "inputs": {"mode": "simple", "mode.num_iterations": ["plan", 1], "cache_iterations": False}},
        "entry": {"class_type": "ZVAnimateExecutionEntry", "inputs": {"animate_plan": ["plan", 0], "iteration_index": ["start", 0], "previous_result": ["start", 4]}},
        "mask-frame": {"class_type": "ZVAnimateMaskFrame", "inputs": {"segment_context": ["entry", 0], "frames": ["entry", 1], "front_padding": 0}},
        "mask-detect": {"class_type": "AnimateSmokeMaskDetect", "inputs": {"context": ["entry", 0], "source": ["entry", 1], "index": ["mask-frame", 0], "text": ["mask-frame", 1]}},
        "mask-seed": {"class_type": "ZVAnimateMaskSeed", "inputs": {"segment_context": ["entry", 0], "mask": ["mask-detect", 0]}},
        "mask-track": {"class_type": "AnimateSmokeMaskTrack", "inputs": {"source": ["entry", 1], "seed": ["mask-seed", 0]}},
        "mask-gate": {"class_type": "ZVAnimateMaskGate", "inputs": {"segment_context": ["entry", 0], "mask": ["mask-track", 0], "bg_images": ["mask-track", 1]}},
        "body": {"class_type": "AnimateSmokeBody", "inputs": {"context": ["entry", 0], "source": ["entry", 1], "transition": ["entry", 6], "picture": ["entry", 5], "mask": ["mask-gate", 0], "background": ["mask-gate", 1]}},
        "record": {"class_type": "ZVAnimateSegmentRecorder", "inputs": {"segment_context": ["entry", 0], "frames": ["body", 0], "source_audio": ["entry", 3], "previous_result": ["start", 4]}},
        "close": {"class_type": "EndLoop", "inputs": {"output_value": ["record", 0], "next_iteration_value": ["record", 0], "accumulate": False}},
        "finish": {"class_type": "ZVAnimateExecutionEnd", "inputs": {"animate_plan": ["plan", 0], "run_result": ["close", 0]}},
        "capture": {"class_type": "AnimateSmokeCapture", "inputs": {"video": ["finish", 0], "count": ["finish", 1], "report": ["finish", 2], "result": ["close", 0]}},
    }
    for index in range(1, 5):
        value[f"cleanup-{index}"] = {"class_type": "AnimateSmokeCleanup", "inputs": {"frames": ["body", 0], "slot": index}}
        value["close"]["inputs"][f"termination{index - 1}"] = [f"cleanup-{index}", 0]
    return value


def main():
    nodes.NODE_CLASS_MAPPINGS.update(nodes_loop.NODE_CLASS_MAPPINGS)
    nodes.NODE_CLASS_MAPPINGS.update({"VHS_LoadVideo": VHS, "AnimateSmokePlan": PlanSource,
        "AnimateSmokeBody": OriginalBody, "AnimateSmokeCleanup": OriginalCleanup, "AnimateSmokeCapture": Capture,
        "AnimateSmokeMaskDetect": OriginalMaskDetect, "AnimateSmokeMaskTrack": OriginalMaskTrack,
        **{name: getattr(MASKING, name) for name in ("ZVAnimateMaskFrame", "ZVAnimateMaskSeed", "ZVAnimateMaskGate")},
        **{name: getattr(RUNTIME, name) for name in ("ZVAnimateExecutionEntry", "ZVAnimateSegmentRecorder", "ZVAnimateExecutionEnd")}})
    evidence = []
    with tempfile.TemporaryDirectory(prefix="zv-animate-native-loop-") as folder:
        root = Path(folder)
        store, original = MEDIA.imported_project(root)
        folder_paths.set_input_directory(str(store.input_root))
        RUNTIME.get_store = lambda: store
        RUNTIME._temp_root = lambda: root / "runtime"
        for mode, enabled in ((seam, enabled) for seam in ("hard_cut", "continuation_21") for enabled in (False, True)):
            STATE.clear()
            source = source_project(original)
            assets = {row["asset_id"]: row for row in source["assets"]}
            tasks = {row["clip_id"]: {"asset_id": row["asset_id"], "prompt": f"target {i}",
                                     "source_frame": round(row["source_in_seconds"] * assets[row["asset_id"]]["probe"]["fps"]) + 1} for i, row in enumerate(source["video_track"])}
            config = {"schema_version": 1, "seam_mode": mode, "mask_enabled": enabled, "mask_tasks": tasks}
            STATE.update(mode=mode, mask_enabled=enabled, mask_calls=[], generated=[], transitions=[], cleanup=[], plan=PLAN.build_plan(source, config, fps=24))
            prompt = graph()
            validation = asyncio.run(execution.validate_prompt(mode, prompt, None))
            assert validation[0], validation
            runner = execution.PromptExecutor(Server(), cache_type=False, cache_args={"ram": 0, "ram_inactive": 0})
            runner.execute(prompt, mode, execute_outputs=validation[2])
            assert runner.success and "final" in STATE, runner.status_messages
            video, count, report, result = STATE["final"]
            assert count == 46 and "24→23（-1）" in report and "8→7（-1）" in report
            assert len(STATE["generated"]) == 3
            assert STATE["mask_calls"] == ([0, 1, 2] if enabled else [])
            assert sorted(STATE["cleanup"]) == [(i, j) for i in range(3) for j in range(1, 5)]
            assert result["completed_count"] == 3
            manifest = json.loads((root / "runtime" / "zv_animate_segments" / result["run_id"] / "manifest.json").read_text(encoding="utf-8"))
            assert [row["frames"] for row in manifest["segments"]] == [23, 7, 16]
            assert [row["frame_delta"] for row in manifest["segments"]] == [-1, -1, 0]
            assert sum(row["audio_samples"] for row in manifest["segments"]) == round(46 * 44100 / 24)
            with av.open(str(video._animate_path)) as encoded:
                assert [frame.pts * frame.time_base for frame in encoded.decode(video=0)] == [Fraction(i, 24) for i in range(46)]
            evidence.append({"mode": mode, "mask_enabled": enabled, "mask_calls": STATE["mask_calls"], "native_iterations": 3, "actual_frames": count,
                "transition_counts": STATE["transitions"], "cleanup_calls": len(STATE["cleanup"]),
                "disk_completed_count": result["completed_count"], "frame_deltas": [-1, -1, 0]})
    print(json.dumps({"passed": True, "native_executor": str(Path(execution.__file__)), "results": evidence}, ensure_ascii=False))


if __name__ == "__main__":
    main()
