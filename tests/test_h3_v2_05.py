"""Native CPU screenshot, controlled HTTP, durability and released H3 contracts."""
import asyncio
import copy
import json
import math
import os
from pathlib import Path
import runpy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT/'tests/h3_v2_03_matrix.py'))
C,I,S = (M[key] for key in ('C','I','S'))

@pytest.fixture(scope='module')
def neutral(tmp_path_factory):
    store,assets=M['setup'](tmp_path_factory.mktemp('capture-05'))
    # Planning normally forbids worker calls; this stage explicitly decodes frames.
    store.worker=type(store).worker.__get__(store)
    previous=M['RUN']._store;M['RUN']._store=store
    yield store,assets
    M['RUN']._store=previous

def request_for(asset,**fields):
    return {'source_handle':asset['source_handle'],'timeline_in_seconds':7,'source_in_seconds':.5,'source_out_seconds':2.5,'playhead_seconds':7.05,**fields}

def pixels(store,asset):
    from PIL import Image
    with Image.open(store.resolve(asset['source_handle'])) as image:
        return image.size,image.getpixel((0,0))

def files(store):return {p.relative_to(store.root).as_posix():p.read_bytes() for p in store.root.rglob('*') if p.is_file()}

def test_actual_native_frame_mapping_dimensions_persistent_and_repeated(neutral):
    store,assets=neutral;source=assets['video'][0];before=store.resolve(source['source_handle']).read_bytes()
    captured=store.capture_frame(**request_for(source))
    assert captured['kind']=='picture' and captured['capture']['method']=='video_frame'
    assert pixels(store,captured)==((32,24),(40,39,101))
    assert captured['capture']['source_seconds']==pytest.approx(.55)
    assert captured['capture']['frame_seconds']==pytest.approx(13/24,abs=.0005)
    assert captured['probe']['width']==32 and captured['probe']['height']==24
    assert store.resolve(source['source_handle']).read_bytes()==before
    assert store.record(captured['source_handle'])==captured
    fresh=type(store)(store.input_root)
    assert fresh.record(captured['source_handle'])==captured
    assert fresh.preview(captured['source_handle'],'original').read_bytes().startswith(b'\x89PNG')
    assert fresh.preview(captured['source_handle'],'thumbnail').is_file()
    again=store.capture_frame(**request_for(source))
    assert again['source_handle']!=captured['source_handle'] and pixels(store,again)==pixels(store,captured)

def test_original_not_proxy_or_thumbnail(neutral):
    import av
    store,assets=neutral;source=assets['video'][0];shot=store.capture_frame(**request_for(source))
    with av.open(str(store.preview(source['source_handle'],'proxy'))) as container:
        stream=container.streams.video[0];assert float(stream.average_rate)==24
        frame=next(container.decode(stream));assert (frame.width,frame.height)!=(32,24)
    from PIL import Image
    with Image.open(store.preview(source['source_handle'],'thumbnail')) as image:
        assert image.getpixel((0,0))!=pixels(store,shot)[1]

@pytest.mark.parametrize('rotation,hflip,vflip',[(90,False,False),(0,True,False),(0,False,True),(90,True,False)])
def test_native_display_rotation_asymmetric_original_pixels(neutral,tmp_path,rotation,hflip,vflip):
    import av
    import imageio_ffmpeg
    import shutil
    import subprocess
    from PIL import Image,ImageDraw
    store,_=neutral;original=Image.new('RGB',(48,32),(10,20,30));draw=ImageDraw.Draw(original)
    draw.rectangle((0,0,20,12),fill=(255,0,0));draw.rectangle((28,20,47,31),fill=(0,255,0))
    image=tmp_path/'orientation.png';original.save(image);video=tmp_path/'orientation.mp4';rotated=tmp_path/'rotated.mp4'
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    for args in [['-loop','1','-framerate','24','-i',str(image),'-t','2','-c:v','libx264rgb','-crf','0','-threads','1',str(video)],['-display_rotation',str(rotation),*(['-display_hflip'] if hflip else []),*(['-display_vflip'] if vflip else []),'-i',str(video),'-c','copy',str(rotated)]]:
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',*args],check=True,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    path,handle,name=store.allocate(rotated.name);shutil.copyfile(rotated,path);asset=store.finish_import(path,handle,name)
    expected_path=tmp_path/'ffmpeg_native.png'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(path),'-frames:v','1','-threads','1',str(expected_path)],check=True,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    captured=store.capture_frame(**request_for(asset,source_out_seconds=1.5))
    with Image.open(store.resolve(captured['source_handle'])) as actual,Image.open(expected_path) as expected:
        assert actual.size==((32,48) if rotation==90 else (48,32)) and actual.tobytes()==expected.convert('RGB').tobytes()

