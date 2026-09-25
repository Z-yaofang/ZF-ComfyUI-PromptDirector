import {app} from "/scripts/app.js";
import {pinDOMWidgetFullWidth} from "./dom_widget_layout.mjs";
import {split, remove} from "./media_evidence_core.mjs";
import {clone,uid,frame,defaultSettings,emptyInterview,parse,manual,changeSegment,splitSegment,removeSegment,addSegment,presetSettings,traceUpstream,readDesk} from "./long_video_core.mjs";

const api=globalThis.comfyAPI?.api?.api??{apiURL:path=>path,fetchApi:(path,options)=>fetch(path,options)};
const sheet=document.createElement("link"); sheet.rel="stylesheet"; sheet.href=new URL("./long_video.css",import.meta.url).href; document.head.append(sheet);
const el=(tag,cls="",text)=>{const e=document.createElement(tag);e.className=cls;if(text!==undefined)e.textContent=text;return e;};
const button=(text,run,primary=false)=>{const e=el("button",primary?"primary":"",text);e.type="button";e.onclick=run;return e;};
const select=(choices,value,change)=>{const e=el("select");for(const [v,t] of choices){const o=el("option","",t);o.value=v;e.append(o);}e.value=value;e.onchange=()=>change(e.value);return e;};
const field=(title,control)=>{const e=el("label","",title);e.append(control);return e;};
const number=(value,change,min=0)=>{const e=el("input");e.type="number";e.step="1";e.min=min;e.value=value;e.onfocus=()=>e.select();e.onchange=()=>{const n=Number(e.value);if(Number.isInteger(n)&&n>=min)change(n);};return e;};
async function request(path,data){const r=await api.fetchApi(`/zf-prompt-director/long-video/${path}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw new Error(result.error||result.errors?.map(x=>x.message).join("；")||`请求失败 ${r.status}`);return result;}
function mount(node,key,title,minHeight=600){
    if(node.zvLong) return null;
    const widget=node.widgets?.find(w=>w.name===key);if(!widget)return null;
    widget.type="converted-widget";widget.computeSize=()=>[0,-4];if(widget.inputEl)widget.inputEl.style.display="none";
    const root=el("div","zv-long");root.append(el("h3","",title));
    for(const event of ["pointerdown","wheel","keydown"])root.addEventListener(event,e=>e.stopPropagation());
    const dom=node.addDOMWidget("zv_long_ui","zv-long",root,{serialize:false,hideOnZoom:false,getMinHeight:()=>minHeight,getMaxHeight:()=>1200});dom.serialize=false;pinDOMWidgetFullWidth(dom);
    const save=value=>{widget.value=JSON.stringify(value);node.graph?.setDirtyCanvas?.(true,true);};
    node.setSize?.([Math.max(1100,node.size?.[0]||0),Math.max(minHeight+110,node.size?.[1]||0)]);
    node.zvLong={root};return {root,widget,save};
}

function attachDesk(node){
    const mounted=mount(node,"segment_data","ZV H3 长视频分段台",650);if(!mounted)return;
    const {root,widget,save}=mounted;
    let settings={...defaultSettings(),...parse(widget.value,defaultSettings)},plan=null,selected=null,playhead=0,scale=2,disposed=false,token=0,timer=null,upstreamText="",snap=true,activePlayheadDrag=null,timelineRenderPending=false;
    const undo=[],redo=[];
    const controls=el("div","bar"),presets=el("div","bar"),toolbar=el("div","bar"),scroll=el("div","time-scroll"),time=el("div","time"),inspector=el("div","bar"),status=el("div","status");scroll.append(time);
    root.append(el("p","","获取素材台的三条轨道后，在此排列分段。此处的分割、删除只影响分段台副本。"),controls,presets,toolbar,scroll,inspector,status);
    function note(message,error=false){status.textContent=message;status.classList.toggle("error",error);}
    function remember(){undo.push(clone(settings));if(undo.length>80)undo.shift();redo.length=0;}
    function commit(next){remember();settings=next;persist();refresh();}
    function persist(){save(settings);node.zvLong.plan=null;node.zvLong.settings=clone(settings);root.dispatchEvent(new CustomEvent("zv-segment-change"));}
    const playheadText=()=>`播放头 ${(playhead/settings.fps).toFixed(3)} 秒 · 第 ${playhead} 帧`;
    function rulerFrame(ruler,clientX){const rect=ruler.getBoundingClientRect(),ratio=ruler.offsetWidth?rect.width/ruler.offsetWidth:1;return (clientX-rect.left)/(scale*(ratio||1));}
    function paintPlayhead(line,maximum){
        line.style.left=`${84+playhead*scale}px`;line.setAttribute("aria-valuenow",String(playhead));line.setAttribute("aria-valuetext",playheadText());line.setAttribute("aria-valuemax",String(maximum));
        const readout=root.querySelector(".playhead-readout");if(readout)readout.textContent=playheadText();
    }
    function beginPlayheadDrag(event,line,ruler,maximum){
        if(event.button!==0||activePlayheadDrag)return;event.preventDefault();event.stopPropagation();
        const pointerId=event.pointerId,before=playhead,grabOffset=rulerFrame(ruler,event.clientX)-playhead,controller=new AbortController();let finished=false;
        line.focus({preventScroll:true});line.setPointerCapture(pointerId);
        const move=e=>{if(e.pointerId!==pointerId)return;playhead=Math.max(0,Math.min(maximum,Math.round(rulerFrame(ruler,e.clientX)-grabOffset)));paintPlayhead(line,maximum);};
        const finish=cancel=>{
            if(finished)return;finished=true;controller.abort();
            if(cancel){playhead=before;paintPlayhead(line,maximum);}
            if(line.hasPointerCapture(pointerId))line.releasePointerCapture(pointerId);
            activePlayheadDrag=null;renderControls();
            if(timelineRenderPending&&!disposed){timelineRenderPending=false;renderTimeline();}
        };
        line.addEventListener("pointermove",move,{signal:controller.signal});
        line.addEventListener("pointerup",e=>{if(e.pointerId===pointerId)finish(false);},{signal:controller.signal});
        line.addEventListener("pointercancel",e=>{if(e.pointerId===pointerId)finish(true);},{signal:controller.signal});
        line.addEventListener("lostpointercapture",()=>finish(false),{signal:controller.signal});
        activePlayheadDrag=cancel=>finish(cancel);
    }
    async function refresh(reload=false){
        const run=++token;let input;
        try{input=readDesk(node);}catch(e){plan=null;note(e.message,true);renderTimeline();return;}
        const captured=JSON.stringify(settings),sourceText=JSON.stringify(input.project);
        // Remember attempted input even when the server rejects it; explicit refresh can still retry.
        upstreamText=sourceText;
        note(reload?"正在获取素材台三条轨道…":"正在检查分段覆盖范围…");
        try{
            const result=await request("plan",{media_project:input.project,settings:{...settings,refresh_sources:reload}});
            if(disposed||run!==token||captured!==JSON.stringify(settings)||sourceText!==JSON.stringify(readDesk(node).project))return;
            plan=result.plan;settings={...settings,source_snapshot:clone(plan.media_project),source_fingerprint:plan.source_fingerprint,refresh_sources:false};
            if(!settings.segments.length&&plan.segments.length)settings.segments=plan.segments.map(({segment_id,start_frame,end_frame})=>({segment_id,start_frame,end_frame}));
            save(settings);node.zvLong.plan=plan;node.zvLong.settings=clone(settings);
            note([`${plan.segments.length} 段 · 目标 ${plan.target_frame_count} 帧 / ${(plan.target_frame_count/plan.fps).toFixed(3)} 秒`,...plan.validation.errors.map(x=>x.message),...plan.validation.warnings.map(x=>x.message)].join("\n"),!plan.validation.ready);
            renderControls();renderTimeline();root.dispatchEvent(new CustomEvent("zv-segment-change"));
        }catch(e){if(!disposed&&run===token)note(e.message,true);}
    }
    function renderControls(){
        const segmentCount=number(settings.segment_count,v=>commit({...settings,segment_count:v}),1);
        segmentCount.disabled=settings.mode!=="generation_count";
        segmentCount.title=segmentCount.disabled?"按素材长度分段时由素材范围、每段帧数和重叠自动计算":"按段数生成的目标段数";
        controls.replaceChildren(button("获取素材台三轨",()=>{remember();refresh(true);},true),
            select([["source_auto","按素材长度分段"],["generation_count","按段数生成"],["source_manual","手动排列素材"],["generation_manual","手动排列生成"]],settings.mode,v=>commit(v.endsWith("_manual")&&plan?manual(settings,plan,v):{...settings,mode:v})),
            field("帧率",number(settings.fps,v=>commit({...settings,fps:v}),1)),
            field("每段帧数",number(settings.segment_frames,v=>commit({...settings,segment_frames:v}),1)),
            field("重叠帧数",number(settings.overlap_frames,v=>commit({...settings,overlap_frames:v}))),
            select([["h3_guide","H3 衔接帧对齐"],["exact","精确重叠 / 硬切"]],settings.overlap_alignment,v=>commit({...settings,overlap_alignment:v})),
            field("段数（仅按段数生成）",segmentCount),
            button("一键排列",()=>commit({...settings,mode:settings.mode.startsWith("generation")?"generation_count":"source_auto",segments:[]}),true),
            el("span","hint","H3 常用单段 8–15 秒；任务保留帧数可直接填，模型长度自动向上补到 5+17k，输出再裁回；重叠 Guide 独立按 1 或 5+17k 对齐。"));
        const snapInput=el("input");snapInput.type="checkbox";snapInput.checked=snap;snapInput.onchange=()=>snap=snapInput.checked;
        const undoButton=button("撤销",()=>{if(!undo.length)return;redo.push(clone(settings));settings=undo.pop();persist();refresh();});undoButton.disabled=!undo.length;
        const redoButton=button("重做",()=>{if(!redo.length)return;undo.push(clone(settings));settings=redo.pop();persist();refresh();});redoButton.disabled=!redo.length;
        toolbar.replaceChildren(field("吸附",snapInput),redoButton,undoButton,button("黄线处分割",()=>{
            if(!plan||!selected)return;
            if(selected.kind==="segment")commit(splitSegment(settings,plan,selected.id,playhead));
            else if(selected.kind!=="picture")commit({...settings,source_snapshot:split(settings.source_snapshot,selected.id,playhead/settings.fps)});
        }),button("＋ 增加分段",()=>plan&&commit(addSegment(settings,plan))),el("span","warning playhead-readout",playheadText()),el("span","grow"),field("缩放",number(scale,v=>{scale=v;renderTimeline();},1)));
    }
    function renderPresets(){
        const builtins=[{name:"H3 长参考动作迁移",mode:"source_auto",fps:24,segment_frames:360,overlap_frames:48,overlap_alignment:"h3_guide"},{name:"H3 连续生成",mode:"generation_count",fps:24,segment_frames:124,overlap_frames:39,overlap_alignment:"h3_guide",segment_count:3},{name:"通用硬切",mode:"source_auto",fps:24,segment_frames:240,overlap_frames:0,overlap_alignment:"exact"}];
        const saved=node.properties?.zv_segment_presets??[];
        const name=el("input");name.placeholder="预设名称";
        const picker=select([["","选择预设参数"],...[...builtins,...saved].map((p,i)=>[String(i),p.name])],"",v=>{if(v!=="")commit(presetSettings(settings,[...builtins,...saved][Number(v)]));});
        presets.replaceChildren(picker,name,button("保存参数预设",()=>{
            if(!name.value.trim())return;node.properties??={};
            const p={name:name.value.trim()};for(const key of ["mode","fps","segment_frames","overlap_frames","overlap_alignment","segment_count"])p[key]=settings[key];
            node.properties.zv_segment_presets=[...saved.filter(x=>x.name!==p.name),p];node.graph?.setDirtyCanvas?.(true,true);renderPresets();
        }),el("p","","选择预设填入参数，再点“一键排列”。自定义预设随工作流保存。"));
    }
    function removeSelected(kind){
        if(!selected||selected.kind!==kind||!plan)return;
        if(kind==="segment"){
            const removedId=selected.id,index=plan.segments.findIndex(row=>row.segment_id===removedId),remaining=plan.segments.filter(row=>row.segment_id!==removedId);
            const next=remaining[Math.min(Math.max(index,0),Math.max(0,remaining.length-1))];selected=next?{kind:"segment",id:next.segment_id}:null;
            commit(removeSegment(settings,plan,removedId));return;
        }
        else if(kind==="audio"){
            const p=clone(settings.source_snapshot),a=p.audio_track.find(x=>x.clip_id===selected.id);
            if(a?.linked_video_clip_id){const v=p.video_track.find(x=>x.clip_id===a.linked_video_clip_id);if(v){v.source_audio_enabled=false;v.audio_link_id=null;}}
            p.audio_track=p.audio_track.filter(x=>x.clip_id!==selected.id);commit({...settings,source_snapshot:p});
        }else commit({...settings,source_snapshot:remove(settings.source_snapshot,selected.id)});
        selected=null;
    }
    function renderTimeline(){
        if(activePlayheadDrag){timelineRenderPending=true;return;}
        timelineRenderPending=false;
        time.replaceChildren();inspector.replaceChildren();
        if(!plan)return;
        const max=Math.max(plan.range_start_frame+plan.target_frame_count,...plan.segments.map(x=>x.end_frame),120);
        playhead=Math.min(playhead,max);
        time.style.width=`${84+Math.max(780,max*scale+60)}px`;
        const ruler=el("div","ruler");time.append(ruler);
        for(let f=0;f<=max;f+=Math.max(settings.fps,Math.ceil(max/20/settings.fps)*settings.fps)){const tick=el("span","tick",`${(f/settings.fps).toFixed(0)}s`);tick.style.left=`${f*scale}px`;ruler.append(tick);}
        ruler.onpointerdown=e=>{if(e.button!==0)return;playhead=Math.max(0,Math.min(max,Math.round(rulerFrame(ruler,e.clientX))));renderControls();renderTimeline();};
        for(const [kind,title] of [["segment","分段轴"],["picture","图片"],["video","视频"],["audio","音频"]]){
            const lane=el("div","lane"),titleBox=el("div","lane-title",title),del=button("删除",()=>removeSelected(kind));del.disabled=selected?.kind!==kind;titleBox.append(del);lane.append(titleBox);time.append(lane);
            const rows=kind==="segment"?plan.segments:plan.media_project[`${kind}_track`];
            rows.forEach((row,index)=>{
                const id=row.segment_id??row.item_id??row.clip_id,asset=plan.media_project.assets.find(x=>x.asset_id===row.asset_id);
                const start=kind==="segment"?row.start_frame:kind==="picture"?index*70/scale:frame(row.timeline_in_seconds,settings.fps);
                const length=kind==="segment"?row.end_frame-row.start_frame:kind==="picture"?68/scale:frame(row.source_out_seconds-row.source_in_seconds,settings.fps);
                const card=el("div",`card ${kind}${selected?.id===id?" selected":""}`);
                card.style.left=`${84+start*scale}px`;card.style.width=`${Math.max(24,length*scale)}px`;
                card.append(el("strong","",kind==="segment"?`第 ${row.order} 段`:asset?.name??id),el("br"),document.createTextNode(kind==="segment"?`${row.frame_count} 帧 · ${row.overlap_frames?`重叠 ${row.overlap_frames}`:row.seam==="first"?"起点":"硬切"}`:kind==="picture"?"固定卡片":`${row.source_in_seconds.toFixed(3)}–${row.source_out_seconds.toFixed(3)}s`));
                if(kind==="segment")for(const side of ["left","right"]){const edge=el("span",`edge ${side}`);edge.dataset.edge=side;card.append(edge);}
                card.onpointerdown=e=>{
                    selected={kind,id};
                    if(kind!=="segment"){renderTimeline();return;}
                    e.preventDefault();const edge=e.target.dataset?.edge,origin=e.clientX,original=clone(row);let nextStart=row.start_frame,nextEnd=row.end_frame;
                    card.setPointerCapture(e.pointerId);
                    card.onpointermove=event=>{
                        let delta=Math.round((event.clientX-origin)/scale);nextStart=original.start_frame+(edge==="right"?0:delta);nextEnd=original.end_frame+(edge==="left"?0:delta);
                        if(snap){const points=[playhead,...plan.segments.filter(x=>x.segment_id!==id).flatMap(x=>[x.start_frame,x.end_frame])];const match=points.find(x=>Math.abs(x-(edge==="right"?nextEnd:nextStart))*scale<7);if(match!==undefined){const shift=match-(edge==="right"?nextEnd:nextStart);if(edge!=="right")nextStart+=shift;if(edge!=="left")nextEnd+=shift;}}
                        if(nextStart<0||nextEnd<=nextStart)return;card.style.left=`${84+nextStart*scale}px`;card.style.width=`${(nextEnd-nextStart)*scale}px`;
                    };
                    card.onpointerup=()=>{card.onpointermove=null;card.onpointerup=null;if(nextStart!==row.start_frame||nextEnd!==row.end_frame)commit(changeSegment(settings,plan,id,nextStart,nextEnd));else renderTimeline();};
                    card.onpointercancel=()=>{card.onpointermove=null;renderTimeline();};
                };lane.append(card);
            });
        }
        const line=el("div","playhead");line.tabIndex=0;line.setAttribute("role","slider");line.setAttribute("aria-label","黄色播放头");line.setAttribute("aria-valuemin","0");paintPlayhead(line,max);
        line.onpointerdown=e=>beginPlayheadDrag(e,line,ruler,max);
        line.onkeydown=e=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;e.preventDefault();e.stopPropagation();playhead=e.key==="Home"?0:e.key==="End"?max:Math.max(0,Math.min(max,playhead+(e.key==="ArrowRight"?1:-1)));paintPlayhead(line,max);renderControls();};
        time.append(line);
        if(selected?.kind==="segment"){
            const row=plan.segments.find(x=>x.segment_id===selected.id);if(row){const model=row.model_padding.model_length==null?"布局未预填模型长度（采访执行时按 H3 调用网格补齐）":`布局模型长度 ${row.model_padding.model_length} 帧`;inspector.append(el("span","",`第 ${row.order} 段`),field("起始帧",number(row.start_frame,v=>commit(changeSegment(settings,plan,row.segment_id,v,row.end_frame)))),field("结束帧（不含）",number(row.end_frame,v=>commit(changeSegment(settings,plan,row.segment_id,row.start_frame,v)),1)),el("span","",`${model} · 任务保留 ${row.frame_count} 帧 · 布局 ${row.model_padding.adapter}`));}
        }
    }
    node.zvLong.refresh=refresh;node.zvLong.getSettings=()=>clone(settings);node.zvLong.getPlan=()=>plan;
    node.zvLong.restore=()=>{settings={...defaultSettings(),...parse(widget.value,defaultSettings)};renderControls();renderPresets();refresh();};
    const prior=node.onRemoved;node.onRemoved=function(){disposed=true;token++;activePlayheadDrag?.(true);activePlayheadDrag=null;timelineRenderPending=false;clearInterval(timer);root.remove();prior?.apply(this,arguments);};
    const priorConnections=node.onConnectionsChange;node.onConnectionsChange=function(){priorConnections?.apply(this,arguments);setTimeout(()=>refresh(),0);};
    timer=setInterval(()=>{try{if(upstreamText!==JSON.stringify(readDesk(node).project))refresh();}catch{}},1800);
    renderControls();renderPresets();refresh();
}

const fields=[["intent","要生成什么 / 本段发生什么"],["style","画面风格"],["must_keep","必须保留"],["must_change","必须改变"],["ending","结尾状态"],["forbidden","不能出现"],["performance","动作与表演"],["camera","镜头与剪辑"],["dialogue","对白 / 歌词原文"],["visible_text","可见文字"],["soundscape","环境与动作声"],["music","配乐"]];
const banks={picture:[["ref_images","参考图片"],["first_frame","首帧"],["last_frame","尾帧"]],video:[["ref_videos","参考视频"]],audio:[["ref_audios","参考音频"],["drive_audio","复用 / 驱动音频"]]};
const roles={picture:[["subject_identity","主体身份/外观"],["composition_reference","构图"],["style_reference","风格"]],video:[["motion_reference","动作参考"],["camera_reference","运镜参考"],["video_edit","原视频编辑"],["video_continue","续写"]],audio:[["music_reference","音乐参考"],["voice_reference","音色参考"],["sound_reference","声音参考"],["audio_reuse","直接复用"],["speech_lipsync","台词口型"]]};
function attachInterview(node){
    const mounted=mount(node,"interview_data","ZV H3 分段采访表",720);if(!mounted)return;
    const {root,widget,save}=mounted;let state={...emptyInterview(),...parse(widget.value,emptyInterview)},active="global",result=null,disposed=false,token=0,lastSource="",delay=null;
    const toolbar=el("div","bar"),editor=el("div","editor"),list=el("div","segments"),form=el("div","form"),assets=el("div","assets"),status=el("div","status");editor.append(list,form,assets);
    toolbar.append(button("检测并对齐全部分段",()=>refresh(true),true),el("p","","先选择分段，勾选本段素材并填写要求。修改后运行前再对齐一次。"));root.append(toolbar,editor,status);
    function scoped(scope){return scope==="global"?state.global:(state.segments[scope]??={});}
    function current(){return scoped(active);}
    function persist(){state.alignment=null;save(state);status.textContent="内容已保存，运行前请检测并对齐全部分段";status.classList.add("error");node.zvLong.result=null;clearTimeout(delay);delay=setTimeout(()=>refresh(false),500);}
    function source(){const desk=traceUpstream(node,"segment_plan",candidate=>Boolean(candidate.zvLong?.getSettings));if(!desk)throw new Error("请连接长视频分段台的 segment_plan");return {desk,...readDesk(desk)};}
    async function refresh(align=false){
        const run=++token,captured=JSON.stringify(state);let input,settings;
        try{input=source();settings=input.desk.zvLong.getSettings();const capturedSource=JSON.stringify([input.project,settings]);
            // A failed attempt must not be replayed on every poll with unchanged source data.
            lastSource=capturedSource;
            const response=await request("interview",{media_project:input.project,settings,state,align});
            if(disposed||run!==token||captured!==JSON.stringify(state)||capturedSource!==JSON.stringify([source().project,source().desk.zvLong.getSettings()]))return;
            const previousIds=(result?.segments??[]).map(row=>row.segment_id),previousIndex=previousIds.indexOf(active);
            result=response;state=response.state;save(state);node.zvLong.result=result;
            const nextIds=(result?.segments??[]).map(row=>row.segment_id);let scopeChanged=false;
            if(active!=="global"&&!nextIds.includes(active)){active=nextIds[Math.min(Math.max(previousIndex,0),Math.max(0,nextIds.length-1))]??"global";scopeChanged=true;}
            status.textContent=response.report;status.classList.toggle("error",!response.ready);
            if(scopeChanged)render();else{renderList();if(align||!assets.contains(document.activeElement))renderAssets();}
        }catch(e){if(!disposed&&run===token){status.textContent=e.message;status.classList.add("error");}}
    }
    function renderList(){
        if(active!=="global"&&!(result?.segments??[]).some(row=>row.segment_id===active))active="global";
        list.replaceChildren(button("全局要求",()=>{active="global";render();}));list.firstChild.classList.toggle("active",active==="global");
        for(const [index,row] of (result?.segments??[]).entries()){const b=button(`第 ${index+1} 段\n${row.frame_count} 帧`,()=>{active=row.segment_id;render();});b.classList.toggle("active",active===row.segment_id);list.append(b);}
    }
    function renderForm(){
        form.replaceChildren(el("p","",active==="global"?"各段继承这些要求。每段编号独立；请在本段素材用途里描述对应关系。":"本段要求追加到全局要求；素材选择可覆盖全局。"));
        const scope=active;for(const [key,title] of fields){const text=el("textarea");text.value=scoped(scope)[key]??"";text.placeholder=scope==="global"?"可留空":"留空则继承全局要求";text.oninput=()=>{if(active!==scope||!text.isConnected)return;scoped(scope)[key]=text.value;persist();};form.append(field(title,text));}
    }
    function renderAssets(){
        assets.replaceChildren();const scope=active,segment=scope==="global"?result?.segments?.[0]:result?.segments?.find(x=>x.segment_id===scope);
        if(scope==="global"){assets.append(el("p","","全局页编辑共同要求。各段素材请在左侧选择对应分段后设置。"));return;}
        const project=segment?.reference_plan?.media_project;
        for(const row of segment?.inventory??[]){
            if(row.linked_video_clip_id)continue;
            const id=row.item_id,cfg=scoped(scope),inherited=state.global.bindings?.[id];
            const binding=cfg.bindings?.[id]??inherited??{item_id:id,participates:row.enabled,banks:[banks[row.kind][0][0]]};
            const box=el("div",`asset${binding.participates?"":" excluded"}`),asset=project?.assets.find(x=>x.asset_id===row.asset_id);
            if(asset&&row.kind!=="audio"){const img=el("img","preview");img.src=api.apiURL(`/zf-media-evidence/preview?source=${encodeURIComponent(asset.source_handle)}&variant=thumbnail`);img.alt=row.name;box.append(img);}
            box.append(el("strong","",row.name),el("small","",segment.call_references.filter(x=>x.item_id===id).map(x=>x.call_label).join(" · ")||"本段已排除"));
            const setBinding=value=>{if(active!==scope||!box.isConnected)return;(scoped(scope).bindings??={})[id]=value;persist();renderAssets();};
            const participates=el("input");participates.type="checkbox";participates.checked=binding.participates;participates.onchange=()=>setBinding({...binding,participates:participates.checked});box.append(field("本段参与",participates));
            box.append(select(banks[row.kind],binding.banks[0],v=>setBinding({...binding,banks:[v]})));
            if(row.kind==="audio")box.append(el("small","","信号参考会传入完整音频，模型可能高度复现；精确复用需把原音轨接到最终合成器。"));
            const choices=el("div","roles");for(const [key,title] of roles[row.kind]){
                const input=el("input");input.type="checkbox";const selectedRoles=cfg.media_roles?.[id]??state.global.media_roles?.[id]??[];input.checked=selectedRoles.includes(key);
                input.onchange=()=>{if(active!==scope||!input.isConnected)return;const values=scoped(scope).media_roles?.[id]??state.global.media_roles?.[id]??[];(scoped(scope).media_roles??={})[id]=input.checked?[...new Set([...values,key])]:values.filter(x=>x!==key);persist();};choices.append(field(title,input));
            }box.append(choices);
            const purpose=el("textarea");purpose.value=cfg.media_purposes?.[id]??state.global.media_purposes?.[id]??"";purpose.placeholder="这份素材在本段用来做什么";purpose.oninput=()=>{if(active!==scope||!purpose.isConnected)return;(scoped(scope).media_purposes??={})[id]=purpose.value;persist();};box.append(purpose);assets.append(box);
        }
    }
    function render(){renderList();renderForm();renderAssets();}
    const watch=setInterval(()=>{try{const s=source(),key=JSON.stringify([s.project,s.desk.zvLong.getSettings()]);if(key!==lastSource)refresh();}catch{}},1800);
    const prior=node.onRemoved;node.onRemoved=function(){disposed=true;token++;clearInterval(watch);clearTimeout(delay);root.remove();prior?.apply(this,arguments);};
    node.zvLong.refresh=refresh;node.zvLong.getState=()=>clone(state);
    node.zvLong.restore=()=>{state={...emptyInterview(),...parse(widget.value,emptyInterview)};render();refresh();};render();refresh();
}

app.registerExtension({name:"ZV.LongVideo",async beforeRegisterNodeDef(type,data){
    const attach={ZVLongVideoSegmentDesk:attachDesk,ZVSegmentInterview:attachInterview}[data.name];if(!attach)return;
    for(const hook of ["onNodeCreated","onConfigure"]){const prior=type.prototype[hook];type.prototype[hook]=function(){prior?.apply(this,arguments);setTimeout(()=>{if(this.zvLong&&hook==="onConfigure")this.zvLong.restore?.();else attach(this);},0);};}
}});

export {attachDesk,attachInterview};
