"""CPU integration smoke for two post-loop native SaveVideo outputs.

This deliberately uses the real Comfy executor, loop expansion, media reader,
segment recorder, whole-film assembler, comparison renderer, and SaveVideo nodes.
Only the expensive model-generation body is synthetic.  Run with the embedded
Comfy Python; no server or GPU job is started.
"""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import av

OUTPUT_QUALITY = sys.argv[1] if len(sys.argv) > 1 else None
spec = importlib.util.spec_from_file_location("animate_native_loop_smoke", Path(__file__).with_name("animate_native_loop_smoke.py"))
smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)


def _frames(path):
    with av.open(str(path)) as video:
        return sum(1 for _ in video.decode(video=0))


def main(output_quality=None):
    comparison = smoke.importlib.import_module(smoke.package.__name__ + ".animate_video.comparison")
    smoke.nodes.NODE_CLASS_MAPPINGS.update(smoke.nodes_loop.NODE_CLASS_MAPPINGS)
    smoke.nodes.NODE_CLASS_MAPPINGS.update({
        "VHS_LoadVideo": smoke.VHS,
        "AnimateSmokePlan": smoke.PlanSource,
        "AnimateSmokeBody": smoke.OriginalBody,
        "AnimateSmokeCleanup": smoke.OriginalCleanup,
        "SaveVideo": smoke.nodes_video.SaveVideo,
        "ZVAnimateFinalComparison": comparison.ZVAnimateFinalComparison,
        "AnimateSmokeMaskDetect": smoke.OriginalMaskDetect,
        "AnimateSmokeMaskTrack": smoke.OriginalMaskTrack,
        **{name: getattr(smoke.MASKING, name) for name in (
            "ZVAnimateMaskFrame", "ZVAnimateMaskSeed", "ZVAnimateMaskGate")},
        **{name: getattr(smoke.RUNTIME, name) for name in (
            "ZVAnimateExecutionEntry", "ZVAnimateSegmentRecorder", "ZVAnimateExecutionEnd")},
    })
    with tempfile.TemporaryDirectory(prefix="zv-animate-dual-save-") as folder:
        root = Path(folder)
        store, original = smoke.MEDIA.imported_project(root)
        smoke.folder_paths.set_input_directory(str(store.input_root))
        smoke.RUNTIME.get_store = lambda: store
        comparison.get_store = lambda: store
        runtime_root = root / "runtime"
        runtime_root.mkdir()
        smoke.RUNTIME._temp_root = lambda: runtime_root
        smoke.folder_paths.set_temp_directory(str(runtime_root))
        output_root = root / "output"
        output_root.mkdir()
        smoke.folder_paths.set_output_directory(str(output_root))

        source = smoke.source_project(original)
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
        smoke.STATE.update(mode="hard_cut", mask_enabled=False, mask_calls=[], track_calls=[],
                           generated=[], transitions=[], cleanup=[], mask_previews=[],
                           plan=smoke.PLAN.build_plan(source, config, fps=24))

        prompt = smoke.single_root_graph()
        if output_quality is not None:
            prompt["finish"]["inputs"]["output_quality"] = output_quality
        prompt["save"]["inputs"]["filename_prefix"] = "complete-film"
        prompt["comparison"] = {
            "class_type": "ZVAnimateFinalComparison",
            "inputs": {"animate_plan": ["plan", 0], "video": ["save", 0]},
        }
        prompt["save-comparison"] = {
            "class_type": "SaveVideo",
            "inputs": {"video": ["comparison", 0], "filename_prefix": "source-comparison", "format": "mp4"},
        }
        assert prompt["comparison"]["inputs"]["video"] == ["save", 0]
        assert all(source_id != "close" for source_id, _ in prompt["comparison"]["inputs"].values())
        validation = asyncio.run(smoke.execution.validate_prompt("dual-save", prompt, None))
        assert validation[0], validation
        assert set(validation[2]) == {"save", "save-comparison"}, validation[2]

        runner = smoke.execution.PromptExecutor(
            smoke.Server(), cache_type=smoke.execution.CacheType.RAM_PRESSURE,
            cache_args={"ram": 64.0, "ram_inactive": 64.0},
        )
        runner.execute(prompt, "dual-save", execute_outputs=validation[2])
        assert runner.success, runner.status_messages
        assert len(smoke.STATE["generated"]) == 3, "the model body repeated or skipped an iteration"
        run_root = runtime_root / "zv_animate_segments"
        run_dirs = [path for path in run_root.iterdir() if path.is_dir()]
        assert len(run_dirs) == 1, run_dirs
        manifest = json.loads((run_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
        assert [row["frames"] for row in manifest["segments"]] == [23, 7, 16], manifest
        film_files = list(output_root.glob("complete-film_*.mp4"))
        comparison_files = list(output_root.glob("source-comparison_*.mp4"))
        assert len(film_files) == len(comparison_files) == 1, (film_files, comparison_files)
        assert _frames(film_files[0]) == 46
        assert _frames(comparison_files[0]) == 46
        with av.open(str(film_files[0])) as movie:
            stream = movie.streams.video[0]
            assert stream.codec_context.name == ("hevc" if output_quality and "H.265" in output_quality else "h264")
            if output_quality and "BT.709" in output_quality:
                assert all(int(getattr(stream.codec_context, field)) == 1 for field in (
                    "colorspace", "color_primaries", "color_trc", "color_range"))
        assert {"save", "save-comparison"}.issubset(runner.history_result["outputs"])
        print(json.dumps({
            "passed": True,
            "body_executions": len(smoke.STATE["generated"]),
            "run_directories": len(run_dirs),
            "film_frames": _frames(film_files[0]),
            "comparison_frames": _frames(comparison_files[0]),
            "output_roots": sorted(validation[2]),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main(OUTPUT_QUALITY)
