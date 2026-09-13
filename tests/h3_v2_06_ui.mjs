// Production desk UI, real neutral HTTP registry, installed LiteGraph/ChangeTracker.
// node tests/h3_v2_06_ui.mjs URL PLAYWRIGHT CHROME FRONTEND_STATIC EVIDENCE_DIR
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile,readdir,mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
const {chromium}=createRequire(import.meta.url)(process.argv[3]);
const assets=join(process.argv[5],'assets'),names=await readdir(assets);
let graphModule;
for(const name of names.filter(n=>/^settingStore-.*\.js$/.test(n)))if(/class LGraph[\s{]/.test(await readFile(join(assets,name),'utf8'))){graphModule=name;break;}
const vueModule=names.find(n=>/^vendor-vue-core-.*\.js$/.test(n));
const browser=await chromium.launch({headless:true,executablePath:process.argv[4]});
const page=await browser.newPage({viewport:{width:1240,height:1180}}),errors=[],records=[],requests=[];
let checks=0;const check=v=>{assert(v);checks++;},deep=(a,b)=>{assert.deepEqual(a,b);checks++;};
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(r.method()!=='GET')requests.push({url:r.url(),method:r.method()});});
await mkdir(process.argv[6],{recursive:true});
const html=`<!doctype html><meta charset="utf-8"><style>body{margin:20px;background:#10151d}#mount{width:1180px;height:1000px}</style><div id="mount"></div><script type="module">
import * as vue from '/assets/${vueModule}';
const find=(mod,name)=>Object.values(mod).find(v=>typeof v==='function'&&v.name===name);
find(vue,'createApp')({}).use(find(vue,'createPinia')());
const mod=await import('/assets/${graphModule}');
window.LiteGraph=Object.values(mod).find(v=>v?.createNode&&v?.registerNodeType);
const LGraph=find(mod,'LGraph'),LGraphNode=find(mod,'LGraphNode'),ChangeTracker=find(mod,'ChangeTracker');
window.LGraph=LGraph;
const workflowStore=Object.values(mod).find(v=>v?.$id==='workflow')();
const nativeApp=Object.values(mod).find(v=>v&&typeof v.loadGraphData==='function');
if(!nativeApp||!ChangeTracker)throw new Error('Installed native app/tracker unavailable');
const {app}=await import('/scripts/app.js');
window.app=app;
const {attachMediaDesk}=await import('/extensions/media_evidence_desk.js');
const edit=await import('/extensions/media_evidence_core.mjs');
window.outlets=await import('/extensions/media_evidence_outlets.mjs?v=h3-v2-07');
window.slots=await import('/extensions/media_evidence_slots.mjs?v=h3-v2-07');
class Desk extends LGraphNode {constructor(){super();this.serialize_widgets=true;this.addWidget('text','project_data',JSON.stringify(edit.freshProject()),()=>{});this.addOutput('media_project','ZV_MEDIA_PROJECT');this.addOutput('project_json','STRING');this.addOutput('原素材来源','ZV_ORIGINAL_SOURCES');this.pos=[40,80];this.size=[1180,1000];}addDOMWidget(n,t,root){if(this.graph===app.canvas?.graph)document.querySelector('#mount').replaceChildren(root);return {};}}
LiteGraph.registerNodeType('ZVUniversalMediaEvidenceDesk',Desk);
for(const type of ['ZVPictureOutlet','ZVPictureSlotOutlet','ZVVideoOutlet','ZVAudioOutlet','ZVOriginalPictureOutlet','ZVOriginalVideoOutlet','ZVOriginalAudioOutlet']){
 class Outlet extends LGraphNode {constructor(){super();this.serialize_widgets=true;const original=type.includes('Original');this.addInput(original?'original_sources':'media_project',original?'ZV_ORIGINAL_SOURCES':'ZV_MEDIA_PROJECT');this.addWidget('text',original?'source_handle':type.includes('SlotOutlet')?'slot_id':type==='ZVPictureOutlet'?'item_id':'clip_id','',()=>{});if(original)this.addWidget('text','asset_id','',()=>{});const outputs=original?[type.includes('Picture')?'IMAGE':type.includes('Video')?'VIDEO':'AUDIO','STRING','STRING','STRING']:type==='ZVVideoOutlet'?['IMAGE','AUDIO','STRING','STRING']:[type.includes('Picture')?'IMAGE':'AUDIO','STRING','STRING'];for(const output of outputs)this.addOutput(output,output);}}
 LiteGraph.registerNodeType(type,Outlet);
}
class Sink extends LGraphNode {constructor(){super();this.addInput('image','IMAGE');this.addOutput('binding','STRING');}}
LiteGraph.registerNodeType('TestSink',Sink);
window.graph=new LGraph();window.deskNode=LiteGraph.createNode('ZVUniversalMediaEvidenceDesk');graph.add(deskNode);app.canvas={graph};nativeApp.rootGraphInternal=graph;nativeApp.canvas=app.canvas;nativeApp.ui={autoQueueEnabled:false};
window.installTracker=()=>{window.tracker=new ChangeTracker({path:'neutral-06.json'},JSON.parse(JSON.stringify(graph.serialize())));workflowStore.activeWorkflow=Object.values(vue).find(v=>v?.name==='markRaw')({path:'neutral-06.json',changeTracker:tracker});graph.onBeforeChange=()=>tracker.beforeChange();graph.onAfterChange=()=>tracker.afterChange();};
nativeApp.loadGraphData=async data=>{graph.configure(data);window.deskNode=graph.findNodesByType('ZVUniversalMediaEvidenceDesk')[0];attachMediaDesk(deskNode);};
window.restoreProject=p=>{deskNode.widgets[0].value=JSON.stringify(p);deskNode.properties.zf_media_desk_view={zoom:35,playhead:0,snap:true,selected:null,asset:null,scroll:0};deskNode.zfMediaDesk.restore();};
window.loadSaved=async data=>nativeApp.loadGraphData(data);
const saved=localStorage.getItem('graph06');
if(saved)await nativeApp.loadGraphData(JSON.parse(saved));else attachMediaDesk(deskNode);
installTracker();window.ready=true;
</script>`;
await page.route('**/assets/**',async route=>{
    const name=new URL(route.request().url()).pathname.split('/').at(-1);
    try{await route.fulfill({contentType:name.endsWith('.css')?'text/css':'application/javascript',body:await readFile(join(assets,name))});}catch{await route.abort();}
});
await page.route(process.argv[2]+'/',route=>route.fulfill({contentType:'text/html',body:html}));
const sync=()=>page.waitForFunction(()=>document.querySelector('.zf-med')?.getAttribute('aria-busy')==='false');
const project=()=>page.evaluate(()=>deskNode.zfMediaDesk.getProject());
const graph=()=>page.evaluate(()=>JSON.parse(JSON.stringify(window.graph.serialize())));
const deskNodeId=g=>g.nodes.find(n=>n.type==='ZVUniversalMediaEvidenceDesk').id;
const stable=g=>g.nodes.map(n=>({id:n.id,type:n.type,widgets:n.widgets_values,properties:n.properties}));
const selectAsset=id=>page.locator(`[data-asset-id="${id}"]`).click();
const selectItem=id=>page.locator(`[data-id="${id}"]`).click({position:{x:10,y:10}});
const restore=async p=>{await page.evaluate(p=>restoreProject(p),p);await sync();};
const original=()=>page.getByRole('button',{name:'发送原素材',exact:true});
const png=async handle=>{const r=await page.request.get(process.argv[2]+'/zf-media-evidence/preview?variant=original&source='+encodeURIComponent(handle));assert(r.ok());return r.body();};
try{
 await page.goto(process.argv[2]);await page.waitForFunction(()=>window.ready);await sync();
 const fixtures=await (await page.request.get(process.argv[2]+'/fixtures')).json();
 const chooserPromise=page.waitForEvent('filechooser');await page.locator('[data-action=import]').click();await (await chooserPromise).setFiles(fixtures);await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===3);await sync();
 let p=await project();const picture=p.assets.find(a=>a.kind==='picture'),video=p.assets.find(a=>a.kind==='video'),audio=p.assets.find(a=>a.kind==='audio');
 const order=await page.locator('.zf-med-tools').evaluate(e=>[...e.children].slice(0,5).map(n=>n.textContent));deep(order,['吸附','重做','撤销','分割','截图']);
 for(const a of [picture,video,audio]){await selectAsset(a.asset_id);check(await page.locator('[data-action=delete-picture]').isDisabled());check(await original().isVisible());check(await page.locator('[data-action=context]').isVisible());}
 await restore(p);check(await original().count()===0);check(await page.locator('[data-action=delete-picture]').isDisabled());
 // Real pool add button, followed by a real native screenshot in the same pool.
 await selectAsset(video.asset_id);await page.locator('[data-action=context]').click();await sync();await page.locator('[data-action=screenshot]').click();await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===4);await sync();
 p=await project();const shot=p.assets.find(a=>a.capture),bytes=await png(picture.source_handle),shotBytes=await png(shot.source_handle);
 for(const a of [picture,picture,shot]){await selectAsset(a.asset_id);await page.locator('[data-action=context]').click();await sync();}
 p=await project();deep(p.picture_track.map(i=>i.asset_id),[picture.asset_id,picture.asset_id,shot.asset_id]);
 const selected=p.picture_track[0].item_id,other=p.picture_track[1].item_id;
 await selectItem(selected);check(!(await page.locator('[data-action=delete-picture]').isDisabled()));check(!(await page.locator('[data-action=context]').isVisible()));check(await original().count()===0);
 check(await page.getByRole('button',{name:'删除此片段',exact:true}).count()===0);
 const slotResult=await page.evaluate(id=>{const r=slots.createSlotOutlet(deskNode,deskNode.zfMediaDesk.getProject(),id,{canvas:{graph}});return {project:r.project,node:r.node.id};},selected);
 const withSlot=slotResult.project;await restore(withSlot);await selectItem(selected);
 await page.locator('.zf-med-create-outlet').click();const beforeDelete=await graph();
 await page.locator('[data-action=delete-picture]').click();await sync();let after=await project();
 deep(after.assets,withSlot.assets);deep(after.picture_track.map(i=>i.item_id),[other,withSlot.picture_track[2].item_id]);deep(after.picture_track.map(i=>i.order),[1,2]);
 deep(after.outlet_slots.items[0].binding_id,null);deep((await graph()).links,beforeDelete.links);check((await graph()).nodes.some(n=>n.type==='ZVPictureOutlet'&&n.title.includes('绑定素材已不存在')));
 deep(await png(picture.source_handle),bytes);deep(await png(shot.source_handle),shotBytes);
 await page.getByRole('button',{name:'撤销',exact:true}).click();await sync();deep((await project()).picture_track,withSlot.picture_track);deep((await project()).outlet_slots,withSlot.outlet_slots);check((await graph()).nodes.some(n=>n.type==='ZVPictureOutlet'&&n.title.includes('图片1')));
 await page.getByRole('button',{name:'重做',exact:true}).click();await sync();deep((await project()).picture_track,after.picture_track);
 await page.getByRole('button',{name:'撤销',exact:true}).click();await sync();await selectItem(selected);await page.locator('.zf-med').press('Delete');await sync();deep((await project()).picture_track,after.picture_track);
 // A synthetic click on the now hidden context must have no deletion path.
 await selectItem(other);const protectedProject=await project();await page.locator('[data-action=context]').evaluate(b=>b.dispatchEvent(new MouseEvent('click',{bubbles:true})));deep(await project(),protectedProject);
 const rect=await page.locator('[data-action=delete-picture]').boundingBox(),gutter=await page.locator('.zf-med-picture-gutter').boundingBox();check(rect.y>=gutter.y&&rect.y+rect.height<=gutter.y+gutter.height);check(rect.x>=gutter.x&&rect.x+rect.width<=gutter.x+gutter.width);
 await page.locator('.zf-med').screenshot({path:join(process.argv[6],'PICTURE_NEAR_DELETE.png')});
 // Three independent source bindings; no parent output links or project mutation.
 await restore(withSlot);for(const a of [picture,video,audio,shot]){
   await selectAsset(a.asset_id);const before=await project(),beforeGraph=await graph(),requestCount=requests.length;
   await original().click();const g=await graph(),type='ZVOriginal'+({picture:'Picture',video:'Video',audio:'Audio'}[a.kind])+'Outlet',n=g.nodes.find(n=>n.type===type&&n.widgets_values[1]===a.asset_id);
   check(!!n);deep(n.outputs.map(o=>o.type),[a.kind==='picture'?'IMAGE':a.kind==='video'?'VIDEO':'AUDIO','STRING','STRING','STRING']);
   deep(n.properties.zv_original_outlet,{binding:'catalog',kind:a.kind,asset_id:a.asset_id,name:a.name});
   deep(await project(),before);deep(g.links.filter(l=>beforeGraph.links.some(old=>old[0]===l[0])),beforeGraph.links);check(g.links.some(l=>l[1]===deskNodeId(g)&&l[2]===2&&l[3]===n.id&&l[5]==='ZV_ORIGINAL_SOURCES'));deep(requests.length,requestCount);
   await original().click();deep(stable(await graph()),stable(g));
   records.push({name:'independent original '+a.kind,node:n});
 }
 const bound=await graph();check(bound.nodes.filter(n=>n.type==='ZVOriginalPictureOutlet').length===2);
 const outside=await page.evaluate(asset=>{
   const other=new LGraph(),desk=LiteGraph.createNode('ZVUniversalMediaEvidenceDesk');other.add(desk);
   const result=outlets.createOriginalOutlet(desk,asset,{canvas:{graph:other}});
   window.otherOriginalGraph=other;const saved=JSON.parse(JSON.stringify(other.serialize()));
   const current=graph.findNodesByType('ZVOriginalAudioOutlet')[0];graph.remove(current);
   return {created:result.created,saved};
 },audio);check(outside.created===1);
 await selectAsset(audio.asset_id);await original().click();check((await graph()).nodes.filter(n=>n.type==='ZVOriginalAudioOutlet').length===1);
 deep(await page.evaluate(()=>JSON.parse(JSON.stringify(otherOriginalGraph.serialize()))),outside.saved);
 await selectAsset(picture.asset_id);await page.locator('.zf-med').screenshot({path:join(process.argv[6],'POOL_SEND_ORIGINAL.png')});
 // Actual installed ChangeTracker transaction, undo and redo; host graph load is neutral adapter.
 await page.evaluate(()=>installTracker());const graphBeforeNew=await graph();
 const newAsset={...picture,asset_id:'neutral-second',name:'Other registered display',source_handle:shot.source_handle};
 await page.evaluate(asset=>{const n=graph.findNodesByType('ZVOriginalPictureOutlet').find(n=>n.widgets[1].value===asset.asset_id);if(n)graph.remove(n);installTracker();},{...newAsset,asset_id:shot.asset_id});
 const graphBeforeUndo=await graph();await selectAsset(shot.asset_id);await original().click();await page.waitForFunction(()=>tracker.undoQueue.length===1);const createdSaved=await graph();
 const counterCreated=await page.evaluate(()=>tracker.changeCount);
 await page.evaluate(()=>tracker.undo());await sync();deep(stable(await graph()),stable(graphBeforeUndo));
 const counterUndo=await page.evaluate(()=>tracker.changeCount);
 await page.evaluate(()=>tracker.redo());await sync();deep(stable(await graph()),stable(createdSaved));console.log('NATIVE_TRACKER_COUNTERS '+JSON.stringify({created:counterCreated,undo:counterUndo,redo:await page.evaluate(()=>tracker.changeCount)}));check(await page.evaluate(()=>tracker.changeCount===0));
 const saved=await graph();await page.evaluate(data=>loadSaved(data),saved);await sync();deep(stable(await graph()),stable(saved));deep((await graph()).links,saved.links);
 await page.evaluate(data=>localStorage.setItem('graph06',JSON.stringify(data)),saved);await page.reload();await page.waitForFunction(()=>window.ready);await sync();deep(stable(await graph()),stable(saved));deep((await graph()).links,saved.links);
 await selectAsset(shot.asset_id);const savedBeforeReuse=await graph();await original().click();deep(stable(await graph()),stable(savedBeforeReuse));
 // Pool removal must leave the independently bound original nodes and source untouched.
 await page.locator(`[data-asset-id="${shot.asset_id}"] .zf-med-unload`).click();await sync();check(!(await project()).assets.some(a=>a.asset_id===shot.asset_id));
 deep((await graph()).nodes.filter(n=>n.type.includes('Original')).map(n=>[n.id,n.widgets_values]),saved.nodes.filter(n=>n.type.includes('Original')).map(n=>[n.id,n.widgets_values]));deep(await png(shot.source_handle),shotBytes);
 // An external STRING input disqualifies reuse; old widget/properties/wires remain untouched.
 await selectAsset(picture.asset_id);await page.evaluate(id=>{const n=graph.findNodesByType('ZVOriginalPictureOutlet').find(n=>n.widgets[1].value===id),s=LiteGraph.createNode('TestSink');graph.add(s);n.addInput('source_handle','STRING');s.connect(0,n,1);},picture.asset_id);
 const external=await graph();await original().click();const externalAfter=await graph();check(externalAfter.nodes.length===external.nodes.length+1);deep(externalAfter.links.filter(l=>external.links.some(old=>old[0]===l[0])),external.links);deep(externalAfter.nodes.find(n=>n.id===external.nodes.find(n=>n.type==='ZVOriginalPictureOutlet'&&n.inputs.length===2).id).widgets_values,['',picture.asset_id]);
 // Detached/wrong graph/canvas/contract/add errors and real add-then-throw rollback.
 for(const failure of ['type','widget','input','output','add','id','size','foreign','canvas','detached','after_once','after_persistent','pointer','pointer_id','after_once_before_failure','after_persistent_before_failure']){
   const result=await page.evaluate(({failure,asset})=>{
     const before=JSON.parse(JSON.stringify(graph.serialize())),create=LiteGraph.createNode,add=graph.add,beforeChange=graph.beforeChange,afterChange=graph.afterChange,deskGraph=deskNode.graph,canvas=app.canvas;let beforeCalls=0,afterCalls=0;
     const target={...asset,asset_id:'fault_'+failure,source_handle:'originals/'+ 'f'.repeat(32)+'.png'};
     LiteGraph.createNode=function(type){if(failure==='type')return null;if(failure==='foreign')return graph.findNodesByType('ZVOriginalPictureOutlet')[0];const n=create.call(this,type);if(failure==='widget')n.widgets=[];if(failure==='input')n.addInput('media_project','ZV_MEDIA_PROJECT');if(failure==='output')n.outputs[0].type='VIDEO';if(failure==='size')n.setSize=()=>{throw new Error('size failure');};return n;};
     graph.add=function(n){const out=add.call(this,n);if(failure==='add')throw new Error('add failure');if(failure==='id')n.id=-1;if(failure.startsWith('pointer')){n.graph=null;if(failure==='pointer_id')n.id=deskNode.id;throw new Error('registered add callback corrupted pointer/id');}return out;};
     graph.beforeChange=function(...args){beforeCalls++;if(failure.endsWith('before_failure')&&beforeCalls===2)throw new Error('second beforeChange failed');return beforeChange.apply(this,args);};
     graph.afterChange=function(...args){const result=afterChange.apply(this,args);afterCalls++;if(failure.startsWith('after_persistent')||failure.startsWith('after_once')&&afterCalls===1)throw new Error('afterChange failed');return result;};
     if(failure==='canvas')app.canvas=null;if(failure==='detached')deskNode.graph=null;
     let message='';try{outlets.createOriginalOutlet(deskNode,target,app);}catch(e){message=e.message;}
     LiteGraph.createNode=create;graph.add=add;graph.beforeChange=beforeChange;graph.afterChange=afterChange;deskNode.graph=deskGraph;app.canvas=canvas;
     return {message,before:before.nodes.map(n=>[n.id,n.type,n.widgets_values]),after:graph.serialize().nodes.map(n=>[n.id,n.type,n.widgets_values]),linksBefore:before.links,linksAfter:graph.serialize().links};
   },{failure,asset:picture});
   check(!!result.message);deep(result.after,result.before);deep(result.linksAfter,result.linksBefore);records.push({name:'rollback '+failure,message:result.message});
 }
 // Invalid project window, a half canvas and unrelated bad asset still allow local source sending.
 const bad=await project();bad.processing_window.end_seconds=-1;bad.canvas={width:1000,height:null};bad.assets.push({...audio,asset_id:'unrelated-bad',source_handle:'originals/'+'0'.repeat(32)+'.wav'});await restore(bad);await selectAsset(video.asset_id);const badBefore=await project();await original().click();deep(await project(),badBefore);
 deep(errors,[]);check(requests.every(r=>new URL(r.url).origin===new URL(process.argv[2]).origin));
 await writeFile(join(process.argv[6],'BROWSER_NATIVE_GRAPH_RECORDS.json'),JSON.stringify({scope:'actual production desk JS, isolated HTTP/CPU files, installed LiteGraph and ChangeTracker; node constructors and app.loadGraphData are neutral UI adapters; no user service',checks,errors,requests,records},null,2));
 console.log('H3_V2_06_BROWSER_OK '+checks+' checks; real LiteGraph/ChangeTracker, HTTP CPU screenshot, delete/history/bindings, originals/reuse/rollback/save-load; 0 page errors');
}catch(e){console.error('H3_V2_06_BROWSER_FAIL '+JSON.stringify({checks,errors,status:await page.locator('.zf-med-status').textContent().catch(()=>null)}));throw e;}finally{await browser.close();}
