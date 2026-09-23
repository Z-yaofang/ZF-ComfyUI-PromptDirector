"""The recorder's diagnostic log must not alter its output contract."""

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
PACKAGE = "zf_animate_recorder_logging_testpkg"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE, package)
NODES = importlib.import_module(PACKAGE + ".animate_video.nodes")
UTILS = importlib.import_module("comfy_execution.utils")


class RecorderLoggingTest(unittest.TestCase):
    def run_recorder(self, execution_context):
        result = {
            "run_id": "a" * 32,
            "last_segment": {
                "expected_frame_count": 7,
                "frames": 7,
                "frame_delta": 0,
                "audio_fit": {
                    "source_sample_rate": 44100,
                    "silent_track": False,
                    "trimmed_tail_samples": 0,
                    "padded_silence_samples": 0,
                },
            },
        }
        context = {"index": 1, "segment_count": 3}
        calls = []

        def persist(segment_context, frames, audio, previous, root):
            calls.append((segment_context, frames, audio, previous, root))
            return result

        with tempfile.TemporaryDirectory(prefix="zv-animate-log-test-") as folder:
            root = Path(folder)
            with mock.patch.object(NODES, "_temp_root", return_value=root), \
                    mock.patch.object(NODES, "persist_segment", side_effect=persist), \
                    mock.patch.object(UTILS, "get_executing_context", side_effect=execution_context):
                with self.assertLogs(NODES.__name__, level="INFO") as captured:
                    actual, report = NODES.ZVAnimateSegmentRecorder().record(context, object())
            self.assertIs(actual, result)
            self.assertIn("第 2 段", report)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][4], root)
            self.assertEqual(len(captured.records), 1)
            return captured.records[0].getMessage(), root, result

    def test_logs_prompt_run_segment_and_paths(self):
        current = types.SimpleNamespace(prompt_id="prompt-123", node_id="974.0.0.1_976")
        line, root, result = self.run_recorder(lambda: current)
        self.assertRegex(line, r"time_utc=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertIn("prompt_id=prompt-123", line)
        self.assertIn("node_id=974.0.0.1_976", line)
        self.assertIn(f"run_id={result['run_id']} segment=2/3", line)
        self.assertIn(str(root / NODES.DIRECTORY / result["run_id"] / "segment-0002.mp4"), line)
        self.assertIn(str(root / NODES.DIRECTORY / result["run_id"] / "manifest.json"), line)

    def test_context_lookup_failure_does_not_change_recorder_result(self):
        def unavailable():
            raise RuntimeError("execution context unavailable")

        line, _, _ = self.run_recorder(unavailable)
        self.assertIn("prompt_id=None node_id=None", line)


if __name__ == "__main__":
    unittest.main()
