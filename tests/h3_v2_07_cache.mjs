// Fixed 07 imports escape a real cached UI01 helper; no Playwright routing.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {writeFile,mkdir} from 'node:fs/promises';
import {join} from 'node:path';
const {chromium}=createRequire(import.meta.url)(process.argv[3]),origin=process.argv[2],out=process.argv[5];
const browser=await chromium.launch({headless:true,executablePath:process.argv[4]});
const context=await browser.newContext({viewport:{width:1240,height:1180}}),page=await context.newPage(),cdp=await context.newCDPSession(page);
await cdp.send('Network.enable');const events=[],errors=[];let checks=0;
const check=v=>{assert(v);checks++;},deep=(a,b)=>{assert.deepEqual(a,b);checks++;};
cdp.on('Network.requestWillBeSent',e=>{if(e.request.url.includes('/extensions/'))events.push({event:'request',id:e.requestId,url:e.request.url});});
cdp.on('Network.requestServedFromCache',e=>events.push({event:'cache',id:e.requestId}));
cdp.on('Network.responseReceived',e=>{if(e.response.url.includes('/extensions/'))events.push({event:'response',id:e.requestId,url:e.response.url,fromDiskCache:e.response.fromDiskCache,fromServiceWorker:e.response.fromServiceWorker,status:e.response.status});});
page.on('pageerror',e=>errors.push(e.message));await mkdir(out,{recursive:true});
const phase=name=>page.request.post(origin+'/test/phase',{data:{phase:name}});
let start=0;const records=async()=> (await (await page.request.get(origin+'/test/records')).json()).slice(start);
const ready=()=>page.waitForFunction(()=>window.ready),sync=()=>page.waitForFunction(()=>document.querySelector('.zf-med')?.getAttribute('aria-busy')==='false');
const graph=()=>page.evaluate(()=>JSON.parse(JSON.stringify(window.graph.serialize()))),project=()=>page.evaluate(()=>deskNode.zfMediaDesk.getProject());
const stable=g=>g.nodes.map(n=>({id:n.id,type:n.type,widgets:n.widgets_values,properties:n.properties}));
try {
    start=(await records()).length;
    await phase('prime');await page.goto(origin+'/?phase=prime');await ready();
    check(await page.evaluate(()=>typeof legacyOutlets.createOriginalOutlet==='function'&&!legacyOutlets.createOriginalOutlet.toString().includes('original_sources')));
    for(const name of ['media_evidence_outlets.mjs'])deep((await records()).filter(r=>r.phase==='prime'&&r.path===`/extensions/${name}?v=h3-v2-06-ui-01`).length,1);
    await phase('mixed');await page.goto(origin+'/?phase=mixed');await ready();
    check(await page.evaluate(()=>!legacyOutlets.createOriginalOutlet.toString().includes('original_sources')));
    for(const name of ['media_evidence_outlets.mjs']) {
        deep((await records()).filter(r=>r.phase==='mixed'&&r.path===`/extensions/${name}?v=h3-v2-06-ui-01`).length,0);
        check(events.some(e=>e.event==='cache'&&events.some(q=>q.event==='request'&&q.id===e.id&&q.url.endsWith(`/${name}?v=h3-v2-06-ui-01`))));
    }
    await phase('fixed');await page.goto(origin+'/?phase=fixed');await ready();await sync();
    check(await page.evaluate(()=>outlets.createOriginalOutlet.toString().includes('original_sources')));
    const paths=await (await page.request.get(origin+'/fixtures')).json(),chooser=page.waitForEvent('filechooser');
    await page.locator('[data-action=import]').click();await (await chooser).setFiles(paths);await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===3);await sync();
    const assets=(await project()).assets;
    for(const asset of assets) {
        await page.locator(`[data-asset-id="${asset.asset_id}"]`).click();await page.evaluate(()=>installTracker());
        const before=await graph(),beforeProject=await project();await page.getByRole('button',{name:'发送原素材',exact:true}).click();const created=await graph();
        check(await page.evaluate(()=>tracker.changeCount===0));
        const n=created.nodes.find(n=>n.widgets_values?.[1]===asset.asset_id&&n.type.includes('Original'));
        check(!!n);deep(n.widgets_values,['',asset.asset_id]);check(created.links.some(l=>l[1]===created.nodes.find(n=>n.type==='ZVUniversalMediaEvidenceDesk').id&&l[2]===2&&l[3]===n.id&&l[5]==='ZV_ORIGINAL_SOURCES'));
        deep(n.outputs.map(o=>o.type),[asset.kind==='picture'?'IMAGE':asset.kind==='video'?'VIDEO':'AUDIO','STRING','STRING','STRING']);deep(await project(),beforeProject);
        await page.getByRole('button',{name:'发送原素材',exact:true}).click();deep(stable(await graph()),stable(created));deep((await graph()).links,created.links);
        await page.waitForFunction(()=>tracker.undoQueue.length===1);await page.evaluate(()=>tracker.undo());await sync();deep(stable(await graph()),stable(before));deep((await graph()).links,before.links);
        check(await page.evaluate(()=>tracker.changeCount===0));
        await page.evaluate(()=>tracker.redo());await sync();deep(stable(await graph()),stable(created));deep((await graph()).links,created.links);
        check(await page.evaluate(()=>tracker.changeCount===0));
        await page.evaluate(id=>{const n=graph.getNodeById(id);for(let i=0;i<4;i++){const s=LiteGraph.createNode('TestSink');s.inputs[0].type=n.outputs[i].type;graph.add(s);n.connect(i,s,0);}},n.id);
    }
    const saved=await graph();await page.evaluate(data=>loadSaved(data),saved);await sync();deep(stable(await graph()),stable(saved));deep((await graph()).links,saved.links);
    await page.evaluate(data=>localStorage.setItem('graph06',JSON.stringify(data)),saved);await page.goto(origin+'/?phase=fixed-again');await ready();await sync();deep(stable(await graph()),stable(saved));deep((await graph()).links,saved.links);
    for(const name of ['media_evidence_outlets.mjs']) {
        deep((await records()).filter(r=>r.phase==='fixed'&&r.path===`/extensions/${name}?v=h3-v2-07`).length,1);
        deep((await records()).filter(r=>r.phase==='fixed'&&r.path===`/extensions/${name}?v=h3-v2-06-ui-01`).length,0);
    }
    check(await page.evaluate(async()=>outlets===await import('/extensions/media_evidence_outlets.mjs?v=h3-v2-07')));
    await page.screenshot({path:join(out,'CACHE_THREE_SOURCE_LINKS.png')});deep(errors,[]);
    await writeFile(join(out,'CACHE_VERIFIED.json'),JSON.stringify({scope:'actual Chrome HTTP cache in same browser/context; full legacy UI01 helper cached; new 07 desk/imports create real source edges; no routing/cache disable; aged fixture Last-Modified explicitly differs from current user service; installed native graph/tracker, neutral constructors/load adapter',checks,errors,events,server_records:await records(),graph:saved},null,2));
    console.log(`H3_V2_07_CACHE_OK ${checks} checks; old-key HTTP delta1/0, new-key delta1 with three real source links/history/output bindings/reload; 0 page errors`);
} finally {await browser.close();}
