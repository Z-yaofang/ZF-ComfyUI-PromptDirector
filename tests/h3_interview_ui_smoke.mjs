// node tests/h3_interview_ui_smoke.mjs PLAYWRIGHT_PACKAGE CHROMIUM [SCREENSHOT] [PYTHON]
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const { chromium } = createRequire(import.meta.url)(process.argv[2] || "playwright");
const python = spawn(process.argv[5] || "E:/AI_Models/ComfyUI-TE-0/python_embeded/python.exe", [fileURLToPath(new URL(process.argv.includes('--stage04') ? "./h3_v2_04_rpc.py" : process.argv.includes('--stage03') ? "./h3_v2_03_rpc.py" : "./h3_v2_plan_rpc.py", import.meta.url))], { windowsHide: true, stdio: ["pipe", "pipe", "inherit"] });
const pending = new Map(); let nextRequest = 0;
createInterface({ input: python.stdout }).on("line", line => {
  const value = JSON.parse(line), request = pending.get(value.id); pending.delete(value.id);
  value.error ? request.reject(new Error(value.error)) : request.resolve(value.result);
});
python.on("exit", code => { for (const request of pending.values()) request.reject(new Error(`Python RPC exited ${code}`)); pending.clear(); });
const rpc = value => new Promise((resolve, reject) => { const id = ++nextRequest; pending.set(id, { resolve, reject }); python.stdin.write(`${JSON.stringify({ id, ...value })}\n`); });
const source = await readFile(new URL("../web/h3_interview.js", import.meta.url), "utf8");
const css = await readFile(new URL("../web/h3_interview.css", import.meta.url), "utf8");
const helper = await readFile(new URL("../web/dom_widget_layout.mjs", import.meta.url), "utf8");
const presetModule = await readFile(new URL("../web/h3_interview_presets.mjs", import.meta.url), "utf8");
const mediaCore = await readFile(new URL("../web/media_evidence_core.mjs", import.meta.url), "utf8");
const mediaPresets = await readFile(new URL("../web/media_evidence_presets.mjs", import.meta.url), "utf8");
const mediaDefinitions = await readFile(new URL("../web/media_processing_presets.json", import.meta.url), "utf8");
const fixture = await rpc({ action: "fixture" });
const browser = await chromium.launch({ headless: true, executablePath: process.argv[3] });
const page = await browser.newPage({ viewport: { width: 1500, height: 1060 } });
const errors = []; let scenarios = 0, assertions = 0, previews = 0, lastPlan = null;
page.on("pageerror", error => errors.push(error.message));
const check = (condition, message) => { assert(condition, message); assertions++; };
const deep = (actual, expected) => { assert.deepEqual(actual, expected); assertions++; };
const html = `<!doctype html><meta charset="utf-8"><title>H3 V2 UI smoke — neutral fixtures</title><style>
body{margin:20px;background:#0d131c;color:#fff;font-family:system-ui}#outside{position:fixed;right:18px;top:18px;z-index:3}#mount{width:1260px;height:1000px}
</style><button id="outside">画布空白</button><div id="mount"></div><script type="module">
import { app } from "/scripts/app.js"; import * as h3 from "/interview.js"; window.h3=h3;
window.fixture=${JSON.stringify(fixture)}; window.deskEvents=new EventTarget();
window.install=function(state=h3.emptyState(), project=fixture, savedGraph=null, canvasSpec=null){
  window.interviewNode?.onRemoved?.(); window.fixture=structuredClone(project);
  const hubNames=["first_frame","last_frame",...Array.from({length:9},(_,i)=>'ref_image_'+(i+1)),...Array.from({length:3},(_,i)=>'ref_video_'+(i+1)),...Array.from({length:3},(_,i)=>'ref_video_audio_'+(i+1)),"drive_audio","final_audio",...Array.from({length:3},(_,i)=>'ref_audio_'+(i+1)),"reference_plan_json","report"];
  let nodes,links;
  if(savedGraph){nodes=structuredClone(savedGraph.nodes);links=Object.fromEntries(savedGraph.links.map(row=>[row[0],{origin_id:row[1],origin_slot:row[2]}]));}
  else{
    const desk={id:165,type:"ZVUniversalMediaEvidenceDesk",inputs:[],outputs:[{name:"media_project"}]};
    const interview={id:172,type:"ZVH3InterviewForm",inputs:[{name:"media_project",link:1}],outputs:[]};
    const hub={id:182,type:"ZVH3ReferenceOutlet",inputs:[{name:"reference_plan",link:2}],outputs:hubNames.map(name=>({name}))};
    const stage={id:146,type:"ZFPromptDirectorLocalLLM",title:"Stage①",inputs:[{name:"prompt",link:3},{name:"role",link:4}],outputs:[]};
    const low={id:7,type:"MiniMaxH3AudioConditioningT8",title:"LOW",inputs:[{name:"prompt",link:5}],outputs:[]};
    const high={id:14,type:"MiniMaxH3AudioConditioningT8",title:"HIGH",inputs:[{name:"prompt",link:6}],outputs:[]};
    const count={id:171,type:"ZVProcessingWindowOutlet",inputs:[{name:"media_project",link:7}],outputs:[]};
    const math={id:30,type:"ComfyMathExpression",inputs:[{name:"values.a",link:8}],outputs:[],widgets:[{name:"expression",value:"max(5, round(a)) + (5 - (max(5, round(a)) % 17)) % 17"}]};
    low.inputs.push({name:"length",link:9});high.inputs.push({name:"length",link:100});
    nodes=[desk,interview,hub,stage,low,high,count,math];links={1:{origin_id:165,origin_slot:0},2:{origin_id:172,origin_slot:8},3:{origin_id:172,origin_slot:1},4:{origin_id:172,origin_slot:0},5:{origin_id:172,origin_slot:3},6:{origin_id:172,origin_slot:3},7:{origin_id:165,origin_slot:0},8:{origin_id:171,origin_slot:4},9:{origin_id:30,origin_slot:1},100:{origin_id:30,origin_slot:1}};
    let id=10;const connect=(target,name,slot)=>{links[id]={origin_id:182,origin_slot:slot};target.inputs.push({name,link:id++});};
    const map=[["first_frame",0],["last_frame",1],...Array.from({length:9},(_,i)=>['ref_images.ref_image_'+i,2+i]),...Array.from({length:3},(_,i)=>['ref_videos.ref_video_'+i,11+i]),...Array.from({length:3},(_,i)=>['ref_video_audios.ref_video_audio_'+i,14+i]),["drive_audio",17],["final_audio",18],...Array.from({length:3},(_,i)=>['ref_audios.ref_audio_'+i,19+i])];
    for(const target of [low,high]){for(const [name,slot] of map)connect(target,name,slot);target.widgets=[{name:"task_type",value:"Ref2VA — 参考生音视频"},{name:"audio_mode",value:"lock_source"},{name:"add_source_as_reference",value:false},{name:"prompt_primary_audio_ordinal",value:1}];}
    for(let i=0;i<11;i++)connect(stage,'image'+(i+1),i);for(let i=0;i<3;i++)connect(stage,'video_frames'+(i?i+1:''),11+i);
  }
  const graph={_nodes:nodes,links,getNodeById:id=>nodes.find(node=>String(node.id)===String(id)),setDirtyCanvas(){}};
  for(const node of nodes){node.graph=graph;if(savedGraph&&node.type==='MiniMaxH3AudioConditioningT8'){const names=['prompt','width','height','length','task_type','audio_mode','audio_denoise_strength','add_source_as_reference','prompt_primary_audio_ordinal','strict_prompt_tags','ref_image_size','reference_video_policy','allow_above_reference_area'];node.widgets=names.map((name,i)=>({name,value:node.widgets_values[i]}));}if(savedGraph&&node.type==='ComfyMathExpression')node.widgets=[{name:'expression',value:node.widgets_values[0]}];}
  const interview=graph.getNodeById(172),desk=graph.getNodeById(165);
  window.setCanvasSpec=function(spec){
    desk.inputs=desk.inputs.filter(row=>!['width','height'].includes(row.name));
    desk.widgets=(desk.widgets??[]).filter(row=>!['width','height'].includes(row.name));
    if(!spec)return;
    if(spec.kind==='selector'){
      const id=spec.id??29;let node=graph.getNodeById(id);
      if(!node){node={id,type:'ResolutionSelector',inputs:[],outputs:[]};node.graph=graph;nodes.push(node);}
      node.widgets=['aspect_ratio','megapixels','multiple'].filter(name=>spec[name]!==undefined).map(name=>({name,value:spec[name]}));node.inputs=[];
      for(const [name,slot,key] of [['width',0,900],['height',1,901]]){links[key]={origin_id:id,origin_slot:slot};desk.inputs.push({name,link:key});}
    }else for(const [name,key] of [['width',900],['height',901]])if(spec[name]!==undefined){
      const value=spec[name];
      if(typeof value==='number'){desk.inputs.push({name});desk.widgets=(desk.widgets??[]).filter(row=>row.name!==name);desk.widgets.push({name,value});}
      else{let node=graph.getNodeById(value.id);if(!node){node={id:value.id,type:value.type,inputs:[],outputs:[],widgets:[{name:'value',value:value.value}]};node.graph=graph;nodes.push(node);}links[key]={origin_id:value.id,origin_slot:value.slot??0};desk.inputs.push({name,link:key});}
    }
  };if(canvasSpec)setCanvasSpec(canvasSpec);
  if(savedGraph){for(const node of nodes)if(node.type==='ResolutionSelector')node.widgets=['aspect_ratio','megapixels','multiple'].map((name,i)=>({name,value:node.widgets_values[i]}));}
  desk.zfMediaDesk={root:deskEvents,getProject:()=>structuredClone(window.fixture)};
  interview.widgets=[{name:'interview_json',value:JSON.stringify(state),callback(next){this.value=next;}}];interview.setSize=size=>interview.size=size;interview.setDirtyCanvas=()=>{};interview.addDOMWidget=(name,type,root)=>{document.querySelector('#mount').append(root);window.domWidget={};return domWidget;};
  window.interviewNode=interview;window.graphFixture=graph;window.lowNode=graph.getNodeById(7);window.highNode=graph.getNodeById(14);
  h3.attachInterview(interview);
}; window.canvasWheel=0;document.body.addEventListener('wheel',()=>window.canvasWheel++);install();
</script>`;

