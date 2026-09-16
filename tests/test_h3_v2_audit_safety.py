"""Real main boundary tests; negative preflight must perform no audit/copy writes."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


@pytest.fixture
def audit():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tools/h3_v2_audit.py'))


def reject_without_side_effects(audit, workflow, output, copy_to):
    before = {path: path.read_bytes() for path in output.rglob('*') if path.is_file() and not path.is_symlink()}
    source = workflow.read_bytes()
    entries = set(output.iterdir())
    with pytest.raises(SystemExit) as error:
        audit['main'](['--workflow', str(workflow), '--output-dir', str(output), '--copy-to', str(copy_to)])
    assert error.value.code == 2
    assert workflow.read_bytes() == source
    assert set(output.iterdir()) == entries
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not copy_to.exists()


@pytest.mark.parametrize('index', range(5))
def test_main_rejects_workflow_collision_with_every_output(audit, tmp_path, index):
    output = tmp_path / 'out'; output.mkdir()
    workflow = output / audit['OUTPUT_NAMES'][index]
    workflow.write_text('{"nodes": [], "links": []}', encoding='utf-8')
    reject_without_side_effects(audit, workflow, output, tmp_path / 'runtime')


@pytest.mark.parametrize('index', range(5))
def test_main_preflights_every_existing_output_including_last(audit, tmp_path, index):
    output = tmp_path / 'out'; output.mkdir()
    workflow = tmp_path / 'source.json'; workflow.write_bytes(b'original source')
    (output / audit['OUTPUT_NAMES'][index]).write_bytes(b'preserve this existing output')
    reject_without_side_effects(audit, workflow, output, tmp_path / 'runtime')


def directory_link(link, target):
    # Windows junction creation needs no symbolic-link privilege; test real reparse points.
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize('kind', ['hardlink', 'junction', 'dangling-junction'])
def test_main_rejects_existing_output_links_without_touching_link_or_target(audit, tmp_path, kind):
    output = tmp_path / 'out'; output.mkdir()
    workflow = tmp_path / 'source.json'; workflow.write_bytes(b'original source')
    target = tmp_path / 'linked-target'
    link = output / audit['OUTPUT_NAMES'][-1]
    if kind == 'hardlink':
        target.write_bytes(b'preserve linked target'); link.hardlink_to(target)
    else:
        if kind == 'junction':
            target.mkdir(); (target / 'kept.txt').write_bytes(b'preserve linked target')
        directory_link(link, target)
        before_link = os.readlink(link)
    reject_without_side_effects(audit, workflow, output, tmp_path / 'runtime')
    if kind == 'hardlink': assert link.samefile(target) and target.read_bytes() == b'preserve linked target'
    else:
        assert os.readlink(link) == before_link
        assert target.exists() == (kind == 'junction')
        if kind == 'junction': assert (target / 'kept.txt').read_bytes() == b'preserve linked target'


@pytest.mark.parametrize('nested', [False, True])
def test_main_rejects_linked_output_directory_or_ancestor(audit, tmp_path, nested):
    real = tmp_path / 'real'; real.mkdir()
    link = tmp_path / 'link'; directory_link(link, real)
    output = link / 'new-output' if nested else link
    workflow = tmp_path / 'source.json'; workflow.write_bytes(b'original source')
    with pytest.raises(SystemExit) as error:
        audit['main'](['--workflow', str(workflow), '--output-dir', str(output)])
    assert error.value.code == 2 and list(real.iterdir()) == []
    assert workflow.read_bytes() == b'original source' and (link.is_symlink() or link.is_junction())


@pytest.mark.parametrize('case', ['existing-copy', 'dangling-copy', 'copy-is-output', 'file-parent'])
def test_main_preflights_copy_destination_and_invalid_parent_before_creating_output(audit, tmp_path, case):
    workflow = tmp_path / 'source.json'; workflow.write_bytes(b'original source')
    output = tmp_path / 'new-out'; copy_to = tmp_path / 'runtime'
    if case == 'existing-copy': copy_to.mkdir()
    elif case == 'dangling-copy': directory_link(copy_to, tmp_path / 'missing')
    elif case == 'copy-is-output': copy_to = output
    else:
        parent = tmp_path / 'file-parent'; parent.write_bytes(b'preserve parent')
        output = parent / 'new-out'
    with pytest.raises(SystemExit) as error:
        audit['main'](['--workflow', str(workflow), '--output-dir', str(output), '--copy-to', str(copy_to)])
    assert error.value.code == 2 and not output.exists()
    assert workflow.read_bytes() == b'original source'
    if case == 'existing-copy': assert list(copy_to.iterdir()) == []
    if case == 'dangling-copy': assert copy_to.is_symlink() or copy_to.is_junction()
    if case == 'file-parent': assert parent.read_bytes() == b'preserve parent'


def test_real_main_new_output_directory_produces_complete_safe_skeleton(audit, tmp_path):
    comfy = Path(__file__).resolve().parents[3]
    workflow = comfy / 'user/default/workflows/MiniMax H3 10Eros Beta4 三步测试-ZV素材出口V1 (2).json'
    source = workflow.read_bytes(); output = tmp_path / 'new-out'
    script = Path(__file__).resolve().parents[1] / 'tools/h3_v2_audit.py'
    result = subprocess.run([sys.executable, str(script), '--workflow', str(workflow), '--output-dir', str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'H3_V2_03_AUDIT_OK' in result.stdout
    assert workflow.read_bytes() == source
    assert {path.name for path in output.iterdir()} == set(audit['OUTPUT_NAMES'])
    graph = json.loads((output / 'H3_V2_03_PREPARATION_WORKFLOW.json').read_bytes())
    proof = json.loads((output / 'H3_V2_03_SHARE_CHECK.json').read_bytes())
    assert graph['extra']['generation_ready'] is proof['generation_ready'] is False
    assert 'final H3 prompt processing chain' in graph['extra']['h3_example']
    assert len(graph['nodes']) == 9 and len(graph['links']) == 74
    assert proof['media_wires_per_conditioning'] == 22 and proof['backend_fixed_hub_wiring_errors'] == []


def test_consecutive_copied_registrations_have_fresh_routes_and_clean_only_owned_modules(audit, tmp_path):
    protected = {key: sys.modules.get(key) for key in ('server', 'comfy_execution', 'comfy_execution.graph')}
    existing = {key: value for key, value in sys.modules.items() if 'h3' in key.lower()}
    destination = audit['copy_runtime'](tmp_path / 'runtime')
    results = []; names = []
    for _ in range(2):
        result, mappings = audit['copied_registration'](destination)
        results.append(result)
        name = mappings['ZVH3InterviewForm'].__module__.split('.')[0]; names.append(name)
        assert not any(key == name or key.startswith(name + '.') for key in sys.modules)
        assert all(sys.modules.get(key) is value for key, value in protected.items())
        assert all(sys.modules.get(key) is value for key, value in existing.items())
        _, proof = audit['skeleton'](mappings)
        assert proof['backend_fixed_hub_wiring_errors'] == []
    assert names[0] != names[1]
    assert results[0]['registered_classes'] == results[1]['registered_classes']
    assert results[0]['routes'] == results[1]['routes'] and len(results[0]['routes']) == 23
    assert {row['path'] for row in results[0]['routes']} >= {
        '/zf-prompt-director/long-video/plan',
        '/zf-prompt-director/long-video/interview',
    }


def test_consecutive_real_main_calls_register_consistent_outputs(audit, tmp_path):
    comfy = Path(__file__).resolve().parents[3]
    workflow = comfy / 'user/default/workflows/MiniMax H3 10Eros Beta4 三步测试-ZV素材出口V1 (2).json'
    before = workflow.read_bytes(); results = []
    for index in range(2):
        output = tmp_path / f'output-{index}'
        audit['main'](['--workflow', str(workflow), '--output-dir', str(output)])
        results.append(json.loads((output / 'H3_V2_03_COPY_REGISTRATION.json').read_bytes()))
        assert {path.name for path in output.iterdir()} == set(audit['OUTPUT_NAMES'])
    assert workflow.read_bytes() == before
    assert results[0] == results[1] and results[0]['passed'] and results[0]['file_hashes_match']


def test_exclusive_reservation_refuses_late_target_without_truncating_it(audit, tmp_path, monkeypatch):
    """A late target appearing after preflight still cannot be opened for overwrite."""
    comfy = Path(__file__).resolve().parents[3]
    workflow = comfy / 'user/default/workflows/MiniMax H3 10Eros Beta4 三步测试-ZV素材出口V1 (2).json'
    output = tmp_path / 'out'; original_open = Path.open
    # Only isolate expensive computation for this filesystem race boundary test.
    globals_ = audit['main'].__globals__
    monkeypatch.setitem(globals_, 'manifest', lambda: {'files': []})
    monkeypatch.setitem(globals_, 'audit_workflow', lambda path: {})
    monkeypatch.setitem(globals_, 'copy_runtime', lambda path: path)
    monkeypatch.setitem(globals_, 'copied_registration', lambda path: ({}, {}))
    monkeypatch.setitem(globals_, 'skeleton', lambda mappings: ({}, {}))
    first = output / audit['OUTPUT_NAMES'][0]
    modes = []
    def late_open(path, mode='r', *args, **kwargs):
        if path == first and mode == 'xb':
            with original_open(path, 'wb') as handle: handle.write(b'late existing output')
        if path.parent == output: modes.append(mode)
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', late_open)
    with pytest.raises(FileExistsError):
        audit['main'](['--workflow', str(workflow), '--output-dir', str(output)])
    assert first.read_bytes() == b'late existing output'
    assert set(output.iterdir()) == {first} and modes[0] == 'xb'
