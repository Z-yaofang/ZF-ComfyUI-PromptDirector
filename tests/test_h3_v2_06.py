"""Independent controlled originals, real native VIDEO and finite CPU decoding."""
import copy
from fractions import Fraction
import hashlib
import importlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import types
import wave

import numpy as np
import pytest
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(ROOT/'tests/media_outlet_smoke.py'))
S,C=M['S'],M['C']
N=importlib.import_module(M['SPEC'].name+'.original_nodes')
W=importlib.import_module(M['SPEC'].name+'.original_worker')
R=importlib.import_module(M['SPEC'].name+'.runtime')
O=importlib.import_module(M['SPEC'].name+'.outlet')


@pytest.fixture(scope='module')
def native():
    sys.path.insert(0,str(ROOT.parents[1]))
    # Earlier legacy tests install a graph bootstrap stub; native verification
    # needs the real namespace/package, then restores that test-owned state.
    previous={key:value for key,value in sys.modules.copy().items() if key=='comfy_execution' or key.startswith('comfy_execution.')}
    for key in previous:sys.modules.pop(key)
    old=sys.argv;sys.argv=['originals-06','--cpu']
    try:
        from comfy.cli_args import args
        cpu=args.cpu;args.cpu=True
        from comfy_api.latest import InputImpl
        from comfy_extras.nodes_video import GetVideoComponents,SaveVideo
        yield InputImpl,GetVideoComponents,SaveVideo
    finally:
        if 'cpu' in locals():args.cpu=cpu
        for key in list(sys.modules):
            if key=='comfy_execution' or key.startswith('comfy_execution.'):sys.modules.pop(key)
        sys.modules.update(previous)
        sys.argv=old


@pytest.fixture(scope='module')
def neutral(tmp_path_factory):
    directory=tmp_path_factory.mktemp('original-06')
    store,project=M['imported_project'](directory)
    for rate,channels in [(48000,1),(48000,2),(32000,1),(96000,2),(48000,6)]:
        source=directory/f'{rate}-{channels}.wav'
        values=np.empty((rate*2+13,channels),dtype='<i2')
        for channel in range(channels):values[:,channel]=(channel+1)*1000
        with wave.open(str(source),'wb') as audio:
            audio.setparams((channels,2,rate,0,'NONE','not compressed'));audio.writeframes(values.tobytes())
        path,handle,name=store.allocate(source.name);shutil.copyfile(source,path)
        project['assets'].append(store.finish_import(path,handle,name))
    jpg=directory/'rotated.jpg'
    image=Image.new('RGB',(37,19),(200,50,0));exif=image.getexif();exif[274]=6
    image.save(jpg,exif=exif)
    path,handle,name=store.allocate(jpg.name);shutil.copyfile(jpg,path)
    project['assets'].append(store.finish_import(path,handle,name))
    old=R._store;R._store=store
    yield store,project,directory
    R._store=old


def export(store,asset):
    cls={'picture':N.ZVOriginalPictureOutlet,'video':N.ZVOriginalVideoOutlet,'audio':N.ZVOriginalAudioOutlet}[asset['kind']]
    before=hashlib.sha256(store.resolve(asset['source_handle']).read_bytes()).hexdigest()
    out=cls().export_media(asset['source_handle'])
    assert len(out)==4 and out[1]==str(store.resolve(asset['source_handle']))
    assert hashlib.sha256(Path(out[1]).read_bytes()).hexdigest()==before
    manifest=json.loads(out[2]);assert manifest['full_source'] and manifest['source_handle']==asset['source_handle']
    return out,manifest


@pytest.mark.parametrize('cls,kind,output',[(N.ZVOriginalPictureOutlet,'picture','IMAGE'),(N.ZVOriginalVideoOutlet,'video','VIDEO'),(N.ZVOriginalAudioOutlet,'audio','AUDIO')])
def test_independent_node_contract(cls,kind,output):
    assert cls.INPUT_TYPES()['required']=={'source_handle':('STRING',{'default':''})}
    assert cls.INPUT_TYPES()['optional']=={'original_sources':('ZV_ORIGINAL_SOURCES',{'forceInput':True}),'asset_id':('STRING',{'default':''})}
    assert cls.RETURN_TYPES==(output,'STRING','STRING','STRING') and cls.KIND==kind
    assert cls.RETURN_NAMES[1:]==('source_path','manifest_json','report')
    assert str(cls.IS_CHANGED(source_handle='x'))=='nan'


@pytest.mark.parametrize('index', [0,1,10])
def test_original_picture_natural_dimensions_exif_alpha_file_bytes(neutral,index):
    store,p,_=neutral;asset=p['assets'][index];out,manifest=export(store,asset)
    with Image.open(out[1]) as image:
        expected=np.asarray(ImageOps.exif_transpose(image).convert('RGB'),dtype=np.float32)/255
    assert out[0].device.type=='cpu' and np.array_equal(out[0].numpy()[0],expected)
    assert out[0].shape[1:]==expected.shape
    if index==1:assert expected.shape==(11,17,3) and 'alpha' in out[3]
    if index==10:assert expected.shape==(37,19,3)


