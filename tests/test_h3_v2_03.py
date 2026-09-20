"""03 integration is deliberately separate from frozen 01/02 evidence."""
import runpy
from pathlib import Path
import json
import pytest


def test_representative_real_registry_http_and_cpu_fixed_outlet_matrix():
    matrix=runpy.run_path(str(Path(__file__).with_name("h3_v2_03_matrix.py")))
    result=matrix["run"]()
    assert result["case_count"]>=22 and result["assertions"]>500
    assert result["failed"]==result["skipped"]==0


def test_missing_template_slot_added_before_matched_source_does_not_overwrite_it():
    h=runpy.run_path(str(Path(__file__).with_name("test_h3_presets.py")))
    P,I,C=h['P'],h['I'],h['C']
    old=h['fresh'](2);state=h['confirmed'](old,intent='<Picture 1> 原有主体；<Picture 2> 新参考')
    state['media_purposes']={'p1':'<Picture 1> 原有主体用途','p2':'<Picture 2> 新参考用途'}
    preset=P.capture_template(state,old)
    current=h['fresh'](1,prefix='x_');loaded=P.apply_template(preset,I.empty_interview(),current)['state']
    added=h['fresh'](2,prefix='x_');added['picture_track'][0]['order']=9;added=C.normalize_project(added)
    result=I.compile_interview(loaded,added)
    assert result['state']['media_purposes']['x_p1']=='<Picture 2> 原有主体用途'
    assert result['state']['media_purposes']['x_p2']=='<Picture 1> 新参考用途'
    assert [row['source']['item_id'] for row in result['state']['reference_texts']['intent']['definitions']]==['x_p1','x_p2']


@pytest.mark.parametrize('kind,label,counts',[('picture','Picture',(3,0,0)),('video','Video',(0,3,0)),('audio','Audio',(0,0,3))])
def test_multiple_missing_slots_front_insert_repeat_reload_and_export_keep_sources(kind,label,counts):
    h=runpy.run_path(str(Path(__file__).with_name('test_h3_presets.py')))
    P,I,C=h['P'],h['I'],h['C'];short=kind[0]
    def fresh(count,prefix=''):
        values=[0,0,0];values[['picture','video','audio'].index(kind)]=count
        return h['fresh'](*values,prefix=prefix)
    old=fresh(3);state=h['confirmed'](old,intent=' / '.join(f'<{label} {i}> logical source {i}' for i in range(1,4)))
    state['media_purposes']={f'{short}{i}':f'<{label} {i}> purpose {i}' for i in range(1,4)}
    preset=P.capture_template(state,old);preset['slots'].reverse()
    current=fresh(1,'x_');loaded=P.apply_template(preset,I.empty_interview(),current)['state']
    for count in (2,3):
        added=fresh(count,'x_')
        for index,row in enumerate(added[kind+'_track']):
            row['order' if kind=='picture' else 'timeline_in_seconds']=count-index
        added=C.normalize_project(added)
        result=I.compile_interview(json.loads(I.dumps(loaded)),added);loaded=result['state']
        assert loaded['media_purposes'][f'x_{short}1']==f'<{label} {count}> purpose 1'
        assert [definition['source']['item_id'] for definition in loaded['reference_texts']['intent']['definitions'][:count]]==[f'x_{short}{i}' for i in range(1,count+1)]
        assert len({definition['source']['item_id'] for definition in loaded['reference_texts']['intent']['definitions'][:count]})==count
        if count==2:assert '<H3待绑定:r3>' in loaded['intent'] and loaded['preset_pending']
        reread=I.normalize_interview(json.loads(I.dumps(loaded)))
        assert all(reread[key]==loaded[key] for key in ('reference_texts','media_purposes','bindings','preset_pending'))
    assert not loaded['preset_pending']
    for i in range(1,4):
        assert loaded['media_purposes'][f'x_{short}{i}']==f'<{label} {4-i}> purpose {i}'
        assert loaded['reference_texts'][f'purpose:x_{short}{i}']['definitions'][0]['source']['item_id']==f'x_{short}{i}'
    exported=P.capture_template(h['H']['aligned'](added,loaded),added)
    assert 'item_id' not in json.dumps(exported) and 'existing_item_ids' not in json.dumps(exported)
    new=fresh(3,'new_');reloaded=P.apply_template(exported,I.empty_interview(),new)['state']
    assert [definition['source']['item_id'] for definition in reloaded['reference_texts']['intent']['definitions']]==[f'new_{short}3',f'new_{short}2',f'new_{short}1']


@pytest.mark.parametrize('case',['missing','duplicate','foreign','unknown','non-list'])
def test_pending_initial_source_metadata_rejects_missing_or_invalid(case):
    h=runpy.run_path(str(Path(__file__).with_name('test_h3_presets.py')))
    state,_=h['pending_voice_setup']();pending=state['preset_pending'][0]
    if case=='missing':pending.pop('existing_item_ids')
    if case=='duplicate':pending['existing_item_ids']*=2
    if case=='foreign':pending['existing_item_ids']=['../foreign']
    if case=='unknown':pending['initial_source_guess']=True
    if case=='non-list':pending['existing_item_ids']={}
    with pytest.raises(h['I'].InterviewError):h['I'].normalize_interview(state)


def test_explicit_runtime_copy_registration_and_real_shared_node_schemas(tmp_path):
    audit=runpy.run_path(str(Path(__file__).resolve().parents[1]/'tools/h3_v2_audit.py'))
    manifest=audit['manifest']();destination=audit['copy_runtime'](tmp_path/'runtime')
    assert all(audit['sha'](destination/row['path'])==row['sha256'] for row in manifest['files'])
    registration,mappings=audit['copied_registration'](destination)
    assert registration['passed'] and not registration['full_comfy_service_started']
    graph,proof=audit['skeleton'](mappings)
    assert proof['actual_plugin_input_output_and_T8_autogrow_checked'] and proof['backend_fixed_hub_wiring_errors']==[]
    assert len(graph['nodes'])==14 and len(graph['links'])==101
    assert sum(node['type']=='ZVH3ReverseStage' for node in graph['nodes'])==3
    assert not list(destination.rglob('*.sqlite3')) and not (destination/'.git').exists()
    with pytest.raises(ValueError):audit['copy_runtime'](destination)
