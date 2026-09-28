// node tests/universal_segment_ui_smoke.mjs PYTHON PLAYWRIGHT_PACKAGE CHROMIUM_EXECUTABLE
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {startUiServer} from "./ui_server_process.mjs";

const {chromium}=createRequire(import.meta.url)(process.argv[3]||"playwright");
let server,browser,checks=0;
try{
    server=await startUiServer(process.argv[2],[fileURLToPath(new URL("./long_video_ui_server.py",import.meta.url))]);
    browser=await chromium.launch({headless:true,executablePath:process.argv[4]||undefined});
    const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
    page.on("pageerror",error=>errors.push(error.message));
    await page.goto(server.url+"/universal");
    await page.waitForFunction(()=>desk.zvUniversal.getPlan()?.segments.length===1);
    const pane=page.locator(".zv-universal"),mode=pane.getByRole("combobox").first(),fpsInput=pane.locator("label").filter({hasText:"分段时钟 fps"}).locator("input");
    assert.equal(await page.locator(".zv-universal").count(),1);assert.equal(await mode.inputValue(),"H3");checks+=2;
    assert.equal(await page.evaluate(()=>desk.zvUniversal.getPlan().fps),24);assert.equal(await fpsInput.inputValue(),"24");checks+=2;
    assert.equal(await page.evaluate(()=>desk.zvUniversal.getPlan().target_frame_count),360);checks++;
    const first=pane.locator(".zv-universal-segment").first();
    await first.getByLabel("前段最后帧",{exact:true}).fill("119");
    await first.getByRole("button",{name:"当前帧后分割",exact:true}).click();
    await page.waitForFunction(()=>desk.zvUniversal.getPlan()?.segments.length===2);
    assert.deepEqual(await page.evaluate(()=>desk.zvUniversal.getPlan().segments.map(row=>[row.start_frame,row.end_frame])),[[0,120],[120,360]]);checks++;
    await page.locator("#interview").getByRole("button",{name:"检测并对齐全部分段",exact:true}).click();
    await page.waitForFunction(()=>interview.zvLong.result?.segments.length===2);assert.equal(await page.evaluate(()=>interview.zvLong.result.segment_plan.target_frame_count),360);checks++;

    await mode.selectOption("Animate");
    await page.waitForFunction(()=>desk.zvUniversal.getMode()==="Animate"&&desk.zvUniversal.getPlan()?.fps===24);
    assert.equal(await page.evaluate(()=>desk.zvUniversal.getPlan().target_frame_count),672);checks++;
    assert.equal(await page.evaluate(()=>desk.zvUniversal.getPlan().settings.schema_version),2);checks++;
    assert.equal(await page.evaluate(()=>JSON.parse(desk.widgets.find(row=>row.name==="segment_data").value).animate.schema_version),2);checks++;
    assert.match(await pane.locator(".zv-universal-status").textContent(),/1 段 · 672 运行帧 \/ 28\.000 秒/);checks++;

    await mode.selectOption("H3");
    await page.waitForFunction(()=>desk.zvUniversal.getMode()==="H3"&&desk.zvUniversal.getPlan()?.target_frame_count===360);
    assert.equal(await fpsInput.inputValue(),"24");checks++;
    assert.equal(await page.evaluate(()=>desk.widgets.find(row=>row.name==="target_mode").value),"H3");checks++;
    assert.deepEqual(errors,[]);checks++;
    await page.evaluate(()=>{interview.onRemoved?.();desk.onRemoved?.();});
    console.log(JSON.stringify({checks,passed:true,url:server.url+"/universal"}));
}finally{try{await browser?.close();}finally{await server?.stop();}}