@pytest.mark.parametrize('field,value,code',[
    ('playhead_seconds',7-1e-6,'capture_window'),('playhead_seconds',9,'capture_window'),
    ('playhead_seconds',float('nan'),'capture_time'),('playhead_seconds',float('inf'),'capture_time'),
    ('playhead_seconds',True,'capture_time'),('source_in_seconds',-.1,'capture_window'),
    ('source_out_seconds',3.1,'capture_window'),('source_out_seconds',.5,'capture_window'),
    ('timeline_in_seconds',-1,'capture_window'),('timeline_in_seconds',43201,'capture_window'),
    ('source_handle','../../secret','unsafe_handle'),('source_handle','https://example.com/a.mp4','unsafe_handle'),
    ('source_handle','originals/'+'0'*32+'.mp4','source_unavailable'),
])
def test_invalid_request_no_new_files(neutral,field,value,code):
    store,assets=neutral;before=files(store)
    with pytest.raises(M['STORE'].MediaError) as error:store.capture_frame(**request_for(assets['video'][0],**{field:value}))
    assert error.value.code==code and files(store)==before

@pytest.mark.parametrize('kind',['picture','audio'])
def test_only_registered_video_accepted(neutral,kind):
    store,assets=neutral;before=files(store)
    with pytest.raises(M['STORE'].MediaError,match='原视频'):store.capture_frame(**request_for(assets[kind][0]))
    assert files(store)==before

@pytest.mark.parametrize('when',['before','decode','register'])
@pytest.mark.parametrize('how',['size','missing'])
def test_source_stat_change_rejected_before_and_after_decode_and_register(neutral,monkeypatch,when,how):
    store,assets=neutral;source=assets['video'][0];path=store.resolve(source['source_handle']);info=path.stat();before=files(store);original=path.read_bytes()
    def change():
        if how=='size':path.write_bytes(original+b'changed')
        if how=='missing':path.unlink()
    worker=store.worker;finish=store.finish_import
    if when=='before':change()
    if when=='decode':
        def altered(*args,**kwargs):
            result=worker(*args,**kwargs)
            if args[0]=='screenshot':change()
            return result
        monkeypatch.setattr(store,'worker',altered)
    if when=='register':
        def altered(*args,**kwargs):
            result=finish(*args,**kwargs);change();return result
        monkeypatch.setattr(store,'finish_import',altered)
    try:
        with pytest.raises(M['STORE'].MediaError) as error:store.capture_frame(**request_for(source))
        assert error.value.code=='source_unavailable'
    finally:
        path.write_bytes(original)
        os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
    assert files(store)==before


@pytest.mark.parametrize('when',['before','decode','register'])
def test_source_mtime_normalization_keeps_capture_available(neutral,monkeypatch,when):
    store,assets=neutral;source=assets['video'][0];path=store.resolve(source['source_handle']);info=path.stat();worker=store.worker;finish=store.finish_import
    def change():os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns+1000000))
    if when=='before':change()
    if when=='decode':
        def altered(*args,**kwargs):
            result=worker(*args,**kwargs)
            if args[0]=='screenshot':change()
            return result
        monkeypatch.setattr(store,'worker',altered)
    if when=='register':
        def altered(*args,**kwargs):
            result=finish(*args,**kwargs);change();return result
        monkeypatch.setattr(store,'finish_import',altered)
    try:
        captured=store.capture_frame(**request_for(source))
        assert captured['kind']=='picture' and store.record(source['source_handle'])==source
    finally:
        os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))

