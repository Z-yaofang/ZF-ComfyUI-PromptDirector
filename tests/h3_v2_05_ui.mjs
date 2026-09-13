// Actual browser JS + isolated HTTP registry + native CPU screenshot worker.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const {chromium}=createRequire(import.meta.url)(process.argv[3]);
const browser=await chromium.launch({headless:true,executablePath:process.argv[4]});
const page=await browser.newPage({viewport:{width:1240,height:1180}}),errors=[],records=[];
let checks=0;const check=value=>{assert(value);checks++;},deep=(a,b)=>{assert.deepEqual(a,b);checks++;};
page.on('pageerror',error=>errors.push(error.message));
const project=()=>page.evaluate(()=>deskNode.zfMediaDesk.getProject());
const sync=()=>page.waitForFunction(()=>document.querySelector('.zf-med').getAttribute('aria-busy')!=='true');
const capture=()=>page.getByRole('button',{name:'截图',exact:true});
const head=async time=>{const ruler=await page.locator('.zf-med-ruler').boundingBox();await page.mouse.click(ruler.x+time*140,ruler.y+32);};
const cut=async(name,value)=>{await page.getByLabel(name,{exact:true}).fill(String(value));await page.getByLabel(name,{exact:true}).press('Tab');await sync();};
const restore=async value=>{await page.evaluate(value=>{deskNode.widgets[0].value=JSON.stringify(value);deskNode.zfMediaDesk.restore();},value);await sync();};
const invariant=value=>{const p=structuredClone(value);delete p.assets;delete p.validation;delete p.label_map;delete p.preset_compatibility;return p;};
async function heldScreenshot({bad=false}={}){
  let release,resolve,requests=0;
  const gate=new Promise(r=>release=r),entered=new Promise(r=>resolve=r);
  await page.route('**/zf-media-evidence/screenshot',async route=>{
    requests++;const body=route.request().postDataJSON();
    const response=await route.fetch(bad?{postData:JSON.stringify({...body,source_handle:'../../not-allowed'})}:{});
    resolve({body,status:response.status(),result:await response.json()});await gate;await route.fulfill({response});
  });
  await capture().click();const result=await entered;
  return {result,requests:()=>requests,release:async()=>{release();await page.waitForFunction(()=>document.querySelector('[data-action=screenshot]')?.getAttribute('aria-busy')!=='true');await page.unroute('**/zf-media-evidence/screenshot');}};
}
try{
  await mkdir(process.argv[5],{recursive:true});await page.goto(process.argv[2]);await page.waitForSelector('.zf-med');await sync();check(await capture().isDisabled());
  const paths=await page.evaluate(()=>fetch('/fixtures').then(r=>r.json()));
  const chooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'＋ 导入素材'}).click();await (await chooser).setFiles(paths);
  await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===3);await sync();
  check(await capture().isDisabled());const assets=(await project()).assets,video=assets.find(a=>a.kind==='video'),picture=assets.find(a=>a.kind==='picture');
  await page.locator(`[data-asset-id="${video.asset_id}"]`).click();await page.getByRole('button',{name:'加入对应轨道（播放头处）'}).click();await sync();
  const clip=(await project()).video_track[0];await page.locator(`[data-id="${clip.clip_id}"]`).click();
  await cut('轨道起点 / 秒',2);await cut('源入点 / 秒',.5);await cut('源出点 / 秒',1.5);
  await page.locator('.zf-med-zoom').fill('140');await page.locator('.zf-med-zoom').dispatchEvent('input');await page.locator('.zf-med-snap').uncheck();
  await head(1);check(await capture().isDisabled());await head(3);check(await capture().isDisabled());await head(2.125);check(await capture().isEnabled());
  const before=await project(),pending=await heldScreenshot();check(pending.result.status===200);check(await capture().isDisabled());check(await page.getByRole('button',{name:'＋ 导入素材'}).isDisabled());
  await page.evaluate(()=>document.querySelector('[data-action=screenshot]').click());check(pending.requests()===1);
  await head(2.875);await page.locator(`[data-asset-id="${picture.asset_id}"]`).click();
  const savedView=await page.evaluate(()=>structuredClone(deskNode.properties.zf_media_desk_view));await pending.release();
  await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===4);await sync();
  let current=await project();deep(invariant(current),invariant(before));deep(await page.evaluate(()=>deskNode.properties.zf_media_desk_view.selected),savedView.selected);
  const shot=current.assets.find(a=>a.capture);check(shot.kind==='picture');check(Math.abs(shot.capture.source_seconds-.625)<.01);check(Math.abs(shot.capture.frame_seconds-.625)<1/24);
  deep([shot.probe.width,shot.probe.height],[320,180]);check(shot.name.includes('截图')&&shot.name.includes('0.625'));
  records.push({name:'native screenshot frozen before seek/selection, pool only',request:pending.result.body,asset:shot});
  for(const [type,color] of [['picture','rgb(255, 219, 113)'],['video','rgb(101, 223, 154)'],['image','rgb(255, 128, 139)'],['audio','rgb(156, 172, 192)']]){
    const marker=page.locator(`.zf-med-pool .zf-med-type-${type}`);check(await marker.count()===1);check(await marker.textContent()===type);deep(await marker.evaluate(e=>getComputedStyle(e).color),color);
  }
  await page.getByRole('button',{name:'撤销',exact:true}).click();await sync();check((await project()).assets.length===3);
  await page.getByRole('button',{name:'重做',exact:true}).click();await sync();check((await project()).assets.length===4);
  const original=await page.request.get(`${process.argv[2]}/zf-media-evidence/preview?source=${encodeURIComponent(shot.source_handle)}&variant=original`);check(original.ok());const png=await original.body();
  await page.locator(`[data-asset-id="${shot.asset_id}"] .zf-med-unload`).click();await sync();check(!(await project()).assets.some(a=>a.asset_id===shot.asset_id));
  const retained=await page.request.get(`${process.argv[2]}/zf-media-evidence/preview?source=${encodeURIComponent(shot.source_handle)}&variant=original`);deep(await retained.body(),png);
  await page.getByRole('button',{name:'撤销',exact:true}).click();await sync();
  // Real pointer drag uses the ordinary picture track accepting kind=picture.
  const source=await page.locator(`[data-asset-id="${shot.asset_id}"]`).boundingBox(),dest=await page.locator('.zf-med-lane[data-track=picture]').boundingBox();
  await page.mouse.move(source.x+20,source.y+25);await page.mouse.down();await page.mouse.move(source.x+40,source.y+25,{steps:4});await page.mouse.move(dest.x+60,dest.y+35,{steps:10});await page.mouse.move(dest.x+61,dest.y+35);await page.mouse.up();await sync();
  check((await project()).picture_track.length===1);check((await project()).picture_track[0].asset_id===shot.asset_id);
  await page.locator(`[data-id="${(await project()).picture_track[0].item_id}"]`).click();check((await page.locator('.zf-med-facts').textContent()).includes('截图/图片'));
  await page.evaluate(()=>saveWorkflow());await page.reload();await page.waitForSelector('.zf-med');await sync();
  current=await project();check(current.assets.find(a=>a.asset_id===shot.asset_id).capture.method==='video_frame');check(current.picture_track[0].asset_id===shot.asset_id);
  await page.locator(`[data-asset-id="${shot.asset_id}"]`).click();await page.waitForFunction(()=>document.querySelector('.zf-med-screen img')?.naturalWidth===320);
  await page.locator('.zf-med').screenshot({path:process.argv[5]+'/SCREENSHOT_TYPES.png'});
  // Half-open split: exact junction must use the right-hand clip descriptor.
  await head(2.25);await page.locator(`[data-id="${clip.clip_id}"]`).click({position:{x:12,y:12}});await head(2.5);await page.getByRole('button',{name:'分割',exact:true}).click();await sync();await head(2.5);
  const splitBefore=await project(),junction=await heldScreenshot();check(junction.result.body.timeline_in_seconds===2.5);check(junction.result.body.source_in_seconds===1);
  await junction.release();await page.waitForFunction(()=>deskNode.zfMediaDesk.getProject().assets.length===5);await sync();
  check((await project()).assets.at(-1).capture.source_seconds===1);deep(invariant(await project()),invariant(splitBefore));records.push({name:'exact split junction',...junction.result});
  const count=(await project()).assets.length;await head(2.625);const failure=await heldScreenshot({bad:true});check(failure.result.status===400);
  await head(1);await failure.release();check((await project()).assets.length===count);check((await page.locator('.zf-med-status').textContent()).includes('截图失败'));check(await capture().isDisabled());
  await head(2.75);const removed=await heldScreenshot();await page.locator(`[data-asset-id="${video.asset_id}"] .zf-med-unload`).click();await sync();const afterRemoval=await project();await removed.release();
  deep(await project(),afterRemoval);check(!(await project()).assets.some(a=>a.asset_id===removed.result.result.asset.asset_id));
  // Reloading a project during a response also cancels its old owner epoch.
  await restore(splitBefore);await head(2.625);const reloaded=await heldScreenshot();await restore(splitBefore);await reloaded.release();deep(invariant(await project()),invariant(splitBefore));check((await project()).assets.length===splitBefore.assets.length);
  await head(2.75);let releaseRemoval,resolveRemoval;const gate=new Promise(r=>releaseRemoval=r),entered=new Promise(r=>resolveRemoval=r);
  await page.route('**/zf-media-evidence/screenshot',async route=>{const response=await route.fetch();resolveRemoval();await gate;await route.fulfill({response});});await capture().click();await entered;
  const disposed=await project();await page.evaluate(()=>deskNode.onRemoved());releaseRemoval();await page.waitForResponse('**/zf-media-evidence/screenshot');deep(await project(),disposed);check(await page.locator('.zf-med').count()===0);
  deep(errors,[]);await writeFile(process.argv[5]+'/BROWSER_NATIVE_RECORDS.json',JSON.stringify({scope:'actual HTTP CPU frame capture and production desk JS; isolated neutral media only',checks,records},null,2));
  console.log(`H3_V2_05_BROWSER_OK ${checks} checks; actual CPU screenshots, frozen response, split junction, pool/undo/reload/drag, reliable four type markers; 0 failed/0 skipped/page errors`);
}catch(error){console.error('H3_V2_05_BROWSER_FAIL '+JSON.stringify({checks,errors,status:await page.locator('.zf-med-status').textContent().catch(()=>null)}));throw error;}finally{await browser.close();}
