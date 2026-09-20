import {writeFile} from 'node:fs/promises';

// Neutral cached fixtures, actual production JS and Python node. No Comfy service.
export async function runStage04Cases({page,rpc,check,deep,saved,detect,projectChange,screenshot}){
  if(!process.argv.includes('--stage03'))await rpc({action:'matrix_setup'});
  const input=await rpc({action:'04_project'}),records=[];let scenarios=0;
  const selector={kind:'selector',aspect_ratio:'9:16 (Portrait Widescreen)',megapixels:.7000000000000001,multiple:32};
  const install=async(state=input.state,project=input.project,spec=selector)=>page.evaluate(value=>window.install(value.state,value.project,null,value.spec),{state,project,spec});
  const build=async(name)=>{
    const result=await rpc({action:'04_build',state:await saved(),project:await page.evaluate(()=>structuredClone(fixture))});
    check(result.ready&&result.tuple_count===7);records.push({name,...result});return result;
  };
  const valid=async()=>check((await saved()).alignment!=null&&(await saved()).reference_detection!=null);
  const invalid=async()=>{await page.waitForFunction(()=>JSON.parse(interviewNode.widgets[0].value).alignment===null);check((await saved()).reference_detection===null);};
  await install();check((await page.evaluate(()=>fixture.output_canvas))==null);await detect();await valid();
  deep((await saved()).alignment.canvas,{width:640,height:1152});deep((await build('raw draft detect then actual desk execution')).canvas,{width:640,height:1152});
  await build('immediate repeat execution');check((await page.evaluate(()=>fixture.output_canvas))==null);scenarios++;

  const persisted=JSON.parse(JSON.stringify(await saved()));await install(persisted,JSON.parse(JSON.stringify(input.project)));await valid();await build('JSON serialize/reload same dimensions');scenarios++;
  await page.evaluate(()=>graphFixture.getNodeById(29).widgets.find(row=>row.name==='megapixels').value=.8);await invalid();
  await detect();await valid();await build('dimension change and redetect');scenarios++;
  const canvas=(await saved()).alignment.canvas;
  await page.evaluate(value=>setCanvasSpec({width:{id:920,type:'PrimitiveInt',value:value.width},height:{id:921,type:'INTConstant',value:value.height}}),canvas);
  await page.waitForTimeout(620);await valid();await build('equivalent dimensions different static nodes');scenarios++;
  await page.evaluate(()=>setCanvasSpec(null));await invalid();await detect();await valid();check((await saved()).alignment.canvas===null);await build('disconnect dimensions and redetect');scenarios++;
  for(const spec of [{width:64},{width:{id:930,type:'DynamicThirdParty',value:64},height:96},{kind:'selector',megapixels:.7,multiple:32}]){
    await page.evaluate(value=>setCanvasSpec(value),spec);await invalid();await detect();check((await saved()).alignment===null);
    check((await page.locator('.zv-h3-detection-status').textContent()).includes('尚未核实'));
  }scenarios++;
  const empty=await rpc({action:'04_project',empty:true});await install(empty.state,empty.project);await detect();await valid();check((await saved()).reference_detection.videos.length===0);
  await page.evaluate(()=>setCanvasSpec({width:{id:935,type:'DynamicThirdParty',value:64},height:96}));await invalid();scenarios++;

  await install();await detect();
  check(await page.getByText('驱动音频',{exact:true}).count()>0);
  check(await page.locator('option[value=Hybrid]').textContent()==='混合参考');
  check((await page.locator('.zv-h3-bank-hint').allTextContents()).some(text=>text.includes('当前轨道选段')));
  check((await page.locator('.zv-h3i').textContent()).includes('原片源入 0.500 秒 / 出 2.500 秒'));
  check(!(await page.locator('.zv-h3i').textContent()).includes('T8 只'));scenarios++;
  // Capture actual hidden paired player; native clocks and playback stay untouched.
  await page.evaluate(()=>{window.nativePlay=HTMLMediaElement.prototype.play;window.playedMedia=[];HTMLMediaElement.prototype.play=function(){playedMedia.push(this);return nativePlay.call(this);};});
  const videoCard=page.locator('.zv-h3i-media-card').filter({has:page.locator('.zv-h3i-media-title b:text-is("素材台 Video 1")')});
  const metadata=await rpc({action:'04_preview_metadata'});console.log('H3_04_CACHE_METADATA '+JSON.stringify(metadata));
  await videoCard.locator('.zv-h3-media-thumb').click();
  const mediaState=()=>page.evaluate(()=>{const v=document.querySelector('.zv-h3-shared-preview video');return v&&{time:v.currentTime,duration:String(v.duration),readyState:v.readyState,seeking:v.seeking,start:v.dataset.sourceIn,end:v.dataset.sourceOut};});
  try{await page.waitForFunction(()=>{const v=document.querySelector('.zv-h3-shared-preview video');return v?.readyState>=2&&!v.seeking&&Math.abs(v.currentTime-.5)<.05;});}catch(error){console.log('H3_04_NATIVE_WAIT_FAILURE '+JSON.stringify(await mediaState()));throw error;}
  const first=await page.evaluate(()=>{const v=document.querySelector('.zv-h3-shared-preview video');return {time:v.currentTime,duration:v.duration,readyState:v.readyState,seeking:v.seeking,start:v.dataset.sourceIn,end:v.dataset.sourceOut};});console.log('H3_04_NATIVE_FIRST '+JSON.stringify(first));
  check(Math.abs(first.time-.5)<.05&&first.duration>2.8,JSON.stringify(first));deep([first.start,first.end],['0.5','2.5']);
  await page.evaluate(()=>document.querySelector('.zv-h3-shared-preview video').play());
  await page.waitForFunction(()=>document.querySelector('.zv-h3-shared-preview video').currentTime>.8);
  const clocks=await page.evaluate(()=>{const v=document.querySelector('.zv-h3-shared-preview video'),a=playedMedia.find(p=>p.tagName==='AUDIO');window.previousVideo=v;window.previousSound=a;return {paired:!!a&& !a.isConnected,delta:a?Math.abs(a.currentTime-v.currentTime):99};});
  check(clocks.paired&&clocks.delta<=.2);
  await page.waitForFunction(()=>{const v=document.querySelector('.zv-h3-shared-preview video');return v.paused&&Math.abs(v.currentTime-2.5)<.05;});
  check(await page.evaluate(()=>previousSound.paused));
  records.push({name:'cached video and actual paired audio playback',metadata,first,clocks,final:await page.evaluate(()=>({video_time:previousVideo.currentTime,video_paused:previousVideo.paused,audio_time:previousSound.currentTime,audio_paused:previousSound.paused}))});
  await page.evaluate(()=>{previousVideo.currentTime=0;});await page.waitForFunction(()=>previousVideo.currentTime>=.5);
  await page.evaluate(()=>{previousVideo.currentTime=2.9;});await page.waitForFunction(()=>previousVideo.currentTime<=2.5);
  if(screenshot){await page.evaluate(()=>document.querySelector('.zv-h3i-body aside').scrollTop=0);await page.screenshot({path:screenshot.replace(/\.png$/,'_04_VIDEO.png'),fullPage:true});}scenarios++;
  const audioCard=page.locator('.zv-h3i-media-card').filter({has:page.locator('.zv-h3i-media-title b:text-is("素材台 Audio 1")')});
  await audioCard.locator('.zv-h3-media-thumb').click();await page.waitForFunction(()=>{const a=document.querySelector('.zv-h3-shared-preview audio');return a?.readyState>=2&&!a.seeking&&Math.abs(a.currentTime-.5)<.05;});
  check(await page.evaluate(()=>previousVideo.paused&&!previousVideo.hasAttribute('src')&&previousSound.paused&&!previousSound.hasAttribute('src')));
  check(await page.locator('.zv-h3-shared-preview audio[controls]').count()===1&&await page.locator('.zv-h3i-media-card audio,.zv-h3i-media-card video').count()===0);
  await page.evaluate(()=>document.querySelector('.zv-h3-shared-preview audio').play());
  await page.waitForFunction(()=>{const a=document.querySelector('.zv-h3-shared-preview audio');return a.paused&&Math.abs(a.currentTime-2.5)<.05;});
  records.push({name:'cached independent audio playback',final:await page.evaluate(()=>{const a=document.querySelector('.zv-h3-shared-preview audio');return {time:a.currentTime,duration:a.duration,paused:a.paused,source_in:Number(a.dataset.sourceIn),source_out:Number(a.dataset.sourceOut)};})});
  await page.evaluate(()=>document.querySelector('.zv-h3-shared-preview audio').currentTime=0);await page.waitForFunction(()=>document.querySelector('.zv-h3-shared-preview audio').currentTime>=.5);
  await page.evaluate(()=>document.querySelector('.zv-h3-shared-preview audio').currentTime=2.9);await page.waitForFunction(()=>document.querySelector('.zv-h3-shared-preview audio').currentTime<=2.5);
  check((await page.locator('.zv-h3-shared-preview .zv-h3-source-range').textContent()).includes('本段 2.000 秒'));
  if(screenshot){await page.evaluate(()=>document.querySelector('.zv-h3i-body aside').scrollTop=0);await page.screenshot({path:screenshot.replace(/\.png$/,'_04_AUDIO.png'),fullPage:true});}
  await page.evaluate(()=>HTMLMediaElement.prototype.play=nativePlay);scenarios++;

  const cpuProject=structuredClone(input.project);cpuProject.output_canvas={width:64,height:96};await install(input.state,cpuProject,null);await detect();
  const output=await rpc({action:'matrix_cpu',state:await saved(),project:await page.evaluate(()=>structuredClone(fixture))});
  check(output.ready&&output.tuple_count===24);const v=output.calls.find(row=>row.kind==='video'),a=output.calls.find(row=>row.port==='ref_video_audio_1');
  deep(v.media.shape,[48,96,64,3]);check(Math.abs(v.signatures.rgb_first[1]-36/255)<.015&&Math.abs(v.signatures.rgb_last[1]-177/255)<.015);
  check(Math.abs(a.signatures.audio_sample-2000/32768)<.001);deep(v.source_window,{start_seconds:.5,end_seconds:2.5});deep(a.source_window,v.source_window);
  const independent=output.calls.find(row=>row.port==='ref_audio_1');check(Math.abs(independent.signatures.audio_sample-4196/32768)<.001);deep(independent.source_window,v.source_window);
  records.push({name:'current source segment outside generation window real CPU output',...output});scenarios++;
  const split=structuredClone(cpuProject),left=split.video_track[0],leftAudio=split.audio_track.find(row=>row.clip_id===left.audio_link_id);
  left.source_in_seconds=0;left.source_out_seconds=1;leftAudio.source_in_seconds=0;leftAudio.source_out_seconds=1;
  const right={...left,clip_id:'v1_right',source_in_seconds:1,source_out_seconds:3,timeline_in_seconds:1,audio_link_id:'va1_right'};
  split.video_track.push(right);split.audio_track.push({...leftAudio,clip_id:'va1_right',linked_video_clip_id:right.clip_id,source_video_clip_id:right.clip_id,source_in_seconds:1,source_out_seconds:3,timeline_in_seconds:1});
  await projectChange(split);check(await page.locator('.zv-h3i-media-card').filter({has:page.locator('.zv-h3-routing input[value=ref_videos]')}).count()===2);
  await detect();check((await saved()).alignment===null);
  const assets=JSON.stringify(split.assets);split.video_track=[right];split.audio_track=split.audio_track.filter(row=>row.clip_id!==leftAudio.clip_id);await projectChange(split);await detect();await valid();
  check((await saved()).reference_detection.videos.length===1&&JSON.stringify(split.assets)===assets);
  check((await page.locator('.zv-h3i').textContent()).includes('原片源入 1.000 秒 / 出 3.000 秒'));await build('manual deletion retains remaining same-asset split segment');scenarios++;
  if(screenshot)await writeFile(screenshot.replace(/\.png$/,'_04_MATRIX.json'),JSON.stringify({scope:'production browser JS, registered neutral sources, actual desk/node, cached preview playback and CPU export; no GPU',records,scenarios},null,2));
  console.log(`H3_V2_04_UI_OK ${scenarios} scenarios; raw draft to actual runtime, canvas changes, bounded cached playback and selected CPU source signatures`);return scenarios;
}
