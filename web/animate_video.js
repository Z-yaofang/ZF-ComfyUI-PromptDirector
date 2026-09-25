import {app} from "/scripts/app.js";
import {pinDOMWidgetFullWidth} from "./dom_widget_layout.mjs";
import {readDesk} from "./long_video_core.mjs";
import {clone,parseSettings,readWorkflowFps} from "./animate_video_core.mjs";

const api=globalThis.comfyAPI?.api?.api??{apiURL:path=>path,fetchApi:(path,options)=>fetch(path,options)};
const sheet=document.createElement("link");sheet.rel="stylesheet";sheet.href=new URL("./animate_video.css",import.meta.url).href;document.head.append(sheet);
const el=(tag,cls="",text)=>{const result=document.createElement(tag);result.className=cls;if(text!==undefined)result.textContent=text;return result;};

export function attachAnimateDesk(node) {
    if(node.zvAnimate)return;
    const widget=node.widgets?.find(w=>w.name==="segment_data");if(!widget)return;
    widget.type="converted-widget";widget.computeSize=()=>[0,-4];if(widget.inputEl)widget.inputEl.style.display="none";
    const root=el("div","zv-animate");
    for(const event of ["pointerdown","wheel","keydown"])root.addEventListener(event,e=>e.stopPropagation());
    const dom=node.addDOMWidget("zv_animate_ui","zv-animate",root,{serialize:false,hideOnZoom:false,getMinHeight:()=>440,getMaxHeight:()=>760});dom.serialize=false;pinDOMWidgetFullWidth(dom);
    node.setSize?.([Math.max(1000,node.size?.[0]??0),Math.max(540,node.size?.[1]??0)]);
    let settings=parseSettings(widget.value),plan=null,disposed=false,token=0,sourceText="";
    const controls=el("div","bar"),input=el("select"),label=el("label","","段间衔接"),summary=el("span","summary"),scroll=el("div","rail-scroll"),rail=el("div","rail"),status=el("div","status");
    const maskToggle=el("input"),maskLabel=el("label","mask-toggle"),modeText=el("span");
    maskToggle.type="checkbox";maskToggle.checked=settings.mask_enabled;maskToggle.setAttribute("aria-label","遮罩管道");maskLabel.append(maskToggle,el("span","","遮罩管道"),modeText);
    for(const [value,text] of [["hard_cut","硬切"],["continuation_21","原生 21 帧承接"]]){const option=el("option","",text);option.value=value;input.append(option);}
    input.value=settings.seam_mode;input.setAttribute("aria-label","段间衔接");label.append(input);controls.append(label,maskLabel,summary);scroll.append(rail);
    root.append(el("h3","","ZV Animate 素材配对台"),el("p","","自动读取素材台：每个视频片段一段，视频原声随段保留。关闭遮罩管道跑整条动作迁移；开启后为各段填写遮罩目标词和参考帧。"),controls,scroll,el("p","hint","修改分段、图片顺序和裁剪请回素材台。硬切不传历史；原生承接传上一段成品尾部 21 帧，短段由 Plus 原生处理。源切点不变，补帧和裁回沿用原工作流；当前 Plus 承接段可能少 1 帧，最终报告实际差异，分段台不额外补帧。"),status);
    function note(message,error=false){status.textContent=message;status.classList.toggle("error",error);}
    function save(){widget.value=JSON.stringify(settings);node.graph?.setDirtyCanvas?.(true,true);}
    function invalidate(message){token++;plan=null;node.zvAnimate.plan=null;note(message,true);render();}
    function render(){
        const focused=rail.contains(document.activeElement)?document.activeElement:null,focusName=focused?.getAttribute("aria-label"),selection=focused?.type==='text'?[focused.selectionStart,focused.selectionEnd]:null;
        rail.replaceChildren();summary.textContent="";
        maskToggle.checked=settings.mask_enabled;modeText.textContent=settings.mask_enabled?"开启 · 整条遮罩替换":"关闭 · 整条动作迁移";
        if(!plan){rail.append(el("p","empty","等待素材台连接和素材…"));return;}
        const clock=readWorkflowFps(node),fpsLabel=plan.fps_origin==='workflow'?'沿用原流':clock.linked?'运行时帧率待解析，预览估算':plan.fps_origin==='source'?'跟随首段源':'源帧率未知，采用工程';
        summary.textContent=`${plan.segments.length} 段 · ${fpsLabel} ${Number(plan.fps.toFixed(6))} fps · ${plan.target_frame_count} 帧`;
        const assets=new Map(plan.media_project.assets.map(row=>[row.asset_id,row]));
        for(const row of plan.segments){
            const pair=assets.get(row.picture_asset_id),video=assets.get(row.video_asset_id),column=el("div","segment-column");column.dataset.segmentId=row.segment_id;
            column.style.width=`${Math.max(220,Math.min(420,row.frame_count/plan.fps*24))}px`;
            const heading=el("div","segment-heading",`第 ${row.ordinal} 段 · ${row.frame_count} 帧`),picture=el("div",`pair${pair?"":" missing"}`),clip=el("div","clip");
            if(pair){const image=el("img");image.alt=pair.name;image.src=api.apiURL(`/zf-media-evidence/preview?source=${encodeURIComponent(pair.source_handle)}&variant=thumbnail`);picture.append(image);}
            picture.append(el("strong","",pair?.name??"缺少配对图片"));
            clip.append(el("strong","",video?.name??row.video_asset_id),el("span","",`源 ${row.source_start_seconds.toFixed(3)}–${row.source_end_seconds.toFixed(3)} 秒`),el("span","",row.source_audio_enabled?"视频 + 原声":"视频 · 无原声"));
            const transition=el("div",`transition${row.guide_frame_count?" active":""}`,row.ordinal===1?"起点":row.guide_frame_count?"← 原生承接 · 上段成品尾部最多 21 帧" :"硬切");
            column.append(heading,picture,clip,transition);
            if(settings.mask_enabled){
                const stored=settings.mask_tasks[row.clip_id],task=stored?.asset_id===row.video_asset_id?stored:{asset_id:row.video_asset_id,prompt:"",source_frame:null};
                const fields=el("div","mask-fields"),prompt=el("input"),frame=el("input"),promptLabel=el("label","","遮罩目标词"),frameLabel=el("label","","原视频源帧（同素材台，从 1 起）");
                prompt.type="text";prompt.value=task.prompt??"";prompt.placeholder="如：上衣、裤子";prompt.setAttribute("aria-label",`第 ${row.ordinal} 段遮罩目标词`);
                frame.type="number";frame.step="1";frame.min=row.mask_frame_min+1;frame.max=row.mask_frame_max+1;frame.value=task.source_frame==null?"":task.source_frame+1;frame.placeholder=`${row.mask_frame_min+1}–${row.mask_frame_max+1}`;frame.setAttribute("aria-label",`第 ${row.ordinal} 段参考帧`);
                const changed=()=>{settings.mask_tasks[row.clip_id]={asset_id:row.video_asset_id,prompt:prompt.value,source_frame:frame.value===""?null:Number(frame.value)-1};save();token++;node.zvAnimate.plan=null;note("遮罩填写已保存，按 Enter 或移出输入框后检查。");};
                prompt.oninput=frame.oninput=changed;
                prompt.onchange=frame.onchange=()=>refresh();
                prompt.onkeydown=frame.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();event.currentTarget.blur();}};
                promptLabel.append(prompt);frameLabel.append(frame);fields.append(promptLabel,frameLabel,el("span","hint",`有效源帧 ${row.mask_frame_min+1}–${row.mask_frame_max+1} · ${Number(row.mask_reference_fps.toFixed(6))} fps；读取素材台预览下方“源帧”，勿填黄线的工程帧号。`));column.append(fields);
            }
            rail.append(column);
        }
        if(focusName){const next=[...rail.querySelectorAll('input')].find(item=>item.getAttribute('aria-label')===focusName);next?.focus({preventScroll:true});if(selection)next?.setSelectionRange(...selection);}
        note([`${plan.segments.length} 段 · 输入片段合计 ${plan.target_frame_count} 帧 / ${(plan.target_frame_count/plan.fps).toFixed(3)} 秒（当前素材时长，不是上限）`,"Animate 无 15 秒单段或总长限制；逐段执行，仍受素材文件和设备资源约束。",...plan.validation.errors.map(row=>row.message),...plan.validation.warnings.map(row=>row.message)].join("\n"),!plan.validation.ready);
    }
    async function refresh(){
        const run=++token;node.zvAnimate.plan=null;let source;
        try{source=readDesk(node).project;}catch(error){invalidate(error.message);return;}
        const captured=JSON.stringify(settings),clock=readWorkflowFps(node),sourceCaptured=JSON.stringify({source,clock});sourceText=sourceCaptured;
        note("正在同步素材台…");
        try{
            const response=await api.fetchApi("/zf-prompt-director/animate-video/plan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({media_project:source,settings,fps:clock.fps})}),result=await response.json();
            if(disposed||run!==token||captured!==JSON.stringify(settings))return;
            let current;try{current=JSON.stringify({source:readDesk(node).project,clock:readWorkflowFps(node)});}catch{invalidate("素材台连接已断开，请重新连接。");return;}
            if(sourceCaptured!==current){refresh();return;}
            if(!response.ok)throw new Error(result.error||result.errors?.map(row=>row.message).join("；")||`检查失败 ${response.status}`);
            plan=result.plan;settings=clone(plan.settings);save();node.zvAnimate.plan=plan;render();
        }catch(error){if(!disposed&&run===token)invalidate(error.message);}
    }
    input.onchange=()=>{settings.seam_mode=input.value;save();refresh();};
    maskToggle.onchange=()=>{settings.mask_enabled=maskToggle.checked;save();render();refresh();};
    node.zvAnimate={root,plan:null,refresh,getSettings:()=>clone(settings),getPlan:()=>node.zvAnimate.plan,restore(){token++;settings=parseSettings(widget.value);input.value=settings.seam_mode;plan=null;save();render();refresh();}};
    const timer=setInterval(()=>{if(disposed)return;try{if(JSON.stringify({source:readDesk(node).project,clock:readWorkflowFps(node)})!==sourceText)refresh();}catch{if(plan)invalidate("素材台连接已断开，请重新连接。");}},750);
    const priorRemoved=node.onRemoved;node.onRemoved=function(){disposed=true;token++;clearInterval(timer);root.remove();priorRemoved?.apply(this,arguments);};
    const priorConnections=node.onConnectionsChange;node.onConnectionsChange=function(){priorConnections?.apply(this,arguments);setTimeout(()=>{if(!disposed)refresh();},0);};
    save();render();refresh();
}

