// Actual Chrome HTTP cache upgrade: no page/context routing or cache disabling.
// node TEST URL PLAYWRIGHT CHROME EVIDENCE_DIR [--reproduce-only]
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
const {chromium}=createRequire(import.meta.url)(process.argv[3]);
const origin=process.argv[2],out=process.argv[5],version='h3-v2-06-ui-01';
const browser=await chromium.launch({headless:true,executablePath:process.argv[4]});
const context=await browser.newContext({viewport:{width:1240,height:1180}}),page=await context.newPage();
const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');
const network=[],errors=[],records=[];let checks=0;
const check=v=>{assert(v);checks++;},deep=(a,b)=>{assert.deepEqual(a,b);checks++;};
cdp.on('Network.requestWillBeSent',e=>{if(e.request.url.includes('/extensions/'))network.push({event:'request',id:e.requestId,url:e.request.url});});
cdp.on('Network.requestServedFromCache',e=>network.push({event:'cache',id:e.requestId}));
cdp.on('Network.responseReceived',e=>{if(e.response.url.includes('/extensions/'))network.push({event:'response',id:e.requestId,url:e.response.url,fromDiskCache:e.response.fromDiskCache,fromServiceWorker:e.response.fromServiceWorker,status:e.response.status});});
page.on('pageerror',e=>errors.push(e.message));
await mkdir(out,{recursive:true});
const phase=async name=>{const r=await page.request.post(origin+'/test/phase',{data:{phase:name}});assert(r.ok());};
const ready=()=>page.waitForFunction(()=>window.ready);
const sync=()=>page.waitForFunction(()=>document.querySelector('.zf-med')?.getAttribute('aria-busy')==='false');
const project=()=>page.evaluate(()=>deskNode.zfMediaDesk.getProject());
const graph=()=>page.evaluate(()=>JSON.parse(JSON.stringify(window.graph.serialize())));
const stable=g=>g.nodes.map(n=>({id:n.id,type:n.type,widgets:n.widgets_values,properties:n.properties}));
const select=id=>page.locator(`[data-asset-id="${id}"]`).click();
const original=()=>page.getByRole('button',{name:'发送原素材',exact:true});
const importFixtures=async()=>{
    const fixtures=await (await page.request.get(origin+'/fixtures')).json();
    const chooser=page.waitForEvent('filechooser');await page.locator('[data-action=import]').click();await (await chooser).setFiles(fixtures);
    await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===3);await sync();
    return project();
};
let serverStart=0;
const serverRecords=async()=> (await (await page.request.get(origin+'/test/records')).json()).slice(serverStart);
try {
    serverStart=(await serverRecords()).length;
    await phase('prime');await page.goto(origin+'/?stage=prime');await ready();
    check(await page.evaluate(()=>typeof oldOutlets.createOriginalOutlet==='undefined'&&typeof oldOutlets.createMediaOutlets==='function'));
    const primeRequests=await serverRecords();
    deep(primeRequests.filter(r=>r.phase==='prime'&&r.path==='/extensions/media_evidence_outlets.mjs').length,1);
    deep(primeRequests.filter(r=>r.phase==='prime'&&r.path==='/extensions/media_evidence_slots.mjs').length,1);
    await phase('mixed');await page.goto(origin+'/?stage=mixed');await ready();await sync();
    check(await page.evaluate(()=>typeof outlets.createOriginalOutlet==='undefined'));
    const p=await importFixtures(),video=p.assets.find(a=>a.kind==='video');
    await select(video.asset_id);const before=await graph(),beforeProject=await project();await original().click();
    check((await page.locator('.zf-med-status').textContent()).includes('outlets.createOriginalOutlet is not a function'));
    check(await page.locator('.zf-med-status').evaluate(e=>e.classList.contains('error')));
    deep(stable(await graph()),stable(before));deep(await project(),beforeProject);
    const mixedRequests=await serverRecords();
    deep(mixedRequests.filter(r=>r.phase==='mixed'&&r.path==='/extensions/media_evidence_outlets.mjs').length,0);
    deep(mixedRequests.filter(r=>r.phase==='mixed'&&r.path==='/extensions/media_evidence_slots.mjs').length,0);
    check(network.some(r=>r.event==='cache'&&network.some(q=>q.event==='request'&&q.id===r.id&&q.url.endsWith('/media_evidence_outlets.mjs'))));
    check(network.some(r=>r.event==='cache'&&network.some(q=>q.event==='request'&&q.id===r.id&&q.url.endsWith('/media_evidence_slots.mjs'))));
    records.push({name:'mixed cache actual reproduction',status:await page.locator('.zf-med-status').textContent(),prime_http_mjs_requests:1,mixed_http_mjs_requests:0,prime_http_slots_requests:1,mixed_http_slots_requests:0});
    await page.screenshot({path:join(out,'CACHE_MIXED_REPRODUCED.png')});
    if(!process.argv.includes('--reproduce-only')) {
        // Same browser/context, ordinary navigation; old URI remains cached.
        await phase('fixed');await page.goto(origin+'/?stage=fixed');await ready();await sync();
        check(await page.evaluate(()=>typeof outlets.createOriginalOutlet==='function'));
        const assets=(await importFixtures()).assets;
        for(const asset of assets) {
            await select(asset.asset_id);await page.evaluate(()=>installTracker());
            const oldGraph=await graph(),oldProject=await project();await original().click();const created=await graph();
            const type='ZVOriginal'+({picture:'Picture',video:'Video',audio:'Audio'}[asset.kind])+'Outlet';
            const node=created.nodes.find(n=>n.type===type&&n.widgets_values[0]===asset.source_handle);
            check(!!node);deep(node.outputs.map(o=>o.type),[asset.kind==='picture'?'IMAGE':asset.kind==='video'?'VIDEO':'AUDIO','STRING','STRING','STRING']);
            deep(node.widgets_values,[asset.source_handle]);deep(await project(),oldProject);deep(created.links,oldGraph.links);
            check(!(await page.locator('.zf-med-status').evaluate(e=>e.classList.contains('error'))));
            await original().click();deep(stable(await graph()),stable(created));
            await page.waitForFunction(()=>tracker.undoQueue.length===1);
            await page.evaluate(()=>tracker.undo());await sync();deep(stable(await graph()),stable(oldGraph));deep((await graph()).links,oldGraph.links);
            await page.evaluate(()=>tracker.redo());await sync();deep(stable(await graph()),stable(created));deep((await graph()).links,created.links);
            // All four downstream output bindings survive reuse and graph save/load.
            await page.evaluate(({id,types})=>{
                const original=graph.getNodeById(id);
                for(let i=0;i<4;i++){const sink=LiteGraph.createNode('TestSink');sink.inputs[0].type=types[i];graph.add(sink);original.connect(i,sink,0);}
            },{id:node.id,types:node.outputs.map(o=>o.type)});
            const boundChanged=await graph();await select(asset.asset_id);await original().click();
            deep(stable(await graph()),stable(boundChanged));deep((await graph()).links,boundChanged.links);
            records.push({name:'versioned '+asset.kind,node_id:node.id,source_handle:asset.source_handle,output_types:node.outputs.map(o=>o.type),wired_outputs:4});
        }
        const saved=await graph();await page.evaluate(data=>loadSaved(data),saved);await sync();deep(stable(await graph()),stable(saved));deep((await graph()).links,saved.links);
        const fixtureRequests=await serverRecords();
        deep(fixtureRequests.filter(r=>r.phase==='fixed'&&r.path===`/extensions/media_evidence_outlets.mjs?v=${version}`).length,1);
        deep(fixtureRequests.filter(r=>r.phase==='fixed'&&r.path===`/extensions/media_evidence_slots.mjs?v=${version}`).length,1);
        deep(fixtureRequests.filter(r=>r.phase==='fixed'&&r.path==='/extensions/media_evidence_outlets.mjs').length,0);
        check(await page.evaluate(async version=>outlets===await import(`/extensions/media_evidence_outlets.mjs?v=${version}`),version));
        await select(assets.find(a=>a.kind==='video').asset_id);await page.screenshot({path:join(out,'CACHE_FIXED_THREE_ORIGINALS.png')});
        // Node type really absent in the native registry: give a restart diagnostic.
        const audio=assets.find(a=>a.kind==='audio');await select(audio.asset_id);
        await page.evaluate(()=>{window.audioCtor=LiteGraph.registered_node_types.ZVOriginalAudioOutlet;for(const n of graph.findNodesByType('ZVOriginalAudioOutlet'))graph.remove(n);LiteGraph.unregisterNodeType('ZVOriginalAudioOutlet');});
        const missingBefore=await graph();await original().click();
        const missingStatus=await page.locator('.zf-med-status').textContent();check(missingStatus.includes('重启 ComfyUI')&&missingStatus.includes('刷新页面'));check(!missingStatus.includes('is not a function'));
        deep(stable(await graph()),stable(missingBefore));deep((await graph()).links,missingBefore.links);
        await page.evaluate(()=>LiteGraph.registerNodeType('ZVOriginalAudioOutlet',audioCtor));records.push({name:'missing native node registration diagnostic',status:missingStatus});
        await page.screenshot({path:join(out,'MISSING_NODE_DIAGNOSTIC.png')});
        // Separate fresh context deliberately serves an old namespace at the new key.
        await phase('missing_api');const guardContext=await browser.newContext(),guardPage=await guardContext.newPage();
        guardPage.on('pageerror',e=>errors.push(e.message));await guardPage.goto(origin+'/?stage=missing_api');await guardPage.waitForFunction(()=>window.ready);await guardPage.waitForFunction(()=>document.querySelector('.zf-med')?.getAttribute('aria-busy')==='false');
        const paths=await (await guardPage.request.get(origin+'/fixtures')).json(),chooser=guardPage.waitForEvent('filechooser');
        await guardPage.locator('[data-action=import]').click();await (await chooser).setFiles(paths);
        await guardPage.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===3&&document.querySelector('.zf-med')?.getAttribute('aria-busy')==='false');
        const id=await guardPage.evaluate(()=>deskNode.zfMediaDesk.getProject().assets.find(a=>a.kind==='video').asset_id);await guardPage.locator(`[data-asset-id="${id}"]`).click();
        const guardBefore=await guardPage.evaluate(()=>JSON.parse(JSON.stringify(graph.serialize())));await guardPage.getByRole('button',{name:'发送原素材',exact:true}).click();
        const guardStatus=await guardPage.locator('.zf-med-status').textContent();check(guardStatus.includes('模块版本不匹配')&&guardStatus.includes('刷新页面'));check(!guardStatus.includes('is not a function'));
        deep(await guardPage.evaluate(()=>JSON.parse(JSON.stringify(graph.serialize()))),guardBefore);records.push({name:'missing API diagnostic',status:guardStatus});await guardContext.close();
    }
    deep(errors,[]);
    const result={scope:'real Chrome HTTP cache, same browser/context prime→mixed→fixed, no Playwright routing/cache disabling; installed LiteGraph/ChangeTracker with neutral node constructors and graph reload; real own HTTP/CPU media fixtures; fixture aged Last-Modified, not user-cache observation',checks,errors,version,network,records,server_records:await serverRecords()};
    await writeFile(join(out,process.argv.includes('--reproduce-only')?'CACHE_REPRO_BEFORE.json':'CACHE_UPGRADE_VERIFIED.json'),JSON.stringify(result,null,2));
    console.log(`H3_V2_06_UI_01_CACHE_OK ${checks} checks; actual HTTP cached old MJS reproduced${process.argv.includes('--reproduce-only')?'':' and versioned imports recovered three originals/history/output wires'}; 0 page errors`);
} finally {await browser.close();}
