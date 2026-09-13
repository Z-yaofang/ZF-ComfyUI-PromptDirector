// node tests/zfi_reroute_ui_smoke.mjs PLAYWRIGHT_PACKAGE CHROMIUM_EXECUTABLE
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';

const {chromium}=createRequire(import.meta.url)(process.argv[2]||'playwright');
const source=await readFile(new URL('../web/zfi_reroute.js',import.meta.url),'utf8');
const browser=await chromium.launch({headless:true,executablePath:process.argv[3]});
const page=await browser.newPage(),errors=[];
page.on('pageerror',error=>errors.push(error.message));
const html=`<!doctype html>
<script>
class LGraphNode {
  constructor(title){this.title=title;this.size=[200,100];this.properties={};this.widgets=[];this.inputs=[];this.outputs=[];}
  addWidget(type,name,value,callback,options){const widget={type,name,value,callback,options};this.widgets.push(widget);return widget;}
  addInput(name,type){this.inputs.push({name,type,link:null});return this.inputs.at(-1);}
  addOutput(name,type){this.outputs.push({name,type,links:[]});return this.outputs.at(-1);}
  removeInput(index){this.inputs.splice(index,1);}
  removeOutput(index){this.outputs.splice(index,1);}
  computeSize(){return [220,92+Math.max(this.inputs.length,this.outputs.length)*12];}
  setSize(size){this.size=size;}
  setDirtyCanvas(){}
}
window.LiteGraph={LGraphNode,registered:{},registerNodeType(type,ctor){this.registered[type]=ctor;},createNode(type){return new this.registered[type]();}};
</script>
<script type="module">
import {app} from '/scripts/app.js';
import '/zfi.js';
app.extensions.find(extension=>extension.name==='ZF.PromptDirector.ZFI').registerCustomNodes();
window.node=LiteGraph.createNode('ZFI');
window.sourceNode={id:101,outputs:[{type:'IMAGE'}]};
node.graph={links:{11:{origin_id:101,origin_slot:0}},getNodeById(id){return id===101?sourceNode:null;},setDirtyCanvas(){}};
node.inputs[0].link=11;
</script>`;
await page.route('**/*',route=>{
  const path=new URL(route.request().url()).pathname;
  const body=path==='/'?html:path==='/zfi.js'?source:path==='/scripts/app.js'?'export const app={extensions:[],registerExtension(extension){this.extensions.push(extension)}};':null;
  return body==null?route.abort():route.fulfill({contentType:path==='/'?'text/html':'application/javascript',body});
});

try {
  await page.goto('https://zfi.test/');
  await page.waitForFunction(()=>window.node?.inputs?.length===3);
  let state=await page.evaluate(()=>({
    title:node.title,
    virtual:node.isVirtualNode,
    inputLabels:node.inputs.map(x=>x.label),
    outputLabels:node.outputs.map(x=>x.label),
    hasExecute:typeof node.onExecute==='function',
    resolved:node.resolveVirtualOutput(0),
  }));
  assert.equal(state.title,'ZFI · 3 路转接');
  assert.equal(state.virtual,true);
  assert.equal(state.hasExecute,false);
  assert.deepEqual(state.inputLabels,['1','2','3']);
  assert.deepEqual(state.outputLabels,['1','2','3']);
  assert.equal(state.resolved.node.id,101);
  assert.equal(state.resolved.slot,0);

  await page.evaluate(()=>node.widgets[1].callback('图片'));
  await page.waitForFunction(()=>node.inputs[2].label==='图片3');
  state=await page.evaluate(()=>({
    widgetName:node.widgets[1].name,
    inputLabels:node.inputs.map(x=>x.label),
    outputLabels:node.outputs.map(x=>x.label),
  }));
  assert.equal(state.widgetName,'通道名称');
  assert.deepEqual(state.inputLabels,['图片1','图片2','图片3']);
  assert.deepEqual(state.outputLabels,state.inputLabels);
  const shorthandRestored=await page.evaluate(()=>{
    const copy=LiteGraph.createNode('ZFI');
    const widgets=[3,'图片'];
    copy.widgets.forEach((widget,index)=>{widget.value=widgets[index];});
    copy.onConfigure({properties:{zfi:{version:1,channel_count:3,channel_notes:'图片'}},widgets_values:widgets});
    return copy.outputs.map(output=>output.label);
  });
  assert.deepEqual(shorthandRestored,['图片1','图片2','图片3']);

  await page.evaluate(()=>{
    node.outputs[0].links=[91,92,93];
    node.widgets[1].callback('图片1 | 视频1 | 音频1 | 处理窗口');
    node.widgets[0].callback(4);
  });
  await page.waitForFunction(()=>node.inputs.length===4&&node.inputs[3].label==='处理窗口');
  state=await page.evaluate(()=>({
    inputLabels:node.inputs.map(x=>x.label),
    outputLabels:node.outputs.map(x=>x.label),
    fanout:node.outputs[0].links,
    size:node.size,
  }));
  assert.deepEqual(state.inputLabels,['图片1','视频1','音频1','处理窗口']);
  assert.deepEqual(state.outputLabels,state.inputLabels);
  assert.deepEqual(state.fanout,[91,92,93]);
  assert(state.size[0]>=240);

  const saved=await page.evaluate(()=>{const info={};node.onSerialize(info);return {info,widgets:node.widgets.map(widget=>widget.value)};});
  assert.deepEqual(saved.info.properties.zfi,{version:1,channel_count:4,channel_notes:'图片1 | 视频1 | 音频1 | 处理窗口'});
  assert.deepEqual(saved.widgets,[4,'图片1 | 视频1 | 音频1 | 处理窗口']);
  const restored=await page.evaluate(({info,widgets})=>{
    const copy=LiteGraph.createNode('ZFI');
    copy.widgets.forEach((widget,index)=>{widget.value=widgets[index];});
    copy.onConfigure({...info,widgets_values:widgets});
    return {title:copy.title,labels:copy.outputs.map(output=>output.label),virtual:copy.isVirtualNode};
  },saved);
  assert.deepEqual(restored,{title:'ZFI · 4 路转接',labels:['图片1','视频1','音频1','处理窗口'],virtual:true});

  await page.evaluate(()=>node.widgets[0].callback(2));
  await page.waitForFunction(()=>node.inputs.length===2&&node.outputs.length===2);
  assert.deepEqual(await page.evaluate(()=>node.outputs[0].links),[91,92,93]);
  assert.deepEqual(errors,[]);
  console.log('ZFI_UI_OK frontend-only virtual reroute, direct resolution, persistence, and fan-out');
} finally {await browser.close();}
