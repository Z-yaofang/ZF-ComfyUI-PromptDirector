// Real isolated HTTP/CPU pool and installed LGraph/ChangeTracker, no user service.
// node TEST URL PLAYWRIGHT CHROME EVIDENCE_DIR
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
const {chromium}=createRequire(import.meta.url)(process.argv[3]);
const browser=await chromium.launch({headless:true,executablePath:process.argv[4]});
const page=await browser.newPage({viewport:{width:1240,height:1180}}),errors=[],records=[];let checks=0;
const check=v=>{assert(v);checks++;},deep=(a,b)=>{assert.deepEqual(a,b);checks++;};
page.on('pageerror',e=>errors.push(e.message));await mkdir(process.argv[5],{recursive:true});
const graph=()=>page.evaluate(()=>JSON.parse(JSON.stringify(window.graph.serialize())));
const stable=g=>g.nodes.map(n=>({id:n.id,type:n.type,widgets:n.widgets_values,properties:n.properties}));
// LiteGraph recomputes the derived execution order during add/remove. Keep all
// persisted node fields, ports and links in the rollback comparison.
const persistentNodes=g=>g.nodes.map(({order,...node})=>node);
const project=()=>page.evaluate(()=>deskNode.zfMediaDesk.getProject());
const sync=()=>page.waitForFunction(()=>document.querySelector('.zf-med')?.getAttribute('aria-busy')==='false');
const send=()=>page.getByRole('button',{name:'发送原素材',exact:true}).click();
const select=id=>page.locator(`[data-asset-id="${id}"]`).click();
try {
    await page.request.post(process.argv[2]+'/test/phase',{data:{phase:'fixed'}});
    await page.goto(process.argv[2]);await page.waitForFunction(()=>window.ready);await sync();
    const paths=await (await page.request.get(process.argv[2]+'/fixtures')).json(),chooser=page.waitForEvent('filechooser');
    await page.locator('[data-action=import]').click();await (await chooser).setFiles(paths);
    await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===3);await sync();
    const p=await project(),picture=p.assets.find(a=>a.kind==='picture');
    // Upgrade an actual serialized two-output desk only after new backend defs.
    const legacy=await page.evaluate(async()=>{
        const Ctor=LiteGraph.registered_node_types.ZVUniversalMediaEvidenceDesk;
        await app.extensions.find(e=>e.name==='ZV.UniversalMediaEvidenceDesk').beforeRegisterNodeDef(Ctor,{name:'ZVUniversalMediaEvidenceDesk',output:['ZV_MEDIA_PROJECT','STRING','ZV_ORIGINAL_SOURCES']});
        const outlet=LiteGraph.createNode('ZVPictureOutlet');graph.add(outlet);deskNode.connect(0,outlet,0);
        const saved=JSON.parse(JSON.stringify(graph.serialize()));saved.nodes.find(n=>n.type==='ZVUniversalMediaEvidenceDesk').outputs=saved.nodes.find(n=>n.type==='ZVUniversalMediaEvidenceDesk').outputs.slice(0,2);return saved;
    });
    await page.evaluate(data=>loadSaved(data),legacy);await sync();const upgraded=await graph();
    deep(upgraded.nodes.find(n=>n.type==='ZVUniversalMediaEvidenceDesk').outputs.map(o=>o.type),['ZV_MEDIA_PROJECT','STRING','ZV_ORIGINAL_SOURCES']);deep(upgraded.links,legacy.links);
    // A saved old independent original node keeps its handle and downstream.
    const independent=await page.evaluate(asset=>{
        const n=LiteGraph.createNode('ZVOriginalPictureOutlet');n.widgets[0].value=asset.source_handle;graph.add(n);const sink=LiteGraph.createNode('TestSink');graph.add(sink);n.connect(0,sink,0);return JSON.parse(JSON.stringify(graph.serialize())).nodes.find(row=>row.type==='ZVOriginalPictureOutlet'&&row.widgets_values[0]===asset.source_handle);
    },picture);
    check(!!independent);
    for(const asset of p.assets) {
        await select(asset.asset_id);await page.evaluate(()=>installTracker());
        check(await page.evaluate(()=>tracker.changeCount===0));
        const before=await graph(),beforeProject=await project();await send();const after=await graph();
        const type='ZVOriginal'+({picture:'Picture',video:'Video',audio:'Audio'}[asset.kind])+'Outlet';
        const n=after.nodes.find(n=>n.type===type&&n.widgets_values[1]===asset.asset_id);
        check(!!n);deep(n.widgets_values,['',asset.asset_id]);deep(n.outputs.map(o=>o.type),[asset.kind==='picture'?'IMAGE':asset.kind==='video'?'VIDEO':'AUDIO','STRING','STRING','STRING']);
        check(after.links.some(l=>l[1]===after.nodes.find(n=>n.type==='ZVUniversalMediaEvidenceDesk').id&&l[2]===2&&l[3]===n.id&&l[4]===0&&l[5]==='ZV_ORIGINAL_SOURCES'));
        deep(after.links.filter(l=>before.links.some(old=>old[0]===l[0])),before.links);deep(await project(),beforeProject);
        await send();deep(stable(await graph()),stable(after));deep((await graph()).links,after.links);
        check(await page.evaluate(()=>tracker.changeCount===0));
        await page.waitForFunction(()=>tracker.undoQueue.length===1);await page.evaluate(()=>tracker.undo());await sync();deep(stable(await graph()),stable(before));deep((await graph()).links,before.links);
        await page.evaluate(()=>tracker.redo());await sync();deep(stable(await graph()),stable(after));deep((await graph()).links,after.links);
        check(await page.evaluate(()=>tracker.changeCount===0));
        records.push({name:'real original source '+asset.kind,id:n.id,asset_id:asset.asset_id,input:n.inputs[0],outputs:n.outputs.map(o=>o.type)});
    }
    deep((await graph()).nodes.find(n=>n.id===independent.id).widgets_values,independent.widgets_values);
    // Four downstream output bindings survive reuse and serialization.
    await select(picture.asset_id);
    await page.evaluate(id=>{const n=graph.findNodesByType('ZVOriginalPictureOutlet').find(n=>n.widgets[1].value===id);for(let i=0;i<4;i++){const sink=LiteGraph.createNode('TestSink');sink.inputs[0].type=n.outputs[i].type;graph.add(sink);n.connect(i,sink,0);}},picture.asset_id);
    const wired=await graph();await send();deep(stable(await graph()),stable(wired));deep((await graph()).links,wired.links);
    await page.evaluate(data=>loadSaved(data),wired);await sync();deep(stable(await graph()),stable(wired));deep((await graph()).links,wired.links);
    // A disconnected new asset_id remains marked; a new click creates a new edge/node.
    await page.evaluate(id=>{const n=graph.findNodesByType('ZVOriginalPictureOutlet').find(n=>n.widgets[1].value===id);n.disconnectInput(0);},picture.asset_id);
    const disconnected=await graph();await select(picture.asset_id);await send();const reconnected=await graph();check(reconnected.nodes.length===disconnected.nodes.length+1);
    deep(reconnected.nodes.find(n=>n.id===wired.nodes.find(n=>n.type==='ZVOriginalPictureOutlet'&&n.widgets_values[1]===picture.asset_id).id).widgets_values,['',picture.asset_id]);
    deep(reconnected.links.filter(l=>disconnected.links.some(old=>old[0]===l[0])),disconnected.links);
    // Another desk's connected node with the same file is never borrowed.
    await page.evaluate(asset=>{const other=new LGraph(),d=LiteGraph.createNode('ZVUniversalMediaEvidenceDesk');d.widgets[0].value=deskNode.widgets[0].value;other.add(d);outlets.createOriginalOutlet(d,asset,{canvas:{graph:other}});window.foreignGraph=other;window.foreignDesk=d;},picture);
    await page.waitForFunction(()=>foreignDesk.zfMediaDesk?.root.getAttribute('aria-busy')==='false');
    const foreign=await page.evaluate(()=>JSON.parse(JSON.stringify(foreignGraph.serialize())));
    await send();deep(await page.evaluate(()=>JSON.parse(JSON.stringify(foreignGraph.serialize()))),foreign);
    // Source connection faults and transaction failures only retract the new node.
    for(const fault of ['connect_null','connect_throw','connect_after_throw','wrong_source','after_once','after_persistent','after_before_failure']) {
        const result=await page.evaluate(({asset,fault})=>{
            const before=JSON.parse(JSON.stringify(graph.serialize())),connect=deskNode.connect,after=graph.afterChange,beforeChange=graph.beforeChange;let afterCalls=0,beforeCalls=0;
            deskNode.connect=function(...args){if(fault==='connect_null')return null;if(fault==='connect_throw')throw Error('connect failed');const result=connect.apply(this,args);if(fault==='connect_after_throw')throw Error('connect after registration');if(fault==='wrong_source')graph.getLink(args[1].inputs[args[2]].link).origin_slot=0;return result;};
            graph.afterChange=function(...args){const result=after.apply(this,args);afterCalls++;if(fault==='after_persistent'||fault.startsWith('after_')&&afterCalls===1)throw Error('afterChange failed');return result;};
            graph.beforeChange=function(...args){beforeCalls++;if(fault==='after_before_failure'&&beforeCalls===2)throw Error('second beforeChange failed');return beforeChange.apply(this,args);};
            let error='';try{outlets.createOriginalOutlet(deskNode,{...asset,asset_id:'fault_'+fault},app);}catch(e){error=e.message;}
            deskNode.connect=connect;graph.afterChange=after;graph.beforeChange=beforeChange;
            return {error,before,after:JSON.parse(JSON.stringify(graph.serialize()))};
        },{asset:picture,fault});
        check(!!result.error);deep(persistentNodes(result.after),persistentNodes(result.before));deep(result.after.links,result.before.links);records.push({name:fault,error:result.error});
    }
    // New JS against old registered classes must diagnose a normal restart.
    for(const old of ['desk','outlet']) {
        const result=await page.evaluate(({asset,old})=>{
            const before=JSON.parse(JSON.stringify(graph.serialize())),outputs=deskNode.outputs,create=LiteGraph.createNode;
            if(old==='desk')deskNode.outputs=outputs.slice(0,2);
            else LiteGraph.createNode=function(type){const n=create.call(this,type);if(type.includes('Original')){n.inputs=[];n.widgets=n.widgets.slice(0,1);}return n;};
            let error='';try{outlets.createOriginalOutlet(deskNode,{...asset,asset_id:'old_backend_'+old},app);}catch(e){error=e.message;}
            deskNode.outputs=outputs;LiteGraph.createNode=create;return {error,before,after:JSON.parse(JSON.stringify(graph.serialize()))};
        },{asset:picture,old});
        check(result.error.includes('重启 ComfyUI')&&result.error.includes('刷新页面'));deep(stable(result.after),stable(result.before));deep(result.after.links,result.before.links);
    }
    await select(picture.asset_id);await page.screenshot({path:join(process.argv[5],'SOURCE_UI_STATE.png')});
    deep(errors,[]);await writeFile(join(process.argv[5],'BROWSER_VERIFIED.json'),JSON.stringify({scope:'real HTTP CPU pool and installed LiteGraph/ChangeTracker; neutral registered node constructors and app graph loader, not user service/generation',checks,errors,records,graph:await graph()},null,2));
    console.log(`H3_V2_07_UI_OK ${checks} checks; real source links/old two-output upgrade/three bindings/history/save-load/fault rollback; 0 page errors`);
} finally {await browser.close();}
