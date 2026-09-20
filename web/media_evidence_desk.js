import { app } from "/scripts/app.js";
const api = globalThis.comfyAPI?.api?.api ?? {
    apiURL: path => path,
    fetchApi: (path, options) => fetch(path, options),
};
import * as edit from "./media_evidence_core.mjs";
import * as presets from "./media_evidence_presets.mjs";
import * as outlets from "./media_evidence_outlets.mjs?v=h3-v2-07";
import { pinDOMWidgetFullWidth } from "./dom_widget_layout.mjs";

const NAME = "ZVUniversalMediaEvidenceDesk";
const sourceEnabledTypes = new WeakSet();
export function restoreOriginalSourceOutput(node) {
    if(sourceEnabledTypes.has(Object.getPrototypeOf(node))&&node.outputs?.length===2&&
        node.outputs[0].type==="ZV_MEDIA_PROJECT"&&node.outputs[1].type==="STRING")
        node.addOutput("原素材来源","ZV_ORIGINAL_SOURCES");
}
const URL_ROOT = "/zf-media-evidence";
const style = document.createElement("link");
style.rel = "stylesheet"; style.href = new URL("./media_evidence_desk.css", import.meta.url).href;
document.head.append(style);
const previewURL = (asset, variant) => api.apiURL(`${URL_ROOT}/preview?source=${encodeURIComponent(asset.source_handle)}&variant=${variant}`);
const el = (tag, className, text) => {const node = document.createElement(tag); node.className = className || ""; if (text !== undefined) node.textContent = text; return node;};
const seconds = n => Number.isFinite(n) ? n.toFixed(3) : "未知";
const sourceFrameLabel = probe => probe.frame_count_exact === true && probe.vfr === false ? "源帧" : "估算帧";
async function request(path, options) {
    const response = await api.fetchApi(`${URL_ROOT}${path}`, options);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(`${data.error?.code || response.status}：${data.error?.message || "请求失败"}`);
    return data;
}

