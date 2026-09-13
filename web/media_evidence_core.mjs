// Model-neutral edit operations. Display labels are exclusively supplied by Python.
import {builtin} from './media_evidence_presets.mjs';
export const clone = (value) => JSON.parse(JSON.stringify(value));
export const uid = () => crypto.randomUUID().replaceAll("-", "");
export const frame = (seconds, fps) => Math.floor(seconds * fps + .5);
export const freshProject = () => ({schema_version: 2, project_clock: {fps: 24}, assets: [], picture_track: [], video_track: [], audio_track: [], processing_window: {start_seconds: 0, end_seconds: 10, fps: 24}, processing_preset:builtin(),outlet_slots:{version:1,items:[]}});
export const duration = (clip) => clip.source_out_seconds - clip.source_in_seconds;
export const compareTimelineClips = (a, b) => a.timeline_in_seconds-b.timeline_in_seconds || (a.clip_id < b.clip_id ? -1 : a.clip_id > b.clip_id ? 1 : 0);
export const sourceTime = (clip, playhead) => clip.source_in_seconds + (playhead-clip.timeline_in_seconds);
export const timelineEnd = project => Math.max(0, ...[...project.video_track, ...project.audio_track].filter(c => Number.isFinite(c.timeline_in_seconds+duration(c)) && duration(c)>0).map(c => c.timeline_in_seconds+duration(c)));
export function timelineAt(project, playhead) {
    const resolve = clip => {
        const asset = project.assets.find(a => a.asset_id === clip.asset_id), time = sourceTime(clip, playhead);
        // Half-open cuts prevent both halves of a split from playing at the boundary.
        return asset && playhead >= clip.timeline_in_seconds && time >= 0 && time < clip.source_out_seconds && time < asset.probe.duration_seconds ? {clip, asset, sourceTime:time} : null;
    };
    // The last painted card wins, using the same stable ordering as the timeline UI.
    const videos = [...project.video_track].sort(compareTimelineClips).map(resolve).filter(Boolean);
    const audio = project.audio_track.filter(clip => {
        if (!clip.enabled) return false;
        if (!clip.linked_video_clip_id) return true;
        const video = project.video_track.find(v => v.clip_id === clip.linked_video_clip_id);
        return video?.source_audio_enabled && video.audio_link_id === clip.clip_id && video.asset_id === clip.asset_id;
    }).map(resolve).filter(Boolean);
    return {video:videos.at(-1) || null, audio};
}
export const locate = (project, id) => ["picture", "video", "audio"].flatMap(track => project[`${track}_track`].filter(c => (c.clip_id || c.item_id) === id).map(clip => ({track, clip})))[0];
export function follow(project, video) {
    const audio = project.audio_track.find(a => a.clip_id === video.audio_link_id);
    if (audio) {
        for (const key of ["timeline_in_seconds", "source_in_seconds", "source_out_seconds"]) audio[key] = video[key];
        audio.enabled = video.source_audio_enabled;
    }
}
export function target(project, id) {
    const item = locate(project, id);
    return item?.clip.linked_video_clip_id ? locate(project, item.clip.linked_video_clip_id) : item;
}
export function addAsset(project, asset, at = 0, id = uid) {
    const p = clone(project);
    if (!p.assets.some(a => a.asset_id === asset.asset_id)) p.assets.push(clone(asset));
    if (asset.kind === "picture") p.picture_track.push({item_id: id(), asset_id: asset.asset_id, order: p.picture_track.length+1});
    else {
        const clip = {clip_id: id(), asset_id: asset.asset_id, timeline_in_seconds: Math.max(0, at), source_in_seconds: 0, source_out_seconds: asset.probe.duration_seconds};
        if (asset.kind === "video") {
            clip.source_audio_enabled = asset.probe.has_audio;
            clip.audio_link_id = asset.probe.has_audio ? id() : null;
            p.video_track.push(clip);
            if (clip.audio_link_id) p.audio_track.push({clip_id: clip.audio_link_id, asset_id: asset.asset_id, timeline_in_seconds: clip.timeline_in_seconds, source_in_seconds: 0, source_out_seconds: clip.source_out_seconds, origin: "video_source", enabled: true, linked_video_clip_id: clip.clip_id, source_video_clip_id: clip.clip_id});
        } else p.audio_track.push({...clip, origin: "standalone", enabled: true, linked_video_clip_id: null, source_video_clip_id: null});
    }
    return p;
}
export function move(project, id, at) {
    const p = clone(project), item = target(p, id);
    if (!item || item.track === "picture") return p;
    item.clip.timeline_in_seconds = Math.max(0, at);
    if (item.track === "video") follow(p, item.clip);
    return p;
}
export function trim(project, id, edge, delta) {
    const p = clone(project), item = target(p, id);
    if (!item || item.track === "picture") return p;
    const c = item.clip, max = p.assets.find(a => a.asset_id === c.asset_id).probe.duration_seconds;
    // Mechanical source limits are visible through the resulting cut fields.
    if (edge === "left") {
        delta = Math.max(-c.source_in_seconds, -c.timeline_in_seconds, Math.min(delta, duration(c)-.001));
        c.source_in_seconds += delta;
        c.timeline_in_seconds += delta;
    } else c.source_out_seconds = Math.max(c.source_in_seconds+.001, Math.min(max, c.source_out_seconds+delta));
    if (item.track === "video") follow(p, c);
    return p;
}
export function editCut(project, id, values) {
    const p = clone(project), item = target(p, id);
    if (!item || item.track === "picture") return p;
    Object.assign(item.clip, values);
    if (item.track === "video") follow(p, item.clip);
    return p;
}
export function split(project, id, time, makeId = uid) {
    const p = clone(project), item = target(p, id);
    if (!item || item.track === "picture") return p;
    const c = item.clip, offset = time-c.timeline_in_seconds;
    if (offset <= .001 || offset >= duration(c)-.001) return p;
    const right = {...c, clip_id: makeId(), timeline_in_seconds: time, source_in_seconds: c.source_in_seconds+offset};
    c.source_out_seconds = right.source_in_seconds;
    if (item.track === "video" && c.audio_link_id) {
        const leftAudio = p.audio_track.find(a => a.clip_id === c.audio_link_id);
        right.audio_link_id = makeId();
        p.audio_track.push({...leftAudio, clip_id: right.audio_link_id, linked_video_clip_id: right.clip_id, source_video_clip_id: right.clip_id});
        follow(p, c); follow(p, right);
    }
    p[`${item.track}_track`].push(right);
    return p;
}
export function remove(project, id) {
    const p = clone(project), item = target(p, id);
    if (!item) return p;
    p[`${item.track}_track`] = p[`${item.track}_track`].filter(c => c !== item.clip);
    if (item.track === "video") p.audio_track = p.audio_track.filter(a => a.clip_id !== item.clip.audio_link_id);
    clearMissingSlotBindings(p);
    return p;
}
export function unloadAsset(project, assetId) {
    const p = clone(project);
    p.assets = p.assets.filter(asset => asset.asset_id !== assetId);
    for (const track of ["picture_track", "video_track", "audio_track"]) {
        p[track] = p[track].filter(item => item.asset_id !== assetId);
    }
    clearMissingSlotBindings(p);
    return p;
}
function clearMissingSlotBindings(project) {
    for(const slot of project.outlet_slots?.items||[]) {
        const key=slot.kind==="picture"?"item_id":"clip_id";
        if(slot.binding_id!==null&&!project[`${slot.kind}_track`].some(item=>item[key]===slot.binding_id))slot.binding_id=null;
    }
}
export function sampleClipPeaks(peaks, sourceDuration, sourceIn, sourceOut, count = 128) {
    if (!peaks?.length || ![sourceDuration, sourceIn, sourceOut, count].every(Number.isFinite) || sourceDuration <= 0 || sourceOut <= sourceIn) return [];
    count = Math.max(2, Math.min(512, Math.floor(count)));
    return Array.from({length: count}, (_, i) => {
        const start = sourceIn + (sourceOut-sourceIn)*i/count;
        const end = sourceIn + (sourceOut-sourceIn)*(i+1)/count;
        const first = Math.max(0, Math.floor(start/sourceDuration*peaks.length));
        const last = Math.min(peaks.length, Math.ceil(end/sourceDuration*peaks.length));
        let peak = 0;
        for (let j = first; j < last; j++) peak = Math.max(peak, peaks[j]);
        return Math.max(0, Math.min(1, peak));
    });
}
export function reorderPicture(project, id, index) {
    const p = clone(project), ordered = [...p.picture_track].sort((a,b) => a.order-b.order);
    const from = ordered.findIndex(c => c.item_id === id);
    if (from < 0) return p;
    const [item] = ordered.splice(from, 1);
    ordered.splice(Math.max(0, Math.min(index, ordered.length)), 0, item);
    ordered.forEach((c,i) => {c.order = i+1;});
    p.picture_track = ordered;
    return p;
}
export function audioAction(project, id, action) {
    const p = clone(project), item = locate(p, id);
    if (!item) return p;
    const audio = item.track === "audio" ? item.clip : p.audio_track.find(a => a.clip_id === item.clip.audio_link_id);
    const video = item.track === "video" ? item.clip : p.video_track.find(v => v.clip_id === (audio?.linked_video_clip_id || audio?.source_video_clip_id));
    if (action === "toggle") {
        if (video && (item.track === "video" || audio?.linked_video_clip_id)) {video.source_audio_enabled = !video.source_audio_enabled; follow(p, video);}
        else if (audio) audio.enabled = !audio.enabled;
    }
    if (action === "unlink" && audio && video) {
        audio.linked_video_clip_id = null; video.audio_link_id = null; video.source_audio_enabled = false;
    }
    if (action === "relink" && audio?.origin === "video_source" && video && !video.audio_link_id && video.asset_id === audio.asset_id) {
        audio.linked_video_clip_id = video.clip_id; video.audio_link_id = audio.clip_id; video.source_audio_enabled = audio.enabled; follow(p, video);
    }
    return p;
}
export function snapTime(value, points, pixelsPerSecond, enabled = true) {
    if (!enabled) return value;
    const close = points.filter(p => Math.abs(p-value)*pixelsPerSecond <= 7).sort((a,b) => Math.abs(a-value)-Math.abs(b-value));
    return close.length ? close[0] : value;
}
export function snapPoints(project, exclude) {
    const item = target(project, exclude), excluded = new Set([item?.clip.clip_id, item?.clip.audio_link_id]);
    return [0, ...(exclude === "window" ? [] : [project.processing_window.start_seconds, project.processing_window.end_seconds]), ...[...project.video_track, ...project.audio_track].filter(c => !excluded.has(c.clip_id)).flatMap(c => [c.timeline_in_seconds, c.timeline_in_seconds+duration(c)])];
}
export function dragWindow(window, delta, edge, points, pixelsPerSecond, enabled = true, alignmentFps = window.fps) {
    const length = window.end_seconds-window.start_seconds, fps = alignmentFps;
    const minimum = edge ? 0 : Math.max(0,-length);
    const quantize = value => fps ? Math.max(Math.ceil(minimum*fps),frame(value,fps))/fps : Math.max(minimum,value);
    const raw = Math.max(minimum,(edge === "right" ? window.end_seconds : window.start_seconds)+delta);
    let at = quantize(raw), distance = Infinity;
    // Test the unsnapped pointer against actual screen pixels before frame quantization.
    if (enabled) for (const offset of edge ? [0] : [0,length]) for (const point of points) {
        const gap = Math.abs(raw+offset-point)*pixelsPerSecond, candidate = point-offset;
        if (candidate >= minimum && gap <= 7 && gap < distance && Math.abs(quantize(candidate)+offset-point)*pixelsPerSecond <= 7) {
            at = quantize(candidate); distance = gap;
        }
    }
    if (edge === "left") return {...window,start_seconds:at};
    if (edge === "right") return {...window,end_seconds:at};
    return {...window,start_seconds:at,end_seconds:at+length};
}
export class History {
    constructor() {this.past = []; this.future = [];}
    record(before) {this.past.push(clone(before)); if (this.past.length > 100) this.past.shift(); this.future = [];}
    undo(current) {if (!this.past.length) return current; this.future.push(clone(current)); return this.past.pop();}
    redo(current) {if (!this.future.length) return current; this.past.push(clone(current)); return this.future.pop();}
}