def test_shared_upload_capture_lock_and_worker_job_limit(neutral,monkeypatch):
    store,assets=neutral;request=request_for(assets['video'][0]);before=files(store)
    with store.import_lock:
        with pytest.raises(M['STORE'].MediaError) as error:store.capture_frame(**request)
        assert error.value.code=='busy'
    store.jobs.acquire();store.jobs.acquire()
    try:
        with pytest.raises(M['STORE'].MediaError) as error:store.capture_frame(**request)
        assert error.value.code=='busy' and files(store)==before
    finally:store.jobs.release();store.jobs.release()
    entered=threading.Event();release=threading.Event();worker=store.worker
    def waiting(*args,**kwargs):
        result=worker(*args,**kwargs)
        if args[0]=='screenshot':entered.set();assert release.wait(10)
        return result
    monkeypatch.setattr(store,'worker',waiting)
    with ThreadPoolExecutor(2) as executor:
        first=executor.submit(store.capture_frame,**request);assert entered.wait(10)
        try:
            with pytest.raises(M['STORE'].MediaError) as error:store.capture_frame(**request)
            assert error.value.code=='busy'
        finally:release.set()
        assert first.result()['kind']=='picture'

@pytest.mark.parametrize('failure',['quota','worker','registry','png-collision','temporary-collision','record-collision'])
def test_failure_cleans_only_this_attempt_preserves_registry_and_conflicts(neutral,monkeypatch,failure):
    store,assets=neutral;before=files(store);original_allocate=store.allocate
    foreign=[]
    if failure=='quota':monkeypatch.setattr(store,'quota',lambda:1)
    if failure=='worker':
        def failed(*args,**kwargs):raise M['STORE'].MediaError('probe_timeout','timeout')
        monkeypatch.setattr(store,'worker',failed)
    if failure=='registry':
        def failed(*args,**kwargs):raise OSError('registry disk failure')
        monkeypatch.setattr(store,'finish_import',failed)
    if 'collision' in failure:
        def conflict(name):
            path,handle,name=original_allocate(name)
            target=path if failure=='png-collision' else path.with_name(path.stem+'.partial.png') if failure=='temporary-collision' else store.root/'cache'/(path.stem+'.json')
            target.write_bytes(b'foreign-conflict');foreign.append(target)
            return path,handle,name
        monkeypatch.setattr(store,'allocate',conflict)
    try:
        with pytest.raises((M['STORE'].MediaError,OSError)):store.capture_frame(**request_for(assets['video'][0]))
        final=files(store)
        assert all(final[name]==data for name,data in before.items())
        assert set(final)-set(before)=={p.relative_to(store.root).as_posix() for p in foreign}
        assert all(p.read_bytes()==b'foreign-conflict' for p in foreign)
        assert store.import_lock.acquire(False);store.import_lock.release()
    finally:
        for path in foreign:path.unlink()

def test_server_provenance_normalize_forgery_and_independence_after_source_removal(neutral):
    store,assets=neutral;shot=store.capture_frame(**request_for(assets['video'][0]));project=C.empty_project();project['assets']=[shot,copy.deepcopy(assets['picture'][0])]
    project['assets'][0]['capture']['source_seconds']=1.75
    project['assets'][1]['name']='假截图.png';project['assets'][1]['capture']=copy.deepcopy(shot['capture'])
    canonical=store.canonical(json.loads(json.dumps(project)))
    assert canonical['assets'][0]['capture']['source_seconds']==pytest.approx(.55)
    assert 'capture' not in canonical['assets'][1]
    assert not canonical['validation']['errors']
    path=store.resolve(assets['video'][0]['source_handle']);info=path.stat()
    try:
        os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns+1000000))
        assert not store.canonical(canonical)['validation']['errors']
        assert pixels(store,canonical['assets'][0])==((32,24),(40,39,101))
    finally:os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))