export function attachMediaDesk(node) {
    const widget = node.widgets?.find(w => w.name === "project_data");
    if (!widget) return;
    if (node.zfMediaDesk) {node.zfMediaDesk.restore(); return;}
    widget.type = "converted-widget"; widget.computeSize = () => [0, -4];
    if (widget.inputEl) widget.inputEl.style.display = "none";
    const root = el("div", "zf-med"); root.tabIndex = 0;
    root.innerHTML = `<div class="zf-med-head"><div class="zf-med-brand"><strong>ZV 通用素材取证台</strong><small>原文件 · 机械事实 · 三轨裁剪计划</small></div><div class="zf-med-presets"><div><select class="zf-med-preset-select" aria-label="当前处理预设"></select><button class="zf-med-preset-add">＋ 添加预设</button></div><div class="zf-med-preset-tools"><button class="zf-med-preset-copy">复制当前</button><button class="zf-med-preset-edit">编辑预设</button><button class="zf-med-preset-delete">删除预设</button></div></div><button data-action="export">导出项目 JSON</button></div>
    <div class="zf-med-top"><section class="zf-med-panel"><div class="zf-med-title">统一素材池 <button data-action="import">＋ 导入素材</button></div><div class="zf-med-pool"></div></section>
    <section class="zf-med-panel zf-med-monitor"><div class="zf-med-title"><span class="zf-med-monitor-mode">素材预览</span><span class="zf-med-preview-name">未选择素材</span></div><div class="zf-med-screen"></div><div class="zf-med-controls"><button data-action="play">播放素材</button><span class="zf-med-spacer"></span><span class="zf-med-time">0.000 / 0.000 秒</span><input class="zf-med-seek" type="range" min="0" max="1" step="0.001" value="0" aria-label="源素材播放位置"></div><div class="zf-med-readout">点击任意素材预览，拖到对应轨道开始编排</div></section>
    <section class="zf-med-panel zf-med-inspector-panel"><div class="zf-med-title">机械信息 / 数值裁剪</div><div class="zf-med-context"><button data-action="context" disabled>选择素材或片段</button></div><div class="zf-med-inspect-actions" role="group" aria-label="素材出口操作"></div><div class="zf-med-inspect"></div></section></div>
    <div class="zf-med-tools"><label><input class="zf-med-snap" type="checkbox" checked>吸附</label><button data-action="redo">重做</button><button data-action="undo">撤销</button><button data-action="split" title="在播放头位置分割当前选中片段；绑定原声随视频同时分割">分割</button><button data-action="screenshot" disabled title="截取黄色播放头所在的原视频画面，只加入素材池">截图</button><span class="zf-med-playhead-time"></span><span class="zf-med-spacer"></span><label>缩放 <input class="zf-med-zoom" type="range" min="2" max="140" value="35" aria-label="时间线缩放"></label><span class="zf-med-window-info"></span></div>
    <div class="zf-med-timeline"><div class="zf-med-gutters"><div class="zf-med-gutter">时间 / 秒</div><div class="zf-med-gutter zf-med-picture-gutter">图片<br><small>固定卡片</small><button class="zf-med-delete-picture" data-action="delete-picture" disabled title="请先选择图片卡片">删除</button></div><div class="zf-med-gutter zf-med-video-gutter">视频<br><small>秒时间轴</small><button class="zf-med-delete-video" data-action="delete-video" disabled title="请先选择视频片段">删除</button><button class="zf-med-unlink-audio" data-action="unlink-audio" disabled title="请先选择带原声的视频">解绑音频</button></div><div class="zf-med-gutter zf-med-audio-gutter">音频<br><small>秒时间轴</small><button class="zf-med-delete-audio" data-action="delete-audio" disabled title="请先选择独立或已解绑音频片段">删除</button></div></div><div class="zf-med-scroll"><div class="zf-med-grid"><div class="zf-med-ruler"></div><div class="zf-med-lane" data-track="picture"></div><div class="zf-med-lane" data-track="video"></div><div class="zf-med-lane" data-track="audio"></div><div class="zf-med-window-guide"></div><div class="zf-med-playhead" role="slider" tabindex="0" aria-label="播放头（拖动定位）" aria-valuemin="0"></div></div></div></div><div class="zf-med-status"></div>`;
    const $ = selector => root.querySelector(selector), $$ = selector => [...root.querySelectorAll(selector)];
    const outletActions=el("div","zf-med-preset-tools");
    for(const [action,title] of [["timeline-outlet","创建时间线混音出口"]]) {
        const button=el("button","",title);button.dataset.action=action;
        button.addEventListener("pointerdown",event=>event.stopPropagation());
        outletActions.append(button);
    }
    $(".zf-med-brand").append(outletActions);
    const projectPanel=el("section","zf-med-project-window");
    projectPanel.innerHTML='<div class="zf-med-project-title"><strong>处理窗口</strong><small class="zf-med-preset-summary"></small></div><div class="zf-med-project-fields"><span class="zf-med-window-total"></span><span class="zf-med-window-frames"></span><span class="zf-med-window-state"></span></div><div class="zf-med-compatibility"></div>';
    root.append(projectPanel);
    const pool = $(".zf-med-pool"), screen = $(".zf-med-screen"), inspector = $(".zf-med-inspect"), grid = $(".zf-med-grid"), scroller = $(".zf-med-scroll");
    let project = edit.freshProject(), history = new edit.History(), revision = 0, disposed = false, importing = false, media = null, sound = null, previewToken = 0, waveform = null, previewAsset = null, previewMode = null;
    let view = {zoom:35, playhead:0, selected:null, asset:null, snap:true, scroll:0, ...(node.properties?.zf_media_desk_view || {})};
    let pending = false, draggingAssetId = null, internalDragController = null, previewSeekTime = 0;
    let capturing = false, captureEpoch = 0, captureSourceId = null;
    let timelinePlaying = false, clockHead = 0, clockStart = 0, animationId = 0, timelineVideo = null, playbackError = "";
    const timelineAudio = new Map();
    let presetLibrary={builtins:presets.builtins,users:[]},libraryRevision=0,presetChoices=new Map();
    const visualCache = new Map(), visualAbort = new AbortController();
    const viewSave = () => {node.properties ||= {}; node.properties.zf_media_desk_view = {...view};};
    const autoFitVideoWindow = (value, kind) => node.properties?.zv_auto_fit_video_window && kind === "video" ? edit.fitProcessingWindowToVideoTrack(value) : value;
    const persist = () => {widget.value = JSON.stringify(project); viewSave(); node.setDirtyCanvas?.(true, true); root.dispatchEvent(new CustomEvent("zf-media-project-change"));};
    const status = (text = "", error = false, warning = false) => {$(".zf-med-status").textContent = text; $(".zf-med-status").classList.remove("valid");$(".zf-med-status").classList.toggle("error", error);$(".zf-med-status").classList.toggle("warning",warning);};
    const label = id => pending ? "编号同步中…" : project.label_map?.find(row => row.item_id === id)?.label || "待编号";
    const selected = () => edit.locate(project, view.selected);
    const linkedAudioVideo = () => {
        const item=selected();
        const video=item?.track==="video"?item.clip:item?.track==="audio"?project.video_track.find(v=>v.clip_id===item.clip.linked_video_clip_id):null;
        return video?.audio_link_id && project.audio_track.some(a=>a.clip_id===video.audio_link_id && a.linked_video_clip_id===video.clip_id)?video:null;
    };
    const activeAsset = () => project.assets.find(a => a.asset_id === (selected()?.clip.asset_id || view.asset));
    function assetType(asset) {return asset.kind==="picture"&&asset.capture?.method==="video_frame"?"image":asset.kind;}
    function captureTarget() {
        const entry=edit.timelineAt(project,view.playhead).video;
        if(!entry||entry.asset.kind!=="video")return null;
        const clip=entry.clip;
        if(![view.playhead,clip.timeline_in_seconds,clip.source_in_seconds,clip.source_out_seconds].every(Number.isFinite)||clip.source_in_seconds<0||entry.sourceTime<clip.source_in_seconds||clip.source_out_seconds>entry.asset.probe.duration_seconds)return null;
        return entry;
    }
    function renderCaptureButton() {
        const button=$("[data-action=screenshot]");
        button.disabled=disposed||capturing||importing||project.assets.length>=128||!captureTarget();
        button.setAttribute("aria-busy",String(capturing));
        button.title=capturing?"正在按点击时冻结的来源与时间截图":importing?"请等待素材导入完成":project.assets.length>=128?"素材池最多128项":button.disabled?"黄色播放头处没有可截图的视频片段":"截取黄色播放头所在的原视频画面，只加入素材池";
    }
    async function captureFrame() {
        if(capturing||importing){status("素材正在导入或截图，请稍后重试",false,true);return;}
        pauseTimeline();media?.pause();sound?.pause();
        const entry=captureTarget();
        if(!entry){status("黄色播放头处没有可截图的视频片段",false,true);return;}
        if(project.assets.length>=128){status("素材池最多128项，无法加入截图",true);return;}
        const frozen={source_handle:entry.asset.source_handle,timeline_in_seconds:entry.clip.timeline_in_seconds,source_in_seconds:entry.clip.source_in_seconds,source_out_seconds:entry.clip.source_out_seconds,playhead_seconds:view.playhead};
        const sourceId=entry.asset.asset_id,clipId=entry.clip.clip_id,token=++captureEpoch;
        captureSourceId=sourceId;capturing=true;$("[data-action=import]").disabled=true;renderCaptureButton();
        status(`截图中：${entry.asset.name} · 原片源 ${seconds(entry.sourceTime)} 秒`);
        try{
            const data=await request("/screenshot",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(frozen)});
            if(disposed||token!==captureEpoch)return;
            if(!project.assets.some(asset=>asset.asset_id===sourceId&&asset.source_handle===frozen.source_handle)||!project.video_track.some(clip=>clip.clip_id===clipId&&clip.asset_id===sourceId)){status("截图来源已从当前项目移除，本次结果未加入",false,true);return;}
            if(project.assets.length>=128){status("素材池已满，本次截图未加入",true);return;}
            const next=edit.clone(project);next.assets.push(data.asset);commit(next);
            status(`已加入素材池：${data.asset.name}。可按普通图片拖入图片轨道。`);
        }catch(error){
            if(!disposed&&token===captureEpoch)status(`截图失败：${error.message}`,true);
        }finally{
            capturing=false;captureSourceId=null;
            if(!disposed){$("[data-action=import]").disabled=importing;renderCaptureButton();}
        }
    }
    function createOutlets(items) {
        try {const result=outlets.createMediaOutlets(node,project,items,app);renderInspector();status(`已创建 ${result.created} 个素材出口，复用 ${result.existing} 个已有出口。稳定素材 ID 已保存，工程口已连接。`);}
        catch(error){status(`创建素材出口失败：${error.message}`,true);}
    }
    function cachedVisual(asset, variant) {
        const key = `${asset.source_handle}:${variant}`;
        if (visualCache.has(key)) {
            const entry = visualCache.get(key); visualCache.delete(key); visualCache.set(key, entry); return entry.promise;
        }
        const entry = {url:null, promise:null};
        entry.promise = (async()=>{
            try {
                const response = await api.fetchApi(`${URL_ROOT}/preview?source=${encodeURIComponent(asset.source_handle)}&variant=${variant}`, {signal:visualAbort.signal});
                if (!response.ok) return null;
                if (variant === "peaks") {
                    const data = await response.json();
                    return Array.isArray(data.peaks) && data.peaks.every(p=>Number.isFinite(p)&&p>=0&&p<=1) ? data : null;
                }
                const blob = await response.blob();
                if(disposed || visualCache.get(key)!==entry) return null;
                entry.url = URL.createObjectURL(blob); return entry.url;
            } catch {return null;}
        })();
        visualCache.set(key, entry);
        while(visualCache.size>256) {const oldest=visualCache.keys().next().value, removed=visualCache.get(oldest);if(removed.url)URL.revokeObjectURL(removed.url);visualCache.delete(oldest);}
        return entry.promise;
    }
    function thumbnail(asset, className="") {
        const img=el("img",className);img.alt="";img.draggable=false;
        cachedVisual(asset,"thumbnail").then(url=>{if(!img.isConnected)return;if(url)img.src=url;else img.hidden=true;});
        return img;
    }
    function clipWaveform(asset, clip, width, height) {
        const canvas=el("canvas","zf-med-clip-wave");canvas.width=Math.max(2,Math.min(2048,Math.ceil(width)));canvas.height=Math.max(16,Math.ceil(height));
        canvas.dataset.sourceIn=clip.source_in_seconds;canvas.dataset.sourceOut=clip.source_out_seconds;
        const draw=peaks=>{
            const ctx=canvas.getContext("2d"),w=canvas.width,h=canvas.height;
            const values=edit.sampleClipPeaks(peaks,asset.probe.duration_seconds,clip.source_in_seconds,clip.source_out_seconds,Math.min(512,w/3));
            ctx.clearRect(0,0,w,h);ctx.beginPath();ctx.strokeStyle="#9ee4d4";ctx.lineWidth=1.3;
            ctx.moveTo(0,h/2);
            values.forEach((value,i)=>ctx.lineTo(i*w/(values.length-1),h/2+(i%2?-1:1)*value*h*.42));
            if(!values.length)ctx.lineTo(w,h/2);
            ctx.stroke();canvas.dataset.waveMode=values.length?"peaks":"fallback";
        };
        draw([]);cachedVisual(asset,"peaks").then(data=>{if(canvas.isConnected)draw(data?.peaks||[]);});
        return canvas;
    }
    function clearPreview() {
        stopPreview();previewAsset=null;previewMode=null;
        view.monitor_mode="source";$(".zf-med-monitor-mode").textContent="素材预览";$(".zf-med-seek").setAttribute("aria-label","源素材播放位置");
        screen.replaceChildren(el("div","zf-med-empty","选择素材后在此预览"));
        $(".zf-med-preview-name").textContent="未选择素材";$(".zf-med-time").textContent="0.000 / 0.000 秒";
        $(".zf-med-readout").textContent="点击任意素材预览，拖到对应轨道开始编排";
        $(".zf-med-seek").value=0;$(".zf-med-seek").disabled=true;$("[data-action=play]").disabled=true;$("[data-action=play]").textContent="播放素材";
    }
    function unload(asset) {
        if(asset.asset_id===captureSourceId)captureEpoch++;
        const next=edit.unloadAsset(project,asset.asset_id);
        if(view.asset===asset.asset_id || selected()?.clip.asset_id===asset.asset_id) {view.asset=null;view.selected=null;}
        if(previewAsset?.asset_id===asset.asset_id)clearPreview();
        commit(next);
    }
    function validationStatus() {
        if(playbackError) {status(playbackError,true);return;}
        const errors = project.validation?.errors || [], warnings = project.validation?.warnings || [];
        const messages={source_unavailable:"素材原文件丢失或已改变，请重新导入",missing_asset:"片段引用的素材不存在",source_window:"裁剪入出点必须处于原始素材范围内，且出点大于入点",timeline_limit:"工程时间线不得超过 12 小时",audio_link:"视频与原声绑定关系无效",missing_audio_link:"视频原声开关已打开，但缺少绑定的音频片段",no_source_audio:"该视频没有原声音轨",track_kind:"素材类型与所在轨道不符",duplicate_id:"素材或片段 ID 重复",estimated_frames:"源帧位置为估算值，请按源秒数裁剪",audio_followed:"绑定原声已跟随视频范围"};
        const c=presets.compatibility(project.processing_window,project.processing_preset);
        const w=project.processing_window;
        if(w.end_seconds<=w.start_seconds||w.start_seconds<0||w.end_seconds>43200||w.fps<1||w.fps>240)status("处理窗口范围或参考帧率无效；原值未改写",true);
        else if (errors.length) status(errors.map(e => messages[e.code]||e.message).join("\n"), true);
        else if(!c.compatible)status(c.issues.map(e=>e.message).join("；")+"；工程本身有效",false,true);
        else {status("工程有效且符合当前预设。"+(warnings.length?warnings.map(e=>messages[e.code]||e.message).filter((x,i,a)=>a.indexOf(x)===i).join("；"):"裁剪计划不会改写原素材。"));$(".zf-med-status").classList.add("valid");}
    }
    async function normalize() {
        const version = ++revision;
        pending = true;root.setAttribute("aria-busy","true"); persist(); renderTimeline();
        try {
            const data = await request("/normalize", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(project)});
            if (disposed || version !== revision) return;
            project = data.project; pending = false;root.setAttribute("aria-busy","false"); persist();
            syncTimeline();
            if(!draggingAssetId){renderPool(); renderTimeline(); renderInspector();renderPresetPicker(); validationStatus();}
        } catch (error) {if (!disposed && version === revision) {pending = false;root.setAttribute("aria-busy","false"); status(error.message, true);}}
    }
    function commit(next, before = project) {
        history.record(before); project = next; persist(); renderPool(); renderTimeline(); renderInspector();renderPresetPicker(); normalize();
        syncTimeline(true);
    }
    function restoreHistory(next) {
        project=next;persist();renderPool();renderTimeline();renderInspector();renderPresetPicker();syncTimeline(true);normalize();
    }
    function restore() {
        captureEpoch++;
        const restoredView=node.properties?.zf_media_desk_view;
        ++revision;pending=false;root.setAttribute("aria-busy","false");stopTimeline();clearPreview();
        try {
            const loaded = presets.migrateProject(JSON.parse(widget.value));
            if (!loaded.assets || !loaded.video_track || !loaded.audio_track || !loaded.picture_track || !loaded.processing_window) throw new Error("缺少项目字段");
            if(!loaded.processing_preset||presets.ruleErrors(loaded.processing_preset.snapshot).length)throw new Error("处理预设快照缺失或规则无效");
            history = new edit.History(); playbackError="";
            project = loaded; view = {...view, ...restoredView};
            view.zoom = Math.max(2, Math.min(140, Number(view.zoom)||35)); view.playhead = Math.max(0, Number(view.playhead)||0);
            $(".zf-med-zoom").value = view.zoom; $(".zf-med-snap").checked = view.snap;
            renderPool(); renderTimeline(); renderInspector();renderPresetPicker(); scroller.scrollLeft = view.scroll || 0; normalize();
            if(view.monitor_mode==="timeline")syncTimeline(true);
            else if (activeAsset()) showPreview(activeAsset());
        } catch (error) {status(`项目 JSON 无法恢复：${error.message}。原始内容仍保留在工作流中。`, true);}
    }
    function renderPresetPicker() {
        const current=project.processing_preset,select=$(".zf-med-preset-select");
        if(!current)return;
        presetChoices=new Map();select.replaceChildren();
        const entries=[...presetLibrary.builtins,...presetLibrary.users];
        const match=entries.find(p=>presets.samePreset(p,current));
        if(!match){const option=el("option","",`${current.snapshot.name}（项目快照 v${current.preset_version}）`);option.value="snapshot";select.append(option);}
        for(const preset of entries){const key=`${preset.preset_id}@${preset.preset_version}`,option=el("option","",preset.snapshot.name);option.value=key;select.append(option);presetChoices.set(key,preset);}
        select.value=match?`${current.preset_id}@${current.preset_version}`:"snapshot";
        const editable=!!match&&current.preset_id.startsWith("user.");
        for(const name of ["edit","delete"]){const button=$(`.zf-med-preset-${name}`);button.disabled=!editable;button.title=editable?"只影响当前用户预设库；其他项目快照保持原样":"内置预设不可覆盖/删除；旧快照可复制，或先选择库中最新版本";}
    }
    async function loadPresetLibrary() {
        const revision=++libraryRevision;
        try {const data=await request("/presets",{signal:visualAbort.signal});if(disposed||revision!==libraryRevision)return;presetLibrary={builtins:data.builtins,users:data.users};renderPresetPicker();}
        catch(error){if(!disposed&&revision===libraryRevision)status(`预设库读取失败：${error.message}。当前项目快照仍可使用。`,false,true);}
    }
    function selectNumberOnFirstClick(input) {
        let firstClick=false;
        input.addEventListener("pointerdown",()=>{firstClick=document.activeElement!==input;});
        input.addEventListener("focus",()=>input.select());
        input.addEventListener("click",()=>{if(firstClick){input.select();firstClick=false;}});
    }
    function openPresetEditor(mode) {
        $(".zf-med-preset-editor")?.remove();
        const editing=mode==="edit",current=presets.copy(project.processing_preset),snapshot=presets.normalizeSnapshot(mode==="add"?presets.builtin().snapshot:current.snapshot);
        if(mode==="add"){snapshot.name="";snapshot.description="";}else if(!editing)snapshot.name+=" 副本";
        const dialog=el("section","zf-med-preset-editor");dialog.setAttribute("role","dialog");dialog.setAttribute("aria-label",editing?"编辑用户预设":"添加用户预设");
        dialog.append(el("strong","",editing?"编辑用户预设":"添加用户预设"),el("small","zf-med-note","保存到当前 ComfyUI 用户配置；应用后项目携带完整规则快照。"));
        const form=el("div","zf-med-preset-form"),inputs={};dialog.append(form);
        const field=(key,title,tag="input")=>{const label=el("label","",title),input=el(tag);input.setAttribute("aria-label",title);input.dataset.presetField=key;label.append(input);form.append(label);inputs[key]=input;return input;};
        field("name","预设名称").value=snapshot.name;
        field("description","模型 / 用途说明","textarea").value=snapshot.description;
        const strategy=field("strategy","策略","select");
        for(const [value,title] of [["single_window","单窗口"],["auto_segment","自动分段"]]){const option=el("option","",title);option.value=value;strategy.append(option);}strategy.value=snapshot.strategy;
        const r=snapshot.rules;
        const numericTitles={target_fps:"目标 fps（可空）",min_frames:"最少帧（可空）",max_frames:"最多帧（可空）",max_seconds:"最长秒数（空=不限）",segment_min_seconds:"单段最少秒数",segment_max_seconds:"单段最多秒数",overlap_frames:"请求重叠帧"};
        for(const [key,title] of Object.entries(numericTitles)){const input=field(key,title);input.type="number";input.step=key.includes("frames")?"1":"any";input.value=r[key]??"";selectNumberOnFirstClick(input);}
        const overlapAlignment=field("overlap_alignment","重叠对齐策略","select");
        for(const [value,title] of [["exact","按请求值（通用）"],["h3_guide","H3 Guide 网格向下对齐"]]){const option=el("option","",title);option.value=value;overlapAlignment.append(option);}overlapAlignment.value=r.overlap_alignment;
        field("align_to_grid","起止帧网格对齐").type="checkbox";inputs.align_to_grid.checked=r.align_to_grid;
        const message=el("div","zf-med-preset-message"),summary=el("div","zf-med-note"),actions=el("div","zf-med-preset-actions"),save=el("button","","保存并应用"),cancel=el("button","","取消");
        actions.append(save,cancel);dialog.append(summary,message,actions);root.append(dialog);
        dialog.addEventListener("keydown",event=>{event.stopPropagation();if(event.key==="Escape"&&!cancel.disabled){event.preventDefault();dialog.remove();}});
        const gather=()=>{
            const segmented=strategy.value==="auto_segment",rules={};
            for(const key of Object.keys(numericTitles)){const input=inputs[key];rules[key]=input.validity.badInput?NaN:input.value.trim()===""?null:input.valueAsNumber;}
            if(!segmented){rules.segment_min_seconds=null;rules.segment_max_seconds=null;rules.overlap_frames=0;}
            rules.overlap_alignment=segmented?overlapAlignment.value:"exact";
            rules.align_to_grid=inputs.align_to_grid.checked;
            return {name:inputs.name.value.trim(),description:inputs.description.value.trim(),strategy:strategy.value,rules};
        };
        const update=()=>{
            const segmented=strategy.value==="auto_segment";
            for(const key of ["segment_min_seconds","segment_max_seconds","overlap_frames","overlap_alignment"])inputs[key].parentElement.hidden=!segmented;
            inputs.max_seconds.parentElement.firstChild.textContent=segmented?"总任务最长秒数（空=不限）":"最长秒数（空=不限）";
            inputs.max_seconds.setAttribute("aria-label",inputs.max_seconds.parentElement.firstChild.textContent);
            for(const key of ["min_frames","max_frames"]){const title=`${segmented?"单段":""}${key==="min_frames"?"最少":"最多"}帧（可空）`;inputs[key].parentElement.firstChild.textContent=title;inputs[key].setAttribute("aria-label",title);}
            const value=gather(),errors=presets.ruleErrors(value);message.textContent=errors.join("；");save.disabled=errors.length>0;
            summary.textContent=errors.length?"":presets.ruleSummary({snapshot:value},project.processing_window);
        };
        strategy.addEventListener("change",()=>{if(strategy.value==="auto_segment"){if(!inputs.target_fps.value)inputs.target_fps.value=24;if(!inputs.segment_min_seconds.value)inputs.segment_min_seconds.value=2;if(!inputs.segment_max_seconds.value)inputs.segment_max_seconds.value=15;if(!inputs.overlap_frames.value)inputs.overlap_frames.value=0;}update();});
        form.addEventListener("input",update);cancel.onclick=()=>dialog.remove();
        save.onclick=async()=>{
            const value=gather(),errors=presets.ruleErrors(value);if(errors.length){message.textContent=errors.join("；");return;}
            save.disabled=true;cancel.disabled=true;
            try {
                const path=editing?`/presets/${encodeURIComponent(current.preset_id)}`:"/presets",body=editing?{snapshot:value,preset_version:current.preset_version}:{snapshot:value};
                const data=await request(path,{method:editing?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
                if(disposed)return;
                commit(presets.selectPreset(project,data.preset));dialog.remove();await loadPresetLibrary();
            } catch(error){if(!disposed){message.textContent=error.message;save.disabled=false;cancel.disabled=false;}}
        };
        update();inputs.name.focus();inputs.name.select();
    }
    $(".zf-med-preset-select").onchange=event=>{const preset=presetChoices.get(event.target.value);if(preset)commit(presets.selectPreset(project,preset));};
    $(".zf-med-preset-select").addEventListener("keydown",event=>event.stopPropagation());
    $(".zf-med-preset-add").onclick=()=>openPresetEditor("add");$(".zf-med-preset-copy").onclick=()=>openPresetEditor("copy");$(".zf-med-preset-edit").onclick=()=>openPresetEditor("edit");
    $(".zf-med-preset-delete").onclick=async()=>{
        const current=presets.copy(project.processing_preset);
        try {await request(`/presets/${encodeURIComponent(current.preset_id)}`,{method:"DELETE",headers:{"Content-Type":"application/json"},body:JSON.stringify({preset_version:current.preset_version})});if(!disposed){await loadPresetLibrary();status("用户预设已从库中删除；当前项目快照保持可用。",false);}}
        catch(error){if(!disposed)status(error.message,false,true);}
    };
    function renderPool() {
        pool.replaceChildren();
        if (!project.assets.length) pool.append(el("div", "zf-med-empty", "导入图片、视频、音频\n支持多选及外部文件拖入"));
        for (const asset of project.assets) {
            const card = el("div", `zf-med-asset${view.asset===asset.asset_id ? " selected" : ""}`); card.draggable = true; card.title = asset.name;card.tabIndex=0;card.dataset.assetId=asset.asset_id;card.setAttribute("role","button");card.setAttribute("aria-label",asset.name);
            if (asset.kind !== "audio") card.append(thumbnail(asset));
            else card.append(el("span", "zf-med-empty", "♫ 音频"));
            const type=assetType(asset),facts=el("small", "", "");
            facts.append(el("span",`zf-med-type zf-med-type-${type}`,type),document.createTextNode(` · ${asset.probe.duration_seconds == null ? `${asset.probe.width}×${asset.probe.height}` : seconds(asset.probe.duration_seconds)+" s"}`));
            card.append(el("span", "", asset.name), facts);
            card.addEventListener("click", () => selectAsset(asset));
            card.addEventListener("keydown",event=>{if(event.target===card&&(event.code==="Space"||event.key==="Enter")){event.preventDefault();event.stopPropagation();selectAsset(asset);}});
            const remove=el("button","zf-med-unload","×");remove.type="button";remove.draggable=false;remove.title="卸载素材（保留磁盘原文件）";remove.setAttribute("aria-label",`卸载 ${asset.name}`);
            remove.addEventListener("pointerdown",event=>{event.preventDefault();event.stopPropagation();});
            remove.addEventListener("dragstart",event=>{event.preventDefault();event.stopPropagation();});
            remove.addEventListener("click",event=>{event.preventDefault();event.stopPropagation();unload(asset);});card.append(remove);
            card.addEventListener("dragstart",event=>{
                if(event.target.closest(".zf-med-unload")||event.target.tagName==="IMG"){event.preventDefault();event.stopPropagation();return;}
                event.stopPropagation();event.dataTransfer.clearData();event.dataTransfer.setData("application/x-zf-media",asset.asset_id);event.dataTransfer.effectAllowed="copy";draggingAssetId=asset.asset_id;
                internalDragController?.abort();internalDragController=new AbortController();
                // Only this desk's own drag is intercepted outside its boundary.
                for(const type of ["dragover","drop"])window.addEventListener(type,e=>{
                    if(!root.contains(e.target)){e.preventDefault();e.stopImmediatePropagation();e.dataTransfer.dropEffect="none";clearDropFeedback();if(type==="drop")finishAssetDrag();}
                },{capture:true,signal:internalDragController.signal});
            });
            card.addEventListener("dragend",finishAssetDrag);
            pool.append(card);
        }
    }
    function selectAsset(asset) {view.asset = asset.asset_id; view.selected = null; viewSave(); renderPool(); renderTimeline(); renderInspector(); showPreview(asset);}
    function stopPreview() {previewToken++; const players=[media,sound];media=null;sound=null;waveform=null;for(const player of players)if(player){player.pause();player.removeAttribute("src");player.load();}}
    function readout() {
        if(view.monitor_mode==="timeline")return;
        const asset = previewAsset;
        if (!asset) return;
        const p = asset.probe, time = media?.currentTime || 0;
        $(".zf-med-time").textContent = `${seconds(time)} / ${seconds(p.duration_seconds || 0)} 秒`;
        $(".zf-med-seek").value = time;
        const sourceFrame = p.fps ? Math.min(p.frame_count || Infinity, edit.frame(time,p.fps)+1) : null;
        $(".zf-med-readout").textContent = previewMode === "picture" ? `静态图片 · ${p.width} × ${p.height} · 无时长` : `${sourceFrame == null || previewMode === "audio" ? "音频" : `${sourceFrameLabel(p)} ${sourceFrame} / ${p.frame_count ?? "未知"} · 源 ${p.fps} fps${p.vfr === true ? " · VFR" : p.vfr == null ? " · 帧率稳定性未确认" : ""}`} · ${p.width && previewMode === "video" ? `${p.width} × ${p.height} · ` : ""}${p.has_audio ? "含音频" : "无音频"}${previewMode==="video" ? " · 12 fps 静音代理 + 独立原声音频" : ""}`;
        if (waveform) drawWave(waveform.canvas, waveform.peaks, time/(p.duration_seconds||1));
        $("[data-action=play]").textContent = media && !media.paused ? "暂停素材" : "播放素材";
    }
    function drawWave(canvas, peaks, progress=0) {
        const ctx = canvas.getContext("2d"), w=canvas.width, h=canvas.height; ctx.clearRect(0,0,w,h);
        ctx.fillStyle="#193036"; ctx.fillRect(0,0,w,h); const step=w/peaks.length;
        peaks.forEach((p,i) => {ctx.fillStyle=i/peaks.length<progress ? "#9debed" : "#4bada3"; const size=Math.max(1,p*(h-12)); ctx.fillRect(i*step,(h-size)/2,Math.max(1,step),size);});
        ctx.fillStyle="#ffd268"; ctx.fillRect(progress*w,0,1,h);
    }
    async function showPreview(asset, sourceTime=null) {
        stopTimeline();view.monitor_mode="source";viewSave();playbackError="";
        $(".zf-med-monitor-mode").textContent="素材预览";$(".zf-med-seek").setAttribute("aria-label","源素材播放位置");
        stopPreview(); previewAsset=asset; previewMode=asset.kind; const token=previewToken;
        previewSeekTime=sourceTime??0;
        screen.replaceChildren(); $(".zf-med-preview-name").textContent=asset.name;
        const seek=$(".zf-med-seek"); seek.max=asset.probe.duration_seconds||1; seek.disabled=previewMode==="picture";
        $("[data-action=play]").disabled=previewMode==="picture";
        if (previewMode==="picture") {const img=el("img"); img.src=previewURL(asset,"original"); img.alt=asset.name;img.draggable=false; screen.append(img); readout(); return;}
        const player=el(previewMode==="video"?"video":"audio"); media=player; player.preload="metadata";
        player.src=previewURL(asset,previewMode==="video"?"proxy":"audio"); player.muted=previewMode==="video";
        readout();
        player.addEventListener("error", () => {if(token===previewToken) status("预览解码失败或生成超时；原始素材仍保留。可重新点击素材重试。",true);});
        player.addEventListener("timeupdate", () => {
            if(token!==previewToken) return;
            if(sound && Math.abs(sound.currentTime-player.currentTime)>.18) sound.currentTime=player.currentTime;
            readout();
        });
        player.addEventListener("pause",()=>{if(token===previewToken){sound?.pause();readout();}});
        player.addEventListener("ended",()=>{if(token===previewToken){sound?.pause();readout();}});
        player.addEventListener("loadedmetadata",()=>{if(token!==previewToken)return;player.currentTime=previewSeekTime;readout();});
        if(previewMode==="video") {
            screen.append(player);
            if(asset.probe.has_audio) {sound=el("audio"); sound.preload="metadata"; sound.src=previewURL(asset,"audio"); sound.addEventListener("loadedmetadata",()=>{if(token===previewToken)sound.currentTime=media.currentTime;});sound.addEventListener("error",()=>{if(token===previewToken)status("原声预览生成失败，视频仍可静音预览。",true);});}
        } else {
            const canvas=el("canvas"); canvas.width=960; canvas.height=150; screen.append(canvas,el("span","zf-med-empty","正在读取真实音频峰值…"));
            try {const data=await cachedVisual(asset,"peaks"); if(!data?.peaks?.length) throw new Error("波形读取失败"); if(token!==previewToken) return; screen.replaceChildren(canvas); waveform={canvas,peaks:data.peaks}; drawWave(canvas,data.peaks);}
            catch(error) {if(token===previewToken) {screen.replaceChildren(el("div","zf-med-empty",error.message)); status(error.message,true);}}
        }
        readout();
    }
    function releaseTimelinePlayer(record) {
        if(!record)return;
        record.released=true;record.player.pause();record.player.removeAttribute("src");record.player.load();record.player.remove();
    }
    function pauseTimelinePlayer(record) {
        record.playAttempt++;record.starting=false;record.player.pause();
    }
    function pauseTimeline() {
        if(timelinePlaying)view.playhead=Math.min(edit.timelineEnd(project),clockHead+(performance.now()-clockStart)/1000);
        timelinePlaying=false;cancelAnimationFrame(animationId);animationId=0;
        for(const record of [timelineVideo,...timelineAudio.values()])if(record)pauseTimelinePlayer(record);
        viewSave();paintPlayhead();
    }
    function stopTimeline() {
        pauseTimeline();releaseTimelinePlayer(timelineVideo);timelineVideo=null;
        for(const record of timelineAudio.values())releaseTimelinePlayer(record);
        timelineAudio.clear();
    }
    function timelineFailure(record, error) {
        if(record.released||disposed)return;
        pauseTimeline();
        playbackError=`时间线播放失败：${record.asset.name}。${error?.name==="NotAllowedError"?"浏览器阻止了播放，请再次点击播放时间线。":"媒体未能播放，请检查素材或重新点击播放时间线。"}`;
        syncTimeline();status(playbackError,true);
    }
    function createTimelinePlayer(entry, video=false) {
        const player=el(video?"video":"audio"),record={...entry,player,released:false,starting:false,playAttempt:0};
        player.dataset.timelineClip=entry.clip.clip_id;player.preload="auto";player.muted=video;player.playsInline=true;
        if(video){player.style.visibility="hidden";screen.replaceChildren(player);}
        player.addEventListener("loadedmetadata",()=>{if(!record.released)syncTimelinePlayer(record,true);});
        const reveal=()=>{if(!record.released&&!player.seeking)player.style.visibility="";};
        player.addEventListener("seeked",reveal);player.addEventListener("loadeddata",reveal);
        player.addEventListener("error",()=>timelineFailure(record,player.error));
        player.src=previewURL(entry.asset,video?"proxy":"audio");
        return record;
    }
    function syncTimelinePlayer(record, force=false) {
        const player=record.player,time=edit.sourceTime(record.clip,view.playhead);
        // The project clock leads; tolerate small drift instead of seeking on every frame.
        if(player.readyState>=1 && (force || (!player.seeking && Math.abs(player.currentTime-time)>.2))) {
            if(player.tagName==="VIDEO"&&Math.abs(player.currentTime-time)>.001)player.style.visibility="hidden";
            player.currentTime=time;
        }
        if(!timelinePlaying){pauseTimelinePlayer(record);return;}
        if(player.paused&&!record.starting) {
            const attempt=++record.playAttempt;record.starting=true;
            player.play().then(()=>{if(attempt===record.playAttempt)record.starting=false;if(record.released||!timelinePlaying)player.pause();})
                .catch(error=>{if(attempt!==record.playAttempt)return;record.starting=false;if(!record.released&&timelinePlaying)timelineFailure(record,error);});
        }
    }
    function syncTimeline(force=false) {
        if(disposed||view.monitor_mode!=="timeline")return;
        if(timelinePlaying)view.playhead=Math.min(edit.timelineEnd(project),clockHead+(performance.now()-clockStart)/1000);
        const active=edit.timelineAt(project,view.playhead),video=active.video;
        if(timelineVideo && (timelineVideo.clip.clip_id!==video?.clip.clip_id || timelineVideo.asset.source_handle!==video?.asset.source_handle)) {releaseTimelinePlayer(timelineVideo);timelineVideo=null;}
        if(video) {
            if(!timelineVideo)timelineVideo=createTimelinePlayer(video,true);
            else Object.assign(timelineVideo,video);
            timelineVideo.player.muted=true;
        } else if(!screen.querySelector(".zf-med-black"))screen.replaceChildren(el("div","zf-med-empty zf-med-black","无画面"));
        const ids=new Set(active.audio.map(entry=>entry.clip.clip_id));
        for(const [id,record] of timelineAudio)if(!ids.has(id)||active.audio.find(entry=>entry.clip.clip_id===id).asset.source_handle!==record.asset.source_handle){releaseTimelinePlayer(record);timelineAudio.delete(id);}
        for(const entry of active.audio) {
            let record=timelineAudio.get(entry.clip.clip_id);
            if(!record){record=createTimelinePlayer(entry);timelineAudio.set(entry.clip.clip_id,record);}
            else Object.assign(record,entry);
            // Listening-only headroom: even correlated full-scale clips sum below unity.
            record.player.volume=.8/Math.max(1,active.audio.length);record.player.muted=false;
        }
        for(const record of [timelineVideo,...timelineAudio.values()])if(record)syncTimelinePlayer(record,force);
        $(".zf-med-monitor-mode").textContent="时间线监看";
        $(".zf-med-preview-name").textContent=video?.asset.name||"无画面";
        $(".zf-med-time").textContent=`工程 ${seconds(view.playhead)} / ${seconds(edit.timelineEnd(project))} 秒`;
        const seek=$(".zf-med-seek");seek.setAttribute("aria-label","工程播放位置");seek.max=Math.max(edit.timelineEnd(project),view.playhead,.001);seek.value=view.playhead;seek.disabled=false;
        const button=$("[data-action=play]");button.disabled=edit.timelineEnd(project)<=0;button.textContent=timelinePlaying?"暂停时间线":"播放时间线";
        const p=video?.asset.probe,sourceFrame=p?.fps?edit.frame(video.sourceTime,p.fps)+1:null;
        $(".zf-med-readout").textContent=`${video?`${sourceFrame==null?"视频":`${sourceFrameLabel(p)} ${sourceFrame} / ${p.frame_count??"未知"} · 源 ${p.fps} fps${p.vfr===true?" · VFR":p.vfr==null?" · 帧率稳定性未确认":""}`} · 源 ${seconds(video.sourceTime)} s` : "黑场"} · ${timelinePlaying?"监听":"已定位"} ${active.audio.length} 路音频`;
        paintPlayhead();viewSave();
    }
    function playTimeline() {
        if(timelinePlaying){pauseTimeline();syncTimeline(true);return;}
        if(view.playhead>=edit.timelineEnd(project)){status("已到工程末尾，请先移动黄色播放头。");return;}
        if(playbackError)stopTimeline();
        playbackError="";validationStatus();clockHead=view.playhead;clockStart=performance.now();timelinePlaying=true;
        // Call every active media play() in this click's user gesture, without awaiting another player.
        syncTimeline(true);
        const tick=()=>{if(!timelinePlaying||disposed)return;syncTimeline();if(view.playhead>=edit.timelineEnd(project)){pauseTimeline();syncTimeline();return;}animationId=requestAnimationFrame(tick);};
        animationId=requestAnimationFrame(tick);
    }
    function renderInspector() {
        renderCaptureButton();
        inspector.replaceChildren(); const asset=activeAsset(), item=selected();
        const quickActions=$(".zf-med-inspect-actions");quickActions.replaceChildren();
        const context=$("[data-action=context]");context.textContent=asset?"加入对应轨道（播放头处）":"选择素材";context.disabled=!asset||!!item;context.parentElement.hidden=!!item;
        const video=linkedAudioVideo(),unlink=$(".zf-med-unlink-audio"),pictureDelete=$(".zf-med-delete-picture"),videoDelete=$(".zf-med-delete-video"),audioDelete=$(".zf-med-delete-audio");
        pictureDelete.disabled=item?.track!=="picture";
        pictureDelete.title=pictureDelete.disabled?"请先选择图片卡片":"只删除当前图片卡片，保留素材池、原文件及其他同源卡片";
        unlink.disabled=!video;
        videoDelete.disabled=item?.track!=="video";
        videoDelete.title=videoDelete.disabled?"请先选择视频片段":"删除当前视频片段及仍绑定的原声；保留原文件、素材池和已解绑音频";
        audioDelete.disabled=item?.track!=="audio"||!!item?.clip.linked_video_clip_id;
        audioDelete.title=item?.track==="audio"&&item.clip.linked_video_clip_id?"音频仍绑定视频，请先解绑音频再删除":"只删除当前选中的独立或已解绑音频片段，保留原文件与素材池";
        unlink.title=video?"解除视频与原声的关联，保留音频片段；之后可单独编辑。":"请先选择带原声的视频";
        if(asset) {
            const p=asset.probe;
            inspector.append(el("strong","",asset.name),el("div","zf-med-facts",`${assetType(asset)==="image"?`image · 截图/图片 · 源 ${seconds(asset.capture.source_seconds)} s` : asset.kind} · ${(p.size_bytes/1024/1024).toFixed(2)} MiB\n${p.width?`${p.width} × ${p.height}\n`:""}${p.duration_seconds!=null?`源时长 ${seconds(p.duration_seconds)} s\n`:""}${p.fps?`源帧率 ${p.fps} fps\n总帧 ${p.frame_count??"未知"}（${sourceFrameLabel(p)}）\n`:""}${p.has_audio?`含音频 · ${p.sample_rate} Hz · ${p.channels} 声道`:"无音频"}\n编码 ${p.codec}`));
        }
        if(asset&&!item) {
            const original=el("button","zf-med-original-outlet primary","发送原素材");
            original.title="从原素材来源口连接所选原文件，不经过轨道裁剪或处理窗口";
            original.addEventListener("pointerdown",event=>event.stopPropagation());
            original.addEventListener("click",event=>{
                event.preventDefault();event.stopPropagation();
                if(selected()||activeAsset()!==asset)return;
                try {
                    if(typeof outlets.createOriginalOutlet!=="function")throw new Error("素材出口模块版本不匹配，请刷新页面重新加载插件；若仍失败，请确认当前服务使用同一版本的插件文件。");
                    const result=outlets.createOriginalOutlet(node,asset,app);status(`已${result.created?"创建":"复用"}原素材出口并连接来源：${asset.name}。完整原文件。`);
                }
                catch(error){status(`发送原素材失败：${error.message}`,true);}
            });
            quickActions.append(original);
        }
        if(item) {
            quickActions.append(el("strong","zf-med-label",label(view.selected)));
            const directItem=outlets.outletItems(project,view.selected)[0];
            const outlet=el("button","zf-med-create-outlet primary",`发送${directItem.label}`);
            outlet.title=`为当前选中的${directItem.label}创建直接素材出口；已有同一出口时复用。`;
            outlet.addEventListener("pointerdown",event=>event.stopPropagation());
            outlet.addEventListener("click",event=>{event.preventDefault();event.stopPropagation();createOutlets([directItem]);});
            quickActions.append(outlet);
            if(item.track!=="picture") {
                for(const [key,title] of [["timeline_in_seconds","轨道起点 / 秒"],["source_in_seconds","源入点 / 秒"],["source_out_seconds","源出点 / 秒"]]) numberField(title,item.clip[key],value=>commit(edit.editCut(project,view.selected,{[key]:value})));
                inspector.append(el("div","zf-med-note",`片段 ${seconds(edit.duration(item.clip))} 秒 · 工程 ${project.project_clock.fps} fps / ${edit.frame(Math.max(0,edit.duration(item.clip)),project.project_clock.fps)} 帧`));
                if(item.track==="audio" || asset?.probe.has_audio) {
                    const actions = item.clip.linked_video_clip_id || item.clip.audio_link_id ? [] : item.track==="audio" ? [["toggle","开 / 关音频"],...(item.clip.origin==="video_source"?[["relink","重新绑定原视频"]]:[])] : [];
                    for(const [action,title] of actions) {
                        const button=el("button","",title); button.onclick=()=>commit(edit.audioAction(project,view.selected,action));
                        if(action==="relink" && !project.video_track.some(v=>v.clip_id===item.clip.source_video_clip_id && !v.audio_link_id)) {button.disabled=true;button.title="原视频片段已删除或已有其他原声绑定";}
                        inspector.append(button);
                    }
                    if(item.clip.linked_video_clip_id) inspector.append(el("small","zf-med-note","已绑定：编辑跟随同源视频；删除此音频前请先解绑，避免误删视频。"));
                }
            } else inspector.append(el("div","zf-med-note","图片卡片只表示左右顺序，没有视频时长。拖动卡片可重新排序。"));
        }
    }
    function numberField(title,value,change,parent=inspector) {
        const label=el("label","zf-med-field",title),input=el("input");input.type="number";input.min="0";input.step="any";input.value=value;input.setAttribute("aria-label",title);
        selectNumberOnFirstClick(input);
        input.onchange=()=>{if(Number.isFinite(input.valueAsNumber))change(input.valueAsNumber);};
        label.append(input);parent.append(label);return input;
    }
    const windowInputs={};
    for(const [key,title] of [["start_seconds","开始 / 秒"],["end_seconds","结束 / 秒"],["fps","窗口参考 fps"]]) {
        let before=null;
        const input=numberField(title,project.processing_window[key],()=>{
            if(before){const previous=before;before=null;commit(project,previous);}
        },$(".zf-med-project-fields"));
        input.addEventListener("input",()=>{
            if(!Number.isFinite(input.valueAsNumber))return;
            before??=edit.clone(project);++revision;project.processing_window[key]=input.valueAsNumber;persist();renderTimeline();
        });
        input.addEventListener("blur",()=>{if(before){const previous=before;before=null;commit(project,previous);}else paintWindow(project.processing_window);});
        windowInputs[key]=input;
    }
    function paintWindow(w) {
        const preset=project.processing_preset,c=presets.compatibility(w,preset),fps=c.target_fps,first=edit.frame(w.start_seconds,fps),last=edit.frame(w.end_seconds,fps),count=last-first,total=w.end_seconds-w.start_seconds;
        const invalid=![w.start_seconds,w.end_seconds,w.fps].every(Number.isFinite)||total<=0||w.start_seconds<0||w.end_seconds>43200||w.fps<1||w.fps>240;
        const windowNode=$(".zf-med-window");
        if(windowNode){windowNode.style.left=`${w.start_seconds*view.zoom}px`;windowNode.style.width=`${Math.max(4,total*view.zoom)}px`;windowNode.classList.toggle("invalid",invalid);windowNode.classList.toggle("incompatible",!invalid&&!c.compatible);}
        const guide=$(".zf-med-window-guide");guide.style.left=`${w.start_seconds*view.zoom}px`;guide.style.width=`${Math.max(4,total*view.zoom)}px`;
        $(".zf-med-window-info").textContent=`${first}–${last} 帧 · ${count} 帧 / ${seconds(total)} s`;
        $(".zf-med-window-total").textContent=`总时长 ${seconds(total)} 秒`;
        $(".zf-med-window-frames").textContent=`${first}–${last} 帧 · 总 ${count} 帧 · 目标 ${fps} fps`;
        const engineeringInvalid=invalid||!!project.validation?.errors?.filter(e=>!e.path.startsWith("/processing_window")).length;
        const state=$(".zf-med-window-state");state.textContent=engineeringInvalid?"工程无效":c.compatible?"工程有效且符合预设":"预设不兼容";state.classList.toggle("error",engineeringInvalid);state.classList.toggle("warning",!engineeringInvalid&&!c.compatible);
        $(".zf-med-project-title strong").textContent=`处理窗口 · ${presets.windowName(preset)}`;
        $(".zf-med-preset-summary").textContent=presets.ruleSummary(preset,w);
        const detail=$(".zf-med-compatibility");detail.textContent=invalid?"处理窗口必须为正范围、合法帧率，并处于 0–43200 秒内；原值未改写":c.issues.map(e=>e.message).join("；")+(c.compatible?"":engineeringInvalid?"":"；工程本身有效");detail.classList.toggle("error",engineeringInvalid);detail.classList.toggle("warning",!engineeringInvalid&&!c.compatible);
        for(const key of ["start_seconds","end_seconds","fps"])if(windowInputs[key]&&document.activeElement!==windowInputs[key])windowInputs[key].value=w[key];
    }
    function paintPlayhead() {
        renderCaptureButton();
        const head=$(".zf-med-playhead");head.style.left=`${Math.max(0,view.playhead)*view.zoom}px`;
        head.setAttribute("aria-valuenow",String(view.playhead));head.setAttribute("aria-valuetext",`${seconds(view.playhead)} 秒`);
        $(".zf-med-playhead-time").textContent=`播放头 ${seconds(view.playhead)} s`;
    }
    function setPlayhead(time) {
        pauseTimeline();stopPreview();previewAsset=null;previewMode=null;
        view.monitor_mode="timeline";view.playhead=Math.max(0,time);syncTimeline(true);
    }
    function renderTimeline() {
        outlets.syncOutletTitles(node,project);
        const timed=[...project.video_track,...project.audio_track], end=Math.max(20,project.processing_window.end_seconds+3,...timed.map(c=>c.timeline_in_seconds+Math.max(0,edit.duration(c))+3));
        grid.style.width=`${Math.max(end*view.zoom,project.picture_track.length*126,scroller.clientWidth)}px`;
        const ruler=$(".zf-med-ruler"); ruler.replaceChildren();
        const step=view.zoom>=60?1:view.zoom>=20?5:view.zoom>=7?10:30;
        for(let t=0;t<=end;t+=step) {const tick=el("span","zf-med-tick",String(t)); tick.style.left=`${t*view.zoom}px`; ruler.append(tick);}
        const windowNode=el("div","zf-med-window",presets.windowName(project.processing_preset));windowNode.title=`处理窗口 · ${presets.windowName(project.processing_preset)}`;
        for(const edge of ["left","right"]) {const handle=el("span",`zf-med-handle ${edge}`); handle.dataset.edge=edge; windowNode.append(handle);}
        windowNode.addEventListener("pointerdown",event=>beginDrag(event,"window")); ruler.append(windowNode);
        paintWindow(project.processing_window);paintPlayhead();$(".zf-med-playhead").setAttribute("aria-valuemax",String(end));
        for(const track of ["picture","video","audio"]) {
            const lane=$(`.zf-med-lane[data-track=${track}]`); lane.replaceChildren();
            const clips=[...project[`${track}_track`]].sort((a,b)=>track==="picture"?a.order-b.order:edit.compareTimelineClips(a,b));
            const rowEnds=[], rows=clips.map(c=>{
                if(track==="picture")return 0;
                let row=rowEnds.findIndex(end=>end<=c.timeline_in_seconds+1e-6);if(row<0)row=rowEnds.length;
                rowEnds[row]=c.timeline_in_seconds+Math.max(.001,edit.duration(c));return row;
            });
            const rowHeight=rowEnds.length>1?Math.max(22,Math.floor(64/Math.min(3,rowEnds.length))):64;
            lane.style.overflowY=rowEnds.length>3?"auto":"hidden";
            clips.forEach((clip,index)=>{
                const id=clip.item_id||clip.clip_id, asset=project.assets.find(a=>a.asset_id===clip.asset_id), card=el("div",`zf-med-clip ${track}${track!=="picture"&&rowHeight<45?" compact":""}${id===view.selected?" selected":""}${track==="audio"&&!clip.enabled?" disabled":""}`);
                card.dataset.id=id; card.style.left=`${track==="picture"?index*126+4:clip.timeline_in_seconds*view.zoom}px`; card.style.width=`${track==="picture"?118:Math.max(4,edit.duration(clip)*view.zoom)}px`;
                card.style.top=`${10+rows[index]*rowHeight}px`;card.style.height=`${track==="picture"?64:rowHeight}px`;
                card.title=`${label(id)} · ${asset?.name||"缺少素材"}`;
                if(asset) {
                    if(track==="audio")card.append(clipWaveform(asset,clip,parseFloat(card.style.width),rowHeight>40?28:rowHeight));
                    else card.append(thumbnail(asset,"zf-med-clip-thumb"),el("span","zf-med-clip-shade"));
                }
                card.append(el("b","",label(id)),el("small","",asset?.name||"缺少素材"),el("small","",track==="picture"?"顺序卡片":`${seconds(clip.source_in_seconds)}–${seconds(clip.source_out_seconds)} s${clip.linked_video_clip_id?" · 已绑定":""}`));
                if(track!=="picture") for(const edge of ["left","right"]) {const handle=el("span",`zf-med-handle ${edge}`); handle.dataset.edge=edge; card.append(handle);}
                card.addEventListener("pointerdown",event=>beginDrag(event,id)); lane.append(card);
            });
        }
        $("[data-action=undo]").disabled=!history.past.length; $("[data-action=redo]").disabled=!history.future.length;
        $("[data-action=split]").disabled=!selected()||selected().track==="picture";
    }
    function gridX(event) {const rect=grid.getBoundingClientRect();return (event.clientX-rect.left)*grid.offsetWidth/rect.width;}
    function screenPixelsPerSecond() {return view.zoom*grid.getBoundingClientRect().width/grid.offsetWidth;}
    function timelineTime(event) {return Math.max(0,gridX(event)/view.zoom);}
    function beginPlayheadDrag(event, fromRuler=false) {
        if(event.button!==0)return;event.preventDefault();event.stopPropagation();root.focus({preventScroll:true});root._playheadAbort?.();
        const startX=gridX(event),before=view.playhead,head=$(".zf-med-playhead"),controller=new AbortController();
        const initial=fromRuler?startX/view.zoom:before;
        const seek=time=>setPlayhead(edit.snapTime(Math.max(0,time),edit.snapPoints(project),screenPixelsPerSecond(),view.snap));
        if(fromRuler)seek(initial);else {head.focus({preventScroll:true});setPlayhead(initial);}
        head.setPointerCapture(event.pointerId);
        const drag=e=>{e.preventDefault();e.stopPropagation();seek(initial+(gridX(e)-startX)/view.zoom);};
        const finish=e=>{e.stopPropagation();controller.abort();if(head.hasPointerCapture(event.pointerId))head.releasePointerCapture(event.pointerId);if(e.type==="pointercancel")setPlayhead(before);};
        window.addEventListener("pointermove",drag,{capture:true,signal:controller.signal});window.addEventListener("pointerup",finish,{capture:true,signal:controller.signal,once:true});window.addEventListener("pointercancel",finish,{capture:true,signal:controller.signal,once:true});
        root._playheadAbort=()=>controller.abort();
    }
    function beginDrag(event,id) {
        if(event.button!==0) return; event.preventDefault(); event.stopPropagation();root.focus({preventScroll:true});
        ++revision; // A response for an earlier edit must never overwrite an active gesture.
        const before=edit.clone(project), startX=gridX(event), edge=event.target.dataset.edge, item=edit.target(project,id), local=edit.locate(project,id);
        if(id!=="window" && local) {view.selected=id; view.asset=local.clip.asset_id; renderInspector();}
        if(local?.track==="picture") {
            const asset=activeAsset(),playhead=view.playhead;
            if(asset)showPreview(asset);
            view.playhead=playhead;paintPlayhead();viewSave();
        } else setPlayhead(view.playhead);
        let moved=false;
        const controller=new AbortController();
        function drag(e) {
            e.preventDefault();e.stopPropagation();
            const delta=(gridX(e)-startX)/view.zoom; if(Math.abs(gridX(e)-startX)>2) moved=true;
            if(!moved) return;
            if(id==="window") {
                const p=edit.clone(before);
                const rule=before.processing_preset.snapshot.rules;
                p.processing_window=edit.dragWindow(before.processing_window,delta,edge,[view.playhead,...edit.snapPoints(before,"window")],screenPixelsPerSecond(),view.snap,rule.align_to_grid?rule.target_fps:null);
                project=p;
            } else if(item?.track==="picture") project=edit.reorderPicture(before,id,Math.floor(gridX(e)/126));
            else if(item) {
                const c=item.clip, base=c.timeline_in_seconds+(edge==="right"?edit.duration(c):0), points=[view.playhead,...edit.snapPoints(before,id)], pixelsPerSecond=screenPixelsPerSecond();
                let at=edit.snapTime(base+delta,points,pixelsPerSecond,view.snap);
                if(!edge) {const endSnap=edit.snapTime(at+edit.duration(c),points,pixelsPerSecond,view.snap); if(endSnap!==at+edit.duration(c)) at=endSnap-edit.duration(c);}
                project=edge?edit.trim(before,id,edge,at-base):edit.move(before,id,at);
            }
            persist(); renderTimeline(); renderInspector();syncTimeline(true);
            if(id==="window")validationStatus();
        }
        function finish(e) {e.stopPropagation();controller.abort(); if(e.type==="pointercancel") {project=before; persist(); renderTimeline();renderInspector();syncTimeline(true);normalize();return;} if(moved) commit(project,before); else {renderTimeline();if(local&&local.track!=="picture")setPlayhead(timelineTime(e));if(pending)normalize();} viewSave();}
        window.addEventListener("pointermove",drag,{capture:true,signal:controller.signal}); window.addEventListener("pointerup",finish,{capture:true,signal:controller.signal,once:true}); window.addEventListener("pointercancel",finish,{capture:true,signal:controller.signal,once:true});
        root._dragAbort=()=>controller.abort();
    }
    async function importFiles(files, track=null, at=view.playhead) {
        if(importing||capturing) {status("素材正在导入或截图，请等待当前操作完成。");return;}
        importing=true; $("[data-action=import]").disabled=true;
        renderCaptureButton();
        let current=at, failures=[];
        try {
            for(const file of files) {
                if(project.assets.length>=128) {failures.push("素材池最多 128 项");break;}
                status(`导入 / 探测：${file.name}`);
                try {
                    const form=new FormData(); form.append("file",file); const data=await request("/upload",{method:"POST",body:form});
                    if(disposed) return;
                    let next=edit.clone(project); next.assets.push(data.asset);
                    if(track && data.asset.kind===track) {next=autoFitVideoWindow(edit.addAsset(next,data.asset,current),data.asset.kind); current+=data.asset.probe.duration_seconds||0;}
                    else if(track) failures.push(`${file.name} 已进入素材池；类型与目标轨道不符`);
                    commit(next); view.asset=data.asset.asset_id; view.selected=null;
                } catch(error) {failures.push(`${file.name}：${error.message}`);}
            }
            renderPool(); renderInspector(); if(activeAsset()) showPreview(activeAsset());
        } finally {importing=false; $("[data-action=import]").disabled=false;renderCaptureButton(); if(failures.length) status(failures.join("\n"),true);}
    }
    const fileInput=el("input"); fileInput.type="file"; fileInput.multiple=true; fileInput.accept=".png,.jpg,.jpeg,.webp,.bmp,.mp4,.mov,.mkv,.webm,.avi,.wav,.mp3,.m4a,.flac,.ogg";
    fileInput.onchange=()=>{importFiles([...fileInput.files]);fileInput.value="";};
    const actions={
        import:()=>fileInput.click(),
        screenshot:()=>captureFrame(),
        "timeline-outlet":()=>createOutlets([outlets.timelineOutletItem()]),
        "delete-picture":()=>{if(selected()?.track==="picture")actions.delete();},
        "delete-video":()=>{if(selected()?.track==="video")actions.delete();},
        "delete-audio":()=>{if(selected()?.track==="audio")actions.delete();},
        "unlink-audio":()=>{if(linkedAudioVideo())commit(edit.audioAction(project,view.selected,"unlink"));},
        undo:()=>restoreHistory(history.undo(project)),
        redo:()=>restoreHistory(history.redo(project)),
        split:()=>commit(edit.split(project,view.selected,view.playhead)),
        context:()=>{const asset=activeAsset();if(!selected()&&asset)commit(autoFitVideoWindow(edit.addAsset(project,asset,view.playhead),asset.kind));},
        delete:()=>{const item=selected();if(!item)return;if(item.track==="audio"&&item.clip.linked_video_clip_id){status("音频仍绑定视频，请先解绑音频再删除",false,true);return;}const next=edit.remove(project,view.selected);view.selected=null;commit(next);},
        play:async()=>{
            if(view.monitor_mode==="timeline"){playTimeline();return;}
            if(!media)return;
            const player=media,audio=sound,token=previewToken;
            try {
                if(!player.paused)player.pause();
                else {if(audio){audio.currentTime=player.currentTime;audio.muted=false;}player.muted=previewMode==="video";await Promise.all([player.play(),...(audio?[audio.play()]:[])]);if(token!==previewToken){player.pause();audio?.pause();}readout();}
            } catch(error){if(token===previewToken){player.pause();audio?.pause();status(`素材播放失败：${error.message}，请再次点击播放素材。`,true);}}
        },
        export:async()=>{try {const data=await request("/normalize",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(project)});const blob=new Blob([JSON.stringify(data.project,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),link=el("a");link.href=url;link.download="zv-media-project-v2.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){status(error.message,true);}}
    };
    $$('[data-action]').forEach(button=>button.addEventListener("click",event=>{event.stopPropagation();actions[button.dataset.action]();}));
    $(".zf-med-seek").oninput=event=>{if(view.monitor_mode==="timeline")setPlayhead(Number(event.target.value));else if(media) {media.pause();media.currentTime=Number(event.target.value);previewSeekTime=media.currentTime;if(sound)sound.currentTime=media.currentTime;readout();}};
    $(".zf-med-zoom").oninput=event=>{view.zoom=Number(event.target.value);viewSave();renderTimeline();};
    $(".zf-med-snap").onchange=event=>{view.snap=event.target.checked;viewSave();};
    scroller.onscroll=()=>{view.scroll=scroller.scrollLeft;viewSave();};
    $(".zf-med-ruler").addEventListener("pointerdown",event=>{if(!event.target.closest(".zf-med-window"))beginPlayheadDrag(event,true);});
    $(".zf-med-playhead").addEventListener("pointerdown",event=>beginPlayheadDrag(event));
    $(".zf-med-playhead").addEventListener("keydown",event=>{if(["ArrowLeft","ArrowRight"].includes(event.key)){event.preventDefault();event.stopPropagation();setPlayhead(view.playhead+(event.key==="ArrowRight"?1:-1)/project.project_clock.fps);}});
    for(const lane of $$(".zf-med-lane"))lane.addEventListener("pointerdown",event=>{if(event.target===lane)beginPlayheadDrag(event,true);});
    document.addEventListener("visibilitychange",()=>{if(document.hidden){pauseTimeline();media?.pause();syncTimeline(true);}},{signal:visualAbort.signal});
    function clearDropFeedback() {for(const lane of $$(".zf-med-lane")){lane.classList.remove("drop-target","drop-reject");delete lane.dataset.dropHint;}pool.classList.remove("zf-med-drop");}
    function finishAssetDrag() {draggingAssetId=null;internalDragController?.abort();internalDragController=null;clearDropFeedback();if(!disposed){renderPool();renderTimeline();renderInspector();}}
    function dragFeedback(event) {
        event.preventDefault();event.stopPropagation();clearDropFeedback();
        const lane=event.target.closest(".zf-med-lane"),id=draggingAssetId||event.dataTransfer.getData("application/x-zf-media"),asset=project.assets.find(a=>a.asset_id===id),files=event.dataTransfer.types.includes("Files");
        if(lane&&(asset||files)) {
            const valid=!asset||asset.kind===lane.dataset.track;
            lane.classList.add(valid?"drop-target":"drop-reject");lane.dataset.dropHint=valid?"释放以加入此轨道":"类型不符，请拖到对应轨道";
            lane.style.setProperty("--drop-hint-x",`${scroller.scrollLeft+12}px`);event.dataTransfer.dropEffect=valid?"copy":"none";
        } else if(files) {pool.classList.add("zf-med-drop");event.dataTransfer.dropEffect="copy";}
        else event.dataTransfer.dropEffect="none";
    }
    root.addEventListener("dragenter",dragFeedback);root.addEventListener("dragover",dragFeedback);
    root.addEventListener("dragleave",event=>{if(!root.contains(event.relatedTarget))clearDropFeedback();});
    root.addEventListener("drop",event=>{
        event.preventDefault();event.stopPropagation();
        const lane=event.target.closest(".zf-med-lane"),track=lane?.dataset.track,at=track==="picture"?0:timelineTime(event);
        const id=draggingAssetId||event.dataTransfer.getData("application/x-zf-media"),asset=project.assets.find(a=>a.asset_id===id),files=[...event.dataTransfer.files];
        finishAssetDrag();
        if(files.length)importFiles(files,track,track?at:view.playhead);
        else if(asset&&track){if(asset.kind!==track)status("请将素材拖到对应类型的轨道。",true);else {commit(autoFitVideoWindow(edit.addAsset(project,asset,at),asset.kind));setPlayhead(at);}}
    });
    root.addEventListener("keydown",event=>{if(event.target.closest(".zf-med-preset-editor")||event.target.matches("input,textarea,select")||(event.code==="Space"&&event.target.matches("button")))return;let action;if(event.code==="Space")action="play";if(event.key==="Delete"||event.key==="Backspace")action="delete";if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="z")action=event.shiftKey?"redo":"undo";if(action){event.preventDefault();event.stopPropagation();actions[action]();}});
    root.addEventListener("pointerdown",event=>{event.stopPropagation();if(!event.target.matches("input,textarea,select,button"))root.focus({preventScroll:true});});
    root.addEventListener("wheel",event=>event.stopPropagation(),{passive:true});
    const dom=node.addDOMWidget("media_evidence_desk","zf-media-evidence",root,{serialize:false,hideOnZoom:false,getMinHeight:()=>1000,getMaxHeight:()=>1200});dom.serialize=false;
    pinDOMWidgetFullWidth(dom);
    const previousRemoved=node.onRemoved;node.onRemoved=function(){disposed=true;captureEpoch++;revision++;stopTimeline();stopPreview();root._dragAbort?.();root._playheadAbort?.();internalDragController?.abort();visualAbort.abort();for(const entry of visualCache.values())if(entry.url)URL.revokeObjectURL(entry.url);visualCache.clear();root.remove();previousRemoved?.apply(this,arguments);};
    node.zfMediaDesk={restore,root,getProject:()=>edit.clone(project)};
    node.setSize?.([Math.max(node.size?.[0]||0,1180),Math.max(node.size?.[1]||0,1100)]);
    restore();
    loadPresetLibrary();
}

app.registerExtension({name:"ZV.UniversalMediaEvidenceDesk",async beforeRegisterNodeDef(type,data){if(data.name!==NAME)return;if(data.output?.[0]==="ZV_MEDIA_PROJECT"&&data.output?.[1]==="STRING"&&data.output?.[2]==="ZV_ORIGINAL_SOURCES")sourceEnabledTypes.add(type.prototype);for(const hook of ["onNodeCreated","onConfigure"]){const previous=type.prototype[hook];type.prototype[hook]=function(){previous?.apply(this,arguments);restoreOriginalSourceOutput(this);setTimeout(()=>attachMediaDesk(this),0);};}},nodeCreated(node){if([node.comfyClass,node.type,node.constructor?.comfyClass].includes(NAME)){restoreOriginalSourceOutput(node);setTimeout(()=>attachMediaDesk(node),0);}},loadedGraphNode(node){if([node.comfyClass,node.type,node.constructor?.comfyClass].includes(NAME)){restoreOriginalSourceOutput(node);setTimeout(()=>attachMediaDesk(node),0);}}});
