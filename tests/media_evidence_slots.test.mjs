import test from 'node:test';
import assert from 'node:assert/strict';
import * as e from '../web/media_evidence_core.mjs';
import * as s from '../web/media_evidence_slots.mjs';

const fixture=()=>({ ...e.freshProject(), assets:[{asset_id:'p',name:'picture.png',kind:'picture',probe:{}},{asset_id:'v',name:'video.mp4',kind:'video',probe:{duration_seconds:20}},{asset_id:'a',name:'audio.wav',kind:'audio',probe:{duration_seconds:20}}],
 picture_track:[{item_id:'p1',asset_id:'p',order:1},{item_id:'p2',asset_id:'p',order:2}],
 video_track:[{clip_id:'v1',asset_id:'v',timeline_in_seconds:0,source_in_seconds:2,source_out_seconds:8,audio_link_id:'linked',source_audio_enabled:true}],
 audio_track:[{clip_id:'linked',asset_id:'v',timeline_in_seconds:0,source_in_seconds:2,source_out_seconds:8,linked_video_clip_id:'v1',source_video_clip_id:'v1',origin:'video_source',enabled:true},{clip_id:'a1',asset_id:'a',timeline_in_seconds:0,source_in_seconds:0,source_out_seconds:6,linked_video_clip_id:null,enabled:true}],
 outlet_slots:{version:1,items:[{slot_id:'ps',kind:'picture',ordinal:9,binding_id:'p1'},{slot_id:'vs',kind:'video',ordinal:3,binding_id:'v1'},{slot_id:'as',kind:'audio',ordinal:2,binding_id:'a1'}]}});

test('old project without slots remains valid and slot IDs are independent of track ordinals',()=>{
 const p=fixture();delete p.outlet_slots;assert.deepEqual(s.slotItems(p),[]);
 const original=fixture(),reordered=e.reorderPicture(original,'p1',1);assert.deepEqual(reordered.outlet_slots,original.outlet_slots);assert.equal(s.slotLabel(reordered.outlet_slots.items[0]),'图片9');
});
for(const [name,change] of [
 ['version',p=>p.outlet_slots.version=true],['duplicate id',p=>p.outlet_slots.items[1].slot_id='ps'],
 ['duplicate ordinal',p=>p.outlet_slots.items.push({...p.outlet_slots.items[0],slot_id:'new'})],['kind array',p=>p.outlet_slots.items[0].kind=['picture']],
 ['extra field',p=>p.outlet_slots.items[0].other=1],['empty binding',p=>p.outlet_slots.items[0].binding_id=''],
 ['bad id',p=>p.outlet_slots.items[0].slot_id='../x'],['fractional ordinal',p=>p.outlet_slots.items[0].ordinal=1.5],
 ['too many',p=>p.outlet_slots.items=Array(257).fill(p.outlet_slots.items[0])],
])test(`strict slot state rejects ${name}`,()=>{const p=fixture();change(p);assert.throws(()=>s.slotItems(p),/槽位/);});
test('send changes only one binding and rejects missing or mismatched explicit targets',()=>{
 const p=fixture(),next=s.assignSlot(p,'ps','p2');assert.equal(p.outlet_slots.items[0].binding_id,'p1');
 const expected=e.clone(p);expected.outlet_slots.items[0].binding_id='p2';assert.deepEqual(next,expected);
 assert.throws(()=>s.assignSlot(p,null,'p2'),/选择/);assert.throws(()=>s.assignSlot(p,'vs','p2'),/类型/);
 assert.throws(()=>s.assignSlot(p,'ps','p'),/入轨/);
});
test('paired original chooses video slot while independent audio chooses audio slot',()=>{
 const p=fixture();assert.equal(s.assignSlot(p,'vs','linked').outlet_slots.items[1].binding_id,'v1');assert.throws(()=>s.assignSlot(p,'as','linked'),/类型/);
 assert.equal(s.assignSlot(p,'as','a1').outlet_slots.items[2].binding_id,'a1');
});
test('delete and unload clear matching assignments but preserve slot identities and other bindings',()=>{
 const p=fixture(),removed=e.remove(p,'p1');assert.equal(removed.outlet_slots.items[0].binding_id,null);assert.equal(removed.outlet_slots.items[1].binding_id,'v1');
 const gone=e.unloadAsset(p,'v');assert.equal(gone.outlet_slots.items[1].binding_id,null);assert.equal(gone.outlet_slots.items.length,3);
 assert.deepEqual(gone.outlet_slots.items.map(({binding_id,...slot})=>slot),p.outlet_slots.items.map(({binding_id,...slot})=>slot));
});
test('slot map send clear deletion undo redo and JSON reload preserve stable definitions',()=>{
 let p=fixture();const history=new e.History(),original=e.clone(p);history.record(p);p=s.clearSlot(p,'ps');assert.equal(p.outlet_slots.items[0].binding_id,null);
 p=history.undo(p);assert.deepEqual(p,original);p=history.redo(p);assert.equal(p.outlet_slots.items[0].binding_id,null);
 history.record(p);p=s.assignSlot(p,'ps','p2');history.record(p);p=e.remove(p,'p2');assert.equal(p.outlet_slots.items[0].binding_id,null);
 p=history.undo(p);assert.equal(p.outlet_slots.items[0].binding_id,'p2');assert.deepEqual(s.slotItems(JSON.parse(JSON.stringify(p))),p.outlet_slots.items);
});
test('new interface definitions retained for desk undo have empty maps without renumbering',()=>{
 const p=fixture(),next=s.retainSlotDefinitions(p,[{slot_id:'later',kind:'picture',ordinal:12,binding_id:'p2'}]);
 assert.deepEqual(next.outlet_slots.items.at(-1),{slot_id:'later',kind:'picture',ordinal:12,binding_id:null});assert.equal(next.outlet_slots.items[0].ordinal,9);
});
