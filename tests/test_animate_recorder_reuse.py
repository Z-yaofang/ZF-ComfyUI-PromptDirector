"""A repeated native-loop visit must reuse a verified disk result before frames run."""

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
PACKAGE = "zf_animate_recorder_reuse_testpkg"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
NODES = importlib.import_module(PACKAGE + ".animate_video.nodes")
EXECUTION = importlib.import_module(PACKAGE + ".animate_video.execution")
UTILS = importlib.import_module("comfy_execution.utils")


class RecorderReuseTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="zv-animate-recorder-reuse-")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.execution_context = types.SimpleNamespace(prompt_id="prompt-one", node_id="974.0.0.0_976")
        self.context = {
            "plan_fingerprint": "plan-one",
            "index": 0,
            "segment_count": 2,
            "fps": 30,
            "segment": {"segment_id": "segment-one", "frame_count": 3, "source_audio_enabled": False},
            "outgoing_guide": None,
        }
        self.frames = torch.ones((3, 8, 8, 3), dtype=torch.float32)
        self.encode_calls = []
        self.persist_calls = []
        NODES._RECORDED_SEGMENTS.clear()
        self.addCleanup(NODES._RECORDED_SEGMENTS.clear)
        for patcher in (
            mock.patch.object(NODES, "_temp_root", return_value=self.root),
            mock.patch.object(UTILS, "get_executing_context", side_effect=lambda: self.execution_context),
            mock.patch.object(NODES, "persist_segment", side_effect=self.persist),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.recorder = NODES.ZVAnimateSegmentRecorder()

    def encode(self, images, audio, fps, path):
        self.encode_calls.append(path)
        Path(path).write_bytes(b"encoded-segment-" + str(len(self.encode_calls)).encode())
        return {
            "encoded_frame_count": len(images),
            "fps": fps,
            "audio_sample_rate": 44100,
            "audio_channels": 2,
            "decoded_audio_sample_count": audio["waveform"].shape[-1],
        }

    def persist(self, context, frames, source_audio, previous, root):
        self.persist_calls.append((context, frames, source_audio, previous, root))
        return EXECUTION.persist_segment(context, frames, source_audio, previous, root, self.encode)

    def segment_path(self, result):
        return self.root / NODES.DIRECTORY / result["run_id"] / "segment-0001.mp4"

    def manifest_path(self, result):
        return self.root / NODES.DIRECTORY / result["run_id"] / "manifest.json"

    def test_first_visit_records_and_same_prompt_reuses_without_frames(self):
        self.assertTrue(NODES.ZVAnimateSegmentRecorder.INPUT_TYPES()["required"]["frames"][1]["lazy"])
        self.assertEqual(self.recorder.check_lazy_status(self.context), ["frames"])
        result, report = self.recorder.record(self.context, self.frames)
        self.assertTrue(self.segment_path(result).is_file())
        self.assertTrue(self.manifest_path(result).is_file())
        self.assertEqual(len(self.persist_calls), 1)
        self.assertEqual(len(self.encode_calls), 1)

        self.assertEqual(self.recorder.check_lazy_status(self.context), [])
        self.assertEqual(self.recorder.record(self.context, frames=None), (result, report))
        self.assertEqual(len(self.persist_calls), 1)
        self.assertEqual(len(self.encode_calls), 1)

    def test_different_prompt_cannot_reuse_record(self):
        first, _ = self.recorder.record(self.context, self.frames)
        self.execution_context.prompt_id = "prompt-two"
        self.assertEqual(self.recorder.check_lazy_status(self.context), ["frames"])
        with self.assertRaisesRegex(ValueError, "缺少原流最终画面"):
            self.recorder.record(self.context, frames=None)
        second, _ = self.recorder.record(self.context, self.frames)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(len(self.persist_calls), 2)

    def test_changed_manifest_requires_frames_again(self):
        result, _ = self.recorder.record(self.context, self.frames)
        self.manifest_path(result).write_bytes(b"changed-manifest")
        self.assertEqual(self.recorder.check_lazy_status(self.context), ["frames"])
        with self.assertRaisesRegex(ValueError, "缺少原流最终画面"):
            self.recorder.record(self.context, frames=None)
        self.assertEqual(len(self.persist_calls), 1)

    def test_changed_segment_requires_frames_again(self):
        result, _ = self.recorder.record(self.context, self.frames)
        self.segment_path(result).write_bytes(b"changed-segment")
        self.assertEqual(self.recorder.check_lazy_status(self.context), ["frames"])
        with self.assertRaisesRegex(ValueError, "缺少原流最终画面"):
            self.recorder.record(self.context, frames=None)
        self.assertEqual(len(self.persist_calls), 1)


if __name__ == "__main__":
    unittest.main()
