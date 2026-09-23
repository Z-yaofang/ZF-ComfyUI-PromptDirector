"""CPU regression: legacy per-segment video outputs must not rerun the loop body.

The expensive Animate body is synthetic. Native Comfy execution, loop expansion,
real VHS video encoding, segment recording, and final SaveVideo remain active.
Run directly with the bundled Comfy Python; this does not start a server or GPU.
"""

import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import animate_native_loop_smoke as smoke


def register_nodes():
    smoke.nodes.NODE_CLASS_MAPPINGS.update(smoke.nodes_loop.NODE_CLASS_MAPPINGS)
    smoke.nodes.NODE_CLASS_MAPPINGS.update({
        "VHS_LoadVideo": smoke.VHS,
        "VHS_VideoCombine": smoke.VIDEO_COMBINE,
        "AnimateSmokePlan": smoke.PlanSource,
        "AnimateSmokeBody": smoke.OriginalBody,
        "AnimateSmokeCleanup": smoke.OriginalCleanup,
        "AnimateSmokeMaskDetect": smoke.OriginalMaskDetect,
        "AnimateSmokeMaskTrack": smoke.OriginalMaskTrack,
        "SaveVideo": smoke.nodes_video.SaveVideo,
        **{
            name: getattr(smoke.MASKING, name)
            for name in ("ZVAnimateMaskFrame", "ZVAnimateMaskSeed", "ZVAnimateMaskGate")
        },
        **{
            name: getattr(smoke.RUNTIME, name)
            for name in ("ZVAnimateExecutionEntry", "ZVAnimateSegmentRecorder", "ZVAnimateExecutionEnd")
        },
    })
    smoke.server.PromptServer.instance = smoke.Server()


def add_legacy_savers(prompt):
    prompt = copy.deepcopy(prompt)
    for index in range(2):
        name = f"legacy-save-{index + 1}"
        prompt[name] = {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["body", 0],
                "frame_rate": 24,
                "loop_count": 0,
                "filename_prefix": name,
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
                "pix_fmt": "yuv420p",
                "crf": 19,
                "save_metadata": False,
                "trim_to_audio": False,
            },
        }
        prompt["close"]["inputs"][f"terminations.termination{index + 4}"] = [name, 0]
    return prompt


def run_case(root, source, with_legacy):
    case_root = root / ("legacy-roots" if with_legacy else "final-only")
    output_root = case_root / "output"
    temp_root = case_root / "temp"
    output_root.mkdir(parents=True)
    temp_root.mkdir()
    smoke.folder_paths.set_output_directory(str(output_root))
    smoke.folder_paths.set_temp_directory(str(temp_root))
    smoke.RUNTIME._temp_root = lambda: case_root / "runtime"

    assets = {row["asset_id"]: row for row in source["assets"]}
    tasks = {
        row["clip_id"]: {
            "asset_id": row["asset_id"],
            "prompt": f"target {index}",
            "source_frame": round(row["source_in_seconds"] * assets[row["asset_id"]]["probe"]["fps"]) + 1,
        }
        for index, row in enumerate(source["video_track"])
    }
    config = {"schema_version": 1, "seam_mode": "hard_cut", "mask_enabled": False, "mask_tasks": tasks}
    smoke.STATE.clear()
    smoke.STATE.update(
        mode="hard_cut", mask_enabled=False, mask_calls=[], track_calls=[], generated=[],
        transitions=[], cleanup=[], mask_previews=[], plan=smoke.PLAN.build_plan(source, config, fps=24),
    )
    prompt = smoke.single_root_graph()
    if with_legacy:
        prompt = add_legacy_savers(prompt)
    validation = asyncio.run(smoke.execution.validate_prompt("duplicate-roots", prompt, None))
    assert validation[0], validation
    assert set(validation[2]) == ({"save", "legacy-save-1", "legacy-save-2"} if with_legacy else {"save"})
    ram_headroom = float(os.environ.get("ZV_SMOKE_RAM_HEADROOM_GIB", "0.5"))
    runner = smoke.execution.PromptExecutor(
        smoke.Server(), cache_type=smoke.execution.CacheType.RAM_PRESSURE,
        cache_args={"ram": ram_headroom, "ram_inactive": ram_headroom},
    )
    runner.execute(prompt, "duplicate-roots", execute_outputs=validation[2])
    assert runner.success, runner.status_messages
    assert len(smoke.STATE["generated"]) == 3
    assert smoke.STATE["transitions"] == [0, 0, 0]

    run_root = case_root / "runtime" / "zv_animate_segments"
    runs = list(run_root.iterdir())
    assert len(runs) == 1, runs
    manifest = json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert [row["frames"] for row in manifest["segments"]] == [23, 7, 16]
    assert len(list(output_root.glob("final_*.mp4"))) == 1
    legacy_files = list(output_root.glob("legacy-save-*.mp4"))
    assert len(legacy_files) == (6 if with_legacy else 0), legacy_files
    return {
        "roots": sorted(validation[2]),
        "body_calls": len(smoke.STATE["generated"]),
        "run_ids": len(runs),
        "recorded_frames": [row["frames"] for row in manifest["segments"]],
        "legacy_saves": len(legacy_files),
        "final_saves": 1,
        "cache_active_evictions": runner.caches.outputs.active_evictions,
        "cache_full_evictions": runner.caches.outputs.full_evictions,
        "ram_headroom_gib": ram_headroom,
    }


def main():
    register_nodes()
    with tempfile.TemporaryDirectory(prefix="zv-animate-output-roots-") as folder:
        root = Path(folder)
        store, original = smoke.MEDIA.imported_project(root)
        smoke.folder_paths.set_input_directory(str(store.input_root))
        smoke.RUNTIME.get_store = lambda: store
        source = smoke.source_project(original)
        results = [run_case(root, source, with_legacy) for with_legacy in (True, False)]
    print(json.dumps({"passed": True, "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
