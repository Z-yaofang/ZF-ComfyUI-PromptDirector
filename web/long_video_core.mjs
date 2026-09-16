export const clone = value => structuredClone(value);
export const uid = () => crypto.randomUUID().replaceAll("-", "");
export const frame = (seconds, fps) => Math.floor(seconds * fps + .5);
export const defaultSettings = () => ({schema_version:1, mode:"source_auto", fps:24, segment_frames:360, overlap_frames:48, overlap_alignment:"h3_guide", segment_count:1, segments:[], range_start_frame:null, range_end_frame:null, source_snapshot:null, source_fingerprint:null, refresh_sources:false});
export const emptyInterview = () => ({schema_version:1, global:{}, segments:{}, alignment:null});
export const parse = (text, fallback) => {
    try { const value = JSON.parse(text); return value && typeof value === "object" && !Array.isArray(value) ? value : fallback(); }
    catch { return fallback(); }
};
export function manual(settings, plan, requestedMode=null) {
    const mode=requestedMode??(plan.mode.startsWith("generation")?"generation_manual":"source_manual");
    return {...clone(settings), mode, segments:plan.segments.map(({segment_id,start_frame,end_frame})=>({segment_id,start_frame,end_frame}))};
}
export function changeSegment(settings, plan, id, start, end) {
    const next=manual(settings,plan), row=next.segments.find(x=>x.segment_id===id);
    if (!row || !Number.isInteger(start) || !Number.isInteger(end) || start<0 || end<=start) return next;
    row.start_frame=start; row.end_frame=end;
    return next;
}
export function splitSegment(settings, plan, id, at, makeId=uid) {
    const next=manual(settings,plan), row=next.segments.find(x=>x.segment_id===id);
    if (!row || at<=row.start_frame || at>=row.end_frame) return next;
    const right={segment_id:makeId(),start_frame:at,end_frame:row.end_frame};
    row.end_frame=at; next.segments.push(right);
    return next;
}
export function removeSegment(settings,plan,id) {
    const next=manual(settings,plan); next.segments=next.segments.filter(x=>x.segment_id!==id); return next;
}
export function addSegment(settings,plan,makeId=uid) {
    const next=manual(settings,plan), last=plan.segments.at(-1);
    const overlap=last ? Math.min(plan.effective_overlap_frames,settings.segment_frames-1) : 0;
    const start=last ? last.end_frame-overlap : plan.range_start_frame;
    next.segments.push({segment_id:makeId(),start_frame:start,end_frame:start+settings.segment_frames});
    return next;
}
export function presetSettings(settings,preset) {
    const next=clone(settings);
    for(const key of ["fps","segment_frames","overlap_frames","overlap_alignment","segment_count","mode"]) if(key in preset) next[key]=preset[key];
    return next;
}
export function upstreamNode(node,name) {
    const index=node.inputs?.findIndex(input=>input.name===name)??-1;
    if(index<0) return null;
    const direct=node.getInputNode?.(index); if(direct) return direct;
    const linkId=node.inputs[index].link, links=node.graph?.links;
    const link=links?.get?.(linkId)??links?.[linkId];
    return node.graph?.getNodeById?.(link?.origin_id)??null;
}
export function traceUpstream(node,name,predicate) {
    let source=upstreamNode(node,name), seen=new Set();
    while(source&&!predicate(source)&&!seen.has(source.id)) {
        seen.add(source.id);
        const input=source.inputs?.find(row=>row.link!=null)??source.inputs?.[0];
        source=input?upstreamNode(source,input.name):null;
    }
    return source&&predicate(source)?source:null;
}
function linkedInteger(node,name) {
    const index=node.inputs?.findIndex(row=>row.name===name)??-1, input=node.inputs?.[index];
    if(index<0||input?.link==null)return null;
    const links=node.graph?.links,link=links?.get?.(input.link)??links?.[input.link];
    let source=node.graph?.getNodeById?.(link?.origin_id)??node.getInputNode?.(index),slot=link?.origin_slot??0;
    const seen=new Set();
    while(source&&!seen.has(source.id)) {
        seen.add(source.id);
        if(source.type==="ResolutionSelector") {
            const get=key=>source.widgets?.find(w=>w.name===key)?.value;
            const ratio=String(get("aspect_ratio")??"").match(/^(\d+):(\d+)/),megapixels=Number(get("megapixels")),multiple=Number(get("multiple"));
            if(ratio&&Number.isFinite(megapixels)&&Number.isInteger(multiple)&&multiple>0) {
                const [w,h]=[Number(ratio[1]),Number(ratio[2])],scale=Math.sqrt(megapixels*1024*1024/(w*h));
                return slot===0?Math.round(w*scale/multiple)*multiple:Math.round(h*scale/multiple)*multiple;
            }
        }
        const value=source.widgets?.find(w=>w.name==="value")?.value;
        if(Number.isInteger(value))return value;
        const inputRow=source.inputs?.find(row=>row.link!=null)??source.inputs?.[0];
        if(!inputRow)return null;
        const next=source.graph?.links?.get?.(inputRow.link)??source.graph?.links?.[inputRow.link];
        source=source.graph?.getNodeById?.(next?.origin_id)??upstreamNode(source,inputRow.name);slot=next?.origin_slot??0;
    }
    return null;
}
export function readDesk(node) {
    const source=traceUpstream(node,"media_project",candidate=>candidate.widgets?.some(w=>w.name==="project_data"));
    const widget=source?.widgets?.find(w=>w.name==="project_data");
    if(!widget) throw new Error("请把素材台的 media_project 接到分段台");
    const project=JSON.parse(widget.value);
    for(const key of ["width","height"]) {
        const value=linkedInteger(source,key);
        if(Number.isInteger(value)) (project.output_canvas??={})[key]=value;
    }
    return {source,project};
}