app.registerExtension({name:"ZV.AnimateVideo",async beforeRegisterNodeDef(type,data){if(data.name!=="ZVAnimateSegmentDesk")return;for(const hook of ["onNodeCreated","onConfigure"]){const prior=type.prototype[hook];type.prototype[hook]=function(){prior?.apply(this,arguments);setTimeout(()=>{if(hook==="onConfigure"&&this.zvAnimate)this.zvAnimate.restore();else attachAnimateDesk(this);},0);};}}});

app.registerExtension({name:"ZV.AnimateRunPreviews",async beforeRegisterNodeDef(type,data){
    if(!["ZVAnimateMaskGate","ZVAnimateExecutionEnd"].includes(data.name))return;
    const isMask=data.name==="ZVAnimateMaskGate";
    const created=type.prototype.onNodeCreated;
    type.prototype.onNodeCreated=function(){
        created?.apply(this,arguments);
        const element=el(isMask?"video":"textarea");
        element.style.width="100%";element.style.boxSizing="border-box";
        if(isMask){element.controls=true;element.muted=true;element.loop=true;element.playsInline=true;element.style.minHeight="200px";this.zvMaskVideo=element;}
        else{element.readOnly=true;element.style.height="130px";element.style.resize="vertical";element.style.background="#101c25";element.style.color="#d8e6ee";this.zvFinalReport=element;}
        const widget=this.addDOMWidget(isMask?"mask_background_video":"final_report","preview",element,{serialize:false,hideOnZoom:false,getMinHeight:()=>isMask?240:140,getMaxHeight:()=>isMask?460:250});
        widget.serialize=false;
        this.setSize?.([Math.max(this.size?.[0]??0,isMask?500:470),Math.max(this.size?.[1]??0,isMask?390:300)]);
    };
    const executed=type.prototype.onExecuted;
    type.prototype.onExecuted=function(message){
        executed?.apply(this,arguments);
        if(isMask){
            const preview=message?.gifs?.[0];
            if(!this.zvMaskVideo)return;
            if(!preview){this.zvMaskVideo.removeAttribute("src");this.zvMaskVideo.load();return;}
            const params=new URLSearchParams({filename:preview.filename,subfolder:preview.subfolder??"",type:preview.type??"temp"});
            this.zvMaskVideo.src=api.apiURL(`/view?${params}`);
            this.zvMaskVideo.load();
        }else if(this.zvFinalReport){this.zvFinalReport.value=message?.text?.[0]??"";}
    };
}});
