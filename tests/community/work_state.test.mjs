import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
const source=fs.readFileSync(new URL('../../web/ui/work-state.js',import.meta.url),'utf8');
function backend(){
 const records=new Map(),receipts=new Map(),calls=[];let drop=false,hold,release;
 const api=async(path,method,body)=>{
  calls.push({path,method,body:structuredClone(body)});
  if(path.endsWith('read'))return {schema:'runteams.work-ui-state-list/1',items:Object.fromEntries(records)};
  if(hold)await new Promise(r=>release=r);
  const prior=receipts.get(body.operation_id);
  if(prior){assert.equal(JSON.stringify(prior.request),JSON.stringify(body));return prior.reply;}
  const row=records.get(body.key)||{revision:0,value:null};
  if(row.revision!==body.expected_revision)return {error:'stale',code:'work_ui_state_conflict'};
  const reply={operation_id:body.operation_id,revision:row.revision+1};records.set(body.key,{revision:reply.revision,value:body.value});receipts.set(body.operation_id,{request:structuredClone(body),reply});
  if(drop){drop=false;throw Error('lost persistence reply');}return reply;
 };
 return {api,records,calls,set drop(v){drop=v;},set hold(v){hold=v;},release:()=>{hold=false;release();}};
}
function subject(server,library='library-one'){
 const c={Map,JSON,Number,String,Promise,Error,Object,queueMicrotask,crypto:crypto.webcrypto,_workspaceBusinessGeneration:1,
  S:{localLibrary:{library_id:library,generation:'first'},account:{signed_in:false}},api:server.api};
 c.window=c;c.workspaceAccountCacheToken=()=>JSON.stringify(c.S.localLibrary);c.workspaceDeviceStorageScope=()=>JSON.stringify(['library',c.S.localLibrary.library_id]);
 Object.defineProperty(c,'localStorage',{get(){throw Error('browser localStorage must not store recovery state');}});
 vm.runInNewContext(source,c);return {c,state:c.RunTeamsWorkState,key:kind=>'runteams.'+kind+':'+c.workspaceDeviceStorageScope()+':same-reference'};
}

test('cold UI process reads original operation without browser storage or another business send',async()=>{
 const b=backend(),first=subject(b);await first.state.connect();const original=crypto.randomUUID();first.state.setItem(first.key('pipeline-admission'),JSON.stringify({operation_id:original}));await first.state.flush();
 const second=subject(b);await second.state.connect();assert.equal(JSON.parse(second.state.getItem(second.key('pipeline-admission'))).operation_id,original);assert.equal(second.state.pending,false);
 assert(b.calls.every(c=>/ui-state-(?:read|save)$/.test(c.path)));
});
test('lost save acknowledgement retries exact persistence UUID and revision before work may proceed',async()=>{
 const b=backend(),s=subject(b);await s.state.connect();b.drop=true;s.state.setItem(s.key('pipeline-control'),JSON.stringify({operation_id:crypto.randomUUID()}));await assert.rejects(s.state.flush(),/lost persistence reply/);assert.equal(s.state.pending,true);
 const first=b.calls.find(c=>c.path.endsWith('save')).body;await s.state.flush();const writes=b.calls.filter(c=>c.path.endsWith('save'));assert.equal(writes.length,2);assert.deepEqual(writes[1].body,first);assert.equal(b.records.values().next().value.revision,1);assert.equal(s.state.pending,false);
});
test('pending queue fences native close and a later clear cannot overtake a saved draft',async()=>{
 const b=backend(),s=subject(b);await s.state.connect();b.hold=true;const key=s.key('pipeline-settings');s.state.setItem(key,JSON.stringify({draft:'original'}));const saving=s.state.flush();await new Promise(r=>setImmediate(r));assert.equal(s.state.pending,true);s.state.removeItem(key);b.release();await saving;assert.equal(b.records.values().next().value.value,null);assert.equal(b.records.values().next().value.revision,2);assert.equal(s.state.pending,false);
});
test('scope change stops queued writes and cannot install a late previous-library read',async()=>{
 const b=backend(),s=subject(b);let release;s.c.api=()=>new Promise(r=>release=r);const old=s.state.connect();s.c.S.localLibrary={library_id:'other-library',generation:'second'};release({schema:'runteams.work-ui-state-list/1',items:{}});await assert.rejects(old,/资料库已改变/);assert.equal(s.state.ready,false);
 s.c.api=b.api;await s.state.connect();assert.throws(()=>s.state.setItem('runteams.pipeline-control:["library","library-one"]:foreign','{}'),/保存位置无效/);
});
test('a new card command waits for a peer to clear its receipt, then claims the current empty revision',async()=>{
 const b=backend(),peer=subject(b),local=subject(b);
 await Promise.all([peer.state.connect(),local.state.connect()]);
 const key=local.key('pipeline-card')+':17';
 peer.state.setItem(key,'{"pending":"first"}');await peer.state.flush();
 local.state.setItem(key,'{"pending":"second"}');await assert.rejects(local.state.flush(),/stale/);
 const record=()=>b.records.get('pipeline-card:same-reference:17');
 assert.equal(record().value,'{"pending":"first"}');
 peer.state.removeItem(key);await peer.state.flush();
 await local.state.flush();
 assert.deepEqual(record(),{revision:3,value:'{"pending":"second"}'});
 assert.equal(local.state.pendingSave,false);
});
test('foreign concurrent revision blocks future business execution without overwriting existing state',async()=>{
 const b=backend(),a=subject(b),other=subject(b);await a.state.connect();await other.state.connect();a.state.setItem(a.key('pipeline-create'),'{}');await a.state.flush();other.state.setItem(other.key('pipeline-create'),'{"draft":"different"}');await assert.rejects(other.state.flush(),/stale/);assert.equal(other.state.pending,true);assert.equal(other.state.saveRejected,true);await assert.rejects(other.state.flush(),/stale/);assert.equal(b.records.values().next().value.value,'{}');
});
