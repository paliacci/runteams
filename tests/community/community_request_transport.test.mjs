import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {installSharedTransport} from './community_transport_fixture.mjs';

const library='11111111-1111-4111-8111-111111111111';
function clock() {
  let sequence=0;
  const pending=new Map();
  return {pending,setTimeout(fn,ms){const id=++sequence;pending.set(id,{fn,ms});return id;},
    clearTimeout(id){pending.delete(id);},
    fire(ms){const rows=[...pending].filter(([,row])=>row.ms===ms);assert.equal(rows.length,1);for(const [id,row] of rows){pending.delete(id);row.fn();}}};
}
const tick=()=>new Promise(setImmediate);
async function subject(fetcher,timers) {
  globalThis.window=globalThis;
  globalThis.document={documentElement:{hasAttribute:()=>false},body:{setAttribute(){}}};
  globalThis.fetch=fetcher;
  installSharedTransport(fetcher,timers);
  return import('../../frontend/community/bootstrap.js?bounded-case='+crypto.randomUUID());
}

test('a stalled work UI read uses the original thirty-second read deadline and releases quit',async()=>{
  const timers=clock();let stalled;
  const module=await subject(async(path,options)=>{
    if(path==='/api/library')return Response.json({storage_kind:'local',library_id:library,generation:'original'});
    assert.equal(path,'/api/device/work/source-pipelines/ui-state-read');
    stalled=options;
    return new Promise((resolve,reject)=>options.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));
  },timers);
  const reading=module.request('/api/device/work/source-pipelines/ui-state-read','POST',{});
  reading.catch(()=>{});
  while(!stalled)await tick();
  assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready','a read-only POST must never masquerade as an unfinished save');
  assert.equal([...timers.pending.values()].filter(row=>row.ms===30000).length,1,'free reads must use the shipped shared deadline');
  assert.equal(stalled.headers['X-RunTeams-Library'],library);
  timers.fire(30000);
  await assert.rejects(reading,error=>error.code==='read_timeout');
  assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready');
  assert.equal(RunTeamsRequests.metrics().at(-1).attempts,1);
});

test('a stalled save keeps its operation and blocks quit until explicit original receipt reconciliation',async()=>{
  const timers=clock(),posts=[];let stall=true,revision=0,receipt;
  const module=await subject(async(path,options)=>{
    if(path==='/api/library')return Response.json({storage_kind:'local',library_id:library,generation:'original'});
    assert.equal(path,'/api/settings');
    if(options.method!=='POST')return Response.json({library_id:library,revision,settings:{}});
    const original=JSON.parse(options.body);posts.push(original);
    receipt??={ok:true,library_id:library,operation_id:original.operation_id,revision:++revision,settings:{sound:false}};
    if(stall)return new Promise((resolve,reject)=>options.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));
    return Response.json(receipt);
  },timers);
  await module.readSettings();
  const saving=module.saveSettings({sound:false});saving.catch(()=>{});
  while(!posts.length)await tick();
  assert.equal(window.RunTeamsLocalDesktop.checkClose(true),'pending');
  assert.equal([...timers.pending.values()].filter(row=>row.ms===120000).length,1,'free writes must use the shipped shared deadline');
  timers.fire(120000);
  await assert.rejects(saving,error=>error.code==='mutation_outcome_unknown');
  assert.equal(posts.length,1,'a timeout must never resubmit a write');
  assert.equal(window.RunTeamsLocalDesktop.checkClose(true),'pending');
  await assert.rejects(module.saveSettings({sound:true}),error=>error.code==='mutation_outcome_unknown');
  stall=false;
  const confirmed=await module.readSettings();
  assert.deepEqual(posts[0],posts[1]);
  assert.equal(confirmed.revision,1);
  assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready');
});

test('settings persistence does not cancel the current directory read',async()=>{
  let finish,reads=0;
  const module=await subject(async(path,options)=>{
    if(path==='/api/library')return Response.json({storage_kind:'local',library_id:library,generation:'original'});
    if(path==='/api/chats?device=1'){reads++;return new Promise(resolve=>finish=()=>resolve(Response.json({items:[]})));}
    const body=JSON.parse(options.body);
    return Response.json({ok:true,library_id:library,operation_id:body.operation_id,revision:body.expected_revision+1,settings:body.patch});
  },globalThis);
  const read=module.request('/api/chats?device=1');
  while(!finish)await tick();
  await module.saveSettings({sound:false});finish();
  assert.deepEqual(await read,{items:[]});assert.equal(reads,1);
});

