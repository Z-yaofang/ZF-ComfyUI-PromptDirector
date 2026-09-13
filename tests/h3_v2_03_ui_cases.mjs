import {writeFile} from 'node:fs/promises';

export async function runStage03Cases({page,rpc,check,deep,saved,detect,projectChange,screenshot}){
  const cases=await rpc({action:'matrix_setup'}),records=[];let scenarios=0;
  async function cpu(name){
    const state=await saved(),project=await page.evaluate(()=>structuredClone(fixture));
    const output=await rpc({action:'matrix_cpu',state,project});
    check(output.ready===true&&output.tuple_count===24);
    const front=await page.evaluate(()=>h3.plannedReferenceSnapshot(h3.inventory(fixture),JSON.parse(interviewNode.widgets[0].value)));
    for(const plural of ['pictures','videos','audios'])deep(front[plural],state.reference_detection[plural]);
    for(const call of output.calls){
      const row=front[call.kind==='picture'?'pictures':call.kind==='video'?'videos':'audios'].find(row=>row.item_id===call.item_id&&row.source_port===call.port);
      check(row!==undefined&&call.media.dtype==='torch.float32'&&call.media.device==='cpu');
      if(call.kind==='picture')check(Math.abs(call.signatures.rgb_first[0]-Number(call.item_id.slice(1))*20/255)<.01);
      if(call.kind==='video'){
        deep(call.media.shape,[48,96,64,3]);
        const clip=project.video_track.find(row=>row.clip_id===call.item_id);
        check(Math.abs(call.signatures.rgb_first[1]-clip.source_in_seconds*72/255)<.015);
        check(Math.abs(call.signatures.rgb_last[1]-(clip.source_in_seconds*24+47)*3/255)<.015);
      }
      if(call.kind==='audio')deep(call.media.shape,[1,2,88200]);
    }
    records.push({name,...output});return output;
  }
  for(const entry of cases){
    await page.evaluate(value=>install(value.state,value.project),entry);await detect();
    if(entry.ready)await cpu(entry.name);
    else{
      const state=await saved(),project=await page.evaluate(()=>structuredClone(fixture));
      const output=await rpc({action:'matrix_cpu',state,project});check(!output.ready&&!output.decoded&&output.errors.length>0);records.push({name:entry.name,...output});
    }
    scenarios++;
  }
  const full=cases.find(entry=>entry.name==='6+3+3 Audio6');
  await page.evaluate(value=>install(value.state,value.project),full);await detect();
  await page.locator('textarea[name=intent]').fill('用 <Audio 4> 的独立音频，<Video 2> 原声可自由选择');await page.waitForTimeout(240);
  await page.waitForFunction(()=>JSON.parse(interviewNode.widgets[0].value).reference_texts.intent?.definitions[0]?.source.item_id==='a1');
  let output=await cpu('explicit refs before muted pair');
  check(output.calls.some(row=>row.item_id==='a1'&&row.label==='<Audio 4>'));
  const muted=structuredClone(full.project);muted.video_track[1].source_audio_enabled=false;await projectChange(muted);await detect();
  output=await cpu('explicit refs after muted pair');check((await saved()).intent.includes('<Audio 3>'));
  check((await saved()).reference_texts.intent.definitions[0].source.item_id==='a1');scenarios+=2;
  const changed=structuredClone(muted);changed.picture_track[0].order=99;changed.picture_track=changed.picture_track.filter(row=>row.item_id!=='p3');
  await projectChange(changed);await detect();await cpu('reorder/delete with original graph');scenarios++;
  const missing=await rpc({action:'matrix_missing'});await page.evaluate(value=>install(value.state,value.project),missing);
  for(const count of [2,3]){
    const next=structuredClone(missing.full);next.picture_track=next.picture_track.slice(0,count);next.picture_track.forEach((row,index)=>row.order=count-index);
    await projectChange(next);await detect();const state=await saved();
    check(state.media_purposes.p1===`<Picture ${count}> purpose 1`);
    deep(state.reference_texts.intent.definitions.slice(0,count).map(row=>row.source.item_id),Array.from({length:count},(_,i)=>'p'+(i+1)));
    if(count===2){check(state.intent.includes('<H3待绑定:r3>'));const project=await page.evaluate(()=>structuredClone(fixture));await page.evaluate(value=>install(value.state,value.project),{state,project});}
  }
  await cpu('missing slots sequential front inserts and workflow reload');scenarios++;
  const reloaded=await rpc({action:'matrix_reload',state:await saved(),project:await page.evaluate(()=>structuredClone(fixture))});
  await page.evaluate(value=>install(value.state,value.project),reloaded);await detect();
  output=await cpu('export and load on new IDs');deep((await saved()).reference_texts.intent.definitions.map(row=>row.source.item_id),['n3','n2','n1']);scenarios++;
  check(await page.locator('.zv-h3i-media-card audio,.zv-h3i-media-card video').count()===0);
  await page.locator('.zv-h3-media-thumb').first().click();await page.waitForFunction(()=>document.querySelector('.zv-h3-shared-preview img')?.naturalWidth>0);
  check(await page.locator('.zv-h3-shared-preview').count()===1);
  if(screenshot){await page.screenshot({path:screenshot.replace(/\.png$/,'_MATRIX.png'),fullPage:true});await writeFile(screenshot.replace(/\.png$/,'_MATRIX.json'),JSON.stringify({scope:'actual browser JS + neutral registry + CPU output signatures; graph/app shell only; no GPU',records,scenarios},null,2));}
  console.log(`H3_V2_03_UI_MATRIX_OK ${scenarios} real registry/front-end/CPU scenarios; fixed graph, source signatures, no decode during planning`);return scenarios;
}
