import test from 'node:test';
import assert from 'node:assert/strict';
import * as e from '../web/media_evidence_core.mjs';
let counter=0;
const id=()=>`id${++counter}`;
const video={asset_id:'asset',kind:'video',probe:{duration_seconds:30,has_audio:true}};
const picture={asset_id:'picture',kind:'picture',probe:{duration_seconds:null,has_audio:false}};
const base=()=>e.addAsset(e.freshProject(),video,0,id);

test('timeline source mapping uses trimmed source in and a half-open end',()=>{
    const p=base(),v=p.video_track[0];
    Object.assign(v,{timeline_in_seconds:10,source_in_seconds:3,source_out_seconds:8});e.follow(p,v);
    assert.equal(e.sourceTime(v,12),5);assert.equal(e.timelineAt(p,9.99).video,null);
    assert.equal(e.timelineAt(p,10).video.sourceTime,3);assert.equal(e.timelineAt(p,12).audio[0].sourceTime,5);
    assert.equal(e.timelineAt(p,15).video,null);assert.deepEqual(e.timelineAt(p,15).audio,[]);
});
test('silent video does not suppress independent overlapping audio',()=>{
    let p=e.addAsset(e.freshProject(),{...video,probe:{duration_seconds:30,has_audio:false}},0,id);
    p=e.addAsset(p,{asset_id:'mp3',kind:'audio',probe:{duration_seconds:8,has_audio:true}},2,id);
    assert(p.video_track.length);assert.equal(e.timelineAt(p,4).audio.length,1);assert.equal(e.timelineAt(p,4).audio[0].sourceTime,2);
    assert.equal(e.timelineAt(p,10).audio.length,0);
});
test('original sound and independent sound toggle separately; detached sound is independent',()=>{
    let p=e.addAsset(base(),{asset_id:'mp3',kind:'audio',probe:{duration_seconds:30,has_audio:true}},0,id),v=p.video_track[0],a=p.audio_track[1];
    assert.equal(e.timelineAt(p,1).audio.length,2);
    p=e.audioAction(p,v.clip_id,'toggle');assert.deepEqual(e.timelineAt(p,1).audio.map(a=>a.clip.clip_id),[a.clip_id]);
    p=e.audioAction(p,v.clip_id,'toggle');p=e.audioAction(p,a.clip_id,'toggle');assert.equal(e.timelineAt(p,1).audio[0].clip.clip_id,v.audio_link_id);
    p=e.audioAction(p,v.clip_id,'unlink');assert.equal(e.timelineAt(p,1).audio.length,1);
});
test('linked original sound obeys video switch even before normalization and rejects broken links',()=>{
    const p=base(),v=p.video_track[0];v.source_audio_enabled=false;
    assert.equal(p.audio_track[0].enabled,true);assert.equal(e.timelineAt(p,1).audio.length,0);
    v.source_audio_enabled=true;v.audio_link_id='missing';assert.equal(e.timelineAt(p,1).audio.length,0);
});
test('overlapping video uses last painted start/id order independent of selection or array order',()=>{
    const p=base(),v=p.video_track[0];v.clip_id='a';p.video_track.push({...v,clip_id:'z'},{...v,clip_id:'b',timeline_in_seconds:1});
    assert.equal(e.timelineAt(p,.5).video.clip.clip_id,'z');assert.equal(e.timelineAt(p,2).video.clip.clip_id,'b');
    const before=e.clone(p);p.video_track.reverse();assert.equal(e.timelineAt(p,2).video.clip.clip_id,'b');
    assert.deepEqual([...p.video_track].sort(e.compareTimelineClips).map(v=>v.clip_id),['a','z','b']);
    e.timelineAt(before,2);assert.deepEqual(before.video_track.map(v=>v.clip_id),['a','z','b']);
});
test('split boundary activates only the next video and sound; project end ignores H3 window',()=>{
    const p=base(),split=e.split(p,p.video_track[0].clip_id,20,id);
    assert.equal(e.timelineEnd(split),30);assert.equal(e.timelineAt(split,20).video.clip.clip_id,split.video_track[1].clip_id);
    assert.equal(e.timelineAt(split,20).audio.length,1);assert.equal(e.timelineAt(split,20).audio[0].sourceTime,20);
    assert.deepEqual(e.timelineAt(split,30),{video:null,audio:[]});
});
test('removed assets, invalid cuts and source EOF cannot leave an active picture or sound',()=>{
    const p=base();p.video_track[0].source_out_seconds=50;e.follow(p,p.video_track[0]);
    assert.deepEqual(e.timelineAt(p,31),{video:null,audio:[]});
    p.assets=[];assert.deepEqual(e.timelineAt(p,1),{video:null,audio:[]});
    assert.deepEqual(e.timelineAt(e.freshProject(),0),{video:null,audio:[]});
});

