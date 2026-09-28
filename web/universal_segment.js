import {app} from "/scripts/app.js";
import {pinDOMWidgetFullWidth} from "./dom_widget_layout.mjs";
import {clone,defaultSettings as h3Defaults,parse,manual,changeSegment,splitSegment,removeSegment,addSegment,readDesk} from "./long_video_core.mjs";
import {defaultSettings as animateDefaults,parseSettings as parseAnimate,readWorkflowFps} from "./animate_video_core.mjs";

const api=globalThis.comfyAPI?.api?.api??{apiURL:path=>path,fetchApi:(path,options)=>fetch(path,options)};
const sheet=document.createElement("link");sheet.rel="stylesheet";sheet.href=new URL("./universal_segment.css",import.meta.url).href;document.head.append(sheet);
const el=(tag,cls="",text)=>{const element=document.createElement(tag);element.className=cls;if(text!==undefined)element.textContent=text;return element;};
const button=(text,run)=>{const element=el("button","",text);element.type="button";element.onclick=run;return element;};
const select=(choices,value,change)=>{const element=el("select");for(const [key,label] of choices){const option=el("option","",label);option.value=key;element.append(option);}element.value=value;element.onchange=()=>change(element.value);return element;};
const number=(value,change,minimum=0)=>{const element=el("input");element.type="number";element.step="1";element.min=minimum;element.value=value;element.onfocus=()=>element.select();element.onchange=()=>{const next=Number(element.value);if(Number.isInteger(next)&&next>=minimum)change(next);};return element;};
const field=(label,control)=>{const element=el("label","",label);element.append(control);return element;};
const seconds=value=>Number(value??0).toFixed(3);
const guideOverlap=frames=>frames===1||(frames>=5&&(frames-5)%17===0);

function defaultData(){return {schema_version:1,h3:h3Defaults(),animate:animateDefaults()};}
function readData(value){
    const stored=parse(value,defaultData),result=defaultData();
    const wrapped="h3" in stored||"animate" in stored;
    if(wrapped){
        if(stored.schema_version!==1)return result;
        if(stored.h3&&typeof stored.h3==="object"&&!Array.isArray(stored.h3))result.h3={...result.h3,...stored.h3};
        if(stored.animate)result.animate=parseAnimate(JSON.stringify(stored.animate));
    }else if("seam_mode" in stored)result.animate=parseAnimate(JSON.stringify(stored));
    else if(stored.schema_version===1&&"mode" in stored)result.h3={...result.h3,...stored};
    return result;
}

