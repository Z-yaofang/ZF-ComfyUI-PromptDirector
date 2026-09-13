import {outletItems} from "./media_evidence_outlets.mjs?v=h3-v2-07";

export const SLOT_TYPES={picture:"ZVPictureSlotOutlet",video:"ZVVideoSlotOutlet",audio:"ZVAudioSlotOutlet"};
const NAMES={picture:"图片",video:"视频",audio:"音频"};
const copy=value=>JSON.parse(JSON.stringify(value));
const safeId=value=>typeof value==="string"&&/^[A-Za-z0-9_-]{1,96}$/.test(value);
const keys=(value,names)=>value&&typeof value==="object"&&!Array.isArray(value)&&Object.keys(value).sort().join()===names.sort().join();
export const slotLabel=slot=>`${NAMES[slot.kind]}${slot.ordinal}`;

export function slotItems(project) {
    if(project.outlet_slots===undefined)return [];
    const data=project.outlet_slots;
    if(!keys(data,["version","items"])||data.version!==1||!Array.isArray(data.items)||data.items.length>256)throw new Error("出口槽位结构或版本无效");
    const ids=new Set(),ordinals=new Set();
    for(const slot of data.items){
        if(!keys(slot,["slot_id","kind","ordinal","binding_id"])||!safeId(slot.slot_id)||typeof slot.kind!=="string"||!Object.hasOwn(SLOT_TYPES,slot.kind)||!Number.isInteger(slot.ordinal)||slot.ordinal<1||slot.ordinal>1000000||(slot.binding_id!==null&&!safeId(slot.binding_id)))throw new Error("出口槽位字段无效");
        const ordinal=`${slot.kind}:${slot.ordinal}`;
        if(ids.has(slot.slot_id)||ordinals.has(ordinal))throw new Error("槽位 ID 和同类型序号必须唯一");
        ids.add(slot.slot_id);ordinals.add(ordinal);
    }
    return data.items;
}

export function selectedSlotItem(project, selectedId) {
    if(!selectedId)throw new Error("请先选择一个已入轨的素材");
    return outletItems(project,selectedId)[0];
}

export function slotStatus(project, slot) {
    if(slot.binding_id===null)return {name:"未指定",state:"empty"};
    const key=slot.kind==="picture"?"item_id":"clip_id",item=project[`${slot.kind}_track`].find(c=>c[key]===slot.binding_id);
    const asset=item&&project.assets.find(a=>a.asset_id===item.asset_id);
    if(!asset||slot.kind==="audio"&&item.linked_video_clip_id)return {name:"素材已不存在或类型不符",state:"missing"};
    return {name:asset.name,state:"bound"};
}

export function assignSlot(project, slotId, selectedId) {
    const slot=slotItems(project).find(s=>s.slot_id===slotId);
    if(!slot)throw new Error("请明确选择要发送到的槽位");
    const item=selectedSlotItem(project,selectedId);
    if(slot.kind!==item.track)throw new Error("选中素材与槽位类型不符");
    const next=copy(project);next.outlet_slots.items.find(s=>s.slot_id===slotId).binding_id=item.id;
    return next;
}

export function clearSlot(project, slotId) {
    if(!slotItems(project).some(s=>s.slot_id===slotId))throw new Error("槽位已不存在");
    const next=copy(project);next.outlet_slots.items.find(s=>s.slot_id===slotId).binding_id=null;return next;
}

// Follow only the desk's own project-output edges. Never inspect a model's inputs.
export function connectedSlotNodes(desk) {
    const graph=desk.graph;
    if(!graph?.getLink||!graph.getNodeById)return [];
    return (desk.outputs?.[0]?.links||[]).flatMap(id=>{
        const link=graph.getLink(id),node=link&&graph.getNodeById(link.target_id);
        return link&&String(link.origin_id)===String(desk.id)&&link.origin_slot===0&&link.target_slot===0&&node?.inputs?.[0]?.link===id&&Object.values(SLOT_TYPES).includes(node.type)?[node]:[];
    });
}

export function syncSlotTitles(desk, project) {
    const slots=slotItems(project);
    for(const node of connectedSlotNodes(desk)){
        const id=node.widgets?.find(w=>w.name==="slot_id")?.value,slot=slots.find(s=>s.slot_id===id&&SLOT_TYPES[s.kind]===node.type);
        const status=slot?slotStatus(project,slot):{name:"槽位未指定",state:"missing"};
        const name=status.name.length>28?status.name.slice(0,25)+"…":status.name;
        node.title=slot?`ZV ${NAMES[slot.kind]}槽${slot.ordinal} · ${name}`:`ZV 槽位出口 · ${name}`;
        node.color=status.state==="bound"?"#24515b":status.state==="empty"?"#73582d":"#743f45";
        node.bgcolor=status.state==="bound"?"#1c3039":"#302a25";
    }
}

export function createSlotOutlet(desk, project, selectedId, app) {
    const item=selectedSlotItem(project,selectedId),items=slotItems(project),graph=desk.graph;
    if(items.length>=256)throw new Error("最多支持 256 个出口槽位");
    if(!graph?.getNodeById||graph.getNodeById(desk.id)!==desk||!graph.add||!graph.remove||!desk.connect||!graph.getLink||desk.outputs?.[0]?.type!=="ZV_MEDIA_PROJECT"||!(app.canvas?.graph===graph||graph.list_of_graphcanvas?.some(c=>c.graph===graph)))throw new Error("当前素材台工程画布不可用");
    const ordinal=Math.max(0,...items.filter(s=>s.kind===item.track).map(s=>s.ordinal))+1;
    if(ordinal>1000000)throw new Error("槽位序号已达到上限");
    const slot={slot_id:crypto.randomUUID().replaceAll("-",""),kind:item.track,ordinal,binding_id:item.id};
    const node=globalThis.LiteGraph?.createNode(SLOT_TYPES[item.track]);
    if(!node)throw new Error("槽位出口节点尚未加载，请重启 ComfyUI 后刷新页面");
    const widget=node.widgets?.find(w=>w.name==="slot_id");
    if(!widget||node.inputs?.[0]?.name!=="media_project"||node.inputs[0].type!=="ZV_MEDIA_PROJECT")throw new Error("槽位出口的固定输入契约不符");
    const next=copy(project);next.outlet_slots={version:1,items:[...copy(items),slot]};
    widget.value=slot.slot_id;node.properties||={};node.properties.zv_media_slot={slot_id:slot.slot_id,kind:slot.kind};
    node.pos=[desk.pos[0]+desk.size[0]+48+Math.floor(items.length/6)*340,desk.pos[1]+items.length%6*190];
    try{
        graph.add(node);node.setSize([300,Math.max(100,node.computeSize()[1])]);desk.connect(0,node,0);
        const link=graph.getLink(node.inputs[0].link);
        if(!link||String(link.origin_id)!==String(desk.id)||link.origin_slot!==0||String(link.target_id)!==String(node.id)||link.target_slot!==0)throw new Error("槽位工程连线失败");
        syncSlotTitles(desk,next);return {project:next,slot,node};
    }catch(error){if(node.graph===graph)graph.remove(node);throw error;}
}

// Interface definitions survive desk undo. Undo changes the mapping, never tears off model wires.
export function retainSlotDefinitions(project, definitions) {
    const next=copy(project),items=slotItems(next);
    next.outlet_slots={version:1,items:[...items,...definitions.filter(s=>!items.some(old=>old.slot_id===s.slot_id)).map(s=>({...s,binding_id:null}))]};
    return next;
}