@pytest.mark.parametrize('index,rate,channels,count',[(4,44100,1,132300),(5,48000,1,96013),(6,48000,2,96013),(7,32000,1,64013),(8,96000,2,192013),(9,48000,6,96013)])
def test_original_audio_full_samples_rate_channels(neutral,index,rate,channels,count):
    store,p,_=neutral;out,manifest=export(store,p['assets'][index]);audio=out[0]
    assert audio['sample_rate']==rate and tuple(audio['waveform'].shape)==(1,channels,count)
    assert audio['waveform'].device.type=='cpu'
    assert manifest['sample_count']==count and manifest['channels']==channels
    assert manifest['output_duration_seconds']==pytest.approx(count/rate)
    if index!=4:
        for channel in range(channels):assert np.all(audio['waveform'].numpy()[0,channel]==(channel+1)*1000/32768)


def test_real_native_video_zero_decode_then_actual_components(neutral,native,monkeypatch):
    store,p,_=neutral;InputImpl,Components,Save=native
    def forbidden(*args,**kwargs):raise AssertionError('original VIDEO must not decode video/audio')
    with monkeypatch.context() as patch:
        patch.setattr(InputImpl.VideoFromFile,'get_components',forbidden)
        out,manifest=export(store,p['assets'][3])
    assert type(out[0]) is InputImpl.VideoFromFile
    assert out[0].get_stream_source()==out[1] and manifest['video_decoded_frames']==0
    result=Components.execute(out[0]).result
    assert tuple(result[0].shape)==(36,24,32,3) and result[2]==12 and result[1]['waveform'].shape[-1]>0
    assert Save.define_schema().inputs[0].id=='video'


def test_original_video_over_15_seconds_native_no_full_decode(neutral,native,tmp_path,monkeypatch):
    import av
    store,_,_=neutral;path,handle,name=store.allocate('long-17s.mkv')
    with av.open(str(path),'w') as container:
        stream=container.add_stream('ffv1',rate=2);stream.width=32;stream.height=24;stream.pix_fmt='yuv444p'
        for index in range(34):
            frame=av.VideoFrame.from_ndarray(np.zeros((24,32,3),dtype=np.uint8),format='rgb24');frame.pts=index;frame.time_base=Fraction(1,2)
            for packet in stream.encode(frame):container.mux(packet)
        for packet in stream.encode(None):container.mux(packet)
    asset=store.finish_import(path,handle,name);assert asset['probe']['duration_seconds']==17
    with monkeypatch.context() as patch:
        patch.setattr(N.subprocess,'run',lambda *a,**k:pytest.fail('video original must not run decoder worker'))
        patch.setattr(native[0].VideoFromFile,'get_components',lambda *a:pytest.fail('must remain lazy'))
        out,manifest=export(store,asset)
    assert isinstance(out[0],native[0].VideoFromFile) and manifest['source_fps']==2


def test_actual_vhs_loader_with_inert_host_adapters_source_fps_and_audio(neutral,native,monkeypatch):
    # The installed host's top-level nodes import needs unavailable malloc_graph.
    # Only its unused format registry/queue globals are inert; actual VHS loader,
    # cv2/FFmpeg decoding, path validation and lazy_get_audio remain installed code.
    folder=ROOT.parents[0]/'ComfyUI-VideoHelperSuite'/'videohelpersuite'
    package=types.ModuleType('h3_06_actual_vhs');package.__path__=[str(folder)];sys.modules[package.__name__]=package
    host_nodes=types.ModuleType('nodes');host_nodes.VHSLoadFormats={}
    host_server=types.ModuleType('server');host_server.PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(prompt_queue=types.SimpleNamespace(currently_running={})))
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules,'nodes',host_nodes);patch.setitem(sys.modules,'server',host_server)
        loader=importlib.import_module(package.__name__+'.load_video_nodes')
    store,p,_=neutral;out,_=export(store,p['assets'][3])
    loaded=loader.LoadVideoPath().load_video(video=out[1],force_rate=0,custom_width=0,custom_height=0,frame_load_cap=0,skip_first_frames=0,select_every_nth=1,format='None')
    assert loaded[1]==36 and tuple(loaded[0].shape)==(36,24,32,3)
    assert loaded[3]['source_fps']==12 and loaded[3]['loaded_fps']==12
    assert loaded[2]['sample_rate']>0 and loaded[2]['waveform'].shape[-1]>0