test('shared read groups cancel the older request without changing library authority',async()=>{
  const requests=[];
  const module=await subject(async(path,options)=>{
    if(path==='/api/library')return Response.json({storage_kind:'local',library_id:library,generation:'original'});
    requests.push({path,options});
    if(path.includes('old'))return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));
    return Response.json({items:['current']});
  },globalThis);
  const old=module.request('/api/chats?query=old','GET',undefined,{readGroup:'directory',readSequence:1});old.catch(()=>{});
  while(!requests.length)await tick();
  const current=await module.request('/api/chats?query=current','GET',undefined,{readGroup:'directory',readSequence:2,device:false,headers:{'X-RunTeams-Library':'forged'}});
  await assert.rejects(old,error=>error.code==='request_superseded');
  assert.deepEqual(current,{items:['current']});assert.equal(requests.length,2);
  assert.equal(requests[1].options.headers['X-RunTeams-Library'],library);
  assert.equal(requests[1].options.headers['X-RunTeams-Library-Generation'],'original');
});

test('the original POST pipeline catalog cannot invalidate parallel model discovery at free boot',async()=>{
  let finishModels,channelsError;
  const module=await subject(async(path)=>{
    if(path==='/api/library')return Response.json({storage_kind:'local',library_id:library,generation:'original'});
    if(path==='/api/model-catalog')return new Promise(resolve=>finishModels=()=>resolve(Response.json({channels:[]})));
    if(path==='/api/device/work/source-pipelines/catalog')return Response.json({items:[],errors:[]});
    return Response.json({library_id:library,revision:0,settings:{}});
  },globalThis);
  const models=module.request('/api/model-catalog').catch(error=>{channelsError=error.code;});
  while(!finishModels)await tick();
  await module.request('/api/device/work/source-pipelines/catalog','POST',{});
  finishModels();await models;
  assert.equal(channelsError,undefined);
  assert.equal(RunTeamsRequests.metrics().find(row=>row.path.endsWith('/catalog')).attempts,1);
});

test('the real work UI separates initial reads from retained unknown save receipts at native quit',async()=>{
  const timers=clock(),posts=[];let finishRead,stall=true;
  const module=await subject(async(path,options)=>{
    if(path==='/api/library')return Response.json({storage_kind:'local',library_id:library,generation:'original'});
    if(path.endsWith('ui-state-read'))return new Promise(resolve=>finishRead=()=>resolve(Response.json({schema:'runteams.work-ui-state-list/1',items:{}})));
    assert.ok(path.endsWith('ui-state-save'));
    const body=JSON.parse(options.body);posts.push(body);
    if(stall)return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));
    return Response.json({operation_id:body.operation_id,revision:body.expected_revision+1});
  },timers);
  const context={Map,JSON,Number,Object,Promise,Error,crypto,queueMicrotask,
    _workspaceBusinessGeneration:1,S:{localLibrary:{library_id:library}},api:(...args)=>module.request(...args)};
  context.window=context;
  context.workspaceAccountCacheToken=()=>library;
  context.workspaceDeviceStorageScope=()=>JSON.stringify(['library',library]);
  vm.runInNewContext(fs.readFileSync(new URL('../../web/ui/work-state.js',import.meta.url),'utf8'),context);
  const state=context.RunTeamsWorkState;globalThis.RunTeamsWorkState=state;
  try{
    const reading=state.connect();while(!finishRead)await tick();
    assert.equal(state.pending,true);assert.equal(state.pendingSave,false);
    assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready');
    finishRead();await reading;
    state.setItem('runteams.pipeline-control:'+context.workspaceDeviceStorageScope()+':fixture',JSON.stringify({operation_id:'original-business-operation'}));
    const saving=state.flush();saving.catch(()=>{});while(!posts.length)await tick();
    assert.equal(state.pendingSave,true);assert.equal(window.RunTeamsLocalDesktop.checkClose(true),'pending');
    timers.fire(120000);await assert.rejects(saving,error=>error.code==='mutation_outcome_unknown');
    assert.equal(state.pendingSave,true);assert.equal(state.saveRejected,false);
    assert.equal(window.RunTeamsLocalDesktop.checkClose(true),'pending');assert.equal(posts.length,1);
    stall=false;await state.flush();assert.deepEqual(posts[0],posts[1]);
    assert.equal(state.pendingSave,false);assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready');
  }finally{delete globalThis.RunTeamsWorkState;}
});

test('a requested backup is protected while its original work UI prerequisite is still reading',async()=>{
  let release,posts=0;
  const module=await subject(async(path)=>{
    if(path==='/api/library')return Response.json({storage_kind:'local',library_id:library,generation:'original'});
    assert.equal(path,'/api/backups');posts++;return Response.json({state:'completed'});
  },globalThis);
  globalThis.RunTeamsWorkState={pending:true,pendingSave:false,flush:()=>new Promise(resolve=>release=()=>{globalThis.RunTeamsWorkState.pending=false;resolve();})};
  try{
    const backup=module.request('/api/backups','POST',{});while(!release)await tick();
    assert.equal(posts,0);assert.equal(window.RunTeamsLocalDesktop.checkClose(true),'pending');
    release();assert.deepEqual(await backup,{state:'completed'});assert.equal(posts,1);
    assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready');
  }finally{delete globalThis.RunTeamsWorkState;}
});
