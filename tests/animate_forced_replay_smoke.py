"""Force native-loop recorder replay after eviction, without a server or GPU.

This exercises Comfy's actual prompt executor and loop expansion, rather than
calling the recorder directly. The same prompt id is executed twice. Before
the second execution, its expanded recorder cache entries are explicitly
evicted. Compare a body-dependent cleanup termination to an upstream-only
termination: only the latter allows the recorder's disk-backed lazy result to
avoid re-evaluating the synthetic expensive body.

Run with the bundled Comfy Python runtime.
"""

import asyncio
import json
import logging
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import animate_duplicate_roots_smoke as base


class TrackingRecorder(base.smoke.RUNTIME.ZVAnimateSegmentRecorder):
    lazy_requests = []
    record_calls = []

    def check_lazy_status(self, segment_context, frames=None, source_audio=None, previous_result=None):
        needed = super().check_lazy_status(segment_context, frames, source_audio, previous_result)
        self.lazy_requests.append((segment_context["index"], tuple(needed)))
        return needed

    def record(self, segment_context, frames=None, source_audio=None, previous_result=None):
        from comfy_execution.utils import get_executing_context
        context = get_executing_context()
        self.record_calls.append((segment_context["index"], context.node_id, frames is None))
        return super().record(segment_context, frames, source_audio, previous_result)


class FailOnceBody(base.smoke.OriginalBody):
    failed = False
    calls = []

    def generate(self, context, source, transition, picture, mask, background):
        index = context["index"]
        self.calls.append(index)
        if index == 1 and not self.failed:
            type(self).failed = True
            raise RuntimeError("deliberate interruption after segment one")
        if index < len(base.smoke.STATE["generated"]):
            # A duplicate method invocation stands in for costly regeneration;
            # make a fresh tensor, but keep the fixture's expected append order.
            return (base.smoke.STATE["generated"][index].clone(),)
        return super().generate(context, source, transition, picture, mask, background)


class UpstreamPose:
    calls = []

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "pose"

    def pose(self, source):
        self.calls.append(len(source))
        return (source[:1].clone(),)