test('new video has reciprocal audio and immutable input',()=>{const p=e.freshProject(),out=e.addAsset(p,video,0,id);assert.equal(p.video_track.length,0);assert.equal(out.video_track[0].audio_link_id,out.audio_track[0].clip_id);assert.equal(out.audio_track[0].linked_video_clip_id,out.video_track[0].clip_id);});
test('move bound audio moves entire group',()=>{const p=base(),out=e.move(p,p.audio_track[0].clip_id,7);assert.equal(out.video_track[0].timeline_in_seconds,7);assert.equal(out.audio_track[0].timeline_in_seconds,7);});
test('trim edges honor original bounds and group follows',()=>{const p=base(),out=e.trim(p,p.video_track[0].clip_id,'left',3);assert.equal(out.video_track[0].source_in_seconds,3);assert.equal(out.audio_track[0].source_in_seconds,3);assert.equal(out.video_track[0].timeline_in_seconds,3);const end=e.trim(out,out.video_track[0].clip_id,'right',100);assert.equal(end.video_track[0].source_out_seconds,30);});
test('numeric cuts preserve invalid values for Python validation',()=>{const p=base(),out=e.editCut(p,p.video_track[0].clip_id,{source_out_seconds:50});assert.equal(out.video_track[0].source_out_seconds,50);assert.equal(out.audio_track[0].source_out_seconds,50);});
test('split creates distinct reciprocal groups and correct windows',()=>{const p=base(),out=e.split(p,p.video_track[0].clip_id,12,id);assert.equal(out.video_track.length,2);assert.equal(out.audio_track.length,2);assert.equal(out.video_track[0].source_out_seconds,12);assert.equal(out.video_track[1].source_in_seconds,12);assert.equal(out.video_track[1].source_out_seconds,30);assert.equal(out.audio_track[1].linked_video_clip_id,out.video_track[1].clip_id);assert.equal(out.audio_track[1].timeline_in_seconds,12);assert.equal(new Set([...out.video_track,...out.audio_track].map(c=>c.clip_id)).size,4);});
test('split outside clip is unchanged',()=>{const p=base();assert.deepEqual(e.split(p,p.video_track[0].clip_id,40,id),p);});
test('delete video deletes bound audio only',()=>{const p=base(),out=e.remove(p,p.video_track[0].clip_id);assert.equal(out.video_track.length,0);assert.equal(out.audio_track.length,0);assert.equal(out.assets.length,1);});
test('unlink permits independent move and relink follows original',()=>{const p=base(),v=p.video_track[0].clip_id,a=p.audio_track[0].clip_id;let out=e.audioAction(p,v,'unlink');out=e.move(out,a,15);assert.equal(out.video_track[0].timeline_in_seconds,0);assert.equal(out.audio_track[0].timeline_in_seconds,15);out=e.audioAction(out,a,'relink');assert.equal(out.audio_track[0].timeline_in_seconds,0);assert.equal(out.video_track[0].audio_link_id,a);});
test('toggle audio leaves group stable',()=>{const p=base(),out=e.audioAction(p,p.video_track[0].clip_id,'toggle');assert.equal(out.video_track[0].source_audio_enabled,false);assert.equal(out.audio_track[0].enabled,false);assert.equal(out.audio_track[0].linked_video_clip_id,p.video_track[0].clip_id);});
test('pictures use order only and preserve stable IDs',()=>{let p=e.addAsset(e.freshProject(),picture,80,id);p=e.addAsset(p,picture,0,id);const first=p.picture_track[0].item_id;const out=e.reorderPicture(p,first,1);assert.equal(out.picture_track[1].item_id,first);assert.equal('source_out_seconds' in out.picture_track[0],false);assert.equal('label_map' in out,false);});
test('snap is bounded in screen pixels and can be disabled',()=>{assert.equal(e.snapTime(9.95,[0,10],50),10);assert.equal(e.snapTime(9.7,[0,10],50),9.7);assert.equal(e.snapTime(9.95,[10],50,false),9.95);});
test('playhead points include both H3 edges and clip bounds',()=>{
    const p=base();p.processing_window={start_seconds:5,end_seconds:8,fps:24};const points=e.snapPoints(p);
    for(const t of [5,8,p.video_track[0].timeline_in_seconds])assert.equal(e.snapTime(t+.06,points,100),t);
});
test('H3 drag excludes its own edges but retains clip bounds',()=>{
    const p=base();p.processing_window={start_seconds:5,end_seconds:8,fps:24};const points=e.snapPoints(p,'window');
    assert(!points.includes(5)&&!points.includes(8));assert(points.includes(p.video_track[0].timeline_in_seconds));
});
const window = {start_seconds:2,end_seconds:4,fps:24};
test('both H3 handles snap to the playhead without mutating the window',()=>{
    assert.equal(e.dragWindow(window,-.94,'left',[1],100).start_seconds,1);
    assert.equal(e.dragWindow(window,-.94,'right',[3],100).end_seconds,3);
    assert.deepEqual(window,{start_seconds:2,end_seconds:4,fps:24});
});
test('whole H3 window can snap either edge while preserving its length',()=>{
    assert.deepEqual(e.dragWindow(window,-.94,undefined,[1],100),{start_seconds:1,end_seconds:3,fps:24});
    assert.deepEqual(e.dragWindow(window,1.94,undefined,[6],100),{start_seconds:4,end_seconds:6,fps:24});
});
test('window snaps use actual screen distance at smaller and larger transforms',()=>{
    for(const scale of [.5,1,1.25]) {
        const pps=100*scale;
        assert.equal(e.dragWindow(window,-1+6/pps,'left',[1],pps).start_seconds,1);
        assert.notEqual(e.dragWindow(window,-1+8/pps,'left',[1],pps).start_seconds,1);
    }
});
test('disabled window snapping still quantizes to 24 fps',()=>{
    for(const edge of ['left','right',undefined]) {
        const w=e.dragWindow(window,-.94,edge,[1,3],100,false),at=edge==='right'?w.end_seconds:w.start_seconds;
        assert.equal(at,edge==='right'?73/24:25/24);
    }
});
test('non-frame playhead is resolved to the nearest H3 frame',()=>{
    const w=e.dragWindow(window,-.94,'left',[1.01],100);
    assert.equal(w.start_seconds,1);assert.equal(w.start_seconds*24,Math.round(w.start_seconds*24));
});
test('whole window chooses closest edge target and never makes negative time',()=>{
    const close=e.dragWindow(window,.95,undefined,[3,4.96],100);assert.equal(close.start_seconds,71/24);assert(Math.abs(close.end_seconds-close.start_seconds-2)<1e-12);
    assert.deepEqual(e.dragWindow(window,-5,undefined,[.02],100),{start_seconds:0,end_seconds:2,fps:24});
    assert.equal(e.dragWindow(window,-5,'right',[0],100).end_seconds,0);
});
test('window movement preserves an existing off-grid duration',()=>{
    const w={start_seconds:2,end_seconds:4.01,fps:24},out=e.dragWindow(w,1.94,undefined,[6],100);
    assert(Math.abs((out.end_seconds-out.start_seconds)-(w.end_seconds-w.start_seconds))<1e-12);
    assert.equal(out.start_seconds*24,Math.round(out.start_seconds*24));
});
test('history round trip, branch and bounded size',()=>{const h=new e.History(),p=base(),next=e.move(p,p.video_track[0].clip_id,5);h.record(p);assert.deepEqual(h.undo(next),p);assert.deepEqual(h.redo(p),next);h.undo(next);h.record(p);assert.equal(h.future.length,0);for(let i=0;i<150;i++)h.record(p);assert.equal(h.past.length,100);});
test('frame grid agrees with Python half-up',()=>{assert.equal(e.frame(1/48,24),1);assert.equal(e.frame(15,24),360);assert.equal(e.frame(361/24,24),361);});

