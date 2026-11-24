import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createLocalClient} from './community_transport_fixture.mjs';
const source=fs.readFileSync(process.env.RUNTEAMS_DOCUMENT_SOURCE||'web/index.html','utf8');
function code(name){const start=new RegExp('^(?:async )?function '+name+'\\(','m').exec(source);assert.ok(start);const tail=source.slice(start.index),next=/^(?:(?:async )?function |(?:let|const|class) )/m.exec(tail.slice(start[0].length));return next?tail.slice(0,start[0].length+next.index):tail;}
function load(name,context){vm.createContext(context);vm.runInContext(code(name),context);return context[name];}

test('a real local library opens documents without a signed-in account and cannot enter an organization',()=>{
 const S={account:{signed_in:false},localLibrary:{library_id:'library'}};const available=load('documentsLocalAvailable',{S,RunTeamsHost:{session:{workspace:s=>s.activeOrganization,ready:s=>s.account.signed_in,actor:()=>''}}});
 assert.equal(available(),true);S.activeOrganization='organization';assert.equal(available(),false);S.activeOrganization='';S.localLibrary=null;assert.equal(available(),false);
 S.account.signed_in=true;S.accountSessionReady=true;assert.equal(available(),true);
});

test('a library trash view reads only its actual document source',()=>{
 const S={localLibrary:{library_id:'library'}};const get=load('trashSources',{S,trashBinding:()=> 'local',documentsLocalAvailable:()=>true});
 assert.deepEqual(Object.keys(get()).sort(),['binding','device']);assert.equal(get().device.loaded,false);
});

function restoreBatch(kinds,{localLibrary={library_id:'library'},readDocuments,restore}={}){
 const calls=[],restored=[],notices=[],keys=new Set(kinds.map((_,index)=>String(index)));
 const context={S:{localLibrary},listBatch:null,listSelection:{keys,scope:'device'},syncListSelection(){},
  trashBinding:()=> 'device',refreshTrash:async()=>calls.push('trash'),
  refreshDocuments:async()=>{calls.push('documents');await readDocuments?.(context.S);},
  refreshDeviceDirectory:async options=>{assert.equal(options.identityOnly,true);calls.push('identities');},
  refreshDeviceWorkDirectory:async()=>calls.push('workflows'),
  RunTeamsEmployeeDirectory:{refreshAfterMutation:async()=>calls.push('employees')},
  RunTeamsSourcePipelines:{refreshCatalog:async()=>calls.push('pipelines')},
  render:()=>calls.push('render'),toast:(_message,_severity,key)=>notices.push(key),
  requestTrashRestore:async(item,kind,scope)=>{assert.equal(scope,'device');restored.push(kind);return restore?restore(item):{};}};
 const entries=kinds.map((kind,index)=>({key:String(index),item:{id:index+1},kind,scope:'device'}));
 load('refreshTrashAfterMutation',context);
 const run=load('runListBatch',context);
 return {calls,restored,notices,keys,run:()=>run('trash','restore',entries,'device')};
}

test('restoring local documents never refreshes employee or pipeline work',async()=>{
 const {calls,restored,keys,run}=restoreBatch(['document','document']);
 await run();assert.deepEqual(calls,['trash','documents','render']);
 assert.deepEqual(restored,['document','document']);assert.equal(keys.size,0);
});

test('signed-in document restores also refresh only documents and trash',async()=>{
 const {calls,run}=restoreBatch(['document'],{localLibrary:null});
 await run();assert.deepEqual(calls,['trash','documents','render']);
});

test('a mixed restore keeps the work and pipeline directory refreshes',async()=>{
 const {calls,restored,run}=restoreBatch(['document','task','pipeline'],{localLibrary:null});
 await run();assert.deepEqual(calls,['trash','employees','workflows','pipelines','render']);
 assert.deepEqual(restored,['document','task','pipeline']);
});

