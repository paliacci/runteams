import test from 'node:test';
import assert from 'node:assert/strict';
import {createRuntime, operationKey as runtimeKey} from '../runtime/index.js';
import {createViewClient, operationKey, newOperationKey} from '../view/index.js';

const params = () => ({operation:'save', input:{title:'draft'}, objects:[], operation_key:operationKey('save-1')});
const completed = p => ({ok:true,result:{receipt:{state:'completed',operation_key:p.operation_key,result:{data:{title:p.input.title}}}}});
const bridge = fn => ({methods:['operation.invoke','context.read','context.update','draft.set','draft.discard','context.select'],call:fn});
const runtimeHost = () => ({version:'1.0.0',negotiate:() => ({sdk:'1.0.0',capabilities:['data.query','data.mutate']}),
  data:{query:() => ({items:[{id:'quote-1',revision:'3',value:{total:30}}],next_cursor:null}),
    mutate:p => ({state:'confirmed',operation_key:p.operation_key,release_digest:'a'.repeat(64),result:{status:'confirmed',items:[]}})}});

test('runtime negotiates, returns string revisions, and excludes author control', () => {
  const host=runtimeHost(); const calls=[]; const original=host.negotiate;
  host.negotiate=required => {calls.push(required); return original(required);};
  const rt=createRuntime(host);
  assert.equal(rt.data.query({collection:'quote',limit:100}).items[0].revision,'3');
  rt.data.query({collection:'quote',limit:1});
  assert.deepEqual(calls,[['data.query']]);
  assert.equal(rt.source,undefined); assert.equal(rt.operation,undefined); assert.equal(rt.work,undefined);
  assert.equal(Object.isFrozen(rt.data),true);
});
test('runtime rejects invalid JSON/params before host call', () => {
  let called=0;const host=runtimeHost();host.negotiate=()=>{called++;throw Error();};const rt=createRuntime(host);
  for(const p of [{collection:'quote',limit:0},{collection:'quote',limit:101},{collection:'quote',limit:1,extra:true},
    {collection:'quote',limit:1,filter:{price:NaN}},{collection:'quote',limit:1,filter:{price:2n}},
    {collection:'quote',limit:1,filter:{price:Number.MAX_SAFE_INTEGER+1}}]) {
    assert.throws(()=>rt.data.query(p));
  }
  const p={collection:'quote',limit:1};Object.defineProperty(p,'filter',{get(){throw Error('getter executed');},enumerable:true});
  assert.throws(()=>rt.data.query(p),e=>e.code==='sdk_invalid_json'); assert.equal(called,0);
});
test('runtime missing capability and incompatible host fail closed', () => {
  assert.throws(()=>createRuntime({}),e=>e.code==='sdk_runtime_unavailable');
  const host=runtimeHost();host.negotiate=()=>({sdk:'1.0.0',capabilities:[]});
  assert.throws(()=>createRuntime(host).data.query({collection:'quote',limit:1}),e=>e.code==='sdk_capability_unavailable');
});
test('runtime preserves unknown original-key outcomes without retrying', () => {
  const host=runtimeHost();let calls=0;host.data.mutate=()=>{calls++;throw Object.assign(Error('lost'),{code:'future_code',retry:'reconcile'});};
  const input={collection:'quote',mutations:[{id:'q',base_revision:null,value:{total:30}}],operation_key:runtimeKey('work:save')};
  assert.throws(()=>createRuntime(host).data.mutate(input),e=>e.code==='future_code' && e.outcome==='unknown' && e.operationKey==='work:save');
  assert.equal(calls,1);
  host.data.mutate=()=>({state:'confirmed',operation_key:'wrong',release_digest:'a'.repeat(64)});
  assert.throws(()=>createRuntime(host).data.mutate(input),e=>e.code==='sdk_invalid_reply' && e.outcome==='unknown');
});
test('view keys obey current UI contract, including numeric UUIDs', () => {
  assert.throws(()=>operationKey('12345678-1234-1234-1234-123456789abc'));
  assert.throws(()=>operationKey('A'));assert.throws(()=>operationKey('a'.repeat(65)));
  assert.throws(()=>operationKey('save\n'));
  assert.match(newOperationKey(),/^op-[a-f0-9-]+$/);
});
test('view success and error branches are preserved', async () => {
  const v=createViewClient(bridge((_method,p)=>completed(p)));
  assert.equal((await v.operation.invoke(params())).result.receipt.result.data.title,'draft');v.dispose();
  const error={ok:false,error:{code:'future_host_failure',retry:'never'}};
  const failed=createViewClient(bridge(()=>error));assert.deepEqual(await failed.operation.invoke(params()),error);failed.dispose();
});
test('view preflight rejects numeric UUID and mismatched revision before dispatch', async () => {
  let calls=0;const v=createViewClient(bridge(()=>{calls++;}));
  await assert.rejects(v.operation.invoke({...params(),operation_key:'1234'}),e=>e.code==='sdk_invalid_params' && e.outcome==='not-sent');
  await assert.rejects(v.context.select({base_context:0,objects:[{type:'quote',id:'o1',revision:'1'}],focus:null}));
  await assert.rejects(v.context.update({base_context:Number.MAX_SAFE_INTEGER+1,data:{}}));
  assert.equal(calls,0);v.dispose();
});
test('view unique object refs use structural equality, not JSON property order', async () => {
  const v=createViewClient(bridge(()=>{throw Error('should not dispatch');}));
  await assert.rejects(v.context.select({base_context:0,objects:[{type:'q',id:'o',revision:1},{revision:1,id:'o',type:'q'}],focus:null}),e=>e.code==='sdk_invalid_params');v.dispose();
});
test('view copies inputs before asynchronous dispatch completes', async () => {
  let sent;const v=createViewClient(bridge((_m,p)=>{sent=p;return completed(p);}));const p=params();
  const promise=v.operation.invoke(p);p.input.title='changed';assert.equal(sent.input.title,'draft');
  assert.equal((await promise).result.receipt.result.data.title,'draft');v.dispose();
});
test('timeouts and late replies do not retry or resolve canceled writes', async () => {
  let calls=0,answer;const v=createViewClient(bridge(()=>{calls++;return new Promise(resolve=>answer=resolve);}),{timeoutMs:5});
  await assert.rejects(v.operation.invoke(params()),e=>e.code==='sdk_timeout' && e.outcome==='unknown' && e.operationKey==='save-1');
  answer(completed(params()));await Promise.resolve();assert.equal(calls,1);v.dispose();
});
test('dispose and AbortSignal distinguish not-sent from possibly committed', async () => {
  const v=createViewClient(bridge(()=>new Promise(()=>{})));const promise=v.operation.invoke(params());v.dispose();
  await assert.rejects(promise,e=>e.outcome==='unknown');
  await assert.rejects(v.operation.invoke(params()),e=>e.outcome==='not-sent');
  const controller=new AbortController();controller.abort();const closed=createViewClient(bridge(()=>{throw Error();}),{signal:controller.signal});
  await assert.rejects(closed.context.read(),e=>e.code==='sdk_client_closed');
});
test('bad replies after a write retain original key and unknown state', async () => {
  for(const response of [{ok:true,result:{}},{ok:'yes'},completed({...params(),operation_key:'other'}),
    {ok:false,error:{code:'bad',retry:'new-key'}}]) {
    const v=createViewClient(bridge(()=>response));
    await assert.rejects(v.operation.invoke(params()),e=>e.code==='sdk_invalid_reply' && e.outcome==='unknown' && e.operationKey==='save-1');v.dispose();
  }
});
test('unavailable method never dispatches, reauthorization closes binding', async () => {
  const v=createViewClient({methods:[],call:()=>{throw Error('must not call');}});
  await assert.rejects(v.context.read(),e=>e.code==='sdk_capability_unavailable');v.dispose();
  const closed=createViewClient(bridge(()=>({ok:false,error:{code:'forbidden',retry:'reauthorize'}})));
  assert.equal((await closed.context.read()).ok,false);
  await assert.rejects(closed.context.read(),e=>e.code==='sdk_client_closed');
});
test('transport failure is not an empty success and never falls back to fixtures', async () => {
  assert.throws(()=>createViewClient(undefined),e=>e.code==='sdk_host_unavailable');
  const v=createViewClient(bridge(()=>Promise.reject(Error('offline'))));
  await assert.rejects(v.operation.invoke(params()),e=>e.code==='sdk_transport_failed' && e.outcome==='unknown');v.dispose();
});

