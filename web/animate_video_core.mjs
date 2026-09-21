export const clone = value => structuredClone(value);
export const defaultSettings = () => ({schema_version:1,seam_mode:"hard_cut",mask_enabled:false,mask_tasks:{}});
export function parseSettings(text) {
    try {
        const value=JSON.parse(text);
        if(!value||typeof value!=="object"||Array.isArray(value))return defaultSettings();
        if(value.schema_version!==1||!['hard_cut','continuation_21'].includes(value.seam_mode)||Object.keys(value).some(key=>!Object.keys(defaultSettings()).includes(key)))return defaultSettings();
        const result={...defaultSettings(),...value};
        if(typeof result.mask_enabled!=='boolean'||!result.mask_tasks||typeof result.mask_tasks!=='object'||Array.isArray(result.mask_tasks))return defaultSettings();
        return result;
    } catch {return defaultSettings();}
}

export function readWorkflowFps(node) {
    const slot=node.inputs?.findIndex(input=>input.name==='fps')??-1;
    if(slot<0||node.inputs[slot].link==null)return {fps:null,linked:false};
    const upstream=(owner,index)=>{
        const links=owner.graph?.links,id=owner.inputs?.[index]?.link,link=links?.get?.(id)??links?.[id];
        return owner.getInputNode?.(index)??owner.graph?.getNodeById?.(link?.origin_id)??null;
    };
    let source=upstream(node,slot);const seen=new Set();
    while(source&&!seen.has(source)){
        seen.add(source);
        if(source.type==='GetNode'){
            const key=source.widgets?.[0]?.value,set=node.graph?._nodes?.find(item=>item.type==='SetNode'&&item.widgets?.[0]?.value===key);
            source=set?upstream(set,0):null;continue;
        }
        const value=source.widgets?.find(widget=>widget.name==='value')?.value;
        if(typeof value==='number'&&Number.isFinite(value)&&value>0)return {fps:value,linked:true};
        if(!['Reroute','SetNode'].includes(source.type))break;
        source=upstream(source,0);
    }
    return {fps:null,linked:true};
}
