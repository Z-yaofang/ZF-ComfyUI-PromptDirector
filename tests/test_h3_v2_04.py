"""04 detects the client draft before the actual desk applies connected dimensions."""
import asyncio
import copy
import json
from pathlib import Path
import runpy

import pytest

M = runpy.run_path(str(Path(__file__).with_name('h3_v2_03_matrix.py')))
I, C, S = M['I'], M['C'], M['S']


@pytest.fixture(scope='module')
def neutral(tmp_path_factory):
    store, assets = M['setup'](tmp_path_factory.mktemp('h3-04-real'))
    old_store, old_server = M['RUN']._store, S.get_store
    M['RUN']._store = store; S.get_store = lambda: store
    yield store, assets
    M['RUN']._store = old_store; S.get_store = old_server


def graph(width=None, height=None, selector=False):
    prompt = M['prompt']()
    prompt['165'] = {'class_type': 'ZVUniversalMediaEvidenceDesk', 'inputs': {}}
    if selector:
        prompt['29'] = {'class_type': 'ResolutionSelector', 'inputs': {'aspect_ratio': '9:16 (Portrait Widescreen)', 'megapixels': .7000000000000001, 'multiple': 32}}
        width, height = ['29', 0], ['29', 1]
    if width is not None: prompt['165']['inputs']['width'] = width
    if height is not None: prompt['165']['inputs']['height'] = height
    return prompt


def detect(project, prompt, state=None):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    async def request():
        routes = web.RouteTableDef(); S.register_interview_routes(routes)
        app = web.Application(); app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/zf-prompt-director/h3-interview/plan', json={'state': state or I.empty_interview(), 'media_project': project, 'align': True, 'prompt': prompt, 'interview_id': '172', 'conditioning_count': 2})
            return response.status, await response.json()
    status, result = asyncio.run(request())
    if status == 200:
        result['state']['reference_detection'] = result['snapshot']
        result['state']['alignment'] = result['alignment_context']
    return status, result


def execute(project, state, prompt, width=None, height=None):
    current, _, _ = M['DESK'].ZVUniversalMediaEvidenceDesk().export_project(json.dumps(project), width, height)
    return M['V2']['N'].ZVH3InterviewForm().build(current, I.dumps(state), prompt=prompt, unique_id='172')


def test_detect_raw_draft_then_actual_connected_canvas_build_twice_is_not_stale(neutral):
    _, assets = neutral; project = M['project'](assets, videos=1)
    project.pop('output_canvas', None)
    prompt = graph(selector=True)
    status, result = detect(project, prompt)
    assert status == 200 and result['validation']['ready']
    for _ in range(2):
        built = execute(project, json.loads(I.dumps(result['state'])), prompt, 640, 1152)
        assert built[7] and len(built) == 9
    assert result['alignment_context']['canvas'] == {'width': 640, 'height': 1152}


@pytest.mark.parametrize('case', ['window', 'crop', 'reorder', 'participation', 'bank', 'paired', 'canvas'])
def test_real_mechanical_changes_still_reject_after_detect(neutral, case):
    _, assets = neutral; project = M['project'](assets, pictures=2, videos=2, audios=1)
    prompt = graph(64, 96); status, result = detect(project, prompt)
    assert status == 200 and result['validation']['ready']
    state = copy.deepcopy(result['state']); changed = copy.deepcopy(project); width, height = 64, 96
    if case == 'window': changed['processing_window']['start_seconds'] = 1; changed['processing_window']['end_seconds'] = 6
    if case == 'crop':
        changed['video_track'][0].update(source_in_seconds=1, source_out_seconds=3)
        changed['audio_track'][0].update(source_in_seconds=1, source_out_seconds=3)
    if case == 'reorder': changed['picture_track'][0]['order'] = 9
    if case == 'participation': state['bindings']['p1']['participates'] = False
    if case == 'bank': state['bindings']['p1']['banks'] = ['first_frame']
    if case == 'paired':
        changed['video_track'][0]['source_audio_enabled'] = False; changed['audio_track'][0]['enabled'] = False
    if case == 'canvas': width = 96; prompt = graph(96, 96)
    with pytest.raises(RuntimeError, match='过期'):
        execute(changed, state, prompt, width, height)


