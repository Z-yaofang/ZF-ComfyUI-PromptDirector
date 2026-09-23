"""CPU regression: redundant EndLoop ancestors reproduce an out-of-order loop."""

import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import animate_duplicate_roots_smoke as duplicate

BASE_GRAPH = duplicate.smoke.single_root_graph


def ancestor_graph():
    prompt = BASE_GRAPH()
    prompt["close"]["inputs"] = {
        "output_value": ["record", 0],
        "next_iteration_value": ["record", 0],
        "accumulate": False,
        "terminations.termination0": ["body", 0],
        "terminations.termination1": ["mask-gate", 1],
        "terminations.termination9": ["body", 0],
        "terminations.termination11": ["body", 0],
    }
    return prompt


def minimal_graph():
    prompt = ancestor_graph()
    for name in ("terminations.termination0", "terminations.termination1", "terminations.termination9"):
        del prompt["close"]["inputs"][name]
    return prompt


def main():
    duplicate.register_nodes()
    with tempfile.TemporaryDirectory(prefix="zv-loop-ancestor-") as folder:
        root = Path(folder)
        store, original = duplicate.smoke.MEDIA.imported_project(root)
        duplicate.smoke.folder_paths.set_input_directory(str(store.input_root))
        duplicate.smoke.RUNTIME.get_store = lambda: store
        source = duplicate.smoke.source_project(original)
        result = []
        previous_graph = duplicate.smoke.single_root_graph
        try:
            duplicate.smoke.single_root_graph = minimal_graph
            healthy = duplicate.run_case(root / "minimal-terminations", source, with_legacy=False)
            result.append({"case": "minimal-terminations", "expected": "success", **healthy})

            duplicate.smoke.single_root_graph = ancestor_graph
            try:
                duplicate.run_case(root / "redundant-terminations", source, with_legacy=False)
            except AssertionError as exc:
                messages = exc.args[0] if exc.args else None
                errors = [
                    payload for event, payload in messages
                    if event == "execution_error"
                ] if isinstance(messages, list) else []
                if len(errors) != 1 or errors[0]["exception_message"].strip() != "native loop executed out of order":
                    raise AssertionError("redundant graph failed for an unexpected reason") from exc
                result.append({
                    "case": "redundant-terminations",
                    "expected": "native loop executed out of order",
                    "observed": errors[0]["exception_message"].strip(),
                    "body_calls_before_failure": len(duplicate.smoke.STATE["generated"]),
                })
            else:
                raise AssertionError("redundant graph no longer reproduces the out-of-order loop")
        finally:
            duplicate.smoke.single_root_graph = previous_graph
    print(json.dumps({"passed": True, "results": result}, ensure_ascii=False))


if __name__ == "__main__":
    os.environ.setdefault("ZV_SMOKE_RAM_HEADROOM_GIB", "10")
    main()
