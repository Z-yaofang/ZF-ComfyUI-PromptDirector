// Isolated browser: real desk/core/CSS, deterministic media clocks and play/pause promises.
// node tests/media_evidence_monitor_smoke.mjs PLAYWRIGHT_PACKAGE CHROMIUM_EXECUTABLE [SCREENSHOT]
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
const {chromium}=createRequire(import.meta.url)(process.argv[2]||'playwright');
const files=Object.fromEntries(await Promise.all(['media_evidence_desk.js','media_evidence_core.mjs','media_evidence_presets.mjs','media_evidence_outlets.mjs','media_processing_presets.json','media_evidence_desk.css','dom_widget_layout.mjs'].map(async name=>[name,await readFile(new URL(`../web/${name}`,import.meta.url),'utf8')])));
const browser=await chromium.launch({headless:true,executablePath:process.argv[3]});
const page=await browser.newPage({viewport:{width:1240,height:1060}}),errors=[];
page.on('pageerror',error=>errors.push(error.message));
await page.addInitScript(()=>{
    window.testClock=10000;window.testMedia=[];window.failNext=false;window.deferNext=false;window.holdMetadata=false;
    performance.now=()=>testClock;
    const states=new WeakMap(),proto=HTMLMediaElement.prototype;
    const state=player=>{if(!states.has(player)){const s={player,src:'',time:0,base:testClock,paused:true,ready:1,seeks:0,plays:0,pauses:0,loads:0};states.set(player,s);testMedia.push(s);}return states.get(player);};
    const time=s=>s.time+(s.paused?0:(testClock-s.base)/1000);
    Object.defineProperties(proto,{
        src:{get(){return state(this).src;},set(value){const s=state(this);s.src=value;s.ready=holdMetadata?0:1;if(s.ready)queueMicrotask(()=>{this.dispatchEvent(new Event('loadedmetadata'));this.dispatchEvent(new Event('loadeddata'));});}},
        currentTime:{get(){return time(state(this));},set(value){const s=state(this);s.time=value;s.base=testClock;s.seeks++;queueMicrotask(()=>this.dispatchEvent(new Event('seeked')));}},
        readyState:{get(){return state(this).ready;}},paused:{get(){return state(this).paused;}},seeking:{get(){return false;}},
    });
    proto.play=function(){const s=state(this);s.plays++;if(failNext){failNext=false;return Promise.reject(new DOMException('gesture required','NotAllowedError'));}s.base=testClock;s.paused=false;if(deferNext){deferNext=false;return new Promise((resolve,reject)=>window.finishPlay={resolve:()=>{s.paused=false;resolve();},reject});}return Promise.resolve();};
    proto.pause=function(){const s=state(this);s.time=time(s);s.base=testClock;s.paused=true;s.pauses++;queueMicrotask(()=>this.dispatchEvent(new Event('pause')));};
    proto.load=function(){state(this).loads++;};
    const remove=proto.removeAttribute;proto.removeAttribute=function(name){if(name==='src')state(this).src='';return remove.call(this,name);};
    window.mediaSnapshot=()=>testMedia.map(s=>({clip:s.player.dataset.timelineClip||null,tag:s.player.tagName,src:s.src,time:time(s),paused:s.paused,muted:s.player.muted,volume:s.player.volume,seeks:s.seeks,plays:s.plays,loads:s.loads}));
});
const html=`<!doctype html><meta charset="utf-8"><style>body{margin:20px;background:#10151d}#mount{width:1180px;height:1000px}</style><div id="mount"></div><script type="module">
import {attachMediaDesk} from '/extensions/media_evidence_desk.js';import {freshProject} from '/extensions/media_evidence_core.mjs';
window.deskNode={widgets:[{name:'project_data',value:JSON.stringify(freshProject())}],properties:{},size:[1180,1000],setDirtyCanvas(){},setSize(){},addDOMWidget(n,t,root){document.querySelector('#mount').append(root);return {};}};attachMediaDesk(deskNode);
</script>`;
await page.route('**/*',route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    if(path.endsWith('/presets'))return route.fulfill({json:{ok:true,builtins:JSON.parse(files['media_processing_presets.json']),users:[]}});
    if(path.endsWith('/normalize')){
        const p=route.request().postDataJSON();
        p.label_map=['picture','video','audio'].flatMap(track=>p[`${track}_track`].map((c,i)=>({item_id:c.clip_id||c.item_id,label:`${track} ${i+1}`})));
        p.validation={errors:[],warnings:[]};return route.fulfill({json:{ok:true,project:p}});
    }
    if(path.endsWith('/preview'))return url.searchParams.get('variant')==='peaks'?route.fulfill({json:{peaks:[.1,.4,.8,.3]}}):route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="#295779"/></svg>'});
    const name=path.split('/').at(-1),body=path==='/'?html:name==='app.js'?'export const app={registerExtension(){}};':name==='api.js'?'export const api={apiURL:p=>p,fetchApi:(p,o)=>fetch(p,o)};':files[name];
    return body?route.fulfill({contentType:path==='/'?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.json')?'application/json':'application/javascript',body}):route.abort();
});
const asset=(id,kind,has_audio=true)=>({asset_id:id,source_handle:id,name:`${id}.${kind==='audio'?'mp3':'mp4'}`,kind,probe:{duration_seconds:60,has_audio,width:kind==='video'?320:null,height:kind==='video'?180:null,fps:24,frame_count:1440,frame_count_exact:true,vfr:false,size_bytes:1000}});
const v=(id,asset_id,at,start,end,audio=null)=>({clip_id:id,asset_id,timeline_in_seconds:at,source_in_seconds:start,source_out_seconds:end,source_audio_enabled:!!audio,audio_link_id:audio});
const a=(id,asset_id,at,start,end,video=null)=>({...v(id,asset_id,at,start,end),enabled:true,origin:video?'video_source':'standalone',linked_video_clip_id:video,source_video_clip_id:video});
const fixture=()=>({schema_version:1,project_clock:{fps:24},assets:[asset('silent','video',false),asset('voiced','video'),asset('music','audio')],picture_track:[],video_track:[v('v1','silent',0,3,7),v('v2','voiced',4,10,14,'original')],audio_track:[a('mp3','music',1,7,13),a('original','voiced',4,10,14,'v2')],processing_window:{start_seconds:0,end_seconds:2,fps:24}});
const pictureFixture=()=>{
    const p=fixture();
    for(let i=1;i<=3;i++) {
        p.assets.push({asset_id:`image${i}`,source_handle:`image${i}`,name:`image${i}.png`,kind:'picture',probe:{width:160,height:90,duration_seconds:null,has_audio:false,size_bytes:1000}});
        p.picture_track.push({item_id:`picture${i}`,asset_id:`image${i}`,order:i});
    }
    return p;
};
const reset=async(p=fixture(),head=2,selected='v1',mode='timeline')=>{
    await page.evaluate(({p,head,selected,mode})=>{deskNode.widgets[0].value=JSON.stringify(p);deskNode.properties.zf_media_desk_view={zoom:60,playhead:head,selected,asset:p.video_track.find(c=>c.clip_id===selected)?.asset_id||'silent',snap:false,scroll:0,monitor_mode:mode};deskNode.zfMediaDesk.restore();},{p,head,selected,mode});
    await page.waitForFunction(()=>!document.querySelector('.zf-med-grid').textContent.includes('编号同步中'),{},{polling:20});
};
const snapshot=()=>page.evaluate(()=>mediaSnapshot());
const live=async()=> (await snapshot()).filter(s=>s.src&&s.clip);
const sounding=async()=> (await live()).filter(s=>s.tag==='AUDIO'&&!s.paused&&!s.muted).map(s=>s.clip).sort();
const head=()=>page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead);
const step=async seconds=>{await page.evaluate(seconds=>testClock+=seconds*1000,seconds);await page.waitForTimeout(40);};
const play=()=>page.getByRole('button',{name:'播放时间线',exact:true}).click();
const seek=async seconds=>{await page.getByLabel('工程播放位置',{exact:true}).fill(String(seconds));};
const headSnapshot=()=>page.evaluate(()=>{const slider=document.querySelector('.zf-med-playhead');return {value:deskNode.properties.zf_media_desk_view.playhead,left:slider.style.left,aria:slider.getAttribute('aria-valuenow')};});
const pictureOrder=()=>page.evaluate(()=>deskNode.zfMediaDesk.getProject().picture_track.map(c=>c.item_id));
const assertPicturePreview=async(before,id='picture1',name='image1.png')=>{
    const view=await page.evaluate(()=>deskNode.properties.zf_media_desk_view);
    assert.equal(view.monitor_mode,'source','picture gestures must keep source preview');
    assert.equal(view.selected,id);assert.deepEqual(await headSnapshot(),before,'picture gestures must not move the yellow playhead');
    assert.equal(await page.locator('.zf-med-monitor-mode').textContent(),'素材预览');
    assert.equal(await page.locator('.zf-med-preview-name').textContent(),name);
    assert.equal(await page.locator('.zf-med-inspect > strong').first().textContent(),name);
    assert.equal(await page.locator('.zf-med-clip.picture.selected').getAttribute('data-id'),id);
    await page.waitForFunction(()=>{const img=document.querySelector('.zf-med-screen img');return img?.complete&&img.naturalWidth===160;});
    assert.equal(await page.locator('.zf-med-screen img').getAttribute('alt'),name);
};
let checks=0;
const check=label=>{checks++;console.log(`OK ${label}`);};
try {
    await page.goto('https://monitor.test/');await page.waitForSelector('.zf-med');await reset();
    const frameInput=page.getByRole('spinbutton',{name:'播放头工程帧',exact:true}),locate=page.getByRole('button',{name:'定位',exact:true});
    const projectBefore=await page.evaluate(()=>deskNode.zfMediaDesk.getProject());
    assert.equal(await frameInput.inputValue(),'48');
    await page.locator('.zf-med-snap').check();await frameInput.fill('95');assert.equal(await head(),2);await frameInput.press('Enter');
    assert.equal(await head(),95/24);assert.equal(await frameInput.inputValue(),'95');assert.equal((await live()).find(s=>s.clip==='v1').time,3+95/24);check('frame entry confirms on Enter and bypasses nearby 4-second snapping');
    await frameInput.fill('144');await locate.click();assert.equal(await head(),6);assert.equal((await live()).find(s=>s.clip==='v2').time,12);assert((await live()).every(s=>s.paused));
    assert.deepEqual(await page.evaluate(()=>deskNode.zfMediaDesk.getProject()),projectBefore);assert(await page.getByRole('button',{name:'撤销',exact:true}).isDisabled());check('locate button seeks video/audio without editing clips or undo history');
    for(const value of ['', '-1', '1.5', '999999999999']){
        await frameInput.fill(value);await frameInput.press('Enter');assert.equal(await head(),6);assert.equal(await frameInput.evaluate(input=>input.checkValidity()),false);
    }
    await frameInput.press('Escape');assert.equal(await frameInput.inputValue(),'144');assert.equal(await frameInput.evaluate(input=>input.checkValidity()),true);check('invalid frame numbers leave playhead untouched; Escape restores the displayed frame');
    await play();await frameInput.fill('120');await step(.2);assert.equal(await frameInput.inputValue(),'120');await frameInput.press('Enter');assert.equal(await head(),5);assert.deepEqual(await sounding(),[]);check('playback cannot overwrite a frame being typed; confirming pauses and seeks');
    await frameInput.fill('7200');await locate.click();assert.equal(await head(),300);
    assert(await page.evaluate(()=>{const h=document.querySelector('.zf-med-playhead').getBoundingClientRect(),s=document.querySelector('.zf-med-scroll').getBoundingClientRect();return h.x>=s.x&&h.right<=s.right;}));check('distant frame expands and scrolls the timeline to keep the yellow handle visible');
    const fpsProject=fixture();fpsProject.project_clock.fps=29.97;await reset(fpsProject,1);
    await frameInput.fill('185');await frameInput.press('Enter');assert.equal(await head(),185/29.97);assert.equal(await frameInput.inputValue(),'185');check('frame-to-seconds mapping uses the project clock, including fractional fps');
    await reset(fixture(),6,'v1');const fixedHead=await headSnapshot();
    await page.locator('[data-id="v2"]').click({position:{x:40,y:30}});assert.deepEqual(await headSnapshot(),fixedHead);assert.equal(await page.locator('.zf-med-clip.video.selected').getAttribute('data-id'),'v2');
    await page.locator('[data-id="mp3"]').click({position:{x:40,y:30}});assert.deepEqual(await headSnapshot(),fixedHead);
    await page.locator('.zf-med-lane[data-track="video"]').click({position:{x:700,y:60}});assert.deepEqual(await headSnapshot(),fixedHead);check('video, audio and empty-lane clicks cannot displace an already positioned playhead');
    await page.locator('[data-id="v1"]').click();await page.getByRole('button',{name:'分割',exact:true}).click();assert.match(await page.locator('.zf-med-status').textContent(),/黄线不在所选片段内部/);
    assert.equal((await page.evaluate(()=>deskNode.zfMediaDesk.getProject())).video_track.length,2);check('splitting the wrong selected clip reports why instead of silently doing nothing');
    await page.locator('[data-id="v2"]').click({position:{x:40,y:30}});await page.getByRole('button',{name:'分割',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')==='false');
    const splitProject=await page.evaluate(()=>deskNode.zfMediaDesk.getProject());assert.deepEqual(errors,[]);assert.equal(splitProject.video_track.length,3);
    assert.equal(splitProject.video_track[1].source_out_seconds,12);assert.equal(splitProject.video_track[2].source_in_seconds,12);assert.equal(splitProject.video_track[2].timeline_in_seconds,6);
    assert.equal(splitProject.audio_track.filter(s=>s.origin==='video_source').length,2);assert.equal(await head(),6);check('locate, select, split preserves the chosen cut and splits the linked original audio');
    await reset(fixture(),3.5);assert.equal(await frameInput.inputValue(),'84');
    assert.equal(await page.evaluate(()=>{const h=document.querySelector('.zf-med-playhead').getBoundingClientRect();return document.elementFromPoint(h.x+8,h.y+140)?.classList.contains('zf-med-playhead');}),false);
    const handleBox=await page.locator('.zf-med-playhead').boundingBox();
    await page.mouse.move(handleBox.x+8,handleBox.y+6);await page.mouse.down();await page.mouse.move(handleBox.x+38,handleBox.y+6,{steps:5});await page.mouse.up();
    assert.equal(await head(),4);assert.equal(await frameInput.inputValue(),'96');check('only the top triangle catches playhead dragging; the vertical line passes clicks through');
    await reset();
    assert.equal(await page.locator('.zf-med-monitor-mode').textContent(),'时间线监看');
    let records=await live();assert.equal(records.find(s=>s.clip==='v1').time,5);assert.equal(records.find(s=>s.clip==='mp3').time,8);assert(records.every(s=>s.paused));check('seek maps both trimmed sources without playback');
    await play();assert.deepEqual(await sounding(),['mp3']);assert((await live()).find(s=>s.clip==='v1').muted);check('silent video plus independent MP3');
    const rangeBefore=(await page.evaluate(()=>deskNode.zfMediaDesk.getProject())).processing_window;
    await page.getByLabel('当前处理预设',{exact:true}).selectOption('builtin.generic@1');await page.getByLabel('当前处理预设',{exact:true}).press('Space');await page.getByLabel('当前处理预设',{exact:true}).press('Escape');assert.deepEqual(await sounding(),['mp3']);assert.deepEqual((await page.evaluate(()=>deskNode.zfMediaDesk.getProject())).processing_window,rangeBefore);check('preset selection and its keyboard controls preserve timeline playback and processing range');
    const seeks=(await live()).map(s=>s.seeks);await step(.05);assert.deepEqual((await live()).map(s=>s.seeks),seeks);assert.equal(await head(),2.05);check('steady master clock does not seek every frame');
    await page.evaluate(()=>{const s=testMedia.findLast(s=>s.player.dataset.timelineClip==='mp3'&&s.src);s.time-=.5;});await step(.05);
    assert(Math.abs((await live()).find(s=>s.clip==='mp3').time-8.1)<1e-6);check('large audio drift is corrected');
    await step(2);assert.equal(await head(),4.1);assert.deepEqual(await sounding(),['mp3','original']);records=await live();assert(!records.some(s=>s.clip==='v1'));assert(records.find(s=>s.clip==='v2').muted);assert(records.filter(s=>s.tag==='AUDIO').every(s=>s.volume===.4));check('cross video boundary mixes original and MP3 with headroom');
    await step(3);assert.deepEqual(await sounding(),['original']);assert(!(await live()).some(s=>s.clip==='mp3'));check('audio out point releases MP3');
    await step(1);assert.equal(await head(),8);assert.deepEqual(await live(),[]);assert.equal(await page.locator('.zf-med-black').textContent(),'无画面');check('project end outside H3 clears picture and audio');
    await reset(fixture(),5,'v2');await play();await page.getByRole('button',{name:'解绑音频',exact:true}).click();assert.deepEqual(await sounding(),['mp3','original']);
    const unlinked=await page.evaluate(()=>deskNode.zfMediaDesk.getProject());assert.equal(unlinked.video_track.find(v=>v.clip_id==='v2').audio_link_id,null);assert.equal(unlinked.audio_track.find(a=>a.clip_id==='original').linked_video_clip_id,null);check('unlink preserves the sounding original as independent audio');
    await reset(fixture(),5,'mp3');await play();await page.getByRole('button',{name:'开 / 关音频',exact:true}).click();assert.deepEqual(await sounding(),['original']);check('independent sound switch is isolated');
    await page.getByRole('button',{name:'暂停时间线',exact:true}).click();const pausedHead=await head();await step(2);assert.equal(await head(),pausedHead);assert.deepEqual(await sounding(),[]);
    await play();await step(.25);assert.equal(await head(),pausedHead+.25);check('pause holds position and resume uses it');
    await seek(6);assert.deepEqual(await sounding(),[]);assert((await live()).every(s=>s.paused));assert.equal((await live()).find(s=>s.clip==='original').time,12);check('scrubbing stops playback and seeks exact source');
    await reset(fixture(),5,'v2');await play();await page.locator('[data-action="delete-video"]').click();assert.deepEqual(await sounding(),['mp3']);assert.equal(await page.locator('.zf-med-black').textContent(),'无画面');check('delete bound video releases original only');
    await reset(fixture(),5,'v2');await play();await page.getByRole('button',{name:'卸载 music.mp3',exact:true}).click();assert.deepEqual(await sounding(),['original']);check('unload independent asset releases its player');
    const old=(await snapshot()).filter(s=>s.src).length;assert(old>0);await reset();assert.deepEqual(await sounding(),[]);assert((await snapshot()).filter(s=>!s.src).every(s=>s.paused&&s.loads>0));check('restore releases old players even with reused clip IDs');
    await play();await page.locator('[data-asset-id="voiced"]').click();assert.equal(await page.locator('.zf-med-monitor-mode').textContent(),'素材预览');assert.deepEqual(await live(),[]);
    const sourceHead=await head();await page.getByRole('button',{name:'播放素材',exact:true}).click();await step(1);
    records=(await snapshot()).filter(s=>s.src);assert.equal(records.filter(s=>!s.paused).length,2);assert(records.find(s=>s.tag==='VIDEO').muted);assert.equal(await head(),sourceHead);check('source preview has isolated sound and never drives project clock');
    await page.locator('.zf-med-ruler').click({position:{x:3*60,y:30}});assert.equal(await page.locator('.zf-med-monitor-mode').textContent(),'时间线监看');assert((await snapshot()).every(s=>s.paused));check('ruler changes to timeline and stops source sound');
    const selectionHead=await headSnapshot();await page.locator('[data-id="v2"]').click();assert.equal(await page.locator('.zf-med-monitor-mode').textContent(),'时间线监看');assert.deepEqual(await headSnapshot(),selectionHead);assert((await live()).some(s=>s.clip==='v1'));check('clip selection keeps the timeline preview at the fixed playhead, not the clicked clip');
    await reset(pictureFixture(),2.375);const pictureHead=await headSnapshot();
    await page.locator('[data-id="picture1"]').click({position:{x:30,y:30}});await assertPicturePreview(pictureHead);assert.deepEqual(await pictureOrder(),['picture1','picture2','picture3']);check('picture card click previews the selected image and inspector without moving a nonzero playhead');
    const pictureBox=await page.locator('[data-id="picture1"]').boundingBox();
    await page.mouse.move(pictureBox.x+30,pictureBox.y+30);await page.mouse.down();await page.mouse.move(pictureBox.x+290,pictureBox.y+30,{steps:8});
    await assertPicturePreview(pictureHead);assert.deepEqual(await pictureOrder(),['picture2','picture3','picture1']);
    await page.mouse.up();await page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')==='false');await assertPicturePreview(pictureHead);assert.deepEqual(await pictureOrder(),['picture2','picture3','picture1']);check('picture reorder keeps source preview and the playhead during movement and after release');
    await page.getByRole('button',{name:'撤销',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')==='false');assert.deepEqual(await pictureOrder(),['picture1','picture2','picture3']);await assertPicturePreview(pictureHead);
    await page.getByRole('button',{name:'重做',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')==='false');assert.deepEqual(await pictureOrder(),['picture2','picture3','picture1']);await assertPicturePreview(pictureHead);check('picture reorder undo and redo retain the selected image preview and yellow playhead');
    await reset(pictureFixture(),2.375);await play();await step(.125);const playingPictureHead=await headSnapshot();assert.deepEqual(await sounding(),['mp3']);
    // Advance the clock inside pointerdown, before the desk handler and before another animation frame.
    await page.locator('[data-id="picture1"]').evaluate(card=>card.addEventListener('pointerdown',()=>{testClock+=125;},{capture:true,once:true}));
    await page.locator('[data-id="picture1"]').click({position:{x:30,y:30}});await assertPicturePreview(playingPictureHead);assert.deepEqual(await live(),[]);assert((await snapshot()).every(s=>s.paused));
    await step(1);await assertPicturePreview(playingPictureHead);check('picture click during playback freezes the displayed playhead and releases timeline media');
    const overlap=fixture();overlap.video_track.push(v('z-top','silent',4,20,24));await reset(overlap,5,'v2');
    assert.equal((await live()).find(s=>s.tag==='VIDEO').clip,'z-top');assert.equal(await page.locator('.zf-med-clip.video').last().getAttribute('data-id'),'z-top');check('overlap winner matches last painted card, independent of selection');
    const gap=fixture();gap.video_track[1].timeline_in_seconds=5;gap.audio_track[1].timeline_in_seconds=5;await reset(gap,3.8);await play();await step(.4);assert.equal(await page.locator('.zf-med-black').textContent(),'无画面');assert.deepEqual(await sounding(),['mp3']);await step(1);assert.equal((await live()).find(s=>s.tag==='VIDEO').clip,'v2');check('video gap is black while independent audio continues');
    await reset();await page.evaluate(()=>failNext=true);await play();await page.waitForTimeout(20);assert((await live()).every(s=>s.paused));assert((await page.locator('.zf-med-status').textContent()).includes('浏览器阻止了播放'));await play();assert.deepEqual(await sounding(),['mp3']);check('autoplay failure is visible and click can retry');
    await reset();await page.evaluate(()=>deferNext=true);await play();await page.locator('[data-asset-id="silent"]').click();await page.evaluate(()=>finishPlay.resolve());await page.waitForTimeout(20);assert((await snapshot()).filter(s=>!s.src).every(s=>s.paused));check('late play resolution cannot resurrect released media');
    await reset();await page.evaluate(()=>deferNext=true);await play();await page.getByRole('button',{name:'暂停时间线',exact:true}).click();await play();
    await page.evaluate(()=>finishPlay.reject(new DOMException('interrupted by pause','AbortError')));await step(.1);assert.deepEqual(await sounding(),['mp3']);assert(await page.getByRole('button',{name:'暂停时间线',exact:true}).isVisible());check('stale play rejection cannot interrupt a newer resume');
    await page.evaluate(()=>holdMetadata=true);await reset(fixture(),5,'v2');await seek(6);
    await page.evaluate(()=>{holdMetadata=false;for(const s of testMedia.filter(s=>s.src)){s.ready=1;s.player.dispatchEvent(new Event('loadedmetadata'));}});
    records=await live();assert.equal(records.find(s=>s.clip==='v2').time,12);assert.equal(records.find(s=>s.clip==='mp3').time,12);assert(records.every(s=>s.paused));check('delayed metadata uses latest playhead');
    await play();await page.evaluate(()=>{deskNode.widgets[0].value='{bad json';deskNode.zfMediaDesk.restore();});assert((await snapshot()).every(s=>s.paused));assert.deepEqual(await live(),[]);check('invalid JSON restoration still silences and releases players');
    await reset(fixture(),5,'v2');await play();if(process.argv[4])await page.locator('.zf-med').screenshot({path:process.argv[4]});
    await page.evaluate(()=>deskNode.onRemoved());await step(1);assert.deepEqual(await live(),[]);assert((await snapshot()).every(s=>s.paused));check('node destruction releases every player and clock');
    assert.deepEqual(errors,[]);console.log(`MONITOR_SMOKE_OK ${checks} browser checks; no page exceptions`);
} finally {await browser.close();}
