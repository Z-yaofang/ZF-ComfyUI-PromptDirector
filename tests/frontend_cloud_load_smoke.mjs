// Real browser ESM loading through a local simulation of cloud asset publication.
// node tests/frontend_cloud_load_smoke.mjs PLAYWRIGHT_PACKAGE CHROMIUM_EXECUTABLE
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const {chromium}=createRequire(import.meta.url)(process.argv[2]||"playwright");
const names=["media_evidence_desk.js","media_evidence_core.mjs","media_evidence_presets.mjs","media_evidence_outlets.mjs","dom_widget_layout.mjs","media_processing_presets.json","media_evidence_desk.css"];
const files=Object.fromEntries(await Promise.all(names.map(async name=>[name,await readFile(new URL(`../web/${name}`,import.meta.url),"utf8")])));
const publishedName=name=>/\.m?js$/.test(name)?name.replace(/\.m?js$/,`__${createHash("sha256").update(files[name]).digest("hex").slice(0,8)}.js`):name;

// The observed publisher rewrites bare .mjs imports to hashed .js names, but
// query-bearing imports only get their extension changed and then return 404.
function publish(source) {
    return source.replace(/(["'])\.\/([^"']+\.mjs)([?#][^"']*)?\1/g,(_match,quote,name,suffix)=>
        `${quote}./${suffix?name.replace(/\.mjs$/,".js")+suffix:publishedName(name)}${quote}`);
}
const legacy=files["media_evidence_desk.js"].replace(/(["'])\.\/media_evidence_outlets\.mjs(?:[?#][^"']*)?\1/,
    '"./media_evidence_outlets.mjs?v=h3-v2-07"');
const builtins=JSON.parse(files["media_processing_presets.json"]);
const requests=[],unexpected=[];
const server=createServer(async(request,response)=>{
    try {
        const url=new URL(request.url,"http://localhost");
        const send=(status,type,body)=>{response.writeHead(status,{"Content-Type":type});response.end(body);};
        const json=value=>send(200,"application/json",JSON.stringify(value));
        requests.push({path:url.pathname,query:url.search});
        if(url.pathname==="/")return send(200,"text/html",'<!doctype html><meta charset="utf-8"><title>Isolated cloud module test</title><style>body{background:#15202a;margin:20px}#mount{width:1200px}</style><div id="mount"></div>');
        if(url.pathname==="/scripts/app.js")return send(200,"application/javascript","export const app={extensions:[],registerExtension(extension){this.extensions.push(extension);}};");
        if(url.pathname==="/favicon.ico")return send(204,"image/x-icon","");
        if(url.pathname==="/zf-media-evidence/presets")return json({ok:true,builtins,users:[]});
        if(url.pathname==="/zf-media-evidence/normalize"&&request.method==="POST"){
            let body="";for await(const chunk of request)body+=chunk;
            const project=JSON.parse(body);
            project.label_map=["picture","video","audio"].flatMap(track=>project[`${track}_track`].map((clip,index)=>({item_id:clip.item_id||clip.clip_id,label:`${track} ${index+1}`})));
            project.validation={errors:[],warnings:[]};
            return json({ok:true,project});
        }
        if(url.pathname==="/zf-media-evidence/preview")return url.searchParams.get("variant")==="peaks"?
            json({peaks:[0,.3,.7,.2]}):send(200,"image/svg+xml",'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="#389"/></svg>');
        const match=url.pathname.match(/^\/(legacy|current)\/extensions\/([^/]+)$/);
        if(match){
            const name=names.find(name=>publishedName(name)===match[2]);
            if(name){
                const source=name==="media_evidence_desk.js"&&match[1]==="legacy"?legacy:files[name];
                const type=name.endsWith(".json")?"application/json":name.endsWith(".css")?"text/css":"application/javascript";
                return send(200,type,/\.m?js$/.test(name)?publish(source):source);
            }
        }
        if(url.pathname!=="/legacy/extensions/media_evidence_outlets.js")unexpected.push(url.pathname);
        send(404,"text/plain","No asset published at this path");
    } catch(error){unexpected.push(error.message);response.writeHead(500);response.end("Harness error");}
});
await new Promise((resolve,reject)=>{server.once("error",reject);server.listen(0,"127.0.0.1",resolve);});
const origin=`http://127.0.0.1:${server.address().port}`;
let browser;
try {
    browser=await chromium.launch({headless:true,executablePath:process.argv[3]});
    const context=await browser.newContext({viewport:{width:1280,height:1200}});
    await context.route("**/*",route=>{
        if(new URL(route.request().url()).origin===origin)return route.continue();
        unexpected.push(`external request: ${route.request().url()}`);return route.abort();
    });
    for(const mode of ["legacy","current"]){
        const page=await context.newPage(),errors=[];
        page.on("pageerror",error=>errors.push(error.message));
        await page.goto(origin);
        const result=await page.evaluate(async moduleURL=>{
            window.app=(await import("/scripts/app.js")).app;
            try {await import(moduleURL);return {loaded:true,count:app.extensions.length};}
            catch(error){return {loaded:false,count:app.extensions.length,error:error.message};}
        },`${origin}/${mode}/extensions/${publishedName("media_evidence_desk.js")}`);
        if(mode==="legacy"){
            assert.equal(result.loaded,false,"The regression fixture must fail in the real ESM loader");
            assert.equal(result.count,0,"Dependency failure must prevent extension registration");
            assert(requests.some(r=>r.path==="/legacy/extensions/media_evidence_outlets.js"&&r.query==="?v=h3-v2-07"));
        } else {
            assert.deepEqual(result,{loaded:true,count:1});
            assert(requests.some(r=>r.path===`/current/extensions/${publishedName("media_evidence_outlets.mjs")}`));
            await page.evaluate(async coreURL=>{
                const core=await import(coreURL);
                window.fixture=core.addAsset(core.addAsset(core.freshProject(),{
                    asset_id:"picture_test",name:"generated-picture.png",kind:"picture",source_handle:`originals/${"a".repeat(32)}.png`,
                    probe:{width:320,height:180,has_audio:false,duration_seconds:null,fps:null},
                },0,()=>"picture_item"),{
                    asset_id:"video_test",name:"generated-video.mp4",kind:"video",source_handle:`originals/${"b".repeat(32)}.mp4`,
                    probe:{width:320,height:180,has_audio:true,duration_seconds:2,fps:24,frame_count:48,frame_count_exact:true,vfr:false},
                },1,(()=>{let id=0;return ()=>`clip_${++id}`;})());
                window.mountDesk=(saved=null)=>{
                    window.deskNode?.onRemoved?.();
                    const state=saved||{type:"ZVUniversalMediaEvidenceDesk",widgets_values:[JSON.stringify(core.freshProject())],properties:{}};
                    window.deskNode={...state,comfyClass:state.type,widgets:[{name:"project_data",value:state.widgets_values[0]}],size:[1200,1100],setDirtyCanvas(){},setSize(){},addDOMWidget(_name,_type,root){document.querySelector("#mount").append(root);return {};}};
                    const extension=app.extensions[0];
                    extension[saved?"loadedGraphNode":"nodeCreated"](deskNode);
                };
                mountDesk();
            },`${origin}/current/extensions/${publishedName("media_evidence_core.mjs")}`);
            const ready=()=>page.waitForFunction(()=>!!window.deskNode?.zfMediaDesk&&document.querySelector(".zf-med")?.getAttribute("aria-busy")==="false");
            await ready();
            assert.equal(await page.locator(".zf-med").count(),1);
            assert.equal(await page.locator(".zf-med-playhead-frame").isVisible(),true);
            assert.deepEqual(await page.evaluate(()=>deskNode.zfMediaDesk.getProject().assets),[]);
            const before=await page.evaluate(()=>{
                const saved=JSON.parse(JSON.stringify({type:"ZVUniversalMediaEvidenceDesk",widgets_values:[JSON.stringify(fixture)],properties:{zf_media_desk_view:{playhead:1.25,zoom:40}}}));
                mountDesk(saved);return JSON.parse(saved.widgets_values[0]);
            });
            await ready();
            const after=await page.evaluate(()=>JSON.parse(deskNode.widgets[0].value));
            for(const key of ["assets","picture_track","video_track","audio_track","project_clock","processing_window","processing_preset"])assert.deepEqual(after[key],before[key],`Restoring a saved node must preserve ${key}`);
            assert.equal(await page.locator(".zf-med-clip.picture").count(),1);
            assert.equal(await page.locator(".zf-med-clip.video").count(),1);
            assert.equal(await page.locator(".zf-med-clip.audio").count(),1);
            await page.evaluate(async()=>{
                app.extensions[0].loadedGraphNode(deskNode);
                await new Promise(resolve=>setTimeout(resolve,0));
            });
            await ready();
            assert.equal(await page.locator(".zf-med").count(),1,"Reload hooks must reuse the panel");
            assert.deepEqual(errors,[]);
            await page.evaluate(()=>deskNode.onRemoved());
        }
        await page.close();
    }
    assert.deepEqual(unexpected,[]);
    console.log("FRONTEND_CLOUD_LOAD_OK legacy query import fails before registration; current hashed ESM loads; empty and saved desks mount without changing media");
} finally {
    await browser?.close();
    server.closeAllConnections();
    await new Promise(resolve=>server.close(resolve));
}