test('a partial document restore keeps the failed selection and the narrow refresh',async()=>{
 const {calls,notices,keys,run}=restoreBatch(['document','document'],{
  restore:item=>item.id===1?{}:{error:'restore rejected'}});
 await run();assert.deepEqual(calls,['trash','documents','render']);
 assert.deepEqual([...keys],['1']);assert.deepEqual(notices,['listSelection.partial']);
});

test('a failed document refresh asks the user to check the list',async()=>{
 const {calls,notices,run}=restoreBatch(['document'],{readDocuments:state=>{state.documentsError='read failed';}});
 await run();assert.deepEqual(calls,['trash','documents','render']);
 assert.deepEqual(notices,['listSelection.partial']);
});

function conversation(save=true){
 const original={richToken:'editor',doc:{id:123}},S={surface:'docs',docReader:original,railMode:'navigation',corePipelines:[]},draws=[],captured=[],frames=[];
 const context={S,captureConversationPanelDraft(){},rememberConversationPanel(){},closePop(){},railConversationPipelineId:()=>null,requestDetailWorkspaceLeave:()=>false,
 flushDocument:async()=>save,workspaceCaptureCurrent:()=>captured.push(S.docReader),teardownDocumentReader:()=>{S.docReader=null;},resetDetailWorkspace(){},
 newRailConversationPanel:()=>({context:{}}),normalizedConversationContext:p=>p.context,hostConversationInRail:()=>{S._pendingRailMode='assistant';},
 conversationNewRoute:()=>'/chats/new',setAppUrl:async()=>{},activeRailMode:()=>S.railMode,render:()=>draws.push({mode:S.railMode,surface:S.surface,reader:S.docReader}),requestAnimationFrame:fn=>frames.push(fn),setTimeout(){},syncRailRoute(){}};
 return {original,S,draws,captured,frames,run:load('newRailChat',context)};
}

test('leaving a document for a new conversation saves and renders the conversation without waiting on animation frames',async()=>{
 const c=conversation();await c.run();assert.equal(c.captured[0],c.original);assert.equal(c.S.docReader,null);assert.equal(c.S.railMode,'assistant');assert.equal(c.draws[0].mode,'assistant');assert.equal(c.draws[0].surface,'team');
});

test('a failed document flush keeps the document selected and does not create a conversation',async()=>{
 const c=conversation(false);await c.run();assert.equal(c.S.docReader,c.original);assert.equal(c.S.railMode,'navigation');assert.deepEqual(c.draws,[]);assert.deepEqual(c.captured,[]);
});

test('a dropped document-action stream recovers effects and links from the saved reply without another submission',async()=>{
 let payload,posts=0;const ids=[{resource:'documents',id:'123',public_id:'local-'+'a'.repeat(32)}],effects=['创建文档「回执」'];
 const client=createLocalClient(async(path,options)=>{
  if(path.endsWith('/stream')){posts++;payload=JSON.parse(options.body);throw Error('lost receipt');}
  return Response.json({device_page_ids:ids,messages:[{id:41,role:'user',metadata:{local_turn_id:payload.operation_id}},{id:42,role:'bot',text:'saved',applied:effects,metadata:{local_turn_id:payload.operation_id}}]});
 });client.libraryId='library';const events=[];await client.stream('/api/chat/123/stream',{message:'write a document'},event=>events.push(event));
 assert.equal(posts,1);assert.deepEqual(events.at(-1).applied,effects);assert.deepEqual(events.at(-1).device_page_ids,ids);
});

test('completed community stream installs document identities before delivering the reply',async()=>{
 const order=[],result={type:'result',device_page_ids:[{resource:'documents',id:'123'}]},app={edition:'community',stream:async(path,body,send)=>send(result)},context={workspaceAccountCacheToken:()=>"local-library",RunTeamsHost:{lifecycle:app},deviceChatRemember:value=>{assert.equal(value,result);order.push('identity');}};context.globalThis=context;
 await load('streamApi',context)('/api/chat/123/stream',{},()=>order.push('reply'));assert.deepEqual(order,['identity','reply']);
});