def test_semantics_and_derived_numeric_fields_do_not_invalidate(neutral):
    _, assets = neutral; project = M['project'](assets, videos=1)
    project['processing_window'].update(start_frame=999, end_frame=1001, frame_count=2)
    prompt = graph(64, 96); status, result = detect(project, prompt)
    assert status == 200 and result['validation']['ready']
    state = result['state']; state.update(intent='新的镜头表现', style='手持自然光', media_roles={'v1': ['plot_carrier']}, media_purposes={'v1': '表演与镜头参考'})
    project['processing_window'].update(start_seconds=0.0, end_seconds=5.0)
    project['video_track'][0]['timeline_out_seconds'] = 999
    assert execute(project, json.loads(I.dumps(state)), prompt, 64, 96)[7]


def test_dimension_change_redetect_and_equivalent_static_source_and_disconnect(neutral):
    _, assets = neutral; project = M['project'](assets, videos=1)
    project.pop('output_canvas', None); prompt = graph(selector=True)
    _, result = detect(project, prompt); state = result['state']
    equivalent = graph(['w', 0], ['h', 0])
    equivalent.update(w={'class_type': 'PrimitiveInt', 'inputs': {'value': 640}}, h={'class_type': 'INTConstant', 'inputs': {'value': 1152}})
    status, same = detect(project, equivalent, state)
    assert status == 200 and same['alignment_context'] == result['alignment_context']
    assert execute(project, state, equivalent, 640, 1152)[7]
    changed = graph(96, 96)
    with pytest.raises(RuntimeError, match='过期'): execute(project, state, changed, 96, 96)
    _, redetected = detect(project, changed, state)
    assert execute(project, redetected['state'], changed, 96, 96)[7]
    disconnected = graph()
    with pytest.raises(RuntimeError, match='过期'): execute(project, redetected['state'], disconnected)
    _, final = detect(project, disconnected, redetected['state'])
    assert final['alignment_context']['canvas'] is None and execute(project, final['state'], disconnected)[7]


@pytest.mark.parametrize('case', ['single', 'unknown', 'wrong-slot', 'dynamic-param', 'bool', 'non-grid', 'area'])
def test_unknown_or_invalid_connected_dimensions_are_explicit_http_errors(neutral, case):
    _, assets = neutral; project = M['project'](assets)
    prompt = graph(64, 96)
    if case == 'single': prompt['165']['inputs'].pop('height')
    if case == 'unknown': prompt['165']['inputs']['width'] = ['upstream', 0]; prompt['upstream'] = {'class_type': 'DynamicThirdParty', 'inputs': {}}
    if case == 'wrong-slot': prompt = graph(selector=True); prompt['165']['inputs']['width'][1] = 2
    if case == 'dynamic-param': prompt = graph(selector=True); prompt['29']['inputs']['megapixels'] = ['dynamic', 0]
    if case == 'bool': prompt['165']['inputs']['width'] = True
    if case == 'non-grid': prompt['165']['inputs']['width'] = 65
    if case == 'area': prompt['165']['inputs'].update(width=16384, height=16384)
    status, result = detect(project, prompt)
    assert status == 400 and result['errors'][0]['code'] == 'canvas_unverified'
    assert '尚未核实' in result['errors'][0]['message']


@pytest.mark.parametrize('case', ['size', 'missing'])
def test_registry_stat_change_remains_rejected_without_reprobe(neutral, case):
    import os
    store, assets = neutral; project = M['project'](assets, pictures=1)
    prompt = graph(); _, result = detect(project, prompt)
    path = store.resolve(assets['picture'][0]['source_handle']); info = path.stat(); original = path.read_bytes()
    try:
        if case == 'size': path.write_bytes(original + b'changed')
        if case == 'missing': path.unlink()
        forged = copy.deepcopy(project); forged['validation'] = {'errors': [], 'warnings': []}
        status, failed = detect(forged, prompt)
        assert status == 200 and not failed['validation']['ready']
        assert 'source_unavailable' in {row['code'] for row in failed['validation']['errors']}
        built = execute(project, result['state'], prompt)
        assert not built[7] and not built[8]['ready']
        assert 'source_unavailable' in {row['code'] for row in built[8]['errors']}
        with pytest.raises(M['OUT'].ReferencePlanError):
            M['OUT'].ZVH3ReferenceOutlet().export_references(built[8])
    finally:
        path.write_bytes(original)
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))


