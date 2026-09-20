import {compareTimelineClips} from "./media_evidence_core.mjs";

const TYPES = {picture:"ZVPictureOutlet", video:"ZVVideoOutlet", audio:"ZVAudioOutlet", timeline:"ZVTimelineAudioOutlet"};
const NAMES = {picture:"图片素材出口", video:"视频素材出口", audio:"音频素材出口", timeline:"时间线混音出口"};
const LABELS = {picture:"图片", video:"视频", audio:"音频"};
const keyFor = track => track === "picture" ? "item_id" : track === "timeline" ? null : "clip_id";
const identity = row => `${row.type}:${row.id || ""}`;
const ORIGINAL_TYPES = {picture:"ZVOriginalPictureOutlet", video:"ZVOriginalVideoOutlet", audio:"ZVOriginalAudioOutlet"};
const ORIGINAL_OUTPUTS = {picture:"IMAGE", video:"VIDEO", audio:"AUDIO"};
const SOURCE_HANDLE = /^originals\/[a-f0-9]{32}\.(png|jpg|jpeg|webp|bmp|mp4|mov|mkv|webm|avi|wav|mp3|m4a|flac|ogg)$/;

export function createOriginalOutlet(desk, asset, app) {
    const graph=desk.graph,type=ORIGINAL_TYPES[asset?.kind];
    if(!type||!SOURCE_HANDLE.test(asset?.source_handle||"")||!(/^[A-Za-z0-9_-]{1,96}$/).test(asset?.asset_id||""))throw new Error("原素材必须有已登记的受控来源和稳定资产ID。");
    if(!graph?.getNodeById||desk.id==null||String(desk.id)==="-1"||graph.getNodeById(desk.id)!==desk)
        throw new Error("素材台尚未加入画布或尚未分配节点 ID。");
    if(!(app.canvas?.graph===graph||graph.list_of_graphcanvas?.some(canvas=>canvas.graph===graph)))
        throw new Error("当前工程画布不可用，无法发送原素材。");
    if(!globalThis.LiteGraph?.createNode||!graph.findNodesByType||!graph.add||!graph.remove||!graph.getLink||!desk.connect)
        throw new Error("画布节点接口不可用，无法发送原素材。");
    if(desk.outputs?.[0]?.type!=="ZV_MEDIA_PROJECT"||desk.outputs?.[1]?.type!=="STRING"||desk.outputs?.[2]?.type!=="ZV_ORIGINAL_SOURCES")
        throw new Error("素材台原素材来源口尚未加载，请正常重启 ComfyUI 加载新版插件后刷新页面。");
    const sourceInput=node=>node.inputs?.findIndex(input=>input.name==="original_sources"&&input.type==="ZV_ORIGINAL_SOURCES");
    const valid=node=>node.type===type&&node.widgets?.some(w=>w.name==="asset_id"&&w.value===asset.asset_id)&&
        node.widgets?.some(w=>w.name==="source_handle"&&w.value==="")&&sourceInput(node)>=0&&node.inputs.filter(input=>input.name==="original_sources").length===1&&
        node.inputs.every(input=>input.name==="original_sources"&&input.type==="ZV_ORIGINAL_SOURCES"||
            ["source_handle","asset_id"].includes(input.name)&&input.type==="STRING"&&input.link==null)&&
        [ORIGINAL_OUTPUTS[asset.kind],"STRING","STRING","STRING"].every((value,index)=>node.outputs?.[index]?.type===value)&&node.outputs.length===4;
    const connected=node=>{
        const index=sourceInput(node),link=index>=0&&graph.getLink(node.inputs[index].link);
        return link&&String(link.origin_id)===String(desk.id)&&link.origin_slot===2&&String(link.target_id)===String(node.id)&&
            link.target_slot===index&&link.type==="ZV_ORIGINAL_SOURCES"&&desk.outputs[2].links?.includes(link.id);
    };
    const existing=graph.findNodesByType(type).find(node=>node.graph===graph&&graph.getNodeById(node.id)===node&&valid(node)&&connected(node));
    if(existing)return {created:0,node_id:existing.id};
    let added=null,assignedId=null,ownedSourceLink=null,result=null,failure=null,cleanupFailure=null,commitFailure=null,compensationFailure=null;
    const priorSourceLinks=new Set(desk.outputs[2].links||[]);
    const registeredId=()=>assignedId!=null&&graph.getNodeById(assignedId)===added?assignedId:
        added&&graph.getNodeById(added.id)===added?added.id:null;
    const rollback=()=>{
        for(let attempt=0;attempt<2;attempt++) {
            const id=registeredId();
            if(id!=null) {
                added.id=id;added.graph=graph;
                try {graph.remove(added);} catch(error) {cleanupFailure=error;}
            }
            if(registeredId()==null&&ownedSourceLink) {
                try {if(graph.getLink(ownedSourceLink.id)===ownedSourceLink)graph.removeLink?.(ownedSourceLink.id);} catch(error) {cleanupFailure=error;}
                if(graph.getLink(ownedSourceLink.id)===ownedSourceLink)continue;
                // A rejected link may have a corrupted origin slot; remove only
                // its proven-owned new reference, never any prior desk edge.
                desk.outputs[2].links=(desk.outputs[2].links||[]).filter(link=>link!==ownedSourceLink.id||priorSourceLinks.has(link));
            }
            if(registeredId()==null)return;
        }
        if(registeredId()!=null||ownedSourceLink&&graph.getLink(ownedSourceLink.id)===ownedSourceLink)
            throw new Error("回滚不完整：本次新增节点或来源线仍登记在原画布中");
    };
    graph.beforeChange?.();
    try {
        const node=globalThis.LiteGraph.createNode(type);
        if(!node)throw new Error("原素材出口节点类型尚未加载，请重启 ComfyUI 主服务加载插件后刷新页面，再重试。");
        if(node.graph)throw new Error("原素材出口创建结果已属于其他画布。");
        const widget=node.widgets?.find(w=>w.name==="asset_id"),legacy=node.widgets?.find(w=>w.name==="source_handle");
        if(!widget||!legacy||!(sourceInput(node)>=0))throw new Error("原素材出口来源输入尚未加载，请正常重启 ComfyUI 加载新版插件后刷新页面。");
        widget.value=asset.asset_id;legacy.value="";
        if(!valid(node))throw new Error("原素材出口输入或输出契约不符。");
        node.properties ||= {};
        node.properties.zv_original_outlet={binding:"catalog",kind:asset.kind,asset_id:asset.asset_id,name:asset.name};
        node.title=`ZV 原${LABELS[asset.kind]}出口 · ${String(asset.name).slice(0,28)}`;
        const index=Object.values(ORIGINAL_TYPES).reduce((count,t)=>count+graph.findNodesByType(t).length,0);
        node.pos=[desk.pos[0]+desk.size[0]+48+Math.floor(index/6)*340,desk.pos[1]+(index%6)*190];
        added=node;
        const onAdded=node.onAdded;
        node.onAdded=function(...args){assignedId=this.id;return onAdded?.apply(this,args);};
        try {graph.add(node);} finally {node.onAdded=onAdded;}
        if(node.id==null||String(node.id)==="-1"||node.graph!==graph||graph.getNodeById(node.id)!==node)
            throw new Error("原素材出口未获得有效画布节点 ID。");
        node.setSize([300,Math.max(100,node.computeSize()[1])]);
        if(!valid(node))throw new Error("原素材绑定在加入画布时被改变。");
        const beforeConnect=graph.beforeChange,afterConnect=graph.afterChange;
        // LiteGraph's fresh-input connect can emit afterChange without its own
        // beforeChange. Defer connection hooks to this creation transaction.
        try {
            graph.beforeChange=()=>{};graph.afterChange=()=>{};
            desk.connect(2,node,sourceInput(node));
        } finally {
            graph.beforeChange=beforeConnect;graph.afterChange=afterConnect;
            const link=graph.getLink(node.inputs[sourceInput(node)]?.link);
            if(link&&String(link.target_id)===String(assignedId)&&link.target_slot===sourceInput(node)&&!priorSourceLinks.has(link.id))ownedSourceLink=link;
        }
        if(!connected(node)||!valid(node))throw new Error("原素材来源线未正确连接；本次发送已失败。");
        graph.setDirtyCanvas?.(true,true);
        result={created:1,node_id:node.id};
    } catch(error) {
        failure=error;
        try {rollback();} catch(error) {cleanupFailure=error;}
    }
    try {graph.afterChange?.();} catch(error) {
        commitFailure=error;
        if(!failure) {
            failure=error;
            // Commit hooks may already have run. Give owned-node rollback its own transaction.
            let compensationStarted=false;
            try {graph.beforeChange?.();compensationStarted=true;} catch(error) {compensationFailure=error;}
            try {rollback();} catch(error) {cleanupFailure=error;}
            if(compensationStarted)try {graph.afterChange?.();} catch(error) {cleanupFailure=error;}
        }
    }
    if(failure) {
        const incomplete=registeredId()!=null||ownedSourceLink&&graph.getLink(ownedSourceLink.id)===ownedSourceLink;
        throw new Error(`${failure.message||failure}${incomplete?"；回滚不完整：本次新增节点或来源线仍登记在原画布中":added?"；本次新增节点已撤回":""}${compensationFailure?`；补偿事务启动异常：${compensationFailure.message||compensationFailure}`:""}${cleanupFailure?`；清理异常：${cleanupFailure.message||cleanupFailure}`:""}${commitFailure?"；画布提交异常，无法确认事务闭合":""}`);
    }
    return result;
}