await page.route("**/*", async route => {
  const url = new URL(route.request().url()), path = url.pathname;
  try {
    if (path.startsWith("/zf-prompt-director/h3-interview/presets")) {
      const result = await rpc({action:"presets",method:route.request().method(),path:path.slice('/zf-prompt-director/h3-interview/presets'.length),body:route.request().postData()});
      return route.fulfill({status:result.status,contentType:"application/json",body:JSON.stringify(result.body)});
    }
    if (path === "/zf-prompt-director/h3-interview/plan") { lastPlan = await rpc({ action: "plan", value: route.request().postDataJSON() }); return route.fulfill({ contentType: "application/json", body: JSON.stringify(lastPlan) }); }
    if (path === "/zf-media-evidence/preview") {
      const variant = url.searchParams.get("variant");
      const cache = await rpc({ action: "preview", handle: url.searchParams.get("source"), variant }); previews++;
      const contentType = { thumbnail: "image/jpeg", proxy: "video/mp4", audio: "audio/mp4", peaks: "application/json", original: "image/png" }[variant];
      const bytes=await readFile(cache),range=route.request().headers()['range'];
      // Match production aiohttp FileResponse: native media seeks require byte ranges.
      const headers={'Accept-Ranges':'bytes','Cache-Control':'private, max-age=86400'};
      if(range){
        const match=/^bytes=(\d*)-(\d*)$/.exec(range);
        if(!match)return route.fulfill({status:416,headers:{...headers,'Content-Range':`bytes */${bytes.length}`},body:''});
        const start=match[1]?Number(match[1]):Math.max(0,bytes.length-Number(match[2]));
        const end=match[1]?(match[2]?Math.min(Number(match[2]),bytes.length-1):bytes.length-1):bytes.length-1;
        if(start>end||start>=bytes.length)return route.fulfill({status:416,headers:{...headers,'Content-Range':`bytes */${bytes.length}`},body:''});
        return route.fulfill({status:206,contentType,headers:{...headers,'Content-Range':`bytes ${start}-${end}/${bytes.length}`},body:bytes.subarray(start,end+1)});
      }
      return route.fulfill({ contentType,headers, body: bytes });
    }
    const content = path === "/" ? html : path === "/interview.js" ? source : path === "/h3_interview.css" ? css : path === "/dom_widget_layout.mjs" ? helper : path === "/h3_interview_presets.mjs" ? presetModule : path === "/scripts/app.js" ? "export const app={extensions:[],registerExtension(entry){this.extensions.push(entry)}};" : path === "/scripts/api.js" ? "export const api={apiURL:path=>path,fetchApi:(path,options)=>fetch(path,options)};" : null;
    if(path === "/media_evidence_core.mjs")return route.fulfill({contentType:"application/javascript",body:mediaCore});
    if(path === "/media_evidence_presets.mjs")return route.fulfill({contentType:"application/javascript",body:mediaPresets});
    if(path === "/media_processing_presets.json")return route.fulfill({contentType:"application/json",body:mediaDefinitions});
    if (content === null) return route.abort();
    return route.fulfill({ contentType: path === "/" ? "text/html" : path.endsWith(".css") ? "text/css" : "application/javascript", body: content });
  } catch (error) { return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ errors: [{ message: error.message }] }) }); }
});