def test_registry_mtime_change_with_same_content_keeps_plan_ready(neutral):
    import os
    store, assets = neutral; project = M['project'](assets, pictures=1)
    prompt = graph(); path = store.resolve(assets['picture'][0]['source_handle']); info = path.stat()
    try:
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
        status, detected = detect(project, prompt)
        assert status == 200 and detected['validation']['ready']
        built = execute(project, detected['state'], prompt)
        assert built[7] and built[8]['ready']
    finally:
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))


def test_client_validation_cannot_forge_registry_failure_or_trust(neutral):
    _, assets = neutral; project = M['project'](assets, videos=1)
    project['validation'] = {'errors': [{'path': '/assets/0', 'code': 'source_unavailable', 'message': 'forged'}], 'warnings': []}
    prompt = graph(64, 96); status, result = detect(project, prompt)
    assert status == 200 and result['validation']['ready']
    assert execute(project, result['state'], prompt, 64, 96)[7]


def test_outlet_rechecks_registry_when_previously_ready_plan_source_disappears(neutral):
    _, assets = neutral; project = M['project'](assets, pictures=1)
    prompt = graph(); _, result = detect(project, prompt)
    plan = copy.deepcopy(execute(project, result['state'], prompt)[8])
    assert plan['ready']
    asset_id = plan['media_project']['picture_track'][0]['asset_id']
    next(asset for asset in plan['media_project']['assets'] if asset['asset_id']==asset_id)['source_handle'] = 'originals/'+'0'*32+'.png'
    with pytest.raises(M['V2']['OUT'].OutletError):
        M['OUT'].ZVH3ReferenceOutlet().export_references(plan)


def test_split_same_asset_lists_both_segments_then_manual_delete_exports_remaining_source(neutral):
    _, assets = neutral; project = M['project'](assets, videos=1)
    left = project['video_track'][0]; left.update(source_in_seconds=0, source_out_seconds=1)
    right = copy.deepcopy(left); right.update(clip_id=left['clip_id']+'_right', timeline_in_seconds=1, source_in_seconds=1, source_out_seconds=3, audio_link_id=left['audio_link_id']+'_right')
    left_audio = project['audio_track'][0]; left_audio.update(source_in_seconds=0, source_out_seconds=1)
    right_audio = copy.deepcopy(left_audio); right_audio.update(clip_id=right['audio_link_id'], linked_video_clip_id=right['clip_id'], source_video_clip_id=right['clip_id'], timeline_in_seconds=1, source_in_seconds=1, source_out_seconds=3)
    project['video_track'].append(right); project['audio_track'].append(right_audio)
    prompt = graph(64, 96); status, split = detect(project, prompt)
    assert status == 200 and not split['validation']['ready']
    assert len(split['snapshot']['videos']) == 2 and len(split['snapshot']['audios']) == 2
    assert [row['source_in_seconds'] for row in I.media_inventory(C.normalize_project(project)) if row['kind']=='video'] == [0,1]
    assert 'reference_video_frames' in {row['code'] for row in split['validation']['errors']}
    original_assets = copy.deepcopy(project['assets'])
    project['video_track'] = [right]; project['audio_track'] = [right_audio]
    project['processing_window'].update(start_seconds=10, end_seconds=15)
    status, selected = detect(project, prompt)
    assert status == 200 and selected['validation']['ready']
    assert project['assets'] == original_assets and len(selected['snapshot']['videos']) == 1
    built = execute(project, selected['state'], prompt, 64, 96)
    output = M['OUT'].ZVH3ReferenceOutlet().export_references(built[8])
    video, audio = output[11], output[14]
    assert list(video.shape) == [48,96,64,3]
    assert abs(float(video[0,0,0,1])-72/255) < .015 and abs(float(video[-1,0,0,1])-213/255) < .015
    assert abs(float(audio['waveform'][0,0,1000])-2500/32768) < .001
    manifests=json.loads(output[22])['decoded_manifests']
    assert manifests['video:'+right['clip_id']]['items'][0]['source_window'] == {'start_seconds':1,'end_seconds':3}