export function outletItems(project, selectedId) {
    const rows = [];
    for (const track of ["picture", "video", "audio"]) {
        const items = [...project[`${track}_track`]].filter(c => track !== "audio" || !c.linked_video_clip_id);
        items.sort(track === "picture" ? (a,b) => a.order-b.order || (a.item_id < b.item_id ? -1 : a.item_id > b.item_id ? 1 : 0) : compareTimelineClips);
        items.forEach((item,index) => {
            const asset = project.assets.find(a => a.asset_id === item.asset_id);
            rows.push({track, type:TYPES[track], key:keyFor(track), id:item[keyFor(track)], label:`${LABELS[track]}${index+1}`, name:asset?.name || "来源不存在"});
        });
    }
    if (selectedId === undefined) return rows;
    const linked = project.audio_track.find(c => c.clip_id === selectedId)?.linked_video_clip_id;
    const found = rows.find(row => row.id === (linked || selectedId));
    if (!found) throw new Error("绑定素材已不存在，请先选择一个已入轨的素材。");
    return [found];
}

export const timelineOutletItem = () => ({track:"timeline", type:TYPES.timeline, key:null, id:null, label:"时间线混音", name:"当前处理窗口"});

function connectedOutlets(desk) {
    const graph = desk.graph;
    if (!graph?.getNodeById || !graph.getLink) return [];
    return (desk.outputs?.[0]?.links||[]).flatMap(id=>{
        const link=graph.getLink(id),node=link&&graph.getNodeById(link.target_id),track=Object.keys(TYPES).find(key=>TYPES[key]===node?.type);
        return track&&link&&String(link.origin_id)===String(desk.id)&&link.origin_slot===0&&link.target_slot===0&&node.inputs?.[0]?.link===id?
            [{node,track,type:node.type,key:keyFor(track),id:keyFor(track)?node.widgets?.find(w=>w.name===keyFor(track))?.value:null}]:[];
    });
}

