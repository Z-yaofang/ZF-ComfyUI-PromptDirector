// Real decoding against the isolated media_evidence_smoke.py --serve harness.
// node tests/media_evidence_monitor_media_smoke.mjs URL PLAYWRIGHT_PACKAGE CHROMIUM_EXECUTABLE FIXTURE_DIR [SCREENSHOT]
// FIXTURE_DIR contains an 8-second silent.mp4, voiced.mp4 and music.mp3 (generated test media only).
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
const {chromium}=createRequire(import.meta.url)(process.argv[3]||'playwright');
const browser=await chromium.launch({headless:true,executablePath:process.argv[4]});
const page=await browser.newPage({viewport:{width:1240,height:1060}}),errors=[];
page.on('pageerror',error=>errors.push(error.message));
await page.addInitScript(()=>{
    window.realPlayers=[];const create=document.createElement.bind(document);
    document.createElement=function(...args){const result=create(...args);if(result instanceof HTMLMediaElement)realPlayers.push(result);return result;};
});
const players=()=>page.evaluate(()=>realPlayers.filter(p=>p.getAttribute('src')).map(p=>({clip:p.dataset.timelineClip||null,tag:p.tagName,time:p.currentTime,paused:p.paused,muted:p.muted,volume:p.volume,ready:p.readyState})));
const sounding=async()=> (await players()).filter(p=>p.tag==='AUDIO'&&!p.paused&&!p.muted).map(p=>p.clip).sort();
const restore=async(head=2)=>{
    await page.evaluate(head=>{deskNode.widgets[0].value=JSON.stringify(realFixture);deskNode.properties.zf_media_desk_view={zoom:60,playhead:head,selected:'voiced-clip',asset:realFixture.assets[1].asset_id,snap:false,monitor_mode:'timeline',scroll:0};deskNode.zfMediaDesk.restore();},head);
    await page.waitForFunction(()=>!document.querySelector('.zf-med-grid').textContent.includes('编号同步中')&&realPlayers.filter(p=>p.getAttribute('src')).every(p=>p.readyState>=2));
};
let checks=0;
try {
    await page.goto(process.argv[2]);await page.waitForSelector('.zf-med');
    const assets=[];
    for(const name of ['silent.mp4','voiced.mp4','music.mp3']){
        const response=await page.request.post(`${process.argv[2]}/zf-media-evidence/upload`,{multipart:{file:{name,mimeType:name.endsWith('.mp3')?'audio/mpeg':'video/mp4',buffer:await readFile(join(process.argv[5],name))}}});
        const data=await response.json();assert(data.ok,JSON.stringify(data));assets.push(data.asset);
    }
    assert.equal(assets[0].probe.has_audio,false);assert.equal(assets[1].probe.has_audio,true);checks++;
    await page.evaluate(async assets=>{
        const edit=await import('/extensions/media_evidence_core.mjs');let p=edit.freshProject();
        p=edit.addAsset(p,assets[0],0,()=> 'silent-clip');p=edit.editCut(p,'silent-clip',{source_out_seconds:4});
        const ids=['voiced-clip','original'];p=edit.addAsset(p,assets[1],4,()=>ids.shift());p=edit.editCut(p,'voiced-clip',{source_out_seconds:4});
        p=edit.addAsset(p,assets[2],1,()=> 'mp3');p=edit.editCut(p,'mp3',{source_in_seconds:1,source_out_seconds:7});
        p.processing_window={start_seconds:0,end_seconds:2,fps:24};window.realFixture=p;
    },assets);
    await restore();let active=await players();assert(active.every(p=>p.paused));assert(Math.abs(active.find(p=>p.clip==='mp3').time-2)<.03);checks++;
    await page.getByRole('button',{name:'播放时间线',exact:true}).click();
    await page.waitForFunction(()=>realPlayers.some(p=>p.dataset.timelineClip==='mp3'&&p.getAttribute('src')&&!p.paused&&p.currentTime>2.15));
    assert.deepEqual(await sounding(),['mp3']);assert((await players()).find(p=>p.tag==='VIDEO').muted);checks++;
    await page.waitForFunction(()=>deskNode.properties.zf_media_desk_view.playhead>4.15&&realPlayers.some(p=>p.dataset.timelineClip==='original'&&p.getAttribute('src')&&!p.paused&&p.currentTime>.1));
    assert.deepEqual(await sounding(),['mp3','original']);assert(!(await players()).some(p=>p.clip==='silent-clip'));checks++;
    await page.getByRole('button',{name:'暂停时间线',exact:true}).click();const paused=await page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead);
    await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead),paused);assert((await players()).every(p=>p.paused));checks++;
    await page.getByLabel('工程播放位置',{exact:true}).fill('5');
    await page.waitForFunction(()=>realPlayers.some(p=>p.dataset.timelineClip==='original'&&p.getAttribute('src')&&p.readyState>=2&&Math.abs(p.currentTime-1)<.03));
    active=await players();assert(Math.abs(active.find(p=>p.clip==='mp3').time-5)<.03);assert(active.every(p=>p.paused));checks++;
    await page.getByRole('button',{name:'播放时间线',exact:true}).click();
    await page.waitForFunction(()=>realPlayers.filter(p=>p.getAttribute('src')&&p.tagName==='AUDIO').every(p=>!p.paused&&p.currentTime>1.1));
    assert.deepEqual(await sounding(),['mp3','original']);assert((await players()).filter(p=>p.tag==='AUDIO').every(p=>p.volume===.4));checks++;
    if(process.argv[6])await page.locator('.zf-med').screenshot({path:process.argv[6]});
    await page.locator('[data-id="voiced-clip"]').click();
    await page.getByRole('button',{name:'解绑音频',exact:true}).click();
    await page.locator('[data-id="original"]').click();
    await page.getByRole('button',{name:'开 / 关音频',exact:true}).click();
    await page.getByRole('button',{name:'播放时间线',exact:true}).click();
    await page.waitForFunction(()=>realPlayers.some(p=>p.dataset.timelineClip==='mp3'&&p.getAttribute('src')&&!p.paused&&p.currentTime>5.2));
    assert.deepEqual(await sounding(),['mp3']);checks++;
    await restore(6.8);await page.getByRole('button',{name:'播放时间线',exact:true}).click();
    await page.waitForFunction(()=>deskNode.properties.zf_media_desk_view.playhead>7.05);assert.deepEqual(await sounding(),['original']);checks++;
    await page.waitForFunction(()=>deskNode.properties.zf_media_desk_view.playhead===8);assert.deepEqual(await players(),[]);assert.equal(await page.locator('.zf-med-black').textContent(),'无画面');checks++;
    await restore(2);await page.getByRole('button',{name:'播放时间线',exact:true}).click();
    await page.locator(`[data-asset-id="${assets[1].asset_id}"]`).click();await page.getByRole('button',{name:'播放素材',exact:true}).click();
    await page.waitForFunction(()=>realPlayers.some(p=>p.getAttribute('src')&&!p.dataset.timelineClip&&p.tagName==='AUDIO'&&!p.paused&&p.currentTime>.1));
    active=await players();assert(active.every(p=>p.clip===null));assert.equal(active.filter(p=>!p.paused).length,2);checks++;
    await page.evaluate(()=>deskNode.onRemoved());assert.deepEqual(await players(),[]);assert(await page.evaluate(()=>realPlayers.every(p=>p.paused)));checks++;
    assert.deepEqual(errors,[]);console.log(`MONITOR_MEDIA_OK ${checks} real decoding/playback checks; no page exceptions`);
} finally {await browser.close();}