def run_case(root, source, upstream_only):
        case_root = root / ("upstream-pose-only" if upstream_only else "body-cleanup")
        case_root.mkdir()
        base.smoke.RUNTIME._temp_root = lambda: case_root / "runtime"
        base.smoke.folder_paths.set_output_directory(str(case_root / "output"))
        base.smoke.folder_paths.set_temp_directory(str(case_root / "temp"))
        (case_root / "output").mkdir()
        (case_root / "temp").mkdir()
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
        base.smoke.STATE.clear()
        base.smoke.STATE.update(
            mode="hard_cut", mask_enabled=False, mask_calls=[], track_calls=[], generated=[],
            transitions=[], cleanup=[], mask_previews=[],
            plan=base.smoke.PLAN.build_plan(source, config, fps=24),
        )
        TrackingRecorder.lazy_requests.clear()
        TrackingRecorder.record_calls.clear()
        FailOnceBody.failed = False
        FailOnceBody.calls.clear()
        UpstreamPose.calls.clear()
        base.smoke.RUNTIME._RECORDED_SEGMENTS.clear()
        prompt = base.smoke.single_root_graph()
        if upstream_only:
            for index in range(1, 5):
                del prompt[f"cleanup-{index}"]
                del prompt["close"]["inputs"][f"terminations.termination{index - 1}"]
            prompt["pose"] = {"class_type": "AnimateSmokeUpstreamPose", "inputs": {"source": ["entry", 1]}}
            prompt["close"]["inputs"]["terminations.termination0"] = ["pose", 0]
        valid = asyncio.run(base.smoke.execution.validate_prompt("forced-replay", prompt, None))
        assert valid[0], valid
        assert valid[2] == ["save"], valid[2]
        runner = base.smoke.execution.PromptExecutor(
            base.smoke.Server(), cache_type=base.smoke.execution.CacheType.RAM_PRESSURE,
            cache_args={"ram": 0.5, "ram_inactive": 0.5},
        )
        # The expected first interruption is deliberately quiet.
        logging.disable(logging.CRITICAL)
        try:
            runner.execute(prompt, "forced-replay", execute_outputs=valid[2])
        finally:
            logging.disable(logging.NOTSET)
        assert not runner.success
        assert FailOnceBody.failed
        assert len(base.smoke.STATE["generated"]) == 1
        first_calls = list(TrackingRecorder.record_calls)
        assert len(first_calls) == 1, first_calls
        assert all(not missing for _, _, missing in first_calls), first_calls

        # Force the exact expanded recorder entries out of the executor cache.
        # A retry after a controlled interruption must revisit the loop rather
        # than silently use the first execution's in-memory results.
        output_cache = runner.caches.outputs
        evicted = []
        for _, node_id, _ in first_calls:
            key = output_cache.cache_key_set.get_data_key(node_id)
            assert key is not None, node_id
            was_cached = key in output_cache.cache
            output_cache.cache.pop(key)
            output_cache.used_generation.pop(key, None)
            output_cache.timestamps.pop(key, None)
            output_cache.children.pop(key, None)
            evicted.append({"node_id": node_id, "cached_before_forced_clear": was_cached})
        output_cache.cache.clear()
        output_cache.used_generation.clear()
        output_cache.timestamps.clear()
        output_cache.children.clear()
        output_cache.subcaches.clear()

        runner.execute(prompt, "forced-replay", execute_outputs=valid[2])
        assert runner.success, {
            "status": [(kind, data.get("exception_message")) for kind, data in runner.status_messages],
            "lazy_requests": TrackingRecorder.lazy_requests,
            "record_calls": TrackingRecorder.record_calls,
            "body_calls": len(base.smoke.STATE["generated"]),
        }
        replay_calls = TrackingRecorder.record_calls[len(first_calls):]
        assert len(replay_calls) == 3, replay_calls
        assert [row[0] for row in replay_calls] == [0, 1, 2], replay_calls
        assert replay_calls[0][2], replay_calls
        assert all(not row[2] for row in replay_calls[1:]), replay_calls
        assert len(base.smoke.STATE["generated"]) == 3, "expensive body ran again"
        expected_body_calls = [0, 1, 1, 2] if upstream_only else [0, 1, 0, 1, 2]
        assert FailOnceBody.calls == expected_body_calls, FailOnceBody.calls
        assert UpstreamPose.calls == ([24, 8, 24, 8, 16] if upstream_only else []), UpstreamPose.calls

        run_root = case_root / "runtime" / "zv_animate_segments"
        runs = list(run_root.iterdir())
        assert len(runs) == 1, runs
        manifest = json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8"))
        assert [row["frames"] for row in manifest["segments"]] == [23, 7, 16]
        return {
            "passed": True,
            "upstream_only": upstream_only,
            "evicted_recorder_nodes": evicted,
            "replay_calls_without_frames": sum(row[2] for row in replay_calls),
            "body_invocations_by_segment": FailOnceBody.calls[:],
            "run_ids": len(runs),
            "recorded_frames": [row["frames"] for row in manifest["segments"]],
        }


def run():
    base.register_nodes()
    base.smoke.nodes.NODE_CLASS_MAPPINGS["ZVAnimateSegmentRecorder"] = TrackingRecorder
    base.smoke.nodes.NODE_CLASS_MAPPINGS["AnimateSmokeBody"] = FailOnceBody
    base.smoke.nodes.NODE_CLASS_MAPPINGS["AnimateSmokeUpstreamPose"] = UpstreamPose
    with tempfile.TemporaryDirectory(prefix="zv-animate-forced-replay-") as folder:
        root = Path(folder)
        store, original = base.smoke.MEDIA.imported_project(root)
        base.smoke.folder_paths.set_input_directory(str(store.input_root))
        base.smoke.RUNTIME.get_store = lambda: store
        source = base.smoke.source_project(original)
        results = [run_case(root, source, upstream_only) for upstream_only in (False, True)]
    return {"passed": True, "results": results}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
