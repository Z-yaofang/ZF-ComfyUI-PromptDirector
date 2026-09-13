import {readFile} from "node:fs/promises";

export async function runPresetCases({page,rpc,check,deep,saved,detect,fixture,projectChange,screenshot}) {
  let scenarios = 0;
  const box = page.locator('.zv-h3-presets'), status = box.locator('.zv-h3-preset-status');
  const names = box.locator('input[name="preset-name"]'), list = box.locator('select[name="preset-list"]');
  const click = name => box.getByRole('button',{name,exact:true}).click();
  const waitStatus = text => page.waitForFunction(text => document.querySelector('.zv-h3-preset-status')?.textContent.includes(text),text);
  const waitRefs = () => page.waitForFunction(() => JSON.parse(interviewNode.widgets[0].value).reference_texts.intent?.definitions.length === 3);
  const payload = text => ({name:'中性预设.json',mimeType:'application/json',buffer:Buffer.from(text)});
  await page.evaluate(value=>install(h3.emptyState(),value),fixture); await detect();
  await page.locator('textarea[name=intent]').fill('让 <Picture 1> 的人物动作接续，<Audio 1> 保留视频原声，<Audio 2> 模仿独立台词，图一与0:02不改写');
  await waitRefs(); await names.fill('主体与声音'); await click('保存新预设'); await waitStatus('已保存');
  check(await list.locator('option').count()===1); const firstId = await list.inputValue(); scenarios++;

  await names.fill('人物自由组合'); await click('改名所选'); await waitStatus('已改名');
  check((await list.locator('option:checked').textContent()).includes('v2'));
  await page.locator('textarea[name=style]').fill('中性示例，保持写实光线'); await click('更新所选'); await waitStatus('已更新');
  check((await list.locator('option:checked').textContent()).includes('v3')); scenarios++;

  await names.fill('续写示例'); await click('保存新预设'); await waitStatus('已保存');
  const secondId = await list.inputValue(); check(firstId!==secondId && await list.locator('option').count()===2); scenarios++;

  await list.selectOption([firstId,secondId]);
  const downloading = page.waitForEvent('download'); await click('导出所选'); const download = await downloading;
  const filePath = screenshot.replace(/\.png$/,'_PRESETS.json'); await download.saveAs(filePath);
  const packageText = await readFile(filePath,'utf8'), packageData = JSON.parse(packageText);
  check(packageData.presets.length===2);
  check(!packageText.includes('item_id')&&!packageText.includes('source_handle')&&!packageText.includes('originals/'));
  scenarios++;

  await box.locator('input[type=file]').setInputFiles(payload(packageText)); await waitStatus('已导入');
  check(await list.locator('option').count()===4);
  check((await list.locator('option').allTextContents()).some(text=>text.includes('副本'))); scenarios++;

  await page.waitForTimeout(200); const current = await saved(), currentProject = await page.evaluate(()=>structuredClone(fixture));
  await list.selectOption(firstId); await click('删除所选'); await waitStatus('已删除库条目');
  deep(await saved(),current); deep(await page.evaluate(()=>structuredClone(fixture)),currentProject); check(await list.locator('option').count()===3); scenarios++;

  await page.reload(); await page.waitForSelector('.zv-h3-presets select option');
  check(await list.locator('option').count()===3); await list.selectOption(secondId); await click('载入所选'); await waitStatus('已载入');
  check((await saved()).intent.includes('<Picture 1>')); scenarios++;

  const remapped = structuredClone(fixture);
  for (const track of ['picture_track','video_track','audio_track']) for (const row of remapped[track]) {
    for (const key of ['item_id','clip_id','linked_video_clip_id','source_video_clip_id','audio_link_id']) if(row[key]) row[key]='new_'+row[key];
  }
  remapped.picture_track.push({item_id:'anchor',asset_id:remapped.picture_track[0].asset_id,order:3});
  const normalized = await rpc({action:'normalize',value:remapped});
  await page.evaluate(value=>{const state=h3.emptyState();state.bindings.anchor={item_id:'anchor',participates:true,banks:['first_frame']};install(state,value);},normalized);
  await page.waitForSelector('.zv-h3-presets select option'); await list.selectOption(secondId); await click('载入所选'); await waitStatus('已载入');
  let state = await saved(); check(state.intent.includes('<Picture 2> 的人物'));
  check(state.reference_texts.intent.definitions[0].source.item_id==='new_p1');
  check((await status.textContent()).includes('另有 1 项当前素材')); await detect(); scenarios++;

  const sorted = await page.evaluate(()=>structuredClone(fixture)); sorted.picture_track[0].order=9;
  await projectChange(sorted); await detect(); state=await saved();
  check(state.intent.includes('<Picture 3> 的人物')&&state.reference_texts.intent.definitions[0].source.item_id==='new_p1'); scenarios++;

  const muted = await page.evaluate(()=>structuredClone(fixture)); muted.video_track[0].source_audio_enabled=false;
  await projectChange(muted); await detect(); state=await saved();
  check(state.intent.includes('<H3待绑定:r2> 保留视频原声')&&state.intent.includes('<Audio 1> 模仿独立台词'));
  check((await page.locator('.zv-h3-model-status').textContent()).includes('待绑定')); scenarios++;

  await page.locator('textarea[name=intent]').fill('用户新增剧情：'+state.intent); await page.waitForTimeout(200);
  muted.video_track[0].source_audio_enabled=true; await projectChange(muted); await detect(); state=await saved();
  check(state.intent.startsWith('用户新增剧情：')&&state.intent.includes('<Audio 1> 保留视频原声')&&state.intent.includes('<Audio 2> 模仿独立台词')); scenarios++;

  const restored = state; const project = await page.evaluate(()=>structuredClone(fixture));
  await page.evaluate(value=>install(value.state,value.project),{state:JSON.parse(JSON.stringify(restored)),project}); await detect();
  deep((await saved()).reference_texts.intent.definitions.map(row=>row.source.item_id),restored.reference_texts.intent.definitions.map(row=>row.source.item_id)); scenarios++;

  await page.locator('textarea[name=intent]').fill('用户编辑 <Picture 9>，不要覆盖这句话'); await page.waitForTimeout(220);
  check(await page.locator('textarea[name=intent]').inputValue()==='用户编辑 <Picture 9>，不要覆盖这句话');
  await names.fill('未解析示例'); await click('保存新预设'); await waitStatus('尚未解析');
  check(await page.locator('textarea[name=intent]').inputValue()==='用户编辑 <Picture 9>，不要覆盖这句话');
  await page.locator('textarea[name=intent]').fill('自由续写，普通数字1与0:02不改写'); await page.waitForTimeout(200); await detect();
  await names.fill('自由续写'); await click('保存新预设'); await waitStatus('已保存'); scenarios++;

  const invalid = structuredClone(packageData); invalid.presets[0].template.fields.intent.definitions[0].source.bank='unknown';
  await box.locator('input[type=file]').setInputFiles(payload(JSON.stringify(invalid))); await waitStatus('不匹配');
  check(await list.locator('option').count()===4); scenarios++;

  await list.selectOption(secondId); await click('载入所选'); await waitStatus('已载入'); await detect();
  await page.locator('textarea[name=intent]').focus();
  const insert = page.getByRole('button',{name:'插入 <Picture 2> · reference',exact:true}).first();
  await insert.click(); await page.waitForTimeout(200);
  check((await saved()).intent.includes('<Picture 2>')); scenarios++;
  await page.evaluate(()=>{document.querySelector('.zv-h3i-body aside').scrollTop=0;document.querySelector('.zv-h3i-body main').scrollTop=0;});
  await page.screenshot({path:screenshot.replace(/\.png$/,'_LIBRARY.png'),fullPage:true});
  console.log(`H3_PRESETS_UI_OK ${scenarios} preset/reference scenarios; persistence, CRUD, multi-import/export, remap, sort, pair changes, editing, workflow restore and no private evidence`);
  return scenarios;
}
