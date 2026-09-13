// Real desk UI with a graph API harness matching local ComfyUI LiteGraph add/connect/getLink/remove/serialize.
// node tests/media_evidence_outlets_ui_smoke.mjs PLAYWRIGHT_PACKAGE CHROMIUM_EXECUTABLE [COMFY_FRONTEND_STATIC]
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,readdir} from 'node:fs/promises';
import {join} from 'node:path';
const {chromium}=createRequire(import.meta.url)(process.argv[2]||'playwright');
const files=Object.fromEntries(await Promise.all(['media_evidence_desk.js','media_evidence_core.mjs','media_evidence_presets.mjs','media_evidence_outlets.mjs','media_evidence_slots.mjs','media_processing_presets.json','media_evidence_desk.css','dom_widget_layout.mjs'].map(async name=>[name,await readFile(new URL(`../web/${name}`,import.meta.url),'utf8')])));
const browser=await chromium.launch({headless:true,executablePath:process.argv[3]});
const page=await browser.newPage({viewport:{width:1240,height:1180}}),errors=[];
let requestCount=0;page.on('request',()=>requestCount++);
page.on('pageerror',error=>errors.push(error.message));
const html=`<!doctype html><meta charset="utf-8"><style>body{margin:20px;background:#10151d}#mount{width:1180px;height:1000px}#outside{height:100px}</style><div id="mount"></div><div id="outside">canvas</div><script type="module">
import {app} from '/scripts/app.js';import {attachMediaDesk} from '/extensions/media_evidence_desk.js';import {freshProject} from '/extensions/media_evidence_core.mjs';import * as outlets from '/extensions/media_evidence_outlets.mjs?v=h3-v2-07';
window.app=app;window.outlets=outlets;window.outsideDrops=0;window.nextFailure=null;window.connectCount=0;window.queueCalls=0;
app.queuePrompt=window.queuePrompt=()=>{queueCalls++;throw new Error('Slot edit must not queue');};
class Graph {
 constructor(){this.nodes=[];this.links=new Map();this.lastId=0;this.lastLinkId=0;this.list_of_graphcanvas=[{graph:this}];}
 getNodeById(id){return this.nodes.find(n=>String(n.id)===String(id));}
 getLink(id){return this.links.get(id);}
 findNodesByType(type){return this.nodes.filter(n=>n.type===type);}
 beforeChange(){this.before=(this.before||0)+1;this.lastBefore=structuredClone(this.serialize());} afterChange(){this.after=(this.after||0)+1;this.lastAfter=structuredClone(this.serialize());} setDirtyCanvas(){this.dirty=(this.dirty||0)+1;}
 add(node){if(node.id===-1)node.id=++this.lastId;else this.lastId=Math.max(this.lastId,node.id);this.nodes.push(node);node.graph=this;}
 remove(node){for(const link of [...this.links.values()])if(link.origin_id===node.id||link.target_id===node.id){const source=this.getNodeById(link.origin_id),target=this.getNodeById(link.target_id);if(source)source.outputs[link.origin_slot].links=source.outputs[link.origin_slot].links.filter(id=>id!==link.id);if(target)target.inputs[link.target_slot].link=null;this.links.delete(link.id);}this.nodes=this.nodes.filter(n=>n!==node);node.graph=null;}
 serialize(){return {nodes:this.nodes.map(n=>({id:n.id,type:n.type,title:n.title,pos:n.pos,size:n.size,flags:n.flags,properties:n.properties,widgets_values:n.widgets.map(w=>w.value)})),links:[...this.links.values()].map(l=>[l.id,l.origin_id,l.origin_slot,l.target_id,l.target_slot,l.type])};}
 configure(data){this.nodes=[];this.links.clear();for(const row of data.nodes){const n=row.type==='ZVUniversalMediaEvidenceDesk'?deskNode:LiteGraph.createNode(row.type);Object.assign(n,{id:row.id,title:row.title,pos:row.pos,size:row.size,flags:row.flags,properties:row.properties});n.outputs.forEach(o=>o.links=[]);n.inputs.forEach(i=>i.link=null);row.widgets_values.forEach((v,i)=>n.widgets[i].value=v);this.add(n);}for(const [id,origin_id,origin_slot,target_id,target_slot,type] of data.links){this.links.set(id,{id,origin_id,origin_slot,target_id,target_slot,type});this.getNodeById(origin_id).outputs[origin_slot].links.push(id);this.getNodeById(target_id).inputs[target_slot].link=id;this.lastLinkId=Math.max(this.lastLinkId,id);}}
}
class Node {
 constructor(type){this.id=-1;this.type=type;this.pos=[0,0];this.size=[300,140];this.flags={};this.properties={};this.title=type;this.widgets=[];this.inputs=[];this.outputs=[];}
 computeSize(){return [300,this.type==='ZVVideoOutlet'?140:120];} setSize(size){this.size=size;} setDirtyCanvas(){}
 connect(output,target,input){connectCount++;if(nextFailure==='connect'||nextFailure===connectCount)return null;const g=this.graph,id=++g.lastLinkId,link={id,origin_id:this.id,origin_slot:output,target_id:target.id,target_slot:input,type:this.outputs[output].type};g.links.set(id,link);this.outputs[output].links.push(id);target.inputs[input].link=id;return link;}
 collapse(){this.flags.collapsed=!this.flags.collapsed;}
}
window.LiteGraph={createNode(type){if(nextFailure===type)return null;if(type==='TestSink'){const n=new Node(type);n.inputs=[{name:'image',type:'IMAGE',link:null},{name:'audio',type:'AUDIO',link:null}];return n;}if(!['ZVPictureOutlet','ZVVideoOutlet','ZVAudioOutlet','ZVTimelineAudioOutlet','ZVPictureSlotOutlet','ZVVideoSlotOutlet','ZVAudioSlotOutlet'].includes(type))return null;const n=new Node(type);n.inputs=[{name:'media_project',type:'ZV_MEDIA_PROJECT',link:null}];if(type!=='ZVTimelineAudioOutlet')n.widgets=[{name:type.includes('SlotOutlet')?'slot_id':type==='ZVPictureOutlet'?'item_id':'clip_id',value:''}];n.outputs=((type==='ZVVideoOutlet'||type==='ZVVideoSlotOutlet')?['IMAGE','AUDIO','STRING','STRING']:[(type==='ZVPictureOutlet'||type==='ZVPictureSlotOutlet')?'IMAGE':'AUDIO','STRING','STRING']).map(type=>({type,links:[]}));return n;}};
window.deskNode=new Node('ZVUniversalMediaEvidenceDesk');deskNode.widgets=[{name:'project_data',value:JSON.stringify(freshProject())}];deskNode.outputs=[{type:'ZV_MEDIA_PROJECT',links:[]},{type:'STRING',links:[]}];deskNode.size=[1180,1100];deskNode.pos=[40,80];deskNode.addDOMWidget=(n,t,root)=>{document.querySelector('#mount').append(root);return {};};
window.resetGraph=()=>{window.graph=new Graph();deskNode.id=-1;deskNode.outputs.forEach(o=>o.links=[]);graph.add(deskNode);app.canvas={graph};nextFailure=null;connectCount=0;};resetGraph();attachMediaDesk(deskNode);
window.placeholder=(type,{source=deskNode,binding='',connected=true}={})=>{const node=LiteGraph.createNode(type);node.widgets[0].value=binding;node.properties={keep:'unrelated property',zv_media_outlet:{binding_key:node.widgets[0].name,binding_id:'stale-property'}};node.title='预接出口';graph.add(node);if(connected)source.connect(0,node,0);return node;};
window.wireSinks=node=>{for(let i=0;i<2;i++){const sink=LiteGraph.createNode('TestSink');graph.add(sink);node.connect(0,sink,(node.type==='ZVAudioOutlet'||node.type==='ZVAudioSlotOutlet')?1:0);if(node.type==='ZVVideoOutlet'||node.type==='ZVVideoSlotOutlet')node.connect(1,sink,1);}};
window.otherDesk=()=>{const node=new Node('OtherDesk');node.outputs=[{type:'ZV_MEDIA_PROJECT',links:[]}];graph.add(node);return node;};
window.bindingSnapshot=()=>({graph:graph.serialize(),project:deskNode.zfMediaDesk.getProject(),view:deskNode.properties.zf_media_desk_view,counters:{before:graph.before||0,after:graph.after||0,dirty:graph.dirty||0}});
document.querySelector('#outside').addEventListener('drop',()=>outsideDrops++);
</script>`;
await page.route('**/*',route=>{
    const url=new URL(route.request().url()),path=url.pathname,name=path.split('/').at(-1);
    if(path.endsWith('/presets'))return route.fulfill({json:{ok:true,builtins:JSON.parse(files['media_processing_presets.json']),users:[]}});
    if(path.endsWith('/normalize')){
        const p=route.request().postDataJSON();p.picture_track.sort((a,b)=>a.order-b.order);for(const track of ['video','audio'])p[`${track}_track`].sort((a,b)=>a.timeline_in_seconds-b.timeline_in_seconds||a.clip_id.localeCompare(b.clip_id));
        p.label_map=['picture','video','audio'].flatMap(track=>p[`${track}_track`].map((c,i)=>({item_id:c.clip_id||c.item_id,label:`${track[0].toUpperCase()+track.slice(1)} ${i+1}`})));
        p.validation={errors:[],warnings:[]};return route.fulfill({json:{ok:true,project:p}});
    }
    if(path.endsWith('/preview'))return url.searchParams.get('variant')==='peaks'?route.fulfill({json:{peaks:[.1,.4,.8,.3]}}):route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="#295779"/></svg>'});
    const body=path==='/'?html:name==='app.js'?'export const app={registerExtension(){}};':name==='api.js'?'export const api={apiURL:p=>p,fetchApi:(p,o)=>fetch(p,o),queuePrompt:()=>{globalThis.queueCalls++;throw new Error("Unexpected queue");}};':files[name];
    return body?route.fulfill({contentType:path==='/'?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.json')?'application/json':'application/javascript',body}):route.abort();
});
const asset=(id,kind)=>({asset_id:id,source_handle:id,name:`${id}.${kind==='picture'?'png':kind==='audio'?'mp3':'mp4'}`,kind,probe:{duration_seconds:kind==='picture'?null:30,has_audio:kind!=='picture',width:160,height:90,fps:24,frame_count:720,frame_count_exact:true,vfr:false,size_bytes:1000}});
const clip=(id,asset_id,at=0)=>({clip_id:id,asset_id,timeline_in_seconds:at,source_in_seconds:2,source_out_seconds:8,enabled:true,source_audio_enabled:false,audio_link_id:null,origin:'standalone',linked_video_clip_id:null,source_video_clip_id:null});
const fixture=(pictures=2)=>({schema_version:1,project_clock:{fps:24},assets:[...Array.from({length:pictures},(_,i)=>asset(`image${i+1}`,'picture')),asset('movie1','video'),asset('movie2','video'),asset('music','audio')],picture_track:Array.from({length:pictures},(_,i)=>({item_id:`p${i+1}`,asset_id:`image${i+1}`,order:i+1})),video_track:[{...clip('v1','movie1',2),source_audio_enabled:true,audio_link_id:'linked'},clip('v2','movie2',20)],audio_track:[{...clip('linked','movie1',2),origin:'video_source',linked_video_clip_id:'v1',source_video_clip_id:'v1'},clip('a1','music',1),{...clip('detached','movie2',3),origin:'video_source',source_video_clip_id:'v2'}],processing_window:{start_seconds:0,end_seconds:10,fps:24}});
const reset=async(p=fixture(),selected='p1',clear=true)=>{
    await page.evaluate(({p,selected,clear})=>{if(clear)resetGraph();deskNode.widgets[0].value=JSON.stringify(p);deskNode.properties.zf_media_desk_view={zoom:35,playhead:3.25,selected,asset:selected?p.picture_track.find(c=>c.item_id===selected)?.asset_id||null:'image1',snap:false,scroll:0,monitor_mode:'source'};deskNode.zfMediaDesk.restore();},{p,selected,clear});
    await page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')==='false');
};
const nodes=()=>page.evaluate(()=>graph.serialize());
const single=()=>page.locator('.zf-med-create-outlet').click();
const batch=()=>page.evaluate(()=>outlets.createMediaOutlets(deskNode,deskNode.zfMediaDesk.getProject(),outlets.outletItems(deskNode.zfMediaDesk.getProject()),app));
const bindingSnapshot=()=>page.evaluate(()=>window.bindingSnapshot());
let checks=0;const check=name=>{checks++;console.log(`OK ${name}`);};
try {
    await page.goto('https://outlets.test/');await page.waitForSelector('.zf-med');await reset();
    const deskBefore=await page.evaluate(()=>({size:[...deskNode.size],outputs:deskNode.outputs.length,head:deskNode.properties.zf_media_desk_view.playhead}));
    assert.equal(await page.locator('.zf-med-create-outlet').textContent(),'发送图片1');
    await single();let data=await nodes();assert.equal(data.nodes.length,2);assert.equal(data.nodes[1].type,'ZVPictureOutlet');assert.deepEqual(data.nodes[1].widgets_values,['p1']);assert.deepEqual(data.nodes[1].properties.zv_media_outlet,{binding_key:'item_id',binding_id:'p1'});assert.match(data.nodes[1].title,/图片1.*image1/);assert.deepEqual(data.links[0].slice(1),[1,0,2,0,'ZV_MEDIA_PROJECT']);assert.equal(await page.evaluate(()=>deskNode.properties.zf_media_desk_view.playhead),deskBefore.head);check('发送图片1 creates one stable direct outlet without seeking');
    await single();assert.equal((await nodes()).nodes.length,2);check('single action deduplicates actual graph links');
    await batch();data=await nodes();assert.equal(data.nodes.length,7);assert.equal(data.links.length,6);assert.equal(data.nodes.filter(n=>n.type==='ZVAudioOutlet').length,2);assert.deepEqual(data.nodes.filter(n=>n.type==='ZVAudioOutlet').map(n=>n.widgets_values[0]),['a1','detached']);assert(data.nodes.some(n=>n.widgets_values[0]==='v2'),'batch includes clips outside the current window');check('batch covers ordered tracks and detached audio, with paired original only on its video outlet');
    await reset(fixture(),'linked',false);await single();assert.equal((await nodes()).nodes.length,7);check('paired original inspector reuses its video outlet');
    await page.getByRole('button',{name:'创建时间线混音出口',exact:true}).click();await page.getByRole('button',{name:'创建时间线混音出口',exact:true}).click();assert.equal((await nodes()).nodes.filter(n=>n.type==='ZVTimelineAudioOutlet').length,1);check('timeline mix outlet is optional and deduplicated');
    const saved=await nodes();await page.evaluate(data=>{graph.configure(data);deskNode.zfMediaDesk.restore();},saved);await page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')==='false');await batch();assert.deepEqual((await nodes()).links,saved.links);assert.deepEqual((await nodes()).nodes.map(n=>n.widgets_values),saved.nodes.map(n=>n.widgets_values));check('graph serialization and reload preserve bindings and links without duplicates');
    const reordered=fixture();reordered.picture_track[0].order=2;reordered.picture_track[1].order=1;await reset(reordered,'p1',false);data=await nodes();const p1=data.nodes.find(n=>n.type==='ZVPictureOutlet'&&n.widgets_values[0]==='p1');assert.match(p1.title,/图片2.*image1/);assert.equal(p1.properties.zv_media_outlet.binding_id,'p1');assert.deepEqual(data.links,saved.links);check('reorder updates the Chinese display label while stable ID and graph connection remain identical');
    reordered.picture_track=reordered.picture_track.filter(c=>c.item_id!=='p1');await reset(reordered,'p2',false);data=await nodes();assert.match(data.nodes.find(n=>n.id===p1.id).title,/绑定素材已不存在/);await batch();assert.equal((await nodes()).nodes.find(n=>n.id===p1.id).widgets_values[0],'p1');assert.equal((await nodes()).nodes.length,saved.nodes.length);check('deletion leaves the missing binding explicit and never rebinds to the next item');
    const twenty=fixture(20);twenty.video_track=[];twenty.audio_track=[];await reset(twenty);await batch();data=await nodes();assert.equal(data.nodes.length,21);assert.equal(data.links.length,20);assert(data.nodes.slice(1).every(n=>n.size[0]<=320&&n.size[1]<=180));assert.equal(new Set(data.nodes.slice(1).map(n=>n.pos.join(','))).size,20);assert.deepEqual(await page.evaluate(()=>({size:[...deskNode.size],outputs:deskNode.outputs.length,head:deskNode.properties.zf_media_desk_view.playhead})),deskBefore);await page.evaluate(()=>graph.nodes[1].collapse());assert.equal((await nodes()).nodes[1].flags.collapsed,true);check('20 items create 20 compact independently collapsible nodes without growing the desk or ports');
    await reset(fixture(),null);assert.equal(await page.locator('.zf-med-create-outlet').count(),0);check('preloaded pool items have no per-item outlet action');
    const dragResult=await page.evaluate(()=>{const card=document.querySelector('.zf-med-asset'),outside=document.querySelector('#outside'),dt=new DataTransfer();card.dispatchEvent(new DragEvent('dragstart',{bubbles:true,cancelable:true,dataTransfer:dt}));outside.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:dt}));const drop=new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt});outside.dispatchEvent(drop);return {prevented:drop.defaultPrevented,outsideDrops,nodes:graph.nodes.length,types:[...dt.types]};});assert.deepEqual(dragResult,{prevented:true,outsideDrops:0,nodes:1,types:['application/x-zf-media']});check('pool drag outside remains intercepted without LoadImage creation');
    await reset();await page.evaluate(()=>deskNode.id=-1);await single();assert.match(await page.locator('.zf-med-status').textContent(),/尚未分配节点 ID/);assert.equal((await nodes()).nodes.length,1);check('unassigned source node ID reports a Chinese error without mutation');
    await reset();await page.evaluate(()=>{app.canvas=null;graph.list_of_graphcanvas=[];});await single();assert.match(await page.locator('.zf-med-status').textContent(),/画布不可用/);assert.equal((await nodes()).nodes.length,1);check('unavailable canvas reports a Chinese error without mutation');
    await reset();await page.evaluate(()=>deskNode.graph=null);await single();assert.match(await page.locator('.zf-med-status').textContent(),/尚未加入画布/);check('detached desk reports a Chinese error');
    await reset();await single();await page.evaluate(()=>{const n=graph.nodes[1],l=graph.getLink(n.inputs[0].link);graph.links.delete(l.id);n.inputs[0].link=null;});await single();assert.equal((await nodes()).nodes.length,3);check('a stale property with a disconnected input never suppresses a new connected outlet');
    await reset();await single();await page.evaluate(()=>{const n=graph.nodes[1];n.widgets[0].value='p2';});await single();assert.equal((await nodes()).nodes.length,3);check('current binding widget is authoritative over a stale property');
    const primaryActions=()=>page.locator('.zf-med-inspect-actions button').allTextContents();
    const refreshInspector=async()=>{await page.evaluate(()=>deskNode.zfMediaDesk.restore());await page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')==='false');};
    for(const [selected,title,type,id] of [['p1','发送图片1','ZVPictureOutlet','p1'],['v1','发送视频1','ZVVideoOutlet','v1'],['a1','发送音频1','ZVAudioOutlet','a1'],['linked','发送视频1','ZVVideoOutlet','v1'],['detached','发送音频2','ZVAudioOutlet','detached']]){
        await reset(fixture(),selected);assert.deepEqual(await primaryActions(),[title]);
        await single();const after=await nodes(),created=after.nodes.find(n=>n.type===type&&n.widgets_values[0]===id);assert(created);assert.equal(await page.getByRole('button',{name:'绑定到预接出口',exact:true}).count(),0);assert.equal(await page.getByLabel('目标出口槽位').count(),0);
        const visible=await page.evaluate(()=>{const b=document.querySelector('.zf-med-inspect-actions .primary'),r=b.getBoundingClientRect(),panel=b.closest('.zf-med-panel').getBoundingClientRect();return {outsideScroll:!b.closest('.zf-med-inspect'),visible:r.top>=panel.top&&r.bottom<=panel.bottom&&r.bottom<=innerHeight};});assert(visible.outsideScroll&&visible.visible);
        check(`${selected} exposes one unambiguous ${title} action and creates the correct direct outlet`);
    }
    await reset();await page.evaluate(()=>{const n=placeholder('ZVPictureOutlet');wireSinks(n);});await refreshInspector();const beforeSeparate=await nodes();await single();const afterSeparate=await nodes();assert.equal(afterSeparate.nodes.length,beforeSeparate.nodes.length+1);assert(beforeSeparate.links.every(l=>afterSeparate.links.some(r=>JSON.stringify(r)===JSON.stringify(l))));assert.equal(afterSeparate.nodes.find(n=>n.id===beforeSeparate.nodes[1].id).widgets_values[0],'');check('an old empty prewired node is ignored while the selected material gets a new direct outlet');
    await reset(fixture(),null);assert.deepEqual(await primaryActions(),['发送原素材']);check('pool-only selection has one distinct original-source send action');
    const audioButtons=()=>page.evaluate(()=>{
        const root=document.querySelector('.zf-med'),gutter=root.querySelector('.zf-med-video-gutter'),inspect=root.querySelector('.zf-med-inspect');
        const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
        return {gutter:rect(gutter),buttons:[...gutter.querySelectorAll('button')].map(b=>({text:b.textContent,disabled:b.disabled,title:b.title,rect:rect(b),clientWidth:b.clientWidth,scrollWidth:b.scrollWidth,color:getComputedStyle(b).backgroundColor})),duplicates:root.querySelectorAll('.zf-med-delete-video,.zf-med-unlink-audio').length,inInspector:inspect.querySelectorAll('.zf-med-delete-video,.zf-med-unlink-audio').length,rootScroll:root.scrollTop,inspectScroll:inspect.scrollTop,viewportHeight:innerHeight};
    });
    const assertAudioVisible=s=>{
        assert.equal(s.buttons.length,2);assert.equal(s.duplicates,2);assert.equal(s.inInspector,0);
        assert.equal(s.buttons[1].text,'解绑音频');assert(s.buttons[0].rect.bottom<=s.buttons[1].rect.y);
        assert.notEqual(s.buttons[0].color,s.buttons[1].color);
        for(const b of s.buttons){assert(b.rect.width>0&&b.rect.height>0);assert(b.rect.x>=s.gutter.x&&b.rect.right<=s.gutter.right);assert(b.rect.y>=s.gutter.y&&b.rect.bottom<=s.gutter.bottom);assert(b.rect.bottom<=s.viewportHeight);assert(b.scrollWidth<=b.clientWidth);}
    };
    const synced=()=>page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')==='false');
    for(const selected of ['v1','linked']){
        await reset(fixture(),selected);await page.evaluate(()=>{document.querySelector('.zf-med').scrollTop=0;document.querySelector('.zf-med-inspect').scrollTop=0;});let s=await audioButtons();assertAudioVisible(s);assert.equal(s.buttons[0].disabled,selected!=='v1');assert.equal(s.buttons[1].disabled,false);assert.equal(s.buttons[0].text,'删除');assert.equal(s.rootScroll,0);assert.equal(s.inspectScroll,0);
        assert.equal(await page.getByRole('button',{name:'解除绑定',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'开 / 关原声',exact:true}).count(),0);
        check(`${selected} has a single visible vertical audio toolbar in the video gutter without scrolling`);
        const before=await bindingSnapshot();
        const expected=await page.evaluate(async selected=>{const edit=await import('/extensions/media_evidence_core.mjs');return edit.audioAction(deskNode.zfMediaDesk.getProject(),selected,'unlink');},selected);
        await page.getByRole('button',{name:'解绑音频',exact:true}).click();await synced();const after=await bindingSnapshot();assert.deepEqual(after.project,expected);assert.deepEqual(after.graph.links,before.graph.links);
        assert((await audioButtons()).buttons[1].disabled);await page.getByRole('button',{name:'撤销',exact:true}).click();await synced();assert.deepEqual(await page.evaluate(()=>deskNode.zfMediaDesk.getProject()),before.project);assert(!(await audioButtons()).buttons[1].disabled);
        check(`${selected} toolbar invokes the existing unlink path without changing outlet links`);
        await page.evaluate(()=>document.querySelector('.zf-med-inspect').scrollTop=9999);assertAudioVisible(await audioButtons());check(`${selected} audio toolbar stays visible when the inspector is scrolled`);
    }
    for(const selected of [null,'p1','a1','detached']){
        await reset(fixture(),selected);const before=await bindingSnapshot(),s=await audioButtons();assertAudioVisible(s);assert(s.buttons.every(b=>b.disabled));
        await page.evaluate(()=>{for(const b of document.querySelectorAll('.zf-med-video-gutter button')){b.click();b.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});assert.deepEqual(await bindingSnapshot(),before);
        check(`${selected||'no selection'} keeps both gutter buttons visible and disabled without mutation`);
    }
    await reset(fixture(),'v2');const silentBefore=await bindingSnapshot();assert(!(await audioButtons()).buttons[0].disabled);assert((await audioButtons()).buttons[1].disabled);await page.locator('.zf-med-delete-video').click();await synced();const silentAfter=await bindingSnapshot();assert(!silentAfter.project.video_track.some(v=>v.clip_id==='v2'));assert(silentAfter.project.audio_track.some(a=>a.clip_id==='detached'));assert.deepEqual(silentAfter.project.assets,silentBefore.project.assets);check('silent video delete preserves detached audio and original pool');
    await page.setViewportSize({width:1024,height:800});await page.evaluate(()=>{const mount=document.querySelector('#mount');mount.style.width='980px';mount.style.height='720px';document.querySelector('.zf-med-timeline').style.gridTemplateColumns='70px 1fr';});
    await reset(fixture(),'v1');assertAudioVisible(await audioButtons());assert.equal((await audioButtons()).gutter.width,70);assert.equal((await audioButtons()).rootScroll,0);check('70px video gutter and low node height keep both Chinese labels fully visible without scrolling');
    if(process.argv[5])await page.locator('.zf-med-timeline').screenshot({path:process.argv[5]});
    await page.setViewportSize({width:1240,height:1180});await page.evaluate(()=>{document.querySelector('#mount').removeAttribute('style');document.querySelector('.zf-med-timeline').style.removeProperty('grid-template-columns');});
    const slotFixture=(extra=0)=>{const p=fixture();p.outlet_slots={version:1,items:[{slot_id:'picture-slot',kind:'picture',ordinal:1,binding_id:null},{slot_id:'video-slot',kind:'video',ordinal:1,binding_id:null},{slot_id:'audio-slot',kind:'audio',ordinal:1,binding_id:null},...Array.from({length:extra},(_,i)=>({slot_id:`extra-${i}`,kind:'picture',ordinal:i+2,binding_id:null}))]};return p;};
    const prepareSlots=async(p=slotFixture(),selected='p1')=>{
        await reset(p,selected);await page.evaluate(async()=>{document.querySelector('.zf-med-slot-panel').open=false;const slots=await import('/extensions/media_evidence_slots.mjs');window.slots=slots;for(const slot of deskNode.zfMediaDesk.getProject().outlet_slots.items){const n=LiteGraph.createNode(slots.SLOT_TYPES[slot.kind]);n.widgets[0].value=slot.slot_id;graph.add(n);deskNode.connect(0,n,0);wireSinks(n);}graph.findNodesByType=()=>{throw new Error('Slot UI must follow the project output edges, never scan the graph');};deskNode.zfMediaDesk.restore();});await synced();
    };
    const legacy=slotFixture();legacy.outlet_slots.items[0].binding_id='p1';await prepareSlots(legacy);assert.equal(await page.locator('.zf-med-slot-panel').getAttribute('open'),null);assert.equal(await page.locator('.zf-med-slot-panel summary').textContent(),'旧版固定槽位（3，仅兼容）');assert.equal(await page.locator('.zf-med-inspect-actions .primary').textContent(),'发送图片1');assert.equal(await page.getByLabel('目标出口槽位').count(),0);check('legacy slots stay visible only as a collapsed compatibility panel and never replace direct send');
    const legacyBefore=await bindingSnapshot(),requests=requestCount;await single();const directAfter=await bindingSnapshot();assert.equal(requestCount,requests);assert.equal(await page.evaluate(()=>queueCalls),0);assert.equal(directAfter.project.outlet_slots.items[0].binding_id,'p1');assert(directAfter.graph.nodes.some(n=>n.type==='ZVPictureOutlet'&&n.widgets_values[0]==='p1'));assert(legacyBefore.graph.links.every(link=>directAfter.graph.links.some(row=>JSON.stringify(row)===JSON.stringify(link))));check('发送图片1 adds a direct outlet without changing old slot mappings or downstream wires');
    await page.locator('.zf-med-slot-panel summary').click();const fixed=await nodes(),clearRequests=requestCount;await page.getByRole('button',{name:'清空图片1',exact:true}).click();assert.equal(requestCount,clearRequests);assert.equal((await bindingSnapshot()).project.outlet_slots.items[0].binding_id,null);assert.deepEqual((await nodes()).links,fixed.links);check('legacy clear remains available for old workflows and preserves every wire');
    await prepareSlots(slotFixture(17));const sizeBefore=await page.evaluate(()=>({size:deskNode.size,outputs:deskNode.outputs.length,root:document.querySelector('.zf-med').getBoundingClientRect().height,panel:document.querySelector('.zf-med-slot-panel').getBoundingClientRect().height}));assert(sizeBefore.panel<45);await page.locator('.zf-med-slot-panel summary').click();const large=await page.evaluate(()=>({size:deskNode.size,outputs:deskNode.outputs.length,root:document.querySelector('.zf-med').getBoundingClientRect().height,list:document.querySelector('.zf-med-slot-list').getBoundingClientRect().height,rows:document.querySelectorAll('.zf-med-slot-row').length}));assert.deepEqual(large.size,sizeBefore.size);assert.equal(large.outputs,2);assert.equal(large.root,sizeBefore.root);assert.equal(large.rows,20);assert(large.list<=150);check('20 slots remain in a bounded foldable list without enlarging the desk or its ports');
    const missing=slotFixture();missing.outlet_slots.items[0].binding_id='deleted-picture';await prepareSlots(missing);const missingTitle=await page.evaluate(()=>slots.connectedSlotNodes(deskNode).find(n=>n.type==='ZVPictureSlotOutlet'));assert.match(missingTitle.title,/素材已不存在或类型不符/);assert.equal(missingTitle.color,'#743f45');check('a stale saved binding has an explicit red missing-media title without automatic retargeting');
    if(process.argv[4]) {
        const frontend=process.argv[4],assets=await readdir(join(frontend,'assets'));
        let graphModule;
        for(const name of assets.filter(name=>/^settingStore-.*\.js$/.test(name)))if(/class LGraph[\s{]/.test(await readFile(join(frontend,'assets',name),'utf8'))){graphModule=name;break;}
        const vueModule=assets.find(name=>/^vendor-vue-core-.*\.js$/.test(name));
        assert(graphModule&&vueModule,'local frontend graph and Vue runtime bundles must be present');
        const real=await browser.newPage();real.on('pageerror',error=>errors.push(error.message));
        await real.route('**/*',async route=>{
            const path=new URL(route.request().url()).pathname,name=path.split('/').at(-1);
            try {const body=path==='/'?'<!doctype html><html><body></body></html>':path.startsWith('/extensions/')?files[name]:path.startsWith('/assets/')?await readFile(join(frontend,'assets',name)):null;
                if(body==null)return route.abort();
                return route.fulfill({contentType:path==='/'?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.json')?'application/json':'application/javascript',body});
            } catch {return route.abort();}
        });
        await real.goto('https://actual-litegraph.test/');
        const actual=await real.evaluate(async({graphModule,vueModule,p})=>{
            const vue=await import(`/assets/${vueModule}`),find=(mod,name)=>Object.values(mod).find(value=>typeof value==='function'&&value.name===name);
            find(vue,'createApp')({}).use(find(vue,'createPinia')());
            const mod=await import(`/assets/${graphModule}`),LGraph=find(mod,'LGraph'),LGraphNode=find(mod,'LGraphNode');
            window.LiteGraph=Object.values(mod).find(value=>value?.createNode&&value?.registerNodeType);
            const api=await import('/extensions/media_evidence_outlets.mjs?v=h3-v2-07');
            class Desk extends LGraphNode {constructor(){super();this.addOutput('media_project','ZV_MEDIA_PROJECT');this.addOutput('project_json','STRING');this.pos=[40,80];this.size=[1180,1100];}}
            LiteGraph.registerNodeType('ZVUniversalMediaEvidenceDesk',Desk);
            for(const type of ['ZVPictureOutlet','ZVVideoOutlet','ZVAudioOutlet','ZVTimelineAudioOutlet','ZVPictureSlotOutlet','ZVVideoSlotOutlet','ZVAudioSlotOutlet']) {
                // ComfyNode enables widget serialization in the installed frontend constructor.
                class Outlet extends LGraphNode {constructor(){super();this.serialize_widgets=true;this.addInput('media_project','ZV_MEDIA_PROJECT');if(type!=='ZVTimelineAudioOutlet')this.addWidget('text',type.includes('SlotOutlet')?'slot_id':type==='ZVPictureOutlet'?'item_id':'clip_id','',()=>{});for(const output of (type==='ZVVideoOutlet'||type==='ZVVideoSlotOutlet')?['IMAGE','AUDIO','STRING','STRING']:[(type==='ZVPictureOutlet'||type==='ZVPictureSlotOutlet')?'IMAGE':'AUDIO','STRING','STRING'])this.addOutput(output,output);}}
                LiteGraph.registerNodeType(type,Outlet);
            }
            const graph=new LGraph(),desk=LiteGraph.createNode('ZVUniversalMediaEvidenceDesk');graph.add(desk);
            const app={canvas:{graph}},first=api.createMediaOutlets(desk,p,api.outletItems(p),app),duplicate=api.createMediaOutlets(desk,p,api.outletItems(p),app);
            const saved=JSON.parse(JSON.stringify(graph.serialize()));graph.configure(saved);
            const restored=graph.getNodeById(desk.id),reload=api.createMediaOutlets(restored,p,api.outletItems(p),app);
            const afterReload=JSON.parse(JSON.stringify(graph.serialize()));
            p.picture_track[0].order=2;p.picture_track[1].order=1;api.syncOutletTitles(restored,p);
            const bound=graph.findNodesByType('ZVPictureOutlet').find(n=>n.widgets[0].value==='p1');
            const reordered={title:bound.title,binding:bound.widgets[0].value,property:bound.properties.zv_media_outlet};
            const beforeFailure=graph.findNodesByType('ZVPictureOutlet').length;
            p.picture_track.push({item_id:'new',asset_id:'image1',order:3});const connect=restored.connect;
            restored.connect=()=>null;let failure='';try {api.createMediaOutlets(restored,p,api.outletItems(p),app);}catch(error){failure=error.message;}restored.connect=connect;
            const afterFailure=graph.findNodesByType('ZVPictureOutlet').length;
            bound.collapse();
            class Sink extends LGraphNode {constructor(){super();this.addInput('image','IMAGE');this.addInput('audio','AUDIO');this.addOutput('binding','STRING');}}
            LiteGraph.registerNodeType('TestSink',Sink);
            const bindingGraph=new LGraph(),bindingDesk=LiteGraph.createNode('ZVUniversalMediaEvidenceDesk');
            // Each real workflow owns a separate widget-store namespace.
            bindingGraph.id='11111111-1111-4111-8111-111111111111';bindingGraph.add(bindingDesk);
            const bindingApp={canvas:{graph:bindingGraph}};
            for(const type of ['ZVPictureOutlet','ZVVideoOutlet','ZVAudioOutlet']){
                const outlet=LiteGraph.createNode(type);bindingGraph.add(outlet);bindingDesk.connect(0,outlet,0);
                for(let i=0;i<2;i++){const sink=LiteGraph.createNode('TestSink');bindingGraph.add(sink);outlet.connect(0,sink,type==='ZVAudioOutlet'?1:0);if(type==='ZVVideoOutlet')outlet.connect(1,sink,1);}
            }
            const beforeBinding=JSON.parse(JSON.stringify(bindingGraph.serialize()));
            for(const selected of ['p1','linked','a1'])api.bindSelectedMediaOutlet(bindingDesk,p,selected,bindingApp);
            const savedBinding=JSON.parse(JSON.stringify(bindingGraph.serialize()));bindingGraph.configure(savedBinding);
            const restoredBindingDesk=bindingGraph.getNodeById(bindingDesk.id),afterBindingReload=JSON.parse(JSON.stringify(bindingGraph.serialize()));
            let boundError='';try {api.bindSelectedMediaOutlet(restoredBindingDesk,p,'p2',bindingApp);}catch(error){boundError=error.message;}
            const afterBoundRejection=JSON.parse(JSON.stringify(bindingGraph.serialize()));
            const converted=LiteGraph.createNode('ZVPictureOutlet');converted.addInput('item_id','STRING');bindingGraph.add(converted);restoredBindingDesk.connect(0,converted,0);bindingGraph.findNodesByType('TestSink')[0].connect(0,converted,1);
            const beforeConvertedRejection=JSON.parse(JSON.stringify(bindingGraph.serialize()));let convertedError='';try {api.bindSelectedMediaOutlet(restoredBindingDesk,p,'p2',bindingApp);}catch(error){convertedError=error.message;}
            const afterConvertedRejection=JSON.parse(JSON.stringify(bindingGraph.serialize()));
            const slotApi=await import('/extensions/media_evidence_slots.mjs'),slotGraph=new LGraph();slotGraph.id='22222222-2222-4222-8222-222222222222';
            const slotDesk=LiteGraph.createNode('ZVUniversalMediaEvidenceDesk');slotGraph.add(slotDesk);let slotProject={...p,outlet_slots:{version:1,items:[]}};
            for(const selected of ['p1','linked','a1']){const result=slotApi.createSlotOutlet(slotDesk,slotProject,selected,{canvas:{graph:slotGraph}});slotProject=result.project;for(let i=0;i<2;i++){const sink=LiteGraph.createNode('TestSink');slotGraph.add(sink);result.node.connect(0,sink,result.slot.kind==='audio'?1:0);if(result.slot.kind==='video')result.node.connect(1,sink,1);}}
            const slotSaved=JSON.parse(JSON.stringify(slotGraph.serialize()));slotGraph.configure(slotSaved);const slotReload=JSON.parse(JSON.stringify(slotGraph.serialize()));
            slotProject=slotApi.assignSlot(slotProject,slotProject.outlet_slots.items[0].slot_id,'p2');slotApi.syncSlotTitles(slotGraph.getNodeById(slotDesk.id),slotProject);const slotSwapped=JSON.parse(JSON.stringify(slotGraph.serialize()));
            return {first,duplicate,reload,saved,afterReload,reordered,failure,beforeFailure,afterFailure,collapsed:bound.flags.collapsed,binding:{beforeBinding,savedBinding,afterBindingReload,boundError,afterBoundRejection,beforeConvertedRejection,convertedError,afterConvertedRejection},slots:{slotSaved,slotReload,slotSwapped,slotProject}};
        },{graphModule,vueModule,p:fixture()});
        assert.deepEqual(actual.first,{created:6,existing:0});assert.equal(actual.saved.links.length,6);assert(actual.saved.nodes.slice(1).every(n=>n.size[0]<=320&&n.size[1]<=180));check('actual installed LiteGraph creates compact nodes and real graph links');
        assert.deepEqual(actual.duplicate,{created:0,existing:6});assert.deepEqual(actual.reload,{created:0,existing:6});assert.deepEqual(actual.afterReload.links,actual.saved.links);assert.deepEqual(actual.afterReload.nodes.map(n=>n.widgets_values),actual.saved.nodes.map(n=>n.widgets_values));check('actual LiteGraph serialization/configuration preserves widget values and link-based deduplication');
        assert.match(actual.reordered.title,/图片2.*image1/);assert.equal(actual.reordered.binding,'p1');assert.equal(actual.reordered.property.binding_id,'p1');assert.equal(actual.collapsed,true);check('actual LiteGraph title updates preserve binding and native collapse works');
        assert.match(actual.failure,/自动连线失败/);assert.equal(actual.beforeFailure,actual.afterFailure);check('actual LiteGraph removes failed outlet nodes without removing existing nodes');
        const binding=actual.binding;assert.equal(binding.savedBinding.nodes.length,binding.beforeBinding.nodes.length);assert.deepEqual(binding.savedBinding.links,binding.beforeBinding.links);
        assert.deepEqual(binding.savedBinding.nodes.filter(n=>n.type.endsWith('Outlet')).map(n=>n.widgets_values[0]),['p1','v1','a1']);
        assert.deepEqual(binding.savedBinding.nodes.filter(n=>n.type.endsWith('Outlet')).map(n=>n.properties.zv_media_outlet.binding_id),['p1','v1','a1']);
        assert.deepEqual(binding.savedBinding.nodes.filter(n=>!n.type.endsWith('Outlet')),binding.beforeBinding.nodes.filter(n=>!n.type.endsWith('Outlet')));check('actual LiteGraph binds picture/video-paired-audio/audio without changing any downstream graph link');
        // Native configure recomputes execution order among independent branches.
        const withoutExecutionOrder=graph=>({...graph,nodes:graph.nodes.map(({order,...node})=>node)});
        assert.deepEqual(withoutExecutionOrder(binding.afterBindingReload),withoutExecutionOrder(binding.savedBinding));check('actual LiteGraph serialization/configuration preserves the three prewired bindings');
        assert.match(binding.boundError,/[\u3400-\u9fff]/);assert.deepEqual(binding.afterBoundRejection,binding.afterBindingReload);check('actual LiteGraph rejects overwriting an existing binding without mutation');
        assert.match(binding.convertedError,/[\u3400-\u9fff]/);assert.deepEqual(binding.afterConvertedRejection,binding.beforeConvertedRejection);check('actual LiteGraph protects a connected converted binding input');
        assert.deepEqual(withoutExecutionOrder(actual.slots.slotSaved),withoutExecutionOrder(actual.slots.slotReload));assert.deepEqual(actual.slots.slotReload.links,actual.slots.slotSwapped.links);assert.deepEqual(actual.slots.slotReload.nodes.map(n=>[n.id,n.type,n.widgets_values]),actual.slots.slotSwapped.nodes.map(n=>[n.id,n.type,n.widgets_values]));assert.equal(actual.slots.slotProject.outlet_slots.items[0].binding_id,'p2');check('actual LiteGraph safely serializes all three fixed slot_id nodes and keeps sockets during media swaps');
        await real.close();
    }
    assert.deepEqual(errors,[]);check('no browser page exceptions');console.log(`OUTLETS_UI_OK ${checks}`);
} finally {await browser.close();}