test('unload video removes all instances and source audio including detached audio',()=>{
    let p=e.addAsset(base(),video,8,id);p=e.audioAction(p,p.video_track[0].clip_id,'unlink');
    p=e.addAsset(p,{asset_id:'music',kind:'audio',probe:{duration_seconds:10,has_audio:true}},0,id);
    const before=e.clone(p),out=e.unloadAsset(p,'asset');
    assert.equal(out.video_track.length,0);assert.equal(out.audio_track.length,1);assert.equal(out.audio_track[0].asset_id,'music');assert.equal(out.assets.length,1);assert.deepEqual(p,before);
});
test('unload picture removes every reference and can be undone',()=>{
    let p=e.addAsset(base(),picture,0,id);p=e.addAsset(p,picture,0,id);const h=new e.History();h.record(p);
    const out=e.unloadAsset(p,'picture');assert.equal(out.picture_track.length,0);assert.equal(out.video_track.length,1);assert.deepEqual(h.undo(out),p);assert.deepEqual(h.redo(p),out);
});
test('unload unknown asset preserves project',()=>{const p=base();assert.deepEqual(e.unloadAsset(p,'unknown'),p);});
test('waveform samples source interval rather than timeline position',()=>{
    const peaks=[.1,.2,.8,.9];assert.deepEqual(e.sampleClipPeaks(peaks,4,1,3,2),[.2,.8]);assert.deepEqual(e.sampleClipPeaks(peaks,4,0,2,2),[.1,.2]);assert.deepEqual(e.sampleClipPeaks(peaks,4,2,4,2),[.8,.9]);assert.deepEqual(peaks,[.1,.2,.8,.9]);
});
test('waveform aggregation keeps brief peaks and clamps visual sample count',()=>{assert.deepEqual(e.sampleClipPeaks([0,.9,0,0],4,0,4,2),[.9,0]);assert.equal(e.sampleClipPeaks([.5],1,0,1,9000).length,512);});
test('missing peaks or invalid source interval produces a center-line fallback',()=>{for(const args of [[[],1,0,1],[[.2],0,0,1],[[.2],1,1,0],[[.2],1,NaN,1]])assert.deepEqual(e.sampleClipPeaks(...args),[]);});