@pytest.mark.parametrize('mutation',['invalid_gen','half_canvas','unrelated_bad','delete_pool','delete_track','move_cut','preset'])
def test_bad_project_and_all_timeline_changes_cannot_affect_original(neutral,mutation,monkeypatch):
    store,p,_=neutral;bad=copy.deepcopy(p);asset=bad['assets'][1]
    if mutation=='invalid_gen':bad['processing_window'].update(start_seconds=99,end_seconds=0,fps=-1)
    if mutation=='half_canvas':bad['canvas']={'width':1000,'height':None}
    if mutation=='unrelated_bad':bad['assets'].append({'asset_id':'bad','source_handle':'../bad'})
    if mutation=='delete_pool':bad['assets']=[]
    if mutation=='delete_track':bad['picture_track']=[]
    if mutation=='move_cut':bad['video_track'][0].update(source_out_seconds=999,timeline_in_seconds=500)
    if mutation=='preset':bad['processing_preset']={'bad':True}
    monkeypatch.setattr(store,'canonical',lambda *a:pytest.fail('independent original must not read project'))
    before=copy.deepcopy(bad);out,_=export(store,asset);assert tuple(out[0].shape)==(1,11,17,3) and bad==before


@pytest.mark.parametrize('handle',['',None,True,'../x','https://a.test/x.png',r'C:\x.png','originals/../x.png','originals/'+'0'*32+'.png'])
def test_invalid_unregistered_traversal_handle(neutral,handle):
    with pytest.raises(O.OutletError,match='原素材'):N.ZVOriginalPictureOutlet().export_media(handle)


@pytest.mark.parametrize('cls,index',[(N.ZVOriginalAudioOutlet,3),(N.ZVOriginalVideoOutlet,4),(N.ZVOriginalPictureOutlet,3),(N.ZVOriginalAudioOutlet,0)])
def test_strict_registry_kind(neutral,cls,index):
    with pytest.raises(O.OutletError,match='种类'):cls().export_media(neutral[1]['assets'][index]['source_handle'])


@pytest.mark.parametrize('change',['missing','bytes','mtime','wrong_record_kind','forged_probe','unregistered','source_handle_record'])
def test_actual_source_or_record_change_no_proxy_fallback(neutral,change,tmp_path):
    source_store,p,_=neutral;store=S.MediaStore(tmp_path/'input')
    path,handle,name=store.allocate('copy.png');shutil.copyfile(source_store.resolve(p['assets'][1]['source_handle']),path)
    asset=store.finish_import(path,handle,name);record=store.root/'cache'/f'{path.stem}.json'
    if change=='missing':path.unlink()
    if change=='bytes':path.write_bytes(b'not png')
    if change=='mtime':path.touch()
    if change=='unregistered':record.unlink()
    if change in {'wrong_record_kind','forged_probe','source_handle_record'}:
        data=json.loads(record.read_text())
        if change=='wrong_record_kind':data['asset']['kind']='audio'
        if change=='forged_probe':
            # Registry probe is not used to manufacture dimensions/decoded pixels.
            data['asset']['probe'].update(width=999,height=888)
        if change=='source_handle_record':data['asset']['source_handle']='originals/'+'0'*32+'.png'
        record.write_text(json.dumps(data))
    if change=='forged_probe':
        out=N.export_original(store,handle,'picture');assert tuple(out[0].shape)==(1,11,17,3)
    else:
        with pytest.raises(O.OutletError):N.export_original(store,handle,'picture')


def test_screenshot_pool_is_independent_original_picture(neutral):
    store,p,_=neutral;asset=store.capture_frame(p['assets'][3]['source_handle'],0,0,2,.5)
    out,_=export(store,asset);assert tuple(out[0].shape)==(1,24,32,3)


@pytest.mark.parametrize('field,value,kind,index',[('MAX_BYTES',1,'picture',0),('MAX_BYTES',1,'audio',5),('MAX_PACKETS',0,'audio',5),('MAX_FRAMES',0,'audio',5),('MAX_SECONDS',-1,'picture',0)])
def test_decoder_memory_time_packet_frame_budgets_fail_not_truncate(neutral,tmp_path,monkeypatch,field,value,kind,index):
    monkeypatch.setattr(W,field,value)
    with pytest.raises(ValueError,match='预算'):W.decode(kind,neutral[0].resolve(neutral[1]['assets'][index]['source_handle']),tmp_path/'partial.npy')
    assert not (tmp_path/'partial.npy').exists()


def test_hard_subprocess_timeout_and_busy_release(neutral,monkeypatch):
    store,p,_=neutral
    monkeypatch.setattr(N.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('worker',30)))
    with pytest.raises(O.OutletError,match='30秒'):export(store,p['assets'][0])
    assert store.jobs.acquire(False) and store.jobs.acquire(False)
    try:
        with pytest.raises(O.OutletError,match='忙'):export(store,p['assets'][0])
    finally:store.jobs.release();store.jobs.release()


def test_freshness_recheck_during_decode(neutral,monkeypatch):
    store,p,_=neutral;original=store.record;calls=0
    def change(handle):
        nonlocal calls
        calls+=1
        if calls==2:raise S.MediaError('source_unavailable','changed')
        return original(handle)
    monkeypatch.setattr(store,'record',change)
    with pytest.raises(O.OutletError,match='改变'):export(store,p['assets'][0])