test('JSON serialization never executes hidden or inherited toJSON', () => {
  const host=runtimeHost();const rt=createRuntime(host);
  const values=[];Object.defineProperty(values,'toJSON',{value:()=>{throw Error('executed');}});
  assert.throws(()=>rt.data.query({collection:'quote',limit:1,filter:{values}}),e=>e.code==='sdk_invalid_json');
  const inherited=Object.getOwnPropertyDescriptor(Array.prototype,'toJSON');
  try {
    Object.defineProperty(Array.prototype,'toJSON',{configurable:true,value:()=>{throw Error('executed');}});
    assert.equal(rt.data.query({collection:'quote',limit:1}).items.length,1);
  } finally {
    if(inherited) Object.defineProperty(Array.prototype,'toJSON',inherited);else delete Array.prototype.toJSON;
  }
});
test('invalid context results and throwing transport metadata settle conservatively', async () => {
  for(const result of [null,[],true,'context']) {
    const v=createViewClient(bridge(()=>({ok:true,result})));
    await assert.rejects(v.context.read(),e=>e.code==='sdk_invalid_reply' && e.outcome==='unavailable');v.dispose();
  }
  const error=Object.defineProperty({},'code',{get(){throw Error('metadata unavailable');}});
  const v=createViewClient(bridge(()=>Promise.reject(error)));
  await assert.rejects(v.operation.invoke(params()),e=>e.code==='sdk_transport_failed' && e.outcome==='unknown');v.dispose();
});
