// Real production creator with bounded graph callback faults; no UI or backend mocks claimed native.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createOriginalOutlet} from '../web/media_evidence_outlets.mjs';
const asset={asset_id:'a',kind:'picture',name:'a.png',source_handle:'originals/'+'a'.repeat(32)+'.png'};
function probe(fault='none') {
    const desk={id:1,pos:[0,0],size:[100,100],outputs:[{type:'ZV_MEDIA_PROJECT'},{type:'STRING'},{type:'ZV_ORIGINAL_SOURCES',links:[]}]},old={id:2,type:'Existing',properties:{keep:true}},foreign={id:22,type:'Foreign'},foreignGraph={nodes:[foreign]};
    const nodes=new Map([[1,desk],[2,old]]),links=[{id:90,origin_id:1,target_id:2}],removed=[];let seq=2,after=0,before=0,remove=0;
    const graph={getNodeById:id=>nodes.get(id),getLink:id=>links.find(l=>l.id===id),findNodesByType:type=>[...nodes.values()].filter(n=>n.type===type),
        add(n){n.id=++seq;n.graph=this;nodes.set(n.id,n);n.onAdded?.(this);if(fault.startsWith('pointer')){n.graph=null;if(fault.includes('id'))n.id=old.id;throw Error('add callback detached graph pointer');}if(fault.startsWith('remove'))throw Error('add failed after registration');return n;},
        remove(n){remove++;assert.equal(nodes.get(n.id),n);assert.equal(n.graph,this);assert.notEqual(n,old);if(fault==='remove_persistent'||fault==='connect_remove_persistent'||fault==='remove_once'&&remove===1)throw Error('remove blocked');if(!fault.startsWith('edge_'))for(let i=links.length-1;i>=0;i--)if(links[i].target_id===n.id){desk.outputs[2].links=desk.outputs[2].links.filter(id=>id!==links[i].id);links.splice(i,1);}nodes.delete(n.id);removed.push(n);n.graph=null;},
        removeLink(id){this.edgeCalls=(this.edgeCalls||0)+1;if(fault==='edge_persistent'||fault==='edge_once'&&this.edgeCalls===1)throw Error('removeLink blocked');const index=links.findIndex(l=>l.id===id);if(index>=0)links.splice(index,1);},
        beforeChange(){before++;if(fault.endsWith('before_failure')&&before===2)throw Error('second beforeChange failed');},afterChange(){after++;if(fault.startsWith('after_persistent')||fault.startsWith('after_once')&&after===1)throw Error('afterChange failed');},setDirtyCanvas(){}};
    desk.graph=graph;
    desk.connect=(slot,n,index)=>{assert.equal(slot,2);if(fault==='connect_null')return null;if(fault==='connect_throw')throw Error('connect failed');const link={id:100,origin_id:desk.id,origin_slot:slot,target_id:n.id,target_slot:index,type:'ZV_ORIGINAL_SOURCES'};links.push(link);desk.outputs[2].links.push(link.id);n.inputs[index].link=link.id;if(fault==='connect_after_throw'||fault==='connect_remove_persistent'||fault.startsWith('edge_'))throw Error('connect failed after link registration');return link;};
    globalThis.LiteGraph={createNode:type=>({type,id:-1,widgets:[{name:'source_handle',value:''},{name:'asset_id',value:''}],inputs:[{name:'original_sources',type:'ZV_ORIGINAL_SOURCES',link:null}],outputs:['IMAGE','STRING','STRING','STRING'].map(type=>({type})),setSize(){},computeSize(){return [300,100];}})};
    let result,error;try{result=createOriginalOutlet(desk,asset,{canvas:{graph}});}catch(e){error=e.message;}
    assert.equal(nodes.get(2),old);assert.deepEqual(old.properties,{keep:true});assert.deepEqual(links.filter(l=>l.id===90),[{id:90,origin_id:1,target_id:2}]);assert.deepEqual(foreignGraph.nodes,[foreign]);
    return {result,error,added:nodes.size-2,before,after,remove,nodes,graph,desk,removed};
}
test('normal creation and exact current-file reuse preserve old graph',()=>{
    const p=probe();assert.equal(p.result.created,1);assert.equal(p.added,1);assert.equal(p.before,p.after);
    assert.equal(createOriginalOutlet(p.desk,asset,{canvas:{graph:p.graph}}).created,0);assert.equal(p.nodes.size,3);
});
for(const fault of ['after_once','after_persistent','pointer','pointer_id','remove_once','connect_null','connect_throw','connect_after_throw'])test(`${fault}: only registered owned node is removed`,()=>{
    const p=probe(fault);assert(p.error);assert.equal(p.added,0);assert.equal(p.removed.length,1);assert(!p.error.includes('回滚不完整'));assert.equal(p.before,p.after);
});
test('persistent removal after real source-link registration reports incomplete rollback',()=>{
    const p=probe('connect_remove_persistent');assert.equal(p.added,1);assert.equal(p.remove,2);assert.match(p.error,/回滚不完整/);assert(!p.error.includes('已撤回'));assert.equal(p.graph.getLink(100).target_id,p.result?.node_id||3);
});
test('removeLink transient failure retries after the owned node is already gone',()=>{
    const p=probe('edge_once');assert.equal(p.added,0);assert.equal(p.graph.edgeCalls,2);assert.equal(p.graph.getLink(100),undefined);assert.deepEqual(p.desk.outputs[2].links,[]);assert(!p.error.includes('回滚不完整'));
});
test('persistent edge-only failure truthfully reports the remaining source link',()=>{
    const p=probe('edge_persistent');assert.equal(p.added,0);assert.equal(p.graph.edgeCalls,2);assert(p.graph.getLink(100));assert.match(p.error,/新增节点或来源线仍登记/);assert(!p.error.includes('已撤回'));
});
test('persistent remove failure explicitly reports incomplete rollback',()=>{
    const p=probe('remove_persistent');assert.equal(p.added,1);assert.equal(p.remove,2);assert.match(p.error,/回滚不完整/);assert(!p.error.includes('已撤回'));assert.equal(p.before,p.after);
});
for(const fault of ['after_once_before_failure','after_persistent_before_failure'])test(`${fault}: compensation startup cannot bypass owned cleanup`,()=>{
    const p=probe(fault);assert.equal(p.added,0);assert.equal(p.removed.length,1);
    assert.match(p.error,/afterChange failed/);assert.match(p.error,/second beforeChange failed/);assert.match(p.error,/无法确认事务闭合/);assert(!p.error.includes('回滚不完整'));
});
