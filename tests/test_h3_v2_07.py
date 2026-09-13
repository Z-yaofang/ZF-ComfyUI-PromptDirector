"""Real selected-only CPU outputs and installed core mapping, without service boot."""
import ast
import asyncio
import copy
from contextlib import nullcontext
import hashlib
import importlib
import importlib.util
import inspect
import json
from pathlib import Path
import runpy
import sys
import types

import pytest

ROOT=Path(__file__).resolve().parents[1]
H=runpy.run_path(str(ROOT/'tests/test_h3_v2_06.py'))
native=H['native'];neutral=H['neutral']
N,S,O,R=H['N'],H['S'],H['O'],H['R']
D=importlib.import_module(H['M']['SPEC'].name+'.node')
P=importlib.import_module(H['M']['SPEC'].name+'.original_sources')

@pytest.fixture
def core(monkeypatch):
    path=ROOT.parents[1]/'comfy_execution/graph_utils.py'
    spec=importlib.util.spec_from_file_location('comfy_execution.graph_utils',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules,'comfy_execution.graph_utils',module)
    namespace={'asyncio':asyncio,'inspect':inspect,'is_class':inspect.isclass,'CurrentNodeContext':lambda *a:nullcontext(),'_ComfyNodeInternal':type('UnusedV3',(),{}),'_NodeOutputInternal':type('UnusedOutput',(),{}),'nodes':types.SimpleNamespace(before_node_execution=lambda:None),'ExecutionBlocker':module.ExecutionBlocker,'is_link':module.is_link}
    source=ROOT.parents[1]/'execution.py'
    names={'_async_map_node_over_list','merge_result_data','get_output_data','get_output_from_returns'}
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    parts=[n for n in tree.body if getattr(n,'name',None) in names];assert len(parts)==4
    exec(compile(ast.Module(body=parts,type_ignores=[]),str(source),'exec'),namespace)
    namespace['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    return namespace

def connected(asset,sources):
    cls={'picture':N.ZVOriginalPictureOutlet,'video':N.ZVOriginalVideoOutlet,'audio':N.ZVOriginalAudioOutlet}[asset['kind']]
    return cls().export_media('',original_sources=sources,asset_id=asset['asset_id'])

@pytest.mark.parametrize('index',[0,1,3,5,6,10])
def test_real_three_sources_legacy_equal_full_output(neutral,native,index):
    store,project,_=neutral;asset=project['assets'][index]
    catalog=P.original_sources(json.dumps(project))
    before=hashlib.sha256(store.resolve(asset['source_handle']).read_bytes()).hexdigest()
    output=connected(asset,catalog);legacy=H['export'](store,asset)[0]
    assert output[1]==legacy[1] and json.loads(output[2])['binding']=='catalog_original'
    assert hashlib.sha256(Path(output[1]).read_bytes()).hexdigest()==before
    if asset['kind']=='picture':assert (output[0].numpy()==legacy[0].numpy()).all()
    elif asset['kind']=='audio':
        assert output[0]['sample_rate']==legacy[0]['sample_rate']
        assert (output[0]['waveform'].numpy()==legacy[0]['waveform'].numpy()).all()
    else:
        assert type(output[0]) is native[0].VideoFromFile
        result=native[1].execute(output[0]).result
        assert tuple(result[0].shape)==(36,24,32,3) and result[1]['waveform'].shape[-1]==144000

@pytest.mark.parametrize('mutation',['empty','window','preset','clip','canvas','unknown','other_missing','other_kind','other_shape','other_duplicate','task_duplicates','task_nonfinite'])
def test_task_state_and_unselected_bad_assets_do_not_block_selected(neutral,core,mutation):
    store,project,_=neutral;draft=copy.deepcopy(project);asset=draft['assets'][1]
    if mutation=='empty':
        for key in ('picture_track','video_track','audio_track'):draft[key]=[]
    if mutation=='window':draft['processing_window']={'start_seconds':99,'end_seconds':0,'fps':-1}
    if mutation=='preset':draft['processing_preset']={'bad':True}
    if mutation=='clip':draft['video_track']=[{'garbage':True}]
    if mutation=='canvas':draft['output_canvas']={'width':1000}
    if mutation=='unknown':draft['interview']={'invalid':True}
    if mutation.startswith('other_'):
        row={'asset_id':'bad','kind':'audio','source_handle':'../missing','probe':None}
        if mutation=='other_kind':row['kind']='picture'
        if mutation=='other_shape':row={'garbage':True}
        draft['assets'].append(row)
        if mutation=='other_duplicate':draft['assets'].append(copy.deepcopy(row))
    text=json.dumps(draft)
    if mutation=='task_duplicates':text=text[:-1]+',"processing_window":null}'
    if mutation=='task_nonfinite':text=text[:-1]+',"bad_task_value":NaN}'
    out=D.ZVUniversalMediaEvidenceDesk().export_project(text)
    assert isinstance(out[2],P.OriginalSources)
    assert tuple(connected(asset,out[2])[0].shape)==(1,11,17,3)
    assert 'source_handle' not in repr(out[2]) or asset['source_handle'] in repr(out[2])

@pytest.mark.parametrize('width,height',[(640,None),(None,1152),(641,1152),(32,32)])
def test_internal_canvas_blockers_leave_original_available(neutral,core,width,height):
    store,project,_=neutral;out=D.ZVUniversalMediaEvidenceDesk().export_project(json.dumps(project),width,height)
    if width==height==32:assert out[0]['output_canvas']=={'width':32,'height':32}
    else:assert all(isinstance(v,core['ExecutionBlocker']) for v in out[:2])
    assert tuple(connected(project['assets'][1],out[2])[0].shape)==(1,11,17,3)

@pytest.mark.parametrize('text',['{}','[]','{"assets":{}}','{"assets":[],"assets":[]}','{bad','{"assets":'+json.dumps([{}]*129)+'}','{"assets":[],"task":'+('['*34)+'0'+(']'*34)+'}','\ud800','x'*(2*1024*1024+1)],ids=['missing','root_array','pool_object','duplicate_pool','syntax','many','depth','encoding','size'])
def test_transport_and_pool_ambiguity_rejected(text):
    with pytest.raises(O.OutletError):P.original_sources(text)

@pytest.mark.parametrize('mutation',['duplicate_id','duplicate_field','wrong_kind','wrong_id','wrong_handle','nonstring','removed'])
def test_selected_identity_and_field_errors_early(neutral,mutation):
    store,project,_=neutral;asset=project['assets'][1];pool=[copy.deepcopy(asset)]
    if mutation=='duplicate_id':pool.append(copy.deepcopy(asset))
    if mutation=='wrong_kind':pool[0]['kind']='audio'
    if mutation=='wrong_id':pool[0]['asset_id']='other'
    if mutation=='wrong_handle':pool[0]['source_handle']=project['assets'][0]['source_handle']
    if mutation=='nonstring':pool[0]['source_handle']=False
    if mutation=='removed':pool=[]
    text=json.dumps({'assets':pool})
    if mutation=='duplicate_field':text=text.replace('"kind": "picture"','"kind": "picture", "kind": "picture"')
    with pytest.raises(O.OutletError):connected(asset,P.original_sources(text))

@pytest.mark.parametrize('sources,asset_id',[(None,'marked'),(None,None),(None,False),({},'marked')])
def test_new_binding_never_falls_back_to_valid_legacy_handle(neutral,sources,asset_id):
    asset=neutral[1]['assets'][1]
    with pytest.raises(O.OutletError):N.ZVOriginalPictureOutlet().export_media(asset['source_handle'],sources,asset_id)

@pytest.mark.parametrize('change',['missing','mtime','size'])
def test_actual_selected_file_mutations_rechecked(neutral,tmp_path,change):
    import os
    import shutil
    store,project,_=neutral;original=store.resolve(project['assets'][1]['source_handle'])
    path,handle,name=store.allocate('change.png');shutil.copyfile(original,path);asset=store.finish_import(path,handle,name)
    catalog=P.original_sources(json.dumps({'assets':[asset]}));connected(asset,catalog)
    if change=='missing':path.unlink()
    if change=='mtime':os.utime(path,ns=(path.stat().st_atime_ns,path.stat().st_mtime_ns+1000000))
    if change=='size':path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(O.OutletError,match='改变|丢失'):connected(asset,catalog)

def test_catalog_does_not_hydrate_unused_records(neutral,monkeypatch):
    store,project,_=neutral;asset=project['assets'][1];original=store.record;seen=[]
    def only(handle):
        seen.append(handle);assert handle==asset['source_handle'];return original(handle)
    monkeypatch.setattr(store,'record',only)
    catalog=P.original_sources(json.dumps(project));assert seen==[];connected(asset,catalog)
    assert seen==[asset['source_handle'],asset['source_handle']]

def test_installed_core_maps_production_partial_outputs(neutral,core):
    draft=copy.deepcopy(neutral[1]);draft['processing_preset']={'bad':True}
    result,*_=asyncio.run(core['get_output_data']('neutral','desk',D.ZVUniversalMediaEvidenceDesk(),{'project_data':[json.dumps(draft)]}))
    assert isinstance(result[0][0],core['ExecutionBlocker']) and isinstance(result[2][0],P.OriginalSources)
    asset=draft['assets'][1]
    raw,*_=asyncio.run(core['get_output_data']('neutral','raw',N.ZVOriginalPictureOutlet(),{'source_handle':[''],'asset_id':[asset['asset_id']],'original_sources':result[2]}))
    assert tuple(raw[0][0].shape)==(1,11,17,3)
    class Sink:
        RETURN_TYPES=('STRING',);FUNCTION='run';calls=0
        def run(self,value):self.calls+=1;return ('ran',)
    sink=Sink();blocked,*_=asyncio.run(core['get_output_data']('neutral','task',sink,{'value':result[0]}))
    assert sink.calls==0 and isinstance(blocked[0][0],core['ExecutionBlocker'])

def test_unknown_programming_error_not_swallowed(neutral,core,monkeypatch):
    monkeypatch.setattr(neutral[0],'canonical',lambda p:(_ for _ in ()).throw(RuntimeError('programming fault')))
    with pytest.raises(RuntimeError,match='programming fault'):D.ZVUniversalMediaEvidenceDesk().export_project(json.dumps(neutral[1]))
