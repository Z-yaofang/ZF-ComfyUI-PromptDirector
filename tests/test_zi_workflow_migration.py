import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
PACKAGE_NAME = "zf_prompt_director_zi_migration_test_scripts"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(SCRIPT_ROOT)]
sys.modules[PACKAGE_NAME] = PACKAGE
SPEC = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.migrate_zi_workflows", SCRIPT_ROOT / "migrate_zi_workflows.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


RAW = b'{"nodes":[{"id":7,"type":"ZFPortraitPromptGenerator","pos":[1,2],"inputs":[],"outputs":[{"type":"STRING","links":[9]}],"properties":{"Node name for S&R":"ZFPortraitPromptGenerator"},"widgets_values":["keep",2]}],"links":[[9,7,0,8,0,"STRING"]]}'


def test_minimal_crlf_migration_preserves_entire_graph():
    raw = RAW.replace(b',"links":[[', b',\r\n  "links":[[') + b'\r\n'
    result, changes, checks = M.migrate_bytes(raw)
    assert result == raw.replace(b'ZFPortraitPromptGenerator', b'ZIPortraitPromptGenerator')
    assert len(changes) == 2 and checks['migrated_node_count'] == 1
    assert checks['node_count'] == 1 and checks['connection_count'] == 1
    assert M.graph_facts(json.loads(raw)) == M.graph_facts(json.loads(result))
    assert json.loads(result)['nodes'][0]['widgets_values'] == ['keep', 2]


def test_only_explicit_nodes_migrate_not_opaque_or_similar_text():
    data = json.loads(RAW)
    opaque = {'nodes': [{'id': 1, 'type': M.OLD_ID}]}
    data['nodes'][0]['widgets_values'] = [M.OLD_ID, opaque]
    data['nodes'][0]['properties']['note'] = M.OLD_ID
    data['nodes'].append({'id': 2, 'type': 'Other', 'properties': {'Node name for S&R': M.OLD_ID}})
    data['unrelated'] = {'id': 3, 'type': M.OLD_ID}
    result, changes, _ = M.migrate_bytes(json.dumps(data).encode())
    updated = json.loads(result)
    assert len(changes) == 2
    assert updated['nodes'][0]['widgets_values'] == data['nodes'][0]['widgets_values']
    assert updated['nodes'][0]['properties']['note'] == M.OLD_ID
    assert updated['nodes'][1] == data['nodes'][1] and updated['unrelated'] == data['unrelated']


def test_api_class_type_escaped_name_preserves_inputs_and_metadata():
    raw = b'{"4":{"class_type":"Z\\u0046PortraitPromptGenerator","inputs":{"prompt":{"class_type":"ZFPortraitPromptGenerator","inputs":{}},"text":"ZFPortraitPromptGenerator"},"_meta":{"title":"My title"}}}'
    result, changes, _ = M.migrate_bytes(raw)
    assert result == raw.replace(b'Z\\u0046PortraitPromptGenerator', b'ZIPortraitPromptGenerator')
    assert len(changes) == 1


def test_bom_backup_exact_bytes_unmatched_unchanged_and_idempotence(tmp_path):
    source = tmp_path / 'matched.json'
    raw = b'\xef\xbb\xbf' + RAW
    source.write_bytes(raw)
    other = tmp_path / 'other.json'
    other.write_bytes(b'{ "nodes": [] }\r\n')
    report = M.migrate_directory(tmp_path, apply=True)
    backup = Path(report['hits'][0]['backup'])
    assert backup.parent == tmp_path and '.zi-' in backup.name and backup.suffix == '.bak'
    assert backup.read_bytes() == raw
    assert source.read_bytes() == raw.replace(b'ZFPortraitPromptGenerator', b'ZIPortraitPromptGenerator')
    assert report['unmatched_unchanged'] == 1 and other.read_bytes() == b'{ "nodes": [] }\r\n'
    assert M.migrate_directory(tmp_path, apply=True)['hits'] == []
    assert len(list(tmp_path.glob('*.bak'))) == 1


def test_dry_run_does_not_write(tmp_path):
    source = tmp_path / 'workflow.json'
    source.write_bytes(RAW)
    report = M.migrate_directory(tmp_path)
    assert len(report['hits']) == 1 and report['hits'][0]['backup'] is None
    assert list(tmp_path.iterdir()) == [source] and source.read_bytes() == RAW


@pytest.mark.parametrize("python_flags", [[], ["-I"]], ids=["direct", "isolated"])
def test_script_entrypoint_dry_run_in_subprocess(tmp_path, python_flags):
    source = tmp_path / 'workflow.json'
    source.write_bytes(RAW)
    result = subprocess.run(
        [sys.executable, *python_flags, str(SCRIPT_ROOT / "migrate_zi_workflows.py"), str(tmp_path)],
        cwd=SCRIPT_ROOT.parent, capture_output=True, text=True, encoding="utf-8", timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['scanned'] == 1 and report['applied'] is False
    assert report['parse_errors'] == [] and len(report['hits']) == 1
    assert report['hits'][0]['backup'] is None
    assert report['hits'][0]['checks']['migrated_node_count'] == 1
    assert source.read_bytes() == RAW and list(tmp_path.iterdir()) == [source]


def test_concurrent_change_before_backup_not_overwritten(tmp_path):
    source = tmp_path / 'workflow.json'
    source.write_bytes(b'{"newer":true}')
    with pytest.raises(ValueError, match='changed since scan'):
        M.migrate_file(source, RAW, M.migrate_bytes(RAW)[0])
    assert source.read_bytes() == b'{"newer":true}' and not list(tmp_path.glob('*.bak'))


def test_concurrent_change_during_backup_not_overwritten(tmp_path):
    source = tmp_path / 'workflow.json'
    source.write_bytes(RAW)
    original_open = Path.open

    def changed_open(path, mode='r', *args, **kwargs):
        if path == source and mode == 'r+b':
            with original_open(source, 'wb') as handle:
                handle.write(b'{"newer":true}')
        return original_open(path, mode, *args, **kwargs)

    with patch.object(Path, 'open', changed_open):
        with pytest.raises(ValueError, match='changed during backup'):
            M.migrate_file(source, RAW, M.migrate_bytes(RAW)[0])
    assert source.read_bytes() == b'{"newer":true}'
    assert next(tmp_path.glob('*.bak')).read_bytes() == RAW


def test_duplicate_keys_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        M.migrate_bytes(b'{"nodes":[],"nodes":[]}')


def test_parse_error_prevents_all_writes(tmp_path):
    source = tmp_path / 'a.json'
    source.write_bytes(RAW)
    (tmp_path / 'z.json').write_bytes(b'{')
    with pytest.raises(ValueError, match='nothing was modified'):
        M.migrate_directory(tmp_path, apply=True)
    assert source.read_bytes() == RAW and not list(tmp_path.glob('*.bak'))
