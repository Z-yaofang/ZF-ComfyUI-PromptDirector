// Local fixtures served by Playwright routes; no application or API connection.
// node tests/portrait_ui_smoke.mjs PLAYWRIGHT_PACKAGE CHROMIUM_EXECUTABLE [SCREENSHOT]
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
const {chromium}=createRequire(import.meta.url)(process.argv[2]||'playwright');
const source=await readFile(new URL('../web/portrait_generator.js',import.meta.url),'utf8');
const catalog=JSON.parse(await readFile(new URL('../data/portrait_generator_v12.json',import.meta.url),'utf8'));
const fields=catalog.sections.flatMap(section=>section.fields.map(field=>({section,field})));
const realOptions=field=>field.options.filter(o=>o.value&&o.value!=='不启用'&&!o.adult);
const key=(field,value)=>`${field}::${value}`;
const shortLabel=value=>value.replace(/[（(][^）)]*[）)]/g,'').trim();
const browser=await chromium.launch({headless:true,executablePath:process.argv[3],ignoreDefaultArgs:['--hide-scrollbars']});
const page=await browser.newPage({viewport:{width:1360,height:900}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));let checks=0;
const html=`<!doctype html><meta charset="utf-8"><style>body{background:#10151d;margin:24px}#mount{width:600px}</style><div id="mount"></div><script type="module">
import '/portrait.js';import {app} from '/scripts/app.js';
window.resetPortrait=(initial,quantity=1,properties={})=>{window.portraitNode?.onRemoved?.();document.querySelector('#mount').replaceChildren();window.portraitNode={comfyClass:'ZIPortraitPromptGenerator',type:'ZIPortraitPromptGenerator',properties:structuredClone(properties),widgets:[{name:'state_json',value:JSON.stringify(initial)},{name:'seed',value:0},{name:'control_after_generate',value:'randomize'},{name:'adult_content',value:!!initial.adult_content},{name:'quantity',value:quantity,callback(){} }],size:[600,250],setSize(){},setDirtyCanvas(){},addDOMWidget(name,type,root){document.querySelector('#mount').append(root);return {};}};app.extensions.find(e=>e.name==='ZI.PromptDirector.PortraitGenerator').nodeCreated(portraitNode);};resetPortrait({version:6});
</script>`;
await page.route('**/*',route=>{
    const path=new URL(route.request().url()).pathname;
    const content=path==='/'?html:path==='/portrait.js'?source:path==='/scripts/app.js'?'export const app={extensions:[],registerExtension(e){this.extensions.push(e)}};':path==='/zf-prompt-director/portrait-catalog'?JSON.stringify(catalog):null;
    if(content===null)return route.abort();
    return route.fulfill({status:200,contentType:path==='/'?'text/html':path.endsWith('.js')?'application/javascript':'application/json',body:content});
});
const state=()=>page.evaluate(()=>JSON.parse(portraitNode.widgets[0].value));
const card=k=>page.locator(`[data-option-key=${JSON.stringify(k)}]`);
const ready=()=>page.waitForFunction(()=>JSON.parse(portraitNode.widgets[0].value).version===7&&document.querySelector('.zf-pg-add'));
async function reset(initial={version:6},quantity=1,properties={}) {await page.evaluate(({initial,quantity,properties})=>resetPortrait(initial,quantity,properties),{initial,quantity,properties});await ready();}
async function openField(id) {
    if(!await page.locator('.zf-pg-overlay').count())await page.getByRole('button',{name:'＋ 添加项目',exact:true}).click();
    const {section,field}=fields.find(x=>x.field.id===id);
    await page.locator('.zf-pg-section-button').filter({has:page.getByText(section.title,{exact:true})}).click();
    await page.locator('.zf-pg-field-tab').filter({hasText:shortLabel(field.label)}).first().click();
    await page.waitForFunction(id=>document.querySelector('.zf-pg-overlay').dataset.fieldId===id,id);
}
async function editorLayout() {
    const result=await page.locator('.zf-pg-options').evaluate(options=>{
        const editor=options.querySelector('.zf-pg-option-editor'),r=options.getBoundingClientRect(),e=editor.getBoundingClientRect();
        const within=el=>{const b=el.getBoundingClientRect();return b.top>=r.top-1&&b.bottom<=r.bottom+1&&b.left>=r.left-1&&b.right<=r.right+1;};
        return {first:options.firstElementChild===editor,scroll:options.scrollTop,gridColumn:getComputedStyle(editor).gridColumn,
            formVisible:[editor.querySelector('textarea'),...editor.querySelectorAll('.zf-pg-option-edit-actions button')].every(within),
            otherCardsBelow:[...options.querySelectorAll('.zf-pg-option:not(.zf-pg-option-editor)')].every(c=>c.getBoundingClientRect().top>=e.bottom),
            wrap:getComputedStyle(editor.querySelector('.zf-pg-option-edit-actions')).flexWrap};
    });
    assert(result.first&&result.formVisible&&result.otherCardsBelow);assert.equal(result.scroll,0);assert.equal(result.gridColumn,'1 / -1');assert.equal(result.wrap,'wrap');
}
try {
    await page.goto('http://portrait.test/');await ready();assert.deepEqual((await state()).excluded_options,{});checks++;
    await page.evaluate(()=>{const widget=portraitNode.widgets.find(w=>w.name==='quantity');widget.value=7;widget.callback(7);});
    const quantityProperties=await page.evaluate(()=>structuredClone(portraitNode.properties));assert.equal(quantityProperties.zf_portrait_quantity,7);
    await reset(await state(),1,quantityProperties);assert.equal(await page.evaluate(()=>portraitNode.widgets.find(w=>w.name==='quantity').value),7);checks++;
    await reset(await state(),4,quantityProperties);assert.equal(await page.evaluate(()=>portraitNode.properties.zf_portrait_quantity),4);checks++;
    const lens=fields.find(x=>x.field.id==='lens').field,[a,b]=realOptions(lens),ka=key('lens',a.value),kb=key('lens',b.value);
    await reset({version:6,selected:{lens:a.value},option_overrides:{[ka]:'CUSTOM_LENS_ASSET'}});await openField('lens');
    const count=await page.locator('.zf-pg-option').count(),position=await card(ka).boundingBox();
    await card(ka).locator('.zf-pg-option-exclude').click();
    assert.equal((await state()).excluded_options[ka],true);assert(!('lens' in (await state()).selected));assert.equal((await state()).option_overrides[ka],'CUSTOM_LENS_ASSET');
    assert.equal(await page.locator('.zf-pg-option').count(),count);assert.deepEqual(await card(ka).boundingBox(),position);assert.equal(await card(ka).locator('.zf-pg-option-exclude').textContent(),'＋');checks++;
    await card(ka).dispatchEvent('click');await card(ka).dispatchEvent('dblclick');assert(!('lens' in (await state()).selected));assert.equal(await page.locator('.zf-pg-option-editor').count(),0);checks++;
    await card(ka).locator('.zf-pg-option-exclude').click();assert(!(await state()).excluded_options[ka]);assert(!('lens' in (await state()).selected));checks++;
    await card(ka).locator('.zf-pg-option-exclude').dblclick();assert.equal((await state()).excluded_options[ka],true);assert.equal(await page.locator('.zf-pg-option-editor').count(),0);checks++;
    await page.getByRole('button',{name:'本段排除',exact:true}).click();assert.equal((await state()).section_enabled.shooting_light,false);
    await page.getByRole('button',{name:'本段启用',exact:true}).click();assert.equal((await state()).section_enabled.shooting_light,true);assert.equal((await state()).excluded_options[ka],true);checks++;
    await page.getByRole('button',{name:'节点修复',exact:true}).click();assert.deepEqual((await state()).option_overrides,{});assert.equal((await state()).excluded_options[ka],true);checks++;
    const persisted=await state();await reset(persisted);await openField('lens');assert(await card(ka).evaluate(c=>c.classList.contains('excluded')));checks++;
    for(const locks of [{locked:{lens:true}},{section_locked:{shooting_light:true},section_lock_items:{lens:true}}]) {
        await reset({version:7,selected:{lens:a.value},...locks});await openField('lens');
        await card(ka).locator('.zf-pg-option-exclude').click();assert.equal((await state()).selected.lens,a.value);assert(!(await state()).excluded_options[ka]);assert((await page.locator('.zf-pg-notice').textContent()).includes('请先解锁'));checks++;
        await card(kb).locator('.zf-pg-option-exclude').click();assert.equal((await state()).excluded_options[kb],true);assert.equal((await state()).selected.lens,a.value);checks++;
    }
    for(const [id,categoryId] of [['clothItem','clothCat'],['lingerieItem','lingerieCat']]) {
        const field=fields.find(x=>x.field.id===id).field;
        const groups=[...new Set(field.options.map(o=>o.group).filter(Boolean))];
        const group=groups.find(g=>field.options.filter(o=>o.group===g).length>=3);
        const same=field.options.filter(o=>o.group===group),other=field.options.find(o=>o.group&&o.group!==group);
        const category=categoryId==='clothCat'?group:fields.find(x=>x.field.id===categoryId).field.options.find(o=>String(o.value).split('·').at(-1)===group).value;
        const keys=[key(id,same[0].value),key(id,same[1].value)],otherKey=key(id,other.value);
        await reset({version:7,adult_content:id==='lingerieItem',selected:{[categoryId]:category},excluded_options:{[keys[0]]:true,[keys[1]]:true,[otherKey]:true,[ka]:true}});await openField(id);
        assert(await card(keys[0]).count());assert.equal(await card(otherKey).count(),0);checks++;
        await page.locator('.zf-pg-search').fill(same[0].value);const selectedBefore=(await state()).selected;
        await page.getByRole('button',{name:'＋ 一键添加',exact:true}).click();
        const restored=await state();assert(keys.every(k=>!restored.excluded_options[k]));assert(restored.excluded_options[otherKey]&&restored.excluded_options[ka]);assert.deepEqual(restored.selected,selectedBefore);
        assert((await page.locator('.zf-pg-notice').textContent()).includes('2 项'));assert(await page.getByRole('button',{name:'＋ 一键添加',exact:true}).isDisabled());checks++;
    }
    const excluded=Object.fromEntries(realOptions(lens).filter(o=>o.value!==a.value).map(o=>[key('lens',o.value),true]));
    await reset({version:7,excluded_options:excluded});
    for(let i=0;i<8;i++){await page.getByRole('button',{name:'随机',exact:true}).click();assert.equal((await state()).selected.lens,a.value);}
    await page.getByRole('button',{name:'自动随机：关',exact:true}).click();assert((await state()).auto_random);assert.deepEqual((await state()).excluded_options,excluded);checks++;
    const dense=fields.filter(x=>!x.field.adult&&!['clothItem','lingerieItem'].includes(x.field.id)).sort((x,y)=>realOptions(y.field).length-realOptions(x.field).length)[0].field;
    for(const viewport of [{width:1360,height:900},{width:960,height:700}]) {
        await page.setViewportSize(viewport);await reset();await openField(dense.id);
        const cards=page.locator('.zf-pg-option'),index=Math.min(80,await cards.count()-1),target=cards.nth(index),editKey=await target.getAttribute('data-option-key');
        await target.locator('.zf-pg-option-value').dblclick();await page.waitForSelector('.zf-pg-option-editor textarea');await editorLayout();checks++;
        if(process.argv[4]&&viewport.width===1360)await page.locator('.zf-pg-dialog').screenshot({path:process.argv[4]});
        await page.locator('.zf-pg-option-editor textarea').fill('LOCAL_EDITOR_TEST');await page.getByRole('button',{name:'确认保存',exact:true}).click();assert.equal((await state()).option_overrides[editKey],'LOCAL_EDITOR_TEST');checks++;
        await card(editKey).locator('.zf-pg-option-value').dblclick();await page.locator('.zf-pg-option-editor textarea').fill('DO_NOT_SAVE');await page.getByRole('button',{name:'取消',exact:true}).click();assert.equal((await state()).option_overrides[editKey],'LOCAL_EDITOR_TEST');checks++;
    }
    assert.deepEqual(errors,[]);console.log(`PORTRAIT_UI_OK ${checks} browser checks; no page exceptions`);
} finally {await browser.close();}