export function attachUniversalDesk(node){
    if(node.zvUniversal)return;
    const dataWidget=node.widgets?.find(row=>row.name==="segment_data"),modeWidget=node.widgets?.find(row=>row.name==="target_mode");
    if(!dataWidget||!modeWidget)return;
    for(const widget of [dataWidget,modeWidget]){widget.type="converted-widget";widget.computeSize=()=>[0,-4];if(widget.inputEl)widget.inputEl.style.display="none";}
    const root=el("div","zv-universal"),head=el("div","zv-universal-head"),controls=el("div","zv-universal-controls"),railScroll=el("div","zv-universal-scroll"),rail=el("div","zv-universal-rail"),note=el("p","zv-universal-hint"),status=el("div","zv-universal-status");
    head.append(el("h3","","ZV 通用分段台"));railScroll.append(rail);root.append(head,el("p","zv-universal-intro","每段从同一套素材台取料，交给现有模型执行链逐段处理；采访与遮罩模型仍由各自流程管理。"),controls,railScroll,note,status);
    for(const event of ["pointerdown","wheel","keydown"])root.addEventListener(event,e=>e.stopPropagation());
    const dom=node.addDOMWidget("zv_universal_ui","zv-universal",root,{serialize:false,hideOnZoom:false,getMinHeight:()=>500,getMaxHeight:()=>900});dom.serialize=false;pinDOMWidgetFullWidth(dom);
    node.setSize?.([Math.max(1100,node.size?.[0]??0),Math.max(610,node.size?.[1]??0)]);
    let data=readData(dataWidget.value),mode=modeWidget.value==="Animate"?"Animate":"H3",plan=null,disposed=false,token=0,sourceText="",refreshTimer=null;
    const persist=()=>{dataWidget.value=JSON.stringify(data);modeWidget.value=mode;node.graph?.setDirtyCanvas?.(true,true);root.dispatchEvent(new CustomEvent("zv-segment-change"));};
    const report=(message,error=false)=>{status.textContent=message;status.classList.toggle("error",error);};
    const commitH3=next=>{data.h3=next;persist();refresh();};
    const assetMap=project=>new Map((project?.assets??[]).map(row=>[row.asset_id,row]));
    function preview(asset){
        if(!asset?.source_handle||asset.kind!=="picture")return null;
        const image=el("img");image.alt=asset.name??"参考图片";image.src=api.apiURL(`/zf-media-evidence/preview?source=${encodeURIComponent(asset.source_handle)}&variant=thumbnail`);return image;
    }
    function mediaCard(kind,row,assets){
        const asset=assets.get(row.asset_id),card=el("div",`zv-universal-media ${kind}`),image=kind==="picture"?preview(asset):null;
        if(image)card.append(image);
        const body=el("div","zv-universal-media-body");body.append(el("strong","",asset?.name??row.asset_id));
        if(kind==="picture")body.append(el("small","","参考图片 · 本段是否参与由采访表决定"));
        else body.append(el("small","",`源 ${seconds(row.source_in_seconds)}–${seconds(row.source_out_seconds)} 秒`));
        card.append(body);return card;
    }
    function renderH3(){
        const settings=data.h3,seam=settings.overlap_alignment==="h3_guide"?"guide":settings.overlap_frames===0?"hard_cut":"exact",overlap=number(settings.overlap_frames,value=>commitH3({...settings,overlap_frames:value}));
        overlap.disabled=seam==="hard_cut";
        controls.replaceChildren(field("用途",select([["H3","H3 长视频"],["Animate","Animate"]],mode,value=>switchMode(value))),
            field("排列方式",select([["source_auto","按素材长度"],["generation_count","按段数生成"],["source_manual","手动源分段"],["generation_manual","手动生成"]],settings.mode,value=>commitH3(value.endsWith("_manual")&&plan?manual(settings,plan,value):{...settings,mode:value}))),
            field("分段时钟 fps",number(settings.fps,value=>commitH3({...settings,fps:value}),1)),
            field("单段运行帧数",number(settings.segment_frames,value=>commitH3({...settings,segment_frames:value}),1)),
            field("请求重叠",overlap),
            field("衔接",select([["guide","H3 Guide 自动对齐"],["hard_cut","硬切（0 帧）"],["exact","精确重叠（高级）"]],seam,value=>commitH3({...settings,overlap_alignment:value==="guide"?"h3_guide":"exact",overlap_frames:value==="hard_cut"?0:settings.overlap_frames||39}))),
            ...(settings.mode==="generation_count"?[field("生成段数",number(settings.segment_count,value=>commitH3({...settings,segment_count:value}),1))]:[]),
            button("获取素材台三轨",()=>refresh(true)),
            button("一键排列",()=>commitH3({...settings,mode:settings.mode.startsWith("generation")?"generation_count":"source_auto",segments:[]})));
        note.textContent=(seam==="exact"?"高级精确重叠不自动对齐：现有 H3 Guide 执行链只接受 1 或 5+17k 帧（如 22、39、56）；填 32 帧会在下游失败。可改用 Guide 自动对齐或硬切。":"H3 总段数不受 15 秒限制。硬切固定 0 帧；Guide 请求帧数会对齐到 1 或 5+17k，卡片显示实际承接帧数。")+" 这里的帧号属于分段/生成时钟，不是素材台窗口帧；素材按秒映射。每段要求仍在采访表填写。";
        note.classList.toggle("warning",seam==="exact");
        rail.replaceChildren();
        if(!plan){rail.append(el("p","zv-universal-empty","连接素材台后显示每段对应的图片、视频、音频。"));return;}
        const assets=assetMap(plan.media_project);
        for(const segment of plan.segments){
            const column=el("section","zv-universal-segment"),title=el("div","zv-universal-title"),source=segment.source_slices;
            title.append(el("strong","",`第 ${segment.order} 段 · ${segment.frame_count} 运行帧 / ${seconds(segment.frame_count/plan.fps)} 秒`),el("span","",segment.seam==="first"?"起点":segment.seam==="hard_cut"?"硬切":`承接 ${segment.overlap_frames} 帧`));
            column.append(title);
            for(const [kind,rows,label] of [["picture",source.pictures,"图片"],["video",source.video,"视频"],["audio",source.audio,"音频"]]){
                const group=el("div","zv-universal-group");group.append(el("small","zv-universal-group-label",label));
                if(rows.length)for(const row of rows)group.append(mediaCard(kind,row,assets));
                else group.append(el("div","zv-universal-missing",`本段没有${label}素材`));
                column.append(group);
            }
            const edits=el("div","zv-universal-edits"),start=number(segment.start_frame,value=>commitH3(changeSegment(data.h3,plan,segment.segment_id,value,segment.end_frame))),end=number(segment.end_frame,value=>commitH3(changeSegment(data.h3,plan,segment.segment_id,segment.start_frame,value)),1),splitAt=number(Math.floor((segment.start_frame+segment.end_frame-1)/2),()=>{},segment.start_frame);
            splitAt.max=segment.end_frame-2;
            const splitButton=button("当前帧后分割",()=>{const selectedFrame=Number(splitAt.value),boundary=selectedFrame+1;if(Number.isInteger(selectedFrame)&&selectedFrame>=segment.start_frame&&boundary<segment.end_frame)commitH3(splitSegment(data.h3,plan,segment.segment_id,boundary));});
            edits.append(field("分段起帧",start),field("分段终帧（不含）",end),field("前段最后帧",splitAt),splitButton,button("删除本段",()=>commitH3(removeSegment(data.h3,plan,segment.segment_id))));
            column.append(edits,el("div","zv-universal-foot",`输出贡献 ${segment.output_frame_count} 帧 · 模型长度 ${segment.model_padding.model_length??"执行时确定"} 帧`));rail.append(column);
        }
        const add=button("＋ 增加一段",()=>commitH3(addSegment(data.h3,plan)));rail.append(add);
    }
    function renderAnimate(){
        const settings=data.animate;
        controls.replaceChildren(field("用途",select([["H3","H3 长视频"],["Animate","Animate"]],mode,value=>switchMode(value))),
            field("段间衔接",select([["hard_cut","硬切"],["continuation_21","原生 21 帧承接"]],settings.seam_mode,value=>{data.animate={...settings,seam_mode:value};persist();refresh();})),
            button("刷新素材配对",()=>refresh()));
        note.textContent="Animate 每个视频片段自动成一段，不限制单段或合计时长；切点和图片顺序在素材台编辑。卡片显示的是运行帧，不是素材台窗口帧。通用台不填写逐段遮罩帧或目标词；需要遮罩时继续使用 Animate 素材配对台。";
        rail.replaceChildren();
        if(!plan){rail.append(el("p","zv-universal-empty","连接素材台后显示自动配对结果。"));return;}
        const assets=assetMap(plan.media_project);
        for(const segment of plan.segments){
            const column=el("section","zv-universal-segment"),picture=assets.get(segment.picture_asset_id),video=assets.get(segment.video_asset_id),title=el("div","zv-universal-title");
            title.append(el("strong","",`第 ${segment.ordinal} 段 · ${segment.frame_count} 运行帧`),el("span","",segment.ordinal===1?"起点":segment.guide_frame_count?`承接 ${segment.guide_frame_count} 帧`:"硬切"));column.append(title);
            const pic=el("div","zv-universal-group");pic.append(el("small","zv-universal-group-label","图片"),mediaCard("picture",{asset_id:segment.picture_asset_id},assets));
            const clip=el("div","zv-universal-group");clip.append(el("small","zv-universal-group-label","视频"),mediaCard("video",{asset_id:segment.video_asset_id,source_in_seconds:segment.source_start_seconds,source_out_seconds:segment.source_end_seconds},assets));
            column.append(pic,clip,el("div","zv-universal-foot",`${video?.name??"源视频"} · ${segment.source_audio_enabled?"保留原声":"无原声"}`));rail.append(column);
        }
    }
    function render(){if(mode==="H3")renderH3();else renderAnimate();}
    function switchMode(value){mode=value;persist();plan=null;render();refresh();}
    async function refresh(reload=false){
        const run=++token;let project;
        try{project=readDesk(node).project;}catch(error){plan=null;render();report(error.message,true);return;}
        const currentMode=mode,clock=mode==="Animate"?readWorkflowFps(node):null,source=JSON.stringify({project,clock,mode}),settings=clone(mode==="H3"?data.h3:data.animate);
        sourceText=source;plan=null;render();report("正在检查分段素材…");
        const endpoint=mode==="H3"?"/zf-prompt-director/long-video/plan":"/zf-prompt-director/animate-video/plan";
        const body=mode==="H3"?{media_project:project,settings:{...settings,refresh_sources:reload}}:{media_project:project,settings,fps:clock.fps};
        try{
            const response=await api.fetchApi(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}),result=await response.json();
            if(disposed||run!==token||mode!==currentMode||JSON.stringify(mode==="H3"?data.h3:data.animate)!==JSON.stringify(settings))return;
            if(!response.ok)throw new Error(result.error||result.errors?.map(row=>row.message).join("；")||`检查失败 ${response.status}`);
            const current=JSON.stringify({project:readDesk(node).project,clock:mode==="Animate"?readWorkflowFps(node):null,mode});
            if(current!==source){refresh();return;}
            plan=result.plan;
            if(mode==="H3"){
                data.h3={...data.h3,source_snapshot:clone(plan.media_project),source_fingerprint:plan.source_fingerprint,refresh_sources:false};
                if(!data.h3.segments.length&&plan.segments.length)data.h3.segments=plan.segments.map(({segment_id,start_frame,end_frame})=>({segment_id,start_frame,end_frame}));
            }else data.animate=clone(plan.settings);
            persist();render();
            const invalidGuide=mode==="H3"&&data.h3.overlap_alignment==="exact"&&plan.segments.some(row=>row.overlap_frames>0&&!guideOverlap(row.overlap_frames));
            const messages=[`${plan.segments.length} 段 · ${plan.target_frame_count} 运行帧 / ${seconds(plan.target_frame_count/plan.fps)} 秒`,...plan.validation.errors.map(row=>row.message),...plan.validation.warnings.map(row=>row.message)];
            if(invalidGuide)messages.push("精确重叠不符合 H3 Guide 执行帧数；请选择 Guide 自动对齐或硬切（0 帧）。");
            report(messages.join("\n"),!plan.validation.ready||invalidGuide);
        }catch(error){if(!disposed&&run===token){plan=null;render();report(error.message,true);}}
    }
    node.zvUniversal={root,refresh,getMode:()=>mode,getPlan:()=>plan,restore(){token++;data=readData(dataWidget.value);mode=modeWidget.value==="Animate"?"Animate":"H3";plan=null;render();refresh();}};
    node.zvLong={root,refresh,getSettings:()=>clone(data.h3),getPlan:()=>mode==="H3"?plan:null,restore:()=>node.zvUniversal.restore()};
    node.zvAnimate={root,refresh,getSettings:()=>clone(data.animate),getPlan:()=>mode==="Animate"?plan:null,restore:()=>node.zvUniversal.restore()};
    const timer=setInterval(()=>{if(disposed)return;try{const current=JSON.stringify({project:readDesk(node).project,clock:mode==="Animate"?readWorkflowFps(node):null,mode});if(current!==sourceText)refresh();}catch{if(plan){plan=null;render();report("素材台连接已断开，请重新连接。",true);}}},1500);
    const removed=node.onRemoved;node.onRemoved=function(){disposed=true;token++;clearInterval(timer);clearTimeout(refreshTimer);root.remove();removed?.apply(this,arguments);};
    const connections=node.onConnectionsChange;node.onConnectionsChange=function(){connections?.apply(this,arguments);clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>{if(!disposed)refresh();},0);};
    persist();render();refresh();
}

app.registerExtension({name:"ZV.UniversalSegmentDesk",async beforeRegisterNodeDef(type,data){
    if(data.name!=="ZVUniversalSegmentDesk")return;
    for(const hook of ["onNodeCreated","onConfigure"]){const prior=type.prototype[hook];type.prototype[hook]=function(){prior?.apply(this,arguments);setTimeout(()=>{if(hook==="onConfigure"&&this.zvUniversal)this.zvUniversal.restore();else attachUniversalDesk(this);},0);};}
}});
