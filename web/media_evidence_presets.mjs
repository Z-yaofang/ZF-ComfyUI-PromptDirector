import definitions from './media_processing_presets.json' with {type:'json'};

export const builtins = definitions;
export const copy = value => JSON.parse(JSON.stringify(value));
export const builtin = (id='builtin.generic') => copy(builtins.find(p=>p.preset_id===id));
export function normalizeSnapshot(snapshot) {
    const result=copy(snapshot);
    if(result&&typeof result==='object'&&result.rules&&typeof result.rules==='object'&&!Array.isArray(result.rules)&&!Object.hasOwn(result.rules,'overlap_alignment'))result.rules.overlap_alignment='exact';
    return result;
}
export function samePreset(a,b) {
    const left=normalizeSnapshot(a.snapshot),right=normalizeSnapshot(b.snapshot);
    return a.preset_id===b.preset_id&&a.preset_version===b.preset_version&&['name','description','strategy'].every(key=>left[key]===right[key])&&Object.keys(left.rules).length===Object.keys(right.rules).length&&Object.entries(left.rules).every(([key,value])=>right.rules[key]===value);
}
export function migrateProject(project) {
    const p=copy(project);
    if(p.schema_version===1){p.schema_version=2;p.processing_preset??=builtin('builtin.minimax-h3.single');}
    if(p.processing_preset&&Object.hasOwn(p.processing_preset,'snapshot'))p.processing_preset.snapshot=normalizeSnapshot(p.processing_preset.snapshot);
    delete p.validation;delete p.preset_compatibility;
    return p;
}
export function selectPreset(project,preset) {
    const p=migrateProject(project);p.processing_preset=copy(preset);p.processing_preset.snapshot=normalizeSnapshot(preset.snapshot);return p;
}
export function effectiveOverlapFrames(rules) {
    const requested=rules.overlap_frames;
    return rules.overlap_alignment==='h3_guide'?(requested<5?1:5+17*Math.floor((requested-5)/17)):requested;
}
const hasKeys=(object,keys)=>object&&typeof object==='object'&&!Array.isArray(object)&&Object.keys(object).length===keys.length&&keys.every(k=>Object.hasOwn(object,k));
export function ruleErrors(snapshot) {
    const errors=[];
    if(!hasKeys(snapshot,['name','description','strategy','rules']))return ['预设必须包含名称、用途说明、策略和完整规则'];
    if(typeof snapshot.name!=='string'||!snapshot.name.trim()||[...snapshot.name].length>80)errors.push('预设名称不能为空，且最多 80 个字符');
    if(typeof snapshot.description!=='string'||[...snapshot.description].length>1000)errors.push('模型/用途说明最多 1000 个字符');
    if(!['single_window','auto_segment'].includes(snapshot.strategy))errors.push('请选择单窗口或自动分段策略');
    const r=snapshot.rules;
    if(!hasKeys(r,['target_fps','min_frames','max_frames','max_seconds','align_to_grid','segment_min_seconds','segment_max_seconds','overlap_frames','overlap_alignment']))return [...errors,'预设规则字段不完整或包含未知字段'];
    const titles={target_fps:'目标 fps',min_frames:'最少帧',max_frames:'最多帧',max_seconds:'最长秒数',segment_min_seconds:'单段最少秒数',segment_max_seconds:'单段最多秒数',overlap_frames:'请求重叠帧'};
    for(const [key,title] of Object.entries(titles)) {
        const value=r[key];if(value===null&&key!=='overlap_frames')continue;
        const maximum=key==='target_fps'?240:key.includes('frames')?10368000:43200;
        if(!Number.isFinite(value)||value<(key==='overlap_frames'?0:key==='target_fps'?1:1e-9)||value>maximum)errors.push(`${title}必须是合法有限数值，不能为负或超过 ${maximum}`);
        else if(key.includes('frames')&&!Number.isInteger(value))errors.push(`${title}必须为整数`);
    }
    if(typeof r.align_to_grid!=='boolean')errors.push('帧网格对齐必须为开关值');
    if(!['exact','h3_guide'].includes(r.overlap_alignment))errors.push('请选择按请求值或 H3 Guide 网格的重叠对齐策略');
    if(errors.length)return errors;
    const fps=r.target_fps,segmented=snapshot.strategy==='auto_segment';let minimum=r.min_frames,maximum=r.max_frames;
    if(fps===null&&(minimum!==null||maximum!==null||r.align_to_grid||segmented))return ['帧数限制、帧网格对齐或自动分段需要设置目标 fps'];
    if(segmented){
        if(r.overlap_alignment==='h3_guide'&&r.overlap_frames<1)return ['H3 Guide 请求重叠帧至少为 1'];
        if(r.segment_min_seconds===null||r.segment_max_seconds===null)return ['自动分段必须设置单段最少和最多秒数'];
        minimum=Math.max(minimum||1,Math.ceil(r.segment_min_seconds*fps-1e-9));maximum=Math.min(maximum||Infinity,Math.floor(r.segment_max_seconds*fps+1e-9));
        const overlap=effectiveOverlapFrames(r);
        if(overlap>=minimum)errors.push(`实际重叠 ${overlap} 帧必须小于有效单段最少帧数 ${minimum}`);
        if(r.max_seconds!==null&&r.max_seconds*fps<minimum-1e-9)errors.push('总任务最长秒数不能小于有效单段最短时长');
    }else{
        if(r.segment_min_seconds!==null||r.segment_max_seconds!==null||r.overlap_frames||r.overlap_alignment!=='exact')errors.push('单窗口策略不能保存分段秒数、重叠帧或专用重叠对齐策略');
        if(r.max_seconds!==null&&fps)maximum=Math.min(maximum||Infinity,Math.floor(r.max_seconds*fps+1e-9));
    }
    if(maximum!==null&&(maximum<1||(minimum!==null&&minimum>maximum)))errors.push('最少帧/单段最短时长超过更严格的有效上限，规则冲突');
    return errors;
}
export function compatibility(window,preset) {
    const snapshot=preset.snapshot,r=snapshot.rules,fps=r.target_fps||window.fps,start=window.start_seconds,end=window.end_seconds,duration=end-start;
    const first=Math.floor(start*fps+.5),last=Math.floor(end*fps+.5),count=Math.max(0,last-first),issues=[];
    const issue=(code,message)=>issues.push({path:'/processing_window',code,message});
    const segmented=snapshot.strategy==='auto_segment',secondsCap=segmented?r.segment_max_seconds:r.max_seconds;
    let minimum=r.min_frames,maximum=r.max_frames;
    if(segmented)minimum=Math.max(minimum||1,Math.ceil(r.segment_min_seconds*fps-1e-9));
    if(secondsCap!==null&&r.target_fps)maximum=Math.min(maximum||Infinity,Math.floor(secondsCap*fps+1e-9));
    const effectiveSeconds=Math.min(secondsCap||Infinity,maximum!==null?maximum/fps:Infinity);
    if(r.target_fps&&Math.abs(window.fps-fps)>1e-9)issue('preset_fps',`窗口参考帧率 ${window.fps} fps 与预设目标 ${fps} fps 不符`);
    if(r.align_to_grid&&(Math.abs(first/fps-start)>1e-6||Math.abs(last/fps-end)>1e-6))issue('preset_grid',`起止位置未对齐 ${fps} fps 网格；范围未被改写`);
    const current=`当前 ${duration.toFixed(3)} 秒 / ${count} 帧`;
    const secondsOver=r.max_seconds!==null&&duration>r.max_seconds+1e-9;
    if(!segmented&&maximum!==null&&(count>maximum||duration>effectiveSeconds+1e-9))issue(secondsOver?'preset_seconds':'preset_max_frames',`${current}，超出${snapshot.name}有效上限 ${effectiveSeconds} 秒 / ${maximum} 帧（多 ${Math.max(0,duration-effectiveSeconds).toFixed(3)} 秒 / ${Math.max(0,count-maximum)} 帧）`);
    else if(secondsOver)issue('preset_seconds',`${current}，超出${snapshot.name}上限 ${r.max_seconds} 秒${maximum!==null&&!segmented?` / ${maximum} 帧`:''}（多 ${(duration-r.max_seconds).toFixed(3)} 秒）`);
    let segments=null,overlap=null,stride=null;
    if(segmented){
        overlap=effectiveOverlapFrames(r);stride=maximum-overlap;
        segments=Math.max(1,Math.ceil((count-overlap)/stride));
        if(count+(segments-1)*overlap<segments*minimum)issue('preset_segments',`${current}，无法按每段 ${minimum}–${maximum} 帧、实际重叠 ${overlap} 帧覆盖；需调整范围或分段规则`);
    }else{
        if(minimum!==null&&count<minimum)issue('preset_min_frames',`${current}，不足最少 ${minimum} 帧（少 ${minimum-count} 帧）`);
    }
    return {compatible:!issues.length,issues,target_fps:fps,frame_count:count,effective_min_frames:minimum,effective_max_frames:maximum,effective_max_seconds:Number.isFinite(effectiveSeconds)?effectiveSeconds:null,segment_count:segments,rules_only:segmented,requested_overlap_frames:segmented?r.overlap_frames:null,effective_overlap_frames:overlap,segment_stride_frames:stride};
}
export const windowName=preset=>({'builtin.generic':'通用窗口','builtin.minimax-h3.single':'H3 单段窗口','builtin.minimax-h3.segmented':'H3 长任务范围'}[preset.preset_id]||preset.snapshot.name);
export function ruleSummary(preset,window) {
    const r=preset.snapshot.rules,c=compatibility(window,preset),fps=r.target_fps?`${r.target_fps} fps`:'帧率不限';
    if(preset.snapshot.strategy==='auto_segment')return `${fps} · 每段 ${c.effective_min_frames}–${c.effective_max_frames} 帧 / ${(c.effective_min_frames/c.target_fps).toFixed(3)}–${c.effective_max_seconds} 秒 · 请求重叠 ${r.overlap_frames} 帧，实际 ${c.effective_overlap_frames} 帧（${r.overlap_alignment==='h3_guide'?'按 H3 Guide 网格向下对齐；请求值是可调整的初始值，并非 H3 固定能力':'按请求值'}） · 规划步长 ${c.segment_stride_frames} 帧 · 总任务${r.max_seconds===null?'范围不限':`最多 ${r.max_seconds} 秒`} · ${c.compatible?`预计 ${c.segment_count} 段；`:''}仅规则预览，尚未执行分段`;
    return `${fps} · ${c.effective_min_frames===null?'无最少帧限制':`最少 ${c.effective_min_frames} 帧`} · ${c.effective_max_seconds===null?'时长不限':`有效上限 ${c.effective_max_seconds} 秒${c.effective_max_frames!==null?` / ${c.effective_max_frames} 帧`:''}`} · ${r.align_to_grid?'起止帧网格对齐':'不强制帧网格对齐'}`;
}