def test_pool_only_keeps_alignment_then_picture_banks_actual_24_outlet_and_portable_preset(neutral):
    store,assets=neutral;project=M['project'](assets,1);project['output_canvas']={'width':64,'height':96}
    state=M['V2']['aligned'](project);before=copy.deepcopy(state['alignment'])
    shot=store.capture_frame(**request_for(assets['video'][0]));project['assets'].append(shot)
    assert I.compile_interview(state,store.canonical(project))['alignment_context']==before
    project['picture_track']=[{'item_id':'shot','asset_id':shot['asset_id'],'order':1}]
    assert 'alignment_stale' in {e['code'] for e in I.compile_interview(state,project)['validation']['errors']}
    for bank,slot in [('first_frame',0),('last_frame',1),('ref_images',2)]:
        current=I.empty_interview();current['bindings']={'shot':{'item_id':'shot','participates':True,'banks':[bank]}}
        current=M['V2']['aligned'](store.canonical(project),current)
        built=M['V2']['N'].ZVH3InterviewFormV2().build(project,I.dumps(current),prompt=M['prompt'](),unique_id='172')
        assert built[5]
        outputs=M['OUT'].ZVH3ReferenceOutlet().export_references(built[6])
        assert len(outputs)==24 and list(outputs[slot].shape)==[1,24,32,3]
        assert outputs[slot][0,0,0].tolist()==pytest.approx([40/255,39/255,101/255])
        current['intent']=f"保持 <Picture 1> 的画面";template=M['P'].capture_template(current,project)
        assert shot['source_handle'] not in json.dumps(template) and 'capture' not in json.dumps(template)
        loaded=M['P'].apply_template(template,I.empty_interview(),project)
        assert 'Picture 1' in loaded['state']['intent']

def test_actual_http_strict_payload_capture_preview_and_shared_upload_busy(neutral):
    from aiohttp import web,FormData
    from aiohttp.test_utils import TestClient,TestServer
    import importlib
    store,assets=neutral;server=importlib.import_module(M['PACKAGE']+'.media_evidence.server')
    async def run():
        routes=web.RouteTableDef();server.register_media_routes(routes,lambda:store,lambda _:None)
        app=web.Application();app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            request=request_for(assets['video'][1]);response=await client.post('/zf-media-evidence/screenshot',json=request)
            result=await response.json();assert response.status==200 and result['asset']['kind']=='picture'
            assert pixels(store,result['asset'])==((32,24),(81,39,101))
            response=await client.get('/zf-media-evidence/preview',params={'source':result['asset']['source_handle'],'variant':'original'})
            assert response.status==200 and (await response.read()).startswith(b'\x89PNG')
            for data in [b'{"x":1,"x":2}',b'{"playhead_seconds":NaN}',b'[]',b' '*2049,json.dumps({**request,'output_directory':'C:/'}).encode()]:
                response=await client.post('/zf-media-evidence/screenshot',data=data);assert response.status==400
            with store.import_lock:
                response=await client.post('/zf-media-evidence/screenshot',json=request);assert response.status==429
                form=FormData();form.add_field('file',b'not decoded because busy',filename='a.png')
                response=await client.post('/zf-media-evidence/upload',data=form);assert response.status==429
            response=await client.post('/zf-media-evidence/screenshot',json=request,headers={'Origin':'https://unrelated.example'})
            assert response.status==400 and (await response.json())['error']['code']=='origin'
    asyncio.run(run())

def assert_registered_files_exist(store):
    for path in (store.root/'cache').glob('*.json'):
        if path.name.endswith('.partial.json'):continue
        value=json.loads(path.read_text(encoding='utf-8'))
        if 'asset' in value:assert store.resolve(value['asset']['source_handle']).is_file()

@pytest.mark.parametrize('suffix',['.partial.json','.partial.png'])
def test_actual_unlink_once_retries_preserves_commit_and_releases_lock(neutral,monkeypatch,suffix):
    store,assets=neutral;before=files(store);unlink=Path.unlink;attempts=[]
    def sharing_error(path,*args,**kwargs):
        if path.is_relative_to(store.root) and path.name.endswith(suffix):
            attempts.append(path)
            if len(attempts)==1:raise PermissionError('one real syscall sharing failure')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',sharing_error)
    shot=store.capture_frame(**request_for(assets['video'][0]));assert shot['kind']=='picture'
    assert len(attempts)==2 and store.record(shot['source_handle'])==shot
    assert store.import_lock.acquire(False);store.import_lock.release()
    final=files(store);assert all(final[name]==data for name,data in before.items())
    assert not any('.partial.' in name for name in set(final)-set(before));assert_registered_files_exist(store)

