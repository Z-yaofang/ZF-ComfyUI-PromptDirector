export async function runRaceCases({page,rpc,check,deep,saved,detect,fixture,projectChange}) {
  let scenarios=0;
  const box=page.locator('.zv-h3-presets'),intent=page.locator('textarea[name=intent]');
  const button=name=>box.getByRole('button',{name,exact:true}).click();
  const reset=async()=>{await page.evaluate(value=>install(h3.emptyState(),value),fixture);await detect();await intent.fill('预设旧剧情：参考 <Picture 1>');await page.waitForTimeout(220);};
  await reset();await box.locator('input[name=preset-name]').fill('慢响应中性示例');await button('保存新预设');
  await page.waitForFunction(()=>document.querySelector('.zv-h3-preset-status').textContent.includes('已保存'));
  const id=await box.locator('select').inputValue();
  async function gate(kind, failure=null) {
    let release,reached,held=false;
    const wait=new Promise(resolve=>release=resolve),started=new Promise(resolve=>reached=resolve);
    const pattern=kind==='load'?'**/zf-prompt-director/h3-interview/presets/*/apply':'**/zf-prompt-director/h3-interview/plan';
    await page.route(pattern,async route=>{
      const value=route.request().postDataJSON();
      const result=kind==='load'?await rpc({action:'presets',method:'POST',path:new URL(route.request().url()).pathname.slice('/zf-prompt-director/h3-interview/presets'.length),body:route.request().postData()}):await rpc({action:'plan',value});
      if(!held&&(kind==='load'||value.align)){
        held=true;reached();await wait;
        if(failure==='503')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({errors:[{message:'中性延迟失败'}]})});
        if(failure==='non-json')return route.fulfill({status:200,contentType:'text/plain',body:'中性非法响应'});
        if(failure==='network')return route.abort('failed');
      }
      await route.fulfill({status:kind==='load'?result.status:200,contentType:'application/json',body:JSON.stringify(kind==='load'?result.body:result)});
    });
    return {started,release,remove:()=>page.unroute(pattern)};
  }
  const choose=async()=>{await box.locator('select').selectOption(id);};
  let hold=await gate('load');await choose();await button('载入所选');await hold.started;
  await intent.fill('用户在载入等待期间填写的新剧情：参考 <Picture 1>');await page.waitForTimeout(220);const edited=await saved();
  hold.release();await page.waitForFunction(()=>document.querySelector('.zv-h3-preset-status').textContent.includes('响应已过期'));
  check((await saved()).intent===edited.intent&&await intent.inputValue()===edited.intent);deep((await saved()).reference_detection,edited.reference_detection);await hold.remove();scenarios++;

  hold=await gate('load');await choose();await button('载入所选');await hold.started;
  const reordered=structuredClone(fixture);reordered.picture_track[0].order=9;reordered.video_track[0].source_audio_enabled=false;
  await projectChange(reordered);await intent.fill('换过素材后的最新文本');await page.waitForTimeout(220);const latest=await saved(),media=await page.evaluate(()=>structuredClone(fixture));
  hold.release();await page.waitForFunction(()=>document.querySelector('.zv-h3-preset-status').textContent.includes('响应已过期'));
  deep(await page.evaluate(()=>structuredClone(fixture)),media);check((await saved()).intent===latest.intent&&await intent.inputValue()===latest.intent);deep((await saved()).bindings,latest.bindings);await hold.remove();scenarios++;

  await reset();hold=await gate('detect');const detecting=detect();await hold.started;
  await intent.fill('用户在检测等待期间的新剧情：参考 <Picture 1>');
  const purpose=page.locator('textarea[name="purpose-va1"]');await purpose.fill('用户编辑的新原声用途');await page.waitForTimeout(220);const newDraft=await saved();
  hold.release();await detecting;
  check((await saved()).intent===newDraft.intent&&await intent.inputValue()===newDraft.intent);
  check((await saved()).media_purposes.va1==='用户编辑的新原声用途'&&await purpose.inputValue()==='用户编辑的新原声用途');
  deep((await saved()).reference_detection,newDraft.reference_detection);check((await page.locator('.zv-h3-detection-status').textContent()).includes('响应已过期'));await hold.remove();scenarios++;

  for(const failure of ['503','non-json','network']){
    await reset();hold=await gate('detect',failure);const failed=detect();await hold.started;
    await intent.fill(`等待${failure}期间的新剧情：参考 <Picture 1>`);await page.waitForTimeout(220);const before=await saved();
    check(before.alignment!==null&&before.reference_detection!==null);
    hold.release();await failed;const after=await saved();
    check(after.intent===before.intent&&await intent.inputValue()===before.intent);
    deep(after.alignment,before.alignment);deep(after.reference_detection,before.reference_detection);
    check((await page.locator('.zv-h3-detection-status').textContent()).includes('响应已过期'));await hold.remove();scenarios++;
  }

  await reset();hold=await gate('detect','503');const mediaFailure=detect();await hold.started;
  const changed=structuredClone(fixture);changed.picture_track[0].order=9;changed.video_track[0].source_audio_enabled=false;
  await projectChange(changed);await intent.fill('失败等待期间更换媒体后的新文本');await page.waitForTimeout(220);
  const mediaBefore=await saved(),projectBefore=await page.evaluate(()=>structuredClone(fixture));
  hold.release();await mediaFailure;const mediaAfter=await saved();
  deep(await page.evaluate(()=>structuredClone(fixture)),projectBefore);deep(mediaAfter.bindings,mediaBefore.bindings);
  deep(mediaAfter.alignment,mediaBefore.alignment);deep(mediaAfter.reference_detection,mediaBefore.reference_detection);
  check(mediaAfter.intent===mediaBefore.intent&&await intent.inputValue()===mediaBefore.intent);await hold.remove();scenarios++;

  await reset();hold=await gate('detect','503');const currentFailure=detect();await hold.started;
  hold.release();await currentFailure;const failedCurrent=await saved();
  check(failedCurrent.alignment===null&&failedCurrent.reference_detection===null);
  check((await page.locator('.zv-h3-detection-status').textContent()).includes('中性延迟失败'));await hold.remove();scenarios++;

  await reset();hold=await gate('detect');const first=detect();await hold.started;await detect();const newest=await saved();hold.release();await first;
  deep((await saved()).reference_detection,newest.reference_detection);check((await saved()).intent===newest.intent);await hold.remove();scenarios++;

  hold=await gate('detect');const removed=detect();await hold.started;
  await page.evaluate(value=>{const state=h3.emptyState();state.intent='新节点的文本不可覆写';install(state,value);},fixture);
  hold.release();await removed;check((await saved()).intent==='新节点的文本不可覆写'&&await intent.inputValue()==='新节点的文本不可覆写');check(await page.locator('.zv-h3i').count()===1);await hold.remove();scenarios++;

  let imports=0;const onRequest=request=>{if(request.url().endsWith('/presets/import'))imports++;};page.on('request',onRequest);
  const file=box.locator('input[type=file]'),bad={name:'同一非法文件.json',mimeType:'application/json',buffer:Buffer.from('{"schema_version":"invalid","presets":[]}')};
  const before=await box.locator('select option').count();
  for(let index=0;index<2;index++){await file.setInputFiles(bad);await page.waitForFunction(()=>document.querySelector('.zv-h3-preset-status').textContent.includes('版本'));check(await file.inputValue()==='');}
  check(imports===2&&await box.locator('select option').count()===before);page.off('request',onRequest);scenarios++;
  console.log(`H3_PRESETS_RACES_OK ${scenarios} delayed-response/retry scenarios; no overwritten text, purpose, media, newer detection or replacement node`);
  return scenarios;
}
