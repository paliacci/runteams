import {installSharedTransport} from './community_transport_fixture.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';

async function subject(){
 const calls=[];let finish;
 globalThis.window=globalThis;
 globalThis.document={documentElement:{hasAttribute:()=>false},body:{setAttribute:(key,value)=>calls.push({freeze:key,value})}};
 globalThis.fetch=async(path,options)=>{
  if(path==='/api/library')return Response.json({storage_kind:'local',library_id:'11111111-1111-4111-8111-111111111111',generation:'original-generation'});
  calls.push({path,options});return new Promise(resolve=>finish=resolve);
 };
 installSharedTransport(globalThis.fetch);
 const module=await import('../../frontend/community/bootstrap.js?close-case='+crypto.randomUUID());
 return {module,calls,wait:async()=>{while(!finish)await new Promise(resolve=>setImmediate(resolve));},finish:value=>finish(value)};
}

test('a Windows appearance change awaits native readback before the window closes',async()=>{
 const events=new EventTarget();let request;
 globalThis.chrome={webview:{addEventListener:events.addEventListener.bind(events),
  removeEventListener:events.removeEventListener.bind(events),postMessage(message){request=message.split(':');}}};
 try{
  await subject();
  const desktop=globalThis.RunTeamsLocalDesktop;
  const save=desktop.saveAppearance('interface_font_size',16);
  assert.equal(desktop.checkClose(),'pending');
  assert.deepEqual(request.slice(2),['set','interface_font_size','16']);
  const reply=value=>events.dispatchEvent(Object.assign(new Event('message'),{data:{
   kind:'desktop-settings',id:request[1],result:{appearance:{interface_font_size:value}}
  }}));
  reply(16);await save;
  assert.equal(desktop.checkClose(),'ready');
  const failed=desktop.saveAppearance('interface_font_size',18);
  reply(16);await assert.rejects(failed);
  assert.equal(desktop.checkClose(),'ready');
 }finally{delete globalThis.chrome;}
});

test('a pending status GET permits native shutdown and cannot start another request after freeze',async()=>{
 const s=await subject(),read=s.module.request('/api/chat/7/employee-mcp?observe=1');await s.wait();
 assert.equal(s.calls[0].options.method,'GET');
 assert.equal(s.calls[0].options.headers['X-RunTeams-Library-Generation'],'original-generation');
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'ready');
 assert.deepEqual(s.calls[1],{freeze:'inert',value:''});
 await assert.rejects(s.module.request('/api/chats'),/窗口正在关闭/);assert.equal(s.calls.length,2);
 s.finish(Response.json({enabled:false}));assert.deepEqual(await read,{enabled:false});
});

test('an in-flight write still blocks native close including explicit discard',async()=>{
 const s=await subject(),save=s.module.request('/api/device/work/source-pipelines/configuration','POST',{action:'save'});await s.wait();
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'pending');
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');
 assert.equal(s.calls.length,1);s.finish(Response.json({revision:2}));await save;
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'ready');
});

test('a live model stream remains protected until its original terminal result',async()=>{
 const s=await subject(),events=[],stream=s.module.stream('/api/chat/7/stream',{message:'Engineering only'},event=>events.push(event));await s.wait();
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');
 s.finish(new Response(JSON.stringify({type:'result',reply:'Explicit stream fixture'})+'\n'));
 await stream;assert.equal(events.length,1);assert.equal(events[0].type,'result');
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'ready');
});

test('background reads never discard an unresolved configuration or an unsaved draft',async()=>{
 const s=await subject(),state={pending:true,dirty:true};
 globalThis.RunTeamsEmployeeConfiguration={closeState:()=>state};
 try{
  const read=s.module.request('/api/model-catalog');await s.wait();
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');
  state.pending=false;assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'dirty');
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'ready');
  s.finish(Response.json({channels:[]}));await read;
 }finally{delete globalThis.RunTeamsEmployeeConfiguration;}
});

test('the native preflight checks platform state without freezing before work-page acknowledgement',async()=>{
 const s=await subject();
 assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready');
 assert.equal(s.calls.length,0);
 assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready');
 assert.equal(s.calls.length,0);
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'ready');
 assert.deepEqual(s.calls,[{freeze:'inert',value:''}]);
});

test('a platform change during author cleanup is rechecked before native close commits',async()=>{
 const s=await subject(),state={pending:false,dirty:false};
 globalThis.RunTeamsEmployeeConfiguration={closeState:()=>state};
 try{
  assert.equal(window.RunTeamsLocalDesktop.checkClose(),'ready');
  state.dirty=true;
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'dirty');
  assert.equal(s.calls.length,0);
  state.pending=true;
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');
  assert.equal(s.calls.length,0);
 }finally{delete globalThis.RunTeamsEmployeeConfiguration;}
});