@pytest.mark.parametrize('suffix',['.partial.json','.partial.png'])
def test_actual_persistent_unlink_reports_incomplete_cleanup_and_releases_lock(neutral,monkeypatch,suffix):
    store,assets=neutral;before=files(store);unlink=Path.unlink;attempts=[]
    def locked(path,*args,**kwargs):
        if path.is_relative_to(store.root) and path.name.endswith(suffix):
            attempts.append(path);raise PermissionError('persistent actual unlink failure')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',locked)
    try:
        with pytest.raises(M['STORE'].MediaError) as error:store.capture_frame(**request_for(assets['video'][0]))
        assert error.value.code in {'cleanup_failed','capture_cleanup'}
        assert '未能' in error.value.message and len(attempts)==2
        assert store.import_lock.acquire(False);store.import_lock.release()
        final=files(store);assert all(final[name]==data for name,data in before.items());assert_registered_files_exist(store)
        created=set(final)-set(before)
        if suffix=='.partial.json':assert len(created)==1 and not error.value.asset_committed
        else:assert len(created)==3 and error.value.asset_committed
    finally:
        for name in set(files(store))-set(before):unlink(store.root/name)

@pytest.mark.parametrize('blocked',['partial','record'])
def test_cleanup_failure_does_not_block_sibling_cleanup_or_create_dangling_record(neutral,monkeypatch,blocked):
    store,assets=neutral;source=assets['video'][0];source_path=store.resolve(source['source_handle']);info=source_path.stat();source_bytes=source_path.read_bytes();before=files(store);unlink=Path.unlink;worker=store.worker
    def after_register_probe(*args,**kwargs):
        value=worker(*args,**kwargs)
        if args[0]=='probe' and args[1].suffix=='.png':source_path.write_bytes(source_bytes+b'changed')
        return value
    monkeypatch.setattr(store,'worker',after_register_probe)
    def locked(path,*args,**kwargs):
        if path.is_relative_to(store.root) and ((blocked=='partial' and path.name.endswith('.partial.png')) or (blocked=='record' and path.parent==store.root/'cache' and path.suffix=='.json' and not path.name.endswith('.partial.json') and path.relative_to(store.root).as_posix() not in before)):
            raise PermissionError('persistent one owned sibling lock')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',locked)
    try:
        with pytest.raises(M['STORE'].MediaError) as error:store.capture_frame(**request_for(source))
        assert error.value.code=='capture_cleanup';assert store.import_lock.acquire(False);store.import_lock.release()
        assert_registered_files_exist(store);created=set(files(store))-set(before)
        if blocked=='partial':assert len(created)==1 and next(iter(created)).endswith('.partial.png')
        else:assert len(created)==2 and error.value.asset_committed
    finally:
        source_path.write_bytes(source_bytes)
        os.utime(source_path,ns=(info.st_atime_ns,info.st_mtime_ns))
        for name in set(files(store))-set(before):unlink(store.root/name)

def test_upload_real_unlink_fault_commit_error_preserves_valid_asset_and_releases_lock(neutral,monkeypatch):
    from aiohttp import web,FormData
    from aiohttp.test_utils import TestClient,TestServer
    import importlib
    store,assets=neutral;server=importlib.import_module(M['PACKAGE']+'.media_evidence.server');unlink=Path.unlink;before=files(store)
    def locked(path,*args,**kwargs):
        if path.is_relative_to(store.root) and path.name.endswith('.partial.json'):raise PermissionError('persistent temporary registry file')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',locked)
    async def run():
        routes=web.RouteTableDef();server.register_media_routes(routes,lambda:store,lambda _:None);app=web.Application();app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            form=FormData();form.add_field('file',store.resolve(assets['picture'][0]['source_handle']).read_bytes(),filename='ordinary.png')
            response=await client.post('/zf-media-evidence/upload',data=form)
            assert response.status==400 and (await response.json())['error']['code']=='cleanup_failed'
            assert store.import_lock.acquire(False);store.import_lock.release();assert_registered_files_exist(store)
    try:asyncio.run(run())
    finally:
        for name in set(files(store))-set(before):unlink(store.root/name)