const saved = () => page.evaluate(() => JSON.parse(interviewNode.widgets[0].value));
const detect = () => page.evaluate(() => interviewNode.zvH3Interview.detect());
const projectChange = async project => {
  const canonical = await rpc({ action: "normalize", value: project });
  await page.evaluate(value => { window.fixture = value; deskEvents.dispatchEvent(new Event("zf-media-project-change")); }, canonical);
};

try {
  await page.goto("https://h3-interview.test/"); await page.waitForSelector(".zv-h3i textarea[name=intent]");
  check(await page.locator(".zv-h3i-role-options input:checked").count() === 0);
  await page.getByRole("button", { name: "检测并对齐素材" }).click();
  await page.waitForFunction(() => JSON.parse(interviewNode.widgets[0].value).reference_detection != null);
  let state = await saved();
  deep(state.reference_detection.pictures.map(row => row.item_id), ["p1", "p2"]);
  deep(state.reference_detection.audios.map(row => row.source_port), ["ref_video_audio_1", "ref_audio_1"]);
  check(state.schema_version === "zv-h3-interview-v2" && state.alignment != null);
  check(lastPlan.validation.conditioning.length_verified && lastPlan.validation.conditioning.model_length === 124);
  deep(await page.evaluate(() => lowNode.widgets.map(row => row.value)), ["auto", "native", true, 0]);
  check((await page.locator(".zv-h3-detection-status").textContent()).includes("路由已对齐")); scenarios++;
  if (process.argv[4]) await page.screenshot({ path: process.argv[4].replace(/\.png$/, "_FRESH.png"), fullPage: true });

  const before = state.reference_detection;
  const picture = page.locator(".zv-h3i-media-card").filter({ has: page.locator('.zv-h3i-media-title b:text-is("素材台 Picture 1")') });
  await picture.locator('.zv-h3i-role-options input[value="first_frame"]').check();
  await picture.locator('.zv-h3i-role-options input[value="subject_identity"]').check();
  await picture.locator('textarea[name="purpose-p1"]').fill("同一图定义 <Subject 1> 和 <Subject 2>，自由剧情与转场");
  await page.waitForTimeout(200); deep((await saved()).reference_detection, before);
  await page.locator(".zv-h3-teaching summary").click(); await page.locator(".zv-h3-teaching select").selectOption("video_continue"); deep((await saved()).reference_detection, before);
  await page.getByRole("button", { name: "清空用途" }).click(); deep((await saved()).reference_detection, before); scenarios++;

  await picture.locator('input[name="participates"]').uncheck(); check((await saved()).reference_detection === null);
  await detect(); check(await page.locator(".zv-h3i-media-card").count() === 5); check((await picture.textContent()).includes("未参与本次 H3"));
  await picture.locator('input[name="participates"]').check(); await detect(); scenarios++;

  await page.evaluate(() => {const value=JSON.parse(interviewNode.widgets[0].value);value.media_purposes.deleted='按 <Picture 9> 处理';value.media_roles.deleted=['subject_identity'];install(value,fixture);});
  await page.getByRole('button',{name:'清理失效用途'}).click();
  check((await saved()).media_purposes.deleted == null && (await saved()).media_roles.deleted == null);
  deep((await saved()).reference_detection,before); scenarios++;

  await picture.locator('.zv-h3-routing input[value="first_frame"]').check(); check((await saved()).reference_detection === null); await detect();
  check((await page.locator(".zv-h3i-editor-status").textContent()).includes("混合参考"));
  await picture.locator('.zv-h3-routing input[value="first_frame"]').uncheck(); await detect(); scenarios++;

  const overflow = await page.evaluate(() => structuredClone(fixture));
  for (let index=3;index<=10;index++) overflow.picture_track.push({ item_id:`p${index}`,asset_id:overflow.picture_track[0].asset_id,order:index });
  await projectChange(overflow); await detect();
  check((await saved()).reference_detection === null);
  check((await page.locator(".zv-h3-detection-status").textContent()).includes("ref_images 最多 9"));
  await projectChange(fixture); await detect(); scenarios++;

  const vectorList = await rpc({ action: "vectors" });
  for (const vector of vectorList) {
    const view = await page.evaluate(value => { const rows=h3.inventory(value.project);return {snapshot:h3.plannedReferenceSnapshot(rows,value.state,2),context:h3.mechanicalContext(value.state,value.project,rows),mode:h3.inferMode(value.state,rows)}; }, vector);
    deep(view.snapshot, vector.snapshot); deep(view.context, vector.context); check(view.mode === vector.mode);
  } scenarios++;

  await picture.locator(".zv-h3-media-thumb").click(); await page.waitForFunction(() => document.querySelector('.zv-h3-shared-preview img')?.naturalWidth > 0);
  const video = page.locator(".zv-h3i-media-card").filter({ has: page.locator('.zv-h3i-media-title b:text-is("素材台 Video 1")') });
  await video.locator(".zv-h3-media-thumb").click(); await page.waitForFunction(() => document.querySelector('.zv-h3-shared-preview video')?.readyState >= 1);
  const audio = page.locator(".zv-h3i-media-card").filter({ has: page.locator('.zv-h3i-media-title b:text-is("素材台 Audio 1")') });
  await audio.locator(".zv-h3-media-thumb").click(); await page.waitForFunction(() => document.querySelector('.zv-h3-shared-preview audio')?.readyState >= 1);
  check(await page.locator(".zv-h3-shared-preview audio[controls]").count() === 1 && await page.locator(".zv-h3-shared-preview video").count() === 0);
  check(await page.locator(".zv-h3i-media-card audio,.zv-h3i-media-card video").count() === 0); check(await audio.locator("canvas").count() === 1); scenarios++;
  if (process.argv[4]) { await page.evaluate(() => document.querySelector('.zv-h3i-body aside').scrollTop=0); await page.screenshot({ path:process.argv[4].replace(/\.png$/, "_AUDIO.png"),fullPage:true }); }

  await page.locator("textarea[name=intent]").fill("参考 <Picture 9> 设计剧情");
  await page.waitForFunction(() => document.querySelector('.zv-h3-model-status')?.textContent.includes('引用 Picture 9 不存在'));
  check((await page.locator(".zv-h3-detection-status").textContent()).includes("路由已对齐"));
  await page.locator("textarea[name=intent]").fill("自由组合、续写与转场"); await page.waitForTimeout(210); scenarios++;

  const updated = await page.evaluate(() => structuredClone(fixture)); updated.picture_track[0].order = 8; await projectChange(updated);
  check((await saved()).reference_detection === null); check((await page.locator(".zv-h3-detection-status").textContent()).includes("顺序"));
  await detect(); deep((await saved()).reference_detection.pictures.map(row => row.item_id), ["p2", "p1"]);
  updated.processing_window.end_seconds = 6; await projectChange(updated); check((await saved()).reference_detection === null); await detect(); scenarios++;

  await page.evaluate(() => { const input=highNode.inputs.find(row=>row.name==='first_frame'); graphFixture.links[input.link].origin_slot=1; });
  await detect(); check((await saved()).reference_detection === null); check((await page.locator(".zv-h3-detection-status").textContent()).includes("槽位 0"));
  await page.evaluate(() => { const input=highNode.inputs.find(row=>row.name==='first_frame');graphFixture.links[input.link].origin_slot=0; }); await detect(); scenarios++;

  const persisted = await saved(), currentProject = await page.evaluate(() => structuredClone(fixture));
  await page.evaluate(value => install(value.state, value.project), { state: persisted, project: currentProject });
  check(await page.locator(".zv-h3i").count() === 1); deep((await saved()).reference_detection, persisted.reference_detection);
  await page.evaluate(() => { const main=document.querySelector('.zv-h3i-body main'),aside=document.querySelector('.zv-h3i-body aside');main.scrollTop=150;aside.scrollTop=130;main.dispatchEvent(new WheelEvent('wheel',{deltaY:40,bubbles:true})); });
  await page.getByRole("button", { name: "画布空白" }).click();
  check(await page.evaluate(() => canvasWheel === 0 && document.querySelector('.zv-h3i-body main').scrollTop > 0 && document.querySelector('.zv-h3i-body aside').scrollTop > 0)); scenarios++;

  const actual = await rpc({ action: "workflow" }); const original = actual.graph.nodes.find(node => node.id === 172).widgets_values[0];
  await page.evaluate(value => install(JSON.parse(value.original), value.project, value.graph), { ...actual, original });
  const expectedActual = await page.evaluate(() => h3.plannedReferenceSnapshot(h3.inventory(h3.readProject(interviewNode).project), h3.safeState(interviewNode.widgets[0].value), 2));
  await detect(); state = await saved();
  check(state.recipe === JSON.parse(original).recipe && state.intent === JSON.parse(original).intent);
  check(lastPlan.validation.conditioning.length_verified && lastPlan.validation.conditioning.lengths.every(row=>row.proof === 'known_grid_expression_same_project'));
  for(const kind of ['pictures','videos','audios'])deep(state.reference_detection[kind].map(row => [row.item_id,row.origin]), expectedActual[kind].map(row => [row.item_id,row.origin]));
  check((await page.locator(".zv-h3-detection-status").textContent()).includes(`${expectedActual.pictures.length} 图 / ${expectedActual.videos.length} 视频 / ${expectedActual.audios.length} 音频`));
  await page.locator(".zv-h3i-media-card").first().locator(".zv-h3-media-thumb").click();
  await page.waitForFunction(() => document.querySelector('.zv-h3-shared-preview video')?.readyState >= 1);
  await page.evaluate(() => { document.querySelector('.zv-h3i-body aside').scrollTop=0; });
  const snapshot = state.reference_detection; await page.getByRole("button", { name: "清空用途" }).click(); deep((await saved()).reference_detection, snapshot); scenarios++;

  // Deliver neutral evidence only; the real workflow assertion above stays in memory.
  await page.evaluate(value => install(h3.emptyState(), value), fixture); await detect();
  await page.locator("textarea[name=intent]").fill("用中性测试素材演示主体、动作与声音的自由组合");
  await page.locator(".zv-h3i-media-card").first().locator(".zv-h3-media-thumb").click();
  await page.waitForFunction(() => document.querySelector('.zv-h3-shared-preview img')?.naturalWidth > 0);
  await page.evaluate(() => { document.querySelector('.zv-h3i-body aside').scrollTop=0; });
  if (process.argv[4]) await page.screenshot({ path: process.argv[4], fullPage: true });

  await page.evaluate(() => install(h3.emptyState(), {...fixture,assets:[],picture_track:[],video_track:[],audio_track:[],label_map:[]})); await detect();
  check((await page.locator(".zv-h3i-editor-status").textContent()).includes("T2VA"));
  deep(await page.evaluate(() => [lowNode,highNode].map(node=>node.widgets.find(row=>row.name==='task_type').value)), ["auto","auto"]); scenarios++;
  if (process.argv.includes("--presets")) {
    const {runPresetCases} = await import("./h3_presets_ui_cases.mjs");
    scenarios += await runPresetCases({page,rpc,check,deep,saved,detect,fixture,projectChange,screenshot:process.argv[4]});
    const {runRaceCases} = await import("./h3_presets_ui_races.mjs");
    scenarios += await runRaceCases({page,rpc,check,deep,saved,detect,fixture,projectChange});
  }
  if(process.argv.includes('--stage03')){
    const {runStage03Cases}=await import('./h3_v2_03_ui_cases.mjs');
    scenarios+=await runStage03Cases({page,rpc,check,deep,saved,detect,projectChange,screenshot:process.argv[4]});
  }
  if(process.argv.includes('--stage04')){
    const {runStage04Cases}=await import('./h3_v2_04_ui_cases.mjs');
    scenarios+=await runStage04Cases({page,rpc,check,deep,saved,detect,projectChange,screenshot:process.argv[4]});
  }
  deep(errors, []); check(previews > 0);
  console.log(`H3_INTERVIEW_UI_OK ${scenarios} scenarios, ${vectorList.length} Python/JS plan-context-mode vectors, ${assertions} assertions, ${previews} cache responses, 0 failed, 0 skipped; neutral CPU fixtures imported/cached during setup; planning performs no decode; no GPU generation`);
} finally { await browser.close(); python.stdin.end(); }
