import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("zv_workflow_migration", Path(__file__).resolve().parents[1] / "scripts" / "migrate_zv_workflows.py")
M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)


def test_minimal_migration_preserves_crlf_widgets_properties_and_connections():
    raw = ('{\r\n  "nodes": [{"id":166,"type":"ZFH3FocusCompiler","pos":[1,2],"inputs":[],"outputs":[{"type":"STRING","links":[315]}],'
           '"properties":{"Node name for S&R":"ZFH3FocusCompiler","note":"ZFH3FocusCompiler"},'
           '"widgets_values":["ZFH3FocusCompiler",{"id":7,"type":"ZFH3FocusCompiler"}]}],\r\n'
           '  "links":[[315,166,1,42,0,"STRING"]],"other":{"type":"ZFH3FocusCompiler"}\r\n}\r\n').encode()
    migrated, changes, checks = M.migrate_bytes(raw)
    expected = raw.replace(b'"id":166,"type":"ZFH3FocusCompiler"', b'"id":166,"type":"ZVH3FocusCompiler"').replace(b'"Node name for S&R":"ZFH3FocusCompiler"', b'"Node name for S&R":"ZVH3FocusCompiler"')
    assert migrated == expected and len(changes) == 2
    assert checks["node_count"] == 1 and checks["connection_count"] == 1
    assert checks["connections_equal"] and checks["other_fields_equal"]


def test_api_class_type_and_unicode_escaped_token():
    raw = b'{"4":{"class_type":"\\u005aFH3FocusCompiler","inputs":{"text":["3",0]},"_meta":{"title":"User title"}}}'
    result, changes, _ = M.migrate_bytes(raw)
    assert json.loads(result)["4"]["class_type"] == "ZVH3FocusCompiler"
    assert len(changes) == 1 and json.loads(result)["4"]["inputs"] == {"text": ["3", 0]}


def test_unrelated_properties_and_text_are_not_blindly_replaced():
    raw = b'{"nodes":[{"id":1,"type":"Other","properties":{"Node name for S&R":"ZFH3FocusCompiler"},"widgets_values":["ZFUniversalMediaEvidenceDesk"]}],"links":[]}'
    result, changes, _ = M.migrate_bytes(raw)
    assert result == raw and changes == []


def test_backup_exact_bytes_bom_and_unmatched_file_untouched(tmp_path):
    source = tmp_path / "matched.json"
    raw = b'\xef\xbb\xbf{\r\n"nodes":[{"id":1,"type":"ZFUniversalMediaEvidenceDesk"}],"links":[]\r\n}'
    source.write_bytes(raw)
    untouched = tmp_path / "other.json"; untouched.write_bytes(b'{ "nodes": [] }\r\n')
    report = M.migrate_directory(tmp_path, apply=True)
    assert report["scanned"] == 2 and report["unmatched_unchanged"] == 1
    backup = Path(report["hits"][0]["backup"])
    assert backup.parent == source.parent and backup.suffix == ".bak" and backup.read_bytes() == raw
    assert source.read_bytes() == raw.replace(b'"ZFUniversalMediaEvidenceDesk"', b'"ZVUniversalMediaEvidenceDesk"')
    assert untouched.read_bytes() == b'{ "nodes": [] }\r\n'
    assert M.migrate_directory(tmp_path, apply=True)["hits"] == []


def test_dry_run_has_no_side_effects(tmp_path):
    source = tmp_path / "matched.json"; raw = b'{"nodes":[{"id":1,"type":"ZFH3FocusCompiler"}],"links":[]}'
    source.write_bytes(raw)
    report = M.migrate_directory(tmp_path)
    assert len(report["hits"]) == 1 and report["hits"][0]["backup"] is None
    assert list(tmp_path.iterdir()) == [source] and source.read_bytes() == raw


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError, match="Duplicate"): M.migrate_bytes(b'{"nodes":[],"nodes":[]}')


def test_concurrent_workflow_change_is_not_overwritten(tmp_path):
    path = tmp_path / "workflow.json"; path.write_bytes(b'{"newer":true}')
    with pytest.raises(ValueError, match="changed since scan"): M.migrate_file(path, b'{}', b'{"migrated":true}')
    assert path.read_bytes() == b'{"newer":true}' and list(tmp_path.iterdir()) == [path]
