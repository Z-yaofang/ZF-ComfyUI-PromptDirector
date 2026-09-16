// Isolated browser harness only; never attaches to a running ComfyUI/browser.
// node tests/media_evidence_ui_smoke.mjs URL PLAYWRIGHT_PACKAGE CHROMIUM_EXECUTABLE [--no-screenshot]
import { createRequire } from 'node:module';
import { mkdir, readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { chromium } = createRequire(import.meta.url)(process.argv[3] || 'playwright');
const browser = await chromium.launch({headless:true, executablePath:process.argv[4] || undefined, ignoreDefaultArgs:['--hide-scrollbars']});
const page = await browser.newPage({viewport:{width:1240,height:1180}});
const errors=[];
const visualRequests=new Map();
page.on('request',request=>{const url=new URL(request.url());if(url.pathname.endsWith('/preview')&&['thumbnail','peaks'].includes(url.searchParams.get('variant'))){const key=url.searchParams.get('source')+':'+url.searchParams.get('variant');visualRequests.set(key,(visualRequests.get(key)||0)+1);}});
page.on('pageerror',error=>errors.push(error.message));
let checks=0;
const state=()=>page.evaluate(()=>deskNode.zfMediaDesk.getProject());
const synced=()=>page.waitForFunction(()=>{const p=deskNode.zfMediaDesk.getProject();return p.label_map?.length===p.picture_track.length+p.video_track.length+p.audio_track.length && !document.querySelector('.zf-med-grid').textContent.includes('编号同步中');});
async function clickAsset(name){await page.locator('.zf-med-asset').filter({hasText:name}).click();}
async function clickClip(id){const ruler=await page.locator('.zf-med-ruler').boundingBox();await page.mouse.click(ruler.x+1,ruler.y+32);await page.locator(`[data-id="${id}"]`).click();}
async function addSelected(){await page.getByRole('button',{name:'加入对应轨道（播放头处）'}).click();await synced();}
async function drag(locator,dx){const b=await locator.boundingBox();assert(b);await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.move(b.x+b.width/2+dx,b.y+b.height/2,{steps:8});await page.mouse.up();await synced();}
async function startPoolDrag(assetId,target,offset=30){const source=await page.locator(`[data-asset-id="${assetId}"]`).boundingBox(),dest=await target.boundingBox();await page.mouse.move(source.x+22,source.y+24);await page.mouse.down();await page.mouse.move(source.x+35,source.y+25,{steps:3});await page.mouse.move(dest.x+offset,dest.y+40,{steps:10});await page.mouse.move(dest.x+offset+1,dest.y+40);}
async function completeVisuals(){await page.waitForFunction(()=>[...document.querySelectorAll('.zf-med-clip-thumb')].every(img=>img.complete&&img.naturalWidth>0)&&[...document.querySelectorAll('.zf-med-clip-wave')].every(c=>c.dataset.waveMode==='peaks'));}
async function assertWindowPanel(){const p=await state(),w=p.processing_window;assert.equal(Number(await page.getByLabel('开始 / 秒',{exact:true}).inputValue()),w.start_seconds);assert.equal(Number(await page.getByLabel('结束 / 秒',{exact:true}).inputValue()),w.end_seconds);assert.equal(await page.locator('.zf-med-window-total').textContent(),`总时长 ${(w.end_seconds-w.start_seconds).toFixed(3)} 秒`);}
try {
    await page.goto(process.argv[2]);await page.waitForSelector('.zf-med');
    await page.getByLabel('当前处理预设',{exact:true}).selectOption('builtin.minimax-h3.single@1');await synced();
    assert.equal(await page.evaluate(()=>deskNode.comfyClass),'ZVUniversalMediaEvidenceDesk');
    assert.equal(await page.locator('.zf-med-head strong').textContent(),'ZV 通用素材取证台');checks++;
    assert.equal(await page.locator('.zf-med-lane:visible').count(),3);checks++;
    assert.equal(await page.locator('.zf-med-toggle-audio,[data-action="toggle-audio"]').count(),0);
    assert.equal(await page.locator('[data-action="split"]').textContent(),'分割');
    assert((await page.locator('[data-action="split"]').getAttribute('title')).includes('播放头'));
    assert(await page.locator('.zf-med-delete-video').isDisabled()&&await page.locator('.zf-med-delete-audio').isDisabled());checks++;
    const fixtures=await (await page.request.get(process.argv[2]+'/fixtures')).json();
    const chooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'＋ 导入素材'}).click();await (await chooser).setFiles(fixtures);
    await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===3);await synced();
    assert.equal(await page.locator('.zf-med-asset').count(),3);checks++;
    await clickAsset('generated-picture');await page.waitForFunction(()=>document.querySelector('.zf-med-screen img')?.naturalWidth===320);await addSelected();await clickAsset('generated-picture');await addSelected();checks++;
    let p=await state(),first=p.picture_track[0].item_id;
    await drag(page.locator(`[data-id="${first}"]`),140);p=await state();assert.equal(p.picture_track[1].item_id,first);assert.equal(p.label_map.find(r=>r.item_id===first).label,'Picture 2');checks++;
    await clickAsset('generated-video');await addSelected();p=await state();let vid=p.video_track[0].clip_id;
    assert.equal(p.audio_track[0].linked_video_clip_id,vid);checks++;
    await clickClip(vid);await page.waitForFunction(()=>document.querySelector('.zf-med-screen video')?.readyState>=2);
    // Exercise both UI surfaces using all valid combinations of the probe flags.
    let probeFlags;
    const normalizeRoute='**/zf-media-evidence/normalize';
    await page.route(normalizeRoute,async route=>{
        const flags=probeFlags,response=await route.fetch(),data=await response.json();
        Object.assign(data.project.assets.find(a=>a.kind==='video').probe,flags);
        await route.fulfill({response,json:data});
    });
    for(const [exact,vfr] of [[false,false],[false,true],[false,null],[true,true],[true,null],[true,false]]) {
        probeFlags={frame_count_exact:exact,vfr};
        await page.evaluate(flags=>{
            const project=deskNode.zfMediaDesk.getProject();
            Object.assign(project.assets.find(a=>a.kind==='video').probe,flags);
            deskNode.widgets[0].value=JSON.stringify(project);deskNode.zfMediaDesk.restore();
        },probeFlags);
        await synced();
        const expected=exact&&vfr===false?'源帧':'估算帧';
        const readout=await page.locator('.zf-med-readout').textContent(),facts=await page.locator('.zf-med-facts').textContent();
        assert.match(readout,new RegExp(`^${expected} \\d+ / 48 · 源 24 fps`));
        assert(facts.includes(`总帧 48（${expected}）`)&&facts.includes('源帧率 24 fps'));
        if(vfr===true)assert(readout.includes(' · VFR'));
        if(vfr===null)assert(readout.includes('帧率稳定性未确认'));
        checks++;
    }
    await page.unroute(normalizeRoute);
    const recoveryBefore=await state(),recoveryShape=value=>({assets:value.assets.map(a=>[a.asset_id,a.source_handle]),pictures:value.picture_track.map(a=>a.item_id),videos:value.video_track.map(a=>a.clip_id),audios:value.audio_track.map(a=>a.clip_id)});
    let normalizeCalls=0,releaseHeld,markHeld;
    const heldStarted=new Promise(resolve=>markHeld=resolve),heldGate=new Promise(resolve=>releaseHeld=resolve);
    await page.route(normalizeRoute,async route=>{
        const response=await route.fetch(),data=await response.json();normalizeCalls++;
        if(normalizeCalls===1){const index=data.project.assets.findIndex(a=>a.kind==='video');data.project.validation.errors.push({path:`/assets/${index}`,code:'source_unavailable',message:'素材登记文件不可见；云端存储可能未同步，请重新导入'});}
        if(normalizeCalls===3){markHeld();await heldGate;}
        await route.fulfill({response,json:data});
    });
    await page.getByRole('button',{name:'复测素材',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.zf-med-status').textContent.includes('云端存储可能未同步'));
    await page.evaluate(()=>{const player=document.querySelector('.zf-med-screen video');for(const type of ['loadedmetadata','loadeddata','canplay','seeked','waiting','canplay'])player?.dispatchEvent(new Event(type));});
    await page.waitForTimeout(250);assert.equal(normalizeCalls,1);
    await page.getByRole('button',{name:'复测素材',exact:true}).click();
    await page.waitForFunction(()=>!deskNode.zfMediaDesk.getProject().validation.errors.some(error=>error.code==='source_unavailable'));
    assert.equal(normalizeCalls,2);assert.deepEqual(recoveryShape(await state()),recoveryShape(recoveryBefore));checks++;

    await page.getByRole('button',{name:'复测素材',exact:true}).click();
    await heldStarted;
    await page.evaluate(()=>{const button=document.querySelector('[data-action="revalidate"]');button.click();button.click();});
    await page.waitForTimeout(100);assert.equal(normalizeCalls,3);
    await page.evaluate(()=>{const project=deskNode.zfMediaDesk.getProject();project.assets[0].name='stale-guard-name';deskNode.widgets[0].value=JSON.stringify(project);deskNode.zfMediaDesk.restore();});
    await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets[0].name==='stale-guard-name');
    for(let index=0;index<80&&normalizeCalls<4;index++)await page.waitForTimeout(25);
    assert.equal(normalizeCalls,4);releaseHeld();
    await page.waitForFunction(()=>!document.querySelector('[data-action="revalidate"]').disabled);
    assert.equal((await state()).assets[0].name,'stale-guard-name');checks++;
    await page.evaluate(project=>{deskNode.widgets[0].value=JSON.stringify(project);deskNode.zfMediaDesk.restore();},recoveryBefore);await synced();
    await page.unroute(normalizeRoute);
    const failedProxy='**/zf-media-evidence/preview?*variant=proxy';let failedProxyRequests=0;
    await page.route(failedProxy,route=>{failedProxyRequests++;return route.fulfill({status:503,contentType:'application/json',body:'{"ok":false}'});});
    await clickAsset('generated-picture');await clickAsset('generated-video');
    await page.waitForFunction(()=>document.querySelector('.zf-med-status').textContent.includes('预览解码失败'));
    await page.evaluate(()=>{const player=document.querySelector('.zf-med-screen video');for(const type of ['error','waiting','stalled','canplay'])player?.dispatchEvent(new Event(type));});await page.waitForTimeout(250);
    assert.equal(failedProxyRequests,1);assert(!(await state()).validation.errors.some(error=>error.code==='source_unavailable'));checks++;
    await page.unroute(failedProxy);await clickAsset('generated-picture');await clickAsset('generated-video');
    await page.waitForFunction(()=>document.querySelector('.zf-med-screen video')?.readyState>=2);
    await clickClip(vid);await page.waitForFunction(()=>document.querySelector('.zf-med-screen video')?.readyState>=2);
    await page.getByRole('button',{name:'播放时间线',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.zf-med-screen video')?.currentTime>.15);
    await page.evaluate(()=>{const video=document.querySelector('.zf-med-screen video');Object.defineProperty(video,'readyState',{configurable:true,get:()=>0});video.dispatchEvent(new Event('waiting'));});const frozen=await page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead);
    await page.waitForTimeout(180);assert(Math.abs(await page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead)-frozen)<.02);assert((await page.getByRole('button',{name:/加载中/}).textContent()).includes('加载中'));
    await page.evaluate(()=>{const video=document.querySelector('.zf-med-screen video');delete video.readyState;video.dispatchEvent(new Event('canplay'));});await page.waitForFunction(()=>document.querySelector('[data-action=play]').textContent==='暂停时间线');await page.waitForFunction(value=>deskNode.properties.zf_media_desk_view.playhead>value+.08,frozen);
    await page.evaluate(()=>{const button=document.querySelector('[data-action=play]');if(button.textContent!=='播放时间线')button.click();});await page.waitForFunction(()=>document.querySelector('[data-action=play]').textContent==='播放时间线');checks++;
    const farRuler=await page.locator('.zf-med-ruler').boundingBox();await page.mouse.click(farRuler.x+350,farRuler.y+32);
    await page.waitForSelector('.zf-med-black');assert.equal(await page.locator('.zf-med-screen video').count(),0);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead),10);checks++;
    await page.getByLabel('轨道起点 / 秒',{exact:true}).fill('1');await page.getByLabel('轨道起点 / 秒',{exact:true}).dispatchEvent('change');await synced();
    p=await state();assert.equal(p.audio_track[0].timeline_in_seconds,1);checks++;
    await drag(page.locator(`[data-id="${vid}"] .zf-med-handle.left`),12);
    p=await state();assert(p.video_track[0].source_in_seconds>0);assert.equal(p.audio_track[0].source_in_seconds,p.video_track[0].source_in_seconds);checks++;
    await drag(page.locator(`[data-id="${vid}"] .zf-med-handle.right`),-12);p=await state();assert(p.video_track[0].source_out_seconds<2);checks++;
    // Set a playhead inside the trimmed clip through the visible ruler.
    const c=p.video_track[0], mid=c.timeline_in_seconds+(c.source_out_seconds-c.source_in_seconds)/2;
    const ruler=await page.locator('.zf-med-ruler').boundingBox();await page.mouse.click(ruler.x+mid*35,ruler.y+32);
    await page.getByRole('button',{name:'分割',exact:true}).click();await synced();p=await state();assert.equal(p.video_track.length,2);assert.equal(p.audio_track.length,2);checks++;
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();assert.equal((await state()).video_track.length,1);
    await page.getByRole('button',{name:'重做',exact:true}).click();await synced();assert.equal((await state()).video_track.length,2);checks++;
    await page.getByRole('button',{name:'解绑音频',exact:true}).click();await synced();p=await state();const detached=p.audio_track.find(a=>!a.linked_video_clip_id);assert(detached);assert(p.label_map.find(r=>r.item_id===detached.clip_id).label.startsWith('Audio '));checks++;
    await clickClip(detached.clip_id);assert.equal(await page.locator('.zf-med-monitor-mode').textContent(),'时间线监看');
    await page.getByRole('button',{name:'重新绑定原视频',exact:true}).click();await synced();p=await state();assert(p.audio_track.find(a=>a.clip_id===detached.clip_id).linked_video_clip_id);checks++;
    await clickClip(detached.clip_id);const boundBefore=await state();
    assert(await page.locator('.zf-med-delete-audio').isDisabled()&&await page.locator('.zf-med-delete-video').isDisabled());
    assert(await page.locator('[data-action="context"]').isDisabled());
    assert((await page.locator('.zf-med-delete-audio').getAttribute('title')).includes('先解绑'));checks++;
    for(const key of ['Delete','Backspace']){await page.locator('.zf-med').evaluate(root=>root.focus());await page.keyboard.press(key);assert.deepEqual(await state(),boundBefore);assert((await page.locator('.zf-med-status').textContent()).includes('先解绑'));checks++;}
    await page.locator('.zf-med-delete-audio').evaluate(button=>button.dispatchEvent(new MouseEvent('click',{bubbles:true})));
    assert.deepEqual(await state(),boundBefore);checks++;
    await page.getByRole('button',{name:'解绑音频',exact:true}).click();await synced();const beforeAudioDelete=await state();
    assert(!await page.locator('.zf-med-delete-audio').isDisabled()&&await page.locator('.zf-med-delete-video').isDisabled());
    await page.locator('.zf-med-delete-audio').click();await synced();const afterAudioDelete=await state();
    assert(!afterAudioDelete.audio_track.some(a=>a.clip_id===detached.clip_id));
    assert.deepEqual(afterAudioDelete.video_track,beforeAudioDelete.video_track);assert.deepEqual(afterAudioDelete.assets,beforeAudioDelete.assets);checks++;
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();assert.deepEqual(await state(),beforeAudioDelete);
    await page.getByRole('button',{name:'重做',exact:true}).click();await synced();assert.deepEqual(await state(),afterAudioDelete);
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();checks++;
    await clickClip(detached.source_video_clip_id);const beforeVideoDelete=await state();
    assert(!await page.locator('.zf-med-delete-video').isDisabled()&&await page.locator('.zf-med-delete-audio').isDisabled());
    await page.locator('.zf-med-delete-video').click();await synced();p=await state();
    assert(!p.video_track.some(v=>v.clip_id===detached.source_video_clip_id)&&p.audio_track.some(a=>a.clip_id===detached.clip_id));assert.deepEqual(p.assets,beforeVideoDelete.assets);checks++;
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();assert.deepEqual(await state(),beforeVideoDelete);
    await clickClip(detached.clip_id);await page.getByRole('button',{name:'重新绑定原视频',exact:true}).click();await synced();checks++;
    p=await state();const boundVideo=p.video_track.find(v=>v.audio_link_id),beforeGroupDelete=p;
    await clickClip(boundVideo.clip_id);await page.locator('.zf-med-delete-video').click();await synced();p=await state();
    assert(!p.video_track.some(v=>v.clip_id===boundVideo.clip_id)&&!p.audio_track.some(a=>a.clip_id===boundVideo.audio_link_id));assert.deepEqual(p.assets,beforeGroupDelete.assets);checks++;
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();assert.deepEqual(await state(),beforeGroupDelete);checks++;
    await clickClip((await state()).picture_track[0].item_id);assert(await page.locator('.zf-med-delete-audio').isDisabled()&&await page.locator('.zf-med-delete-video').isDisabled());checks++;
    await clickAsset('generated-audio');await page.waitForSelector('.zf-med-screen canvas');await addSelected();checks++;
    // Reject a mismatched internal drop; the asset stays in the pool.
    const oldCount=(await state()).video_track.length;
    await page.evaluate(()=>{const p=deskNode.zfMediaDesk.getProject(),a=p.assets.find(a=>a.kind==='audio'),dt=new DataTransfer();dt.setData('application/x-zf-media',a.asset_id);document.querySelector('[data-track="video"]').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));});
    assert.equal((await state()).video_track.length,oldCount);assert((await page.locator('.zf-med-status').textContent()).includes('对应类型'));checks++;
    // External file drop imports a program-generated image without opening any existing app.
    const imageBytes=[...await readFile(fixtures[0])];
    await page.evaluate(bytes=>{const dt=new DataTransfer();dt.items.add(new File([new Uint8Array(bytes)],'generated-drop.png',{type:'image/png'}));document.querySelector('.zf-med-pool').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));},imageBytes);
    await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===4);await synced();checks++;
    // Resize beyond the H3 limit: state must remain 361 frames with a visible error.
    await page.getByLabel('结束 / 秒',{exact:true}).fill(String(361/24));await page.getByLabel('结束 / 秒',{exact:true}).dispatchEvent('change');await synced();
    p=await state();assert.equal(p.processing_window.frame_count,361);assert(await page.locator('.zf-med-window.incompatible').count());assert(!p.validation.errors.length);assert(!p.preset_compatibility.compatible);checks++;
    await drag(page.locator('.zf-med-window'),35);p=await state();assert.equal(p.processing_window.start_seconds,1);assert.equal(p.processing_window.frame_count,361);checks++;
    await page.getByLabel('结束 / 秒',{exact:true}).fill('11');await page.getByLabel('结束 / 秒',{exact:true}).dispatchEvent('change');await synced();
    await page.locator('.zf-med-zoom').fill('50');await page.locator('.zf-med-zoom').dispatchEvent('input');
    await page.evaluate(()=>saveWorkflow());const saved=await state();await page.reload();await page.waitForSelector('.zf-med');await synced();
    assert.deepEqual(await state(),saved);assert.equal(await page.locator('.zf-med-zoom').inputValue(),'50');checks++;
    // Correct track drop, movement and deletion round trip use only the visible editor.
    await page.evaluate(()=>{const p=deskNode.zfMediaDesk.getProject(),a=p.assets.find(a=>a.kind==='audio'),dt=new DataTransfer();dt.setData('application/x-zf-media',a.asset_id);const lane=document.querySelector('[data-track="audio"]'),r=lane.getBoundingClientRect();lane.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt,clientX:r.x+400}));});
    await synced();p=await state();const independent=p.audio_track.find(a=>a.timeline_in_seconds===8);assert(independent);checks++;
    await drag(page.locator(`[data-id="${independent.clip_id}"]`),100);p=await state();assert.equal(p.audio_track.find(a=>a.clip_id===independent.clip_id).timeline_in_seconds,10);checks++;
    await page.locator('[data-action="delete-audio"]').click();await synced();assert(!(await state()).audio_track.some(a=>a.clip_id===independent.clip_id));checks++;
    await clickAsset('generated-audio');
    await page.waitForFunction(()=>document.querySelector('.zf-med-screen canvas')&&document.querySelector('.zf-med-screen').children.length===1&&document.querySelector('.zf-med-readout').textContent.startsWith('音频'));
    await page.getByRole('button',{name:'播放素材',exact:true}).click();await page.waitForFunction(()=>parseFloat(document.querySelector('.zf-med-time').textContent)>.15);await page.getByRole('button',{name:'暂停素材',exact:true}).click();checks++;
    await page.getByLabel('源素材播放位置').fill('1');await page.getByLabel('源素材播放位置').dispatchEvent('input');await page.waitForFunction(()=>document.querySelector('.zf-med-time').textContent.startsWith('1.000'));checks++;
    const wBefore=(await state()).processing_window.end_seconds;
    await drag(page.locator('.zf-med-window .zf-med-handle.right'),50);assert.equal((await state()).processing_window.end_seconds,wBefore+1);checks++;
    await page.locator('.zf-med-zoom').fill('110');await page.locator('.zf-med-zoom').dispatchEvent('input');
    await completeVisuals();
    const metrics=await page.locator('.zf-med-scroll').evaluate(s=>({client:s.clientHeight,scroll:s.scrollHeight,overflow:getComputedStyle(s).overflowY,last:s.querySelector('[data-track="audio"]').getBoundingClientRect().bottom,bottom:s.getBoundingClientRect().bottom}));
    assert(metrics.scroll<=metrics.client&&metrics.overflow==='hidden'&&metrics.last<=metrics.bottom);checks++;
    assert.equal(await page.locator('.zf-med-clip.picture .zf-med-clip-thumb').count(),2);assert.equal(await page.locator('.zf-med-clip.video .zf-med-clip-thumb').count(),2);
    assert.equal(await page.locator('.zf-med-clip.audio .zf-med-clip-wave[data-wave-mode="peaks"]').count(),(await state()).audio_track.length);checks++;
    p=await state();for(const c of p.audio_track){const wave=page.locator(`[data-id="${c.clip_id}"] canvas`);assert.equal(Number(await wave.getAttribute('data-source-in')),c.source_in_seconds);assert.equal(Number(await wave.getAttribute('data-source-out')),c.source_out_seconds);}checks++;
    const requestSnapshot=[...visualRequests];
    for(const zoom of ['90','100','110']){await page.locator('.zf-med-zoom').fill(zoom);await page.locator('.zf-med-zoom').dispatchEvent('input');}
    await clickAsset('generated-picture');await clickAsset('generated-audio');await completeVisuals();assert.deepEqual([...visualRequests],requestSnapshot);checks++;
    assert(await page.locator('.zf-med img').evaluateAll(images=>images.every(img=>img.draggable===false)));checks++;
    const imageAsset=p.assets.find(a=>a.kind==='picture'),audioLane=page.locator('[data-track="audio"]'),pictureLane=page.locator('[data-track="picture"]');
    const beforeNative=await state();await startPoolDrag(imageAsset.asset_id,pictureLane,350);await page.waitForSelector('[data-track="picture"].drop-target');await page.mouse.up();await synced();
    assert.equal((await state()).picture_track.length,beforeNative.picture_track.length+1);assert.deepEqual(await page.evaluate(()=>lastMediaDragTypes),['application/x-zf-media']);checks++;
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();
    await startPoolDrag(imageAsset.asset_id,audioLane,450);await page.waitForSelector('[data-track="audio"].drop-reject');await page.mouse.up();assert.deepEqual(await state(),beforeNative);checks++;
    await startPoolDrag(imageAsset.asset_id,page.locator('#outside-canvas'),350);await page.mouse.up();
    assert.deepEqual(await page.evaluate(()=>({types:lastMediaDragTypes,drops:canvasDropLog,nodes:loadImageNodes})),{types:['application/x-zf-media'],drops:[],nodes:0});assert.deepEqual(await state(),beforeNative);assert.equal(await page.locator('.drop-target,.drop-reject').count(),0);checks++;
    // Pool keeps add-to-track; track selection hides the distant context action.
    await clickAsset('generated-video');
    assert.equal(await page.locator('[data-action="context"]').textContent(),'加入对应轨道（播放头处）');
    p=await state();vid=p.video_track[0].clip_id;await page.locator(`[data-id="${vid}"]`).click();
    assert.equal(await page.getByRole('button',{name:'删除此片段',exact:true}).count(),0);assert.equal(await page.locator('[data-action="context"]').isVisible(),false);assert.equal(await page.locator('.zf-med-tools [data-action="delete"]').count(),0);checks++;
    for(const name of ['轨道起点 / 秒','源入点 / 秒','源出点 / 秒','开始 / 秒','结束 / 秒']) {
        const field=page.getByLabel(name,{exact:true}),original=await field.inputValue();
        await page.locator('.zf-med').evaluate(root=>root.focus());await field.click({position:{x:12,y:12}});await page.keyboard.insertText('7');assert.equal(await field.inputValue(),'7');
        await field.fill('123');await field.click({position:{x:12,y:12}});await page.keyboard.insertText('4');assert.equal((await field.inputValue()).length,4);
        await field.fill(original);await field.dispatchEvent('change');await page.locator('.zf-med').evaluate(root=>root.focus());await synced();checks++;
    }
    assert.equal(await page.locator('.zf-med-inspect input[aria-label="开始 / 秒"],.zf-med-inspect input[aria-label="结束 / 秒"]').count(),0);
    await page.getByLabel('开始 / 秒',{exact:true}).fill('2.25');assert.equal(await page.locator('.zf-med-window-total').textContent(),'总时长 9.750 秒');
    await page.getByLabel('结束 / 秒',{exact:true}).fill('13.75');assert.equal(await page.locator('.zf-med-window-total').textContent(),'总时长 11.500 秒');
    await page.locator('.zf-med').evaluate(root=>root.focus());await synced();await assertWindowPanel();checks++;
    await drag(page.locator('.zf-med-window'),55);await assertWindowPanel();assert.equal((await state()).processing_window.start_seconds,2.75);checks++;
    // Bring the right window edge into the viewport before resizing it.
    await page.locator('.zf-med-zoom').fill('50');await page.locator('.zf-med-zoom').dispatchEvent('input');
    await drag(page.locator('.zf-med-window .zf-med-handle.right'),25);await assertWindowPanel();assert.equal((await state()).processing_window.end_seconds,14.75);checks++;
    await page.getByLabel('结束 / 秒',{exact:true}).fill(String(2.75+361/24));assert((await page.locator('.zf-med-window-state').textContent()).includes('预设不兼容'));assert.equal((await state()).processing_window.end_seconds,2.75+361/24);
    await page.getByLabel('结束 / 秒',{exact:true}).fill('14.75');await page.locator('.zf-med').evaluate(root=>root.focus());await synced();checks++;
    // Grab six pixels away from the visible yellow line, in front of the cyan window.
    await page.locator('.zf-med-snap').uncheck();
    p=await state();const clip=p.video_track[0];
    let r=await page.locator('.zf-med-ruler').boundingBox();const initialHead=clip.timeline_in_seconds+.1;await page.mouse.click(r.x+initialHead*50,r.y+32);await page.waitForFunction(()=>document.querySelector('.zf-med-screen video')?.readyState>=2);
    const head=await page.locator('.zf-med-playhead').boundingBox(),windowBefore=structuredClone(p.processing_window);assert.equal(head.width,16);
    assert(await page.evaluate(({x,y})=>document.elementFromPoint(x,y).classList.contains('zf-med-playhead'),{x:head.x+2,y:head.y+8}));
    await page.mouse.move(head.x+2,head.y+8);await page.mouse.down();await page.mouse.move(head.x+12,head.y+8,{steps:4});
    assert(Math.abs(await page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead)-(initialHead+.2))<.01);
    await page.waitForFunction(expected=>Math.abs(document.querySelector('.zf-med-screen video').currentTime-expected)<.03,clip.source_in_seconds+.3);
    await page.mouse.up();assert.deepEqual((await state()).processing_window,windowBefore);checks++;
    // Mimic ComfyUI's transformed DOM surface, including its drag coordinate conversion.
    await page.locator('#mount').evaluate(m=>{m.style.transform='scale(.75)';m.style.transformOrigin='top left';});
    r=await page.locator('.zf-med-ruler').boundingBox();await page.mouse.click(r.x+7*50*.75,r.y+30*.75);assert(Math.abs(await page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead)-7)<.01);
    assert.equal((await page.locator('.zf-med-playhead').boundingBox()).width,12);
    await page.locator('.zf-med-snap').uncheck();const videoBefore=(await state()).video_track.find(c=>c.clip_id===vid).timeline_in_seconds;
    await drag(page.locator(`[data-id="${vid}"]`),37.5);assert(Math.abs((await state()).video_track.find(c=>c.clip_id===vid).timeline_in_seconds-videoBefore-1)<.01);
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();await page.locator('.zf-med-snap').check();await page.locator('#mount').evaluate(m=>{m.style.transform='';});checks++;
    // Unloading is project-only, undoable, and never selects the unload button's asset.
    await clickAsset('generated-audio');const beforeUnload=await state(),videoAsset=beforeUnload.assets.find(a=>a.kind==='video'),audioName=await page.locator('.zf-med-preview-name').textContent();
    await page.evaluate(()=>{window.unloadDragStarts=0;document.addEventListener('dragstart',()=>window.unloadDragStarts++,{capture:true});});
    const unloadBox=await page.getByRole('button',{name:`卸载 ${videoAsset.name}`,exact:true}).boundingBox(),outsideBox=await page.locator('#outside-canvas').boundingBox();
    await page.mouse.move(unloadBox.x+10,unloadBox.y+10);await page.mouse.down();await page.mouse.move(outsideBox.x+100,outsideBox.y+30,{steps:12});await page.mouse.up();
    assert.equal(await page.evaluate(()=>unloadDragStarts),0);assert.deepEqual(await state(),beforeUnload);assert.equal(await page.locator('.zf-med-preview-name').textContent(),audioName);checks++;
    await page.getByRole('button',{name:`卸载 ${videoAsset.name}`,exact:true}).click();await synced();
    p=await state();assert(!p.assets.some(a=>a.asset_id===videoAsset.asset_id)&&!p.video_track.length&&!p.audio_track.some(c=>c.asset_id===videoAsset.asset_id));assert.equal(await page.locator('.zf-med-preview-name').textContent(),audioName);
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();assert.deepEqual(await state(),beforeUnload);checks++;
    await clickAsset('generated-video');await page.getByRole('button',{name:`卸载 ${videoAsset.name}`,exact:true}).click();await synced();
    assert.equal(await page.locator('.zf-med-preview-name').textContent(),'未选择素材');assert.equal(await page.locator('.zf-med-screen video').count(),0);assert.equal(await page.evaluate(()=>deskNode.properties.zf_media_desk_view.asset),null);
    const originalResponse=await page.request.get(process.argv[2]+`/zf-media-evidence/preview?source=${encodeURIComponent(videoAsset.source_handle)}&variant=original`);assert.equal(originalResponse.status(),200);
    await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();assert.deepEqual(await state(),beforeUnload);checks++;
    for(const key of ['Delete','Backspace']){p=await state();const clipId=p.video_track[0].clip_id;await clickClip(clipId);await page.locator('.zf-med').evaluate(root=>root.focus());await page.keyboard.press(key);await synced();assert.equal((await state()).video_track.length,p.video_track.length-1);await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();checks++;}
    // A failed waveform request is cached as a quiet center line; editing still works.
    let failedPeaks=0;const peakRoute='**/zf-media-evidence/preview?*variant=peaks';await page.route(peakRoute,route=>{failedPeaks++;return route.fulfill({status:503,json:{ok:false}});});
    const retryChooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'＋ 导入素材'}).click();await(await retryChooser).setFiles(fixtures[2]);
    await page.waitForFunction(n=>deskNode.zfMediaDesk.getProject().assets.length===n,beforeUnload.assets.length+1);await synced();
    const failedAsset=(await state()).assets.at(-1);await page.locator(`[data-asset-id="${failedAsset.asset_id}"]`).click();await addSelected();
    const failedClip=(await state()).audio_track.find(c=>c.asset_id===failedAsset.asset_id);assert.equal(await page.locator(`[data-id="${failedClip.clip_id}"] canvas`).getAttribute('data-wave-mode'),'fallback');
    await drag(page.locator(`[data-id="${failedClip.clip_id}"]`),100);assert.equal(failedPeaks,1);await page.unroute(peakRoute);await page.locator(`[data-asset-id="${failedAsset.asset_id}"] .zf-med-unload`).click();await synced();checks++;
    // Isolated valid media fixture; only setup/restore bypass the UI, all gestures use the mouse.
    const beforeSnap=await state(),beforeSnapProperties=await page.evaluate(()=>structuredClone(deskNode.properties));
    async function snapFixture(scale,{start=1,end=3,head=.25,snap=true}={}) {
        await page.evaluate(async ({scale,start,end,head,snap})=>{
            const edit=await import('/extensions/media_evidence_core.mjs'),asset=deskNode.zfMediaDesk.getProject().assets.find(a=>a.kind==='video');
            const p=edit.addAsset(edit.freshProject(),asset,0);
            p.processing_preset=(await import('/extensions/media_evidence_presets.mjs')).builtin('builtin.minimax-h3.single');
            p.processing_window={start_seconds:start,end_seconds:end,fps:24};
            deskNode.widgets[0].value=JSON.stringify(p);
            deskNode.properties.zf_media_desk_view={zoom:100,playhead:head,selected:p.video_track[0].clip_id,asset:asset.asset_id,snap,scroll:0};
            const mount=document.querySelector('#mount');mount.style.transform=`scale(${scale})`;mount.style.transformOrigin='top left';
            deskNode.zfMediaDesk.restore();
        },{scale,start,end,head,snap});
        await synced();await page.waitForFunction(()=>document.querySelector('.zf-med-screen video')?.readyState>=2);
        return page.locator('.zf-med-grid').evaluate(g=>100*g.getBoundingClientRect().width/g.offsetWidth);
    }
    const headTime=()=>page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead);
    async function dragHeadTo(time,pps,hold=false) {
        const h=await page.locator('.zf-med-playhead').boundingBox(),old=await headTime();
        await page.mouse.move(h.x+h.width/2,h.y+3);await page.mouse.down();
        await page.mouse.move(h.x+h.width/2+(time-old)*pps,h.y+3,{steps:8});
        if(!hold)await page.mouse.up();
    }
    for(const scale of [1,.5,1.25]) {
        let pps=await snapFixture(scale);assert(Math.abs(pps-100*scale)<.01);
        await dragHeadTo(1-6/pps,pps,true);assert.equal(await headTime(),1);
        await page.waitForFunction(()=>Math.abs(document.querySelector('.zf-med-screen video').currentTime-1)<.03);
        assert.match(await page.locator('.zf-med-readout').textContent(),/^源帧 25 \/ 48/);await page.mouse.up();checks++;
        pps=await snapFixture(scale);await dragHeadTo(3+6/pps,pps);assert.equal(await headTime(),3);checks++;
        pps=await snapFixture(scale);await dragHeadTo(1-8/pps,pps);assert(Math.abs(await headTime()-(1-8/pps))<1e-6);checks++;
        pps=await snapFixture(scale,{snap:false});await dragHeadTo(1-6/pps,pps);assert(Math.abs(await headTime()-(1-6/pps))<1e-6);checks++;
        pps=await snapFixture(scale,{start:2,end:4,head:1});
        await drag(page.locator('.zf-med-window .zf-med-handle.left'),-pps+6);assert.equal((await state()).processing_window.start_seconds,1);checks++;
        pps=await snapFixture(scale,{start:0,end:2,head:1.5});
        await drag(page.locator('.zf-med-window .zf-med-handle.right'),-.5*pps-6);assert.equal((await state()).processing_window.end_seconds,1.5);checks++;
        pps=await snapFixture(scale,{start:2,end:4,head:1});
        await drag(page.locator('.zf-med-window'),-pps+6);let w=(await state()).processing_window;assert.equal(w.start_seconds,1);assert.equal(w.end_seconds,3);checks++;
        pps=await snapFixture(scale,{start:2,end:4,head:6});
        await drag(page.locator('.zf-med-window'),2*pps-6);w=(await state()).processing_window;assert.equal(w.start_seconds,4);assert.equal(w.end_seconds,6);checks++;
        pps=await snapFixture(scale,{start:2,end:4,head:1});
        await drag(page.locator('.zf-med-window .zf-med-handle.left'),-pps+8);w=(await state()).processing_window;assert.notEqual(w.start_seconds,1);assert.equal(w.start_seconds*24,Math.round(w.start_seconds*24));checks++;
        pps=await snapFixture(scale,{start:2,end:4,head:1,snap:false});
        await drag(page.locator('.zf-med-window .zf-med-handle.left'),-pps+6);w=(await state()).processing_window;assert.notEqual(w.start_seconds,1);assert.equal(w.start_seconds*24,Math.round(w.start_seconds*24));checks++;
        pps=await snapFixture(scale,{start:2,end:4,head:6});
        await drag(page.locator('.zf-med-window'),-3*pps);w=(await state()).processing_window;assert.equal(w.start_seconds,0);assert.equal(w.end_seconds,2);checks++;
        pps=await snapFixture(scale,{start:4,end:6});await dragHeadTo(2-6/pps,pps);assert.equal(await headTime(),2);checks++;
    }
    await page.evaluate(({project,properties})=>{deskNode.widgets[0].value=JSON.stringify(project);deskNode.properties=properties;document.querySelector('#mount').style.transform='';deskNode.zfMediaDesk.restore();},{project:beforeSnap,properties:beforeSnapProperties});await synced();
    await page.locator('.zf-med-zoom').fill('140');await page.locator('.zf-med-zoom').dispatchEvent('input');
    await page.getByLabel('开始 / 秒',{exact:true}).fill('0');await page.getByLabel('结束 / 秒',{exact:true}).fill('7.5');await page.locator('.zf-med').evaluate(root=>root.focus());await synced();
    const finalClip=(await state()).video_track[0],finalRuler=await page.locator('.zf-med-ruler').boundingBox();await page.mouse.click(finalRuler.x+(finalClip.timeline_in_seconds+.1)*140,finalRuler.y+32);await completeVisuals();await page.waitForFunction(()=>document.querySelector('.zf-med-screen video')?.readyState>=2);
    assert.deepEqual(errors,[]);
    if(!process.argv.includes('--no-screenshot')) {
        const output=process.argv.find(arg=>arg.startsWith('--evidence-dir='))?.slice('--evidence-dir='.length);
        if(output){await mkdir(output,{recursive:true});await page.locator('.zf-med').screenshot({path:output+'/MEDIA_UI.png'});}
        else{await mkdir(new URL('../docs/evidence/',import.meta.url),{recursive:true});await page.locator('.zf-med').screenshot({path:new URL('../docs/evidence/zf-media-desk-v1.png',import.meta.url).pathname.replace(/^\/(\w:)/,'$1')});}
    }
    console.log(`UI_SMOKE_OK ${checks} isolated browser interaction checks; no page exceptions`);
} catch(error) {
    console.error(JSON.stringify({checks,errors,ui:await page.evaluate(()=>({status:document.querySelector('.zf-med-status')?.textContent,assets:window.deskNode?.zfMediaDesk?.getProject?.().assets.map(a=>a.name),busy:document.querySelector('.zf-med')?.getAttribute('aria-busy')}))}));
    throw error;
} finally {await browser.close();}
