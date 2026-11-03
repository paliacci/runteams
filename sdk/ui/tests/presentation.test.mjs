import test from 'node:test';
import assert from 'node:assert/strict';
import {createPresentationClient, PresentationError} from '../presentation.js';
const adapter = transition => ({version:'0.1.0',transition});

test('acknowledged transitions notify; identical requests do not duplicate effects',async()=>{
  const calls=[],events=[];
  const client=createPresentationClient(adapter(target=>{calls.push(target);return {...target};}));
  const remove=client.subscribe(state=>events.push(state));
  assert.equal(client.getSnapshot().mode,'panel');
  await client.openFull('module-a');await client.openFull('module-a');
  assert.equal(calls.length,1);
  await assert.rejects(client.openFull('module-b'),{code:'return-required'});
  await client.returnToPanel();
  assert.deepEqual(client.getSnapshot(),{mode:'panel',viewId:null,pending:false,error:null});
  assert.equal(events.length,4);assert.ok(events.every(Object.isFrozen));remove();client.dispose();
});
test('failed and mismatched acknowledgement retain last confirmed mode',async()=>{
  let strategy='success';
  const client=createPresentationClient(adapter(target=>{
    if(strategy==='failure')throw new Error('host failure');
    return strategy==='wrong'?{mode:'panel',viewId:'wrong'}:target;
  }));
  await client.openFull('one');strategy='failure';
  await assert.rejects(client.returnToPanel(),{code:'unavailable'});
  assert.equal(client.getSnapshot().mode,'full');
  strategy='wrong';await assert.rejects(client.returnToPanel(),{code:'invalid-acknowledgement'});
  assert.equal(client.getSnapshot().viewId,'one');client.dispose();
});
test('pending duplicate rejected; disposal aborts and ignores late completion',async()=>{
  let finish,signal;const events=[];
  const client=createPresentationClient(adapter((target,options)=>{signal=options.signal;return new Promise(resolve=>finish=()=>resolve(target));}));
  client.subscribe(s=>events.push(s));
  const task=client.openFull('one');await Promise.resolve();
  await assert.rejects(client.openFull('one'),{code:'busy'});
  client.dispose();await assert.rejects(task,{code:'disposed'});assert.ok(signal.aborted);
  finish();await Promise.resolve();assert.equal(events.length,1);
  await assert.rejects(client.returnToPanel(),{code:'disposed'});
});
test('timeout has no false success and late reply cannot replace retry result',async()=>{
  let finish,signal;let count=0;
  const client=createPresentationClient(adapter((target,options)=>{
    count++;if(count===1){signal=options.signal;return new Promise(resolve=>finish=()=>resolve(target));}return target;
  }),{timeoutMs:10});
  await assert.rejects(client.openFull('old'),{code:'timeout'});assert.ok(signal.aborted);
  assert.equal(client.getSnapshot().mode,'panel');
  await client.openFull('new');finish();await Promise.resolve();
  assert.equal(client.getSnapshot().viewId,'new');client.dispose();
});
test('input validation prevents dispatch and listener errors do not corrupt state',async()=>{
  let calls=0;const client=createPresentationClient(adapter(target=>{calls++;return target;}));
  await assert.rejects(client.openFull('../escape'),{code:'invalid-view-id'});assert.equal(calls,0);
  client.subscribe(()=>{throw new Error('render bug');});
  await client.openFull('valid');assert.equal(client.getSnapshot().mode,'full');
  assert.throws(()=>createPresentationClient({version:'9',transition(){}}),PresentationError);
  assert.throws(()=>createPresentationClient(adapter(()=>{}),{timeoutMs:0}),{code:'invalid-timeout'});client.dispose();
});
