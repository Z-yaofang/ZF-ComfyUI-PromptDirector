import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("installation_audit", Path(__file__).resolve().parents[1] / "tools" / "audit_installation.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def install(root, name, retired=()):
    directory = root / name
    directory.mkdir()
    keys = ("ZFPromptDirector", "ZVH3InterviewFormV2", *retired)
    # The audit must not execute a discovered plugin.
    (directory / "nodes.py").write_text("raise RuntimeError('must not import')\nNODE_CLASS_MAPPINGS = {" + ",".join(f"{key!r}: MissingClass" for key in keys) + "}\n", encoding="utf-8")
    return directory


def test_single_current_installation(tmp_path):
    install(tmp_path, "ZF-ComfyUI-PromptDirector")
    result = AUDIT.audit(tmp_path)
    assert result["ready"]
    assert len(result["installations"]) == 1
    assert result["installations"][0]["retired_nodes"] == []


def test_hidden_worktree_is_an_active_duplicate(tmp_path):
    install(tmp_path, "ZF-ComfyUI-PromptDirector")
    install(tmp_path, ".zf-old-worktree", ("ZVH3InterviewForm",))
    result = AUDIT.audit(tmp_path)
    assert not result["ready"]
    assert len(result["installations"]) == 2
    assert any("点号前缀不会禁用" in error for error in result["errors"])
    assert any("ZVH3InterviewForm" in error for error in result["errors"])


def test_disabled_and_unrelated_plugins_do_not_conflict(tmp_path):
    install(tmp_path, "ZF-ComfyUI-PromptDirector")
    install(tmp_path, "old.disabled", tuple(AUDIT.RETIRED_NODES))
    unrelated = tmp_path / "OtherPlugin"
    unrelated.mkdir()
    (unrelated / "nodes.py").write_text("NODE_CLASS_MAPPINGS = {'OtherNode': OtherNode}\n", encoding="utf-8")
    assert AUDIT.audit(tmp_path)["ready"]


def test_retired_nodes_fail_even_in_a_single_copy(tmp_path):
    install(tmp_path, "ZF-ComfyUI-PromptDirector", tuple(AUDIT.RETIRED_NODES))
    result = AUDIT.audit(tmp_path)
    assert not result["ready"]
    assert set(result["installations"][0]["retired_nodes"]) == AUDIT.RETIRED_NODES


def test_empty_or_missing_installation_is_not_reported_clean(tmp_path):
    assert not AUDIT.audit(tmp_path)["ready"]
    with pytest.raises(ValueError, match="目录不存在"):
        AUDIT.audit(tmp_path / "missing")