function titleFor(row) {
    const name = row.name.length > 28 ? `${row.name.slice(0,25)}…` : row.name;
    return `ZV ${NAMES[row.track]} · ${row.label} · ${name}`;
}

export function syncOutletTitles(desk, project) {
    const items = [...outletItems(project), timelineOutletItem()];
    for (const row of connectedOutlets(desk)) {
        const item = items.find(item => identity(item) === identity(row));
        row.node.title = item ? titleFor(item) : `ZV ${NAMES[row.track]} · 绑定素材已不存在`;
        row.node.properties ||= {};
        row.node.properties.zv_media_outlet = {binding_key:row.key, binding_id:row.id};
    }
}

export function createMediaOutlets(desk, project, items, app) {
    const graph = desk.graph;
    if (!graph || !graph.getNodeById || desk.id == null || desk.id === "" || String(desk.id) === "-1" || graph.getNodeById(desk.id) !== desk)
        throw new Error("素材台尚未加入画布或尚未分配节点 ID，请加入画布后重试。");
    if (!(app.canvas?.graph === graph || graph.list_of_graphcanvas?.some(canvas => canvas.graph === graph)))
        throw new Error("当前工程画布不可用，无法创建素材出口。");
    if (!globalThis.LiteGraph?.createNode || !graph.add || !graph.remove || !graph.getLink || !graph.findNodesByType || !desk.connect || desk.outputs?.[0]?.type !== "ZV_MEDIA_PROJECT")
        throw new Error("画布节点接口或素材台工程端口不可用，无法创建素材出口。");
    const existing = connectedOutlets(desk), wanted = [...new Map(items.map(row => [identity(row),row])).values()];
    const missing = wanted.filter(row => !existing.some(old => identity(old) === identity(row) && !old.node.inputs?.some(input => input.name === row.key && input.link != null)));
    const created = [];
    graph.beforeChange?.();
    try {
        for (const row of missing) {
            const node = globalThis.LiteGraph.createNode(row.type);
            if (!node) throw new Error(`未找到 ${NAMES[row.track]} 节点类型，请确认节点已正常加载。`);
            const widget = row.key ? node.widgets?.find(w => w.name === row.key) : null;
            if (node.inputs?.[0]?.name !== "media_project" || node.inputs[0].type !== "ZV_MEDIA_PROJECT" || (row.key && !widget))
                throw new Error(`${NAMES[row.track]} 的工程输入或绑定字段不符合契约。`);
            if (widget) widget.value = row.id;
            node.properties ||= {};
            node.properties.zv_media_outlet = {binding_key:row.key, binding_id:row.id};
            node.title = titleFor(row);
            const index = existing.length + created.length;
            node.pos = [desk.pos[0] + desk.size[0] + 48 + Math.floor(index/6)*340, desk.pos[1] + (index%6)*190];
            created.push(node);
            graph.add(node);
            node.setSize([300, Math.max(100, node.computeSize()[1])]);
            desk.connect(0,node,0);
            const link = graph.getLink(node.inputs[0].link);
            if (!link || String(link.origin_id) !== String(desk.id) || link.origin_slot !== 0 || String(link.target_id) !== String(node.id) || link.target_slot !== 0)
                throw new Error(`${NAMES[row.track]} 自动连线失败，已撤回本次新增节点。`);
        }
        syncOutletTitles(desk,project);
        graph.setDirtyCanvas?.(true,true);
        return {created:created.length, existing:wanted.length-missing.length};
    } catch (error) {
        for (const node of created.reverse()) if (node.graph === graph) graph.remove(node);
        throw error;
    } finally {graph.afterChange?.();}
}
