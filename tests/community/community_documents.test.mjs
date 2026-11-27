import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createLocalClient} from './community_transport_fixture.mjs';
const source=fs.readFileSync(process.env.RUNTEAMS_DOCUMENT_SOURCE||'web/index.html','utf8');
test('restoring a pipeline task from Trash uses its original team and stage visit',async()=>{
 const item={id:41,pipeline_visit:3,pipeline_reference:{library_id:'local',source_id:'worker'}};
 const receipt={status:'committed'};
 const restore=vm.runInNewContext('('+code('requestTrashRestore')+')',{
  RunTeamsSourcePipelines:{restoreCard:entry=>{assert.equal(entry,item);return receipt;}}
 });
 assert.equal(await restore(item,'task','device'),receipt);
});
function code(name){const start=new RegExp('^(?:async )?function '+name+'\\(','m').exec(source);assert.ok(start);const tail=source.slice(start.index),next=/^(?:(?:async )?function |(?:let|const|class) )/m.exec(tail.slice(start[0].length));return next?tail.slice(0,start[0].length+next.index):tail;}
function load(name,context){vm.createContext(context);vm.runInContext(code(name),context);return context[name];}

test('moving root search results uses each selected document’s folder',async()=>{
 const writes=[],context={S:{docsFolder:'',docsQuery:'notes',surface:'docs'},docsMove:null,documentsReadKey:()=>'search',
  render(){},toast(){},docsFinishMove(){},document:{querySelector:()=>null},docsFolders:()=>[{id:'subfolder'}],
  docsFolderMutation:async data=>writes.push(JSON.parse(JSON.stringify(data)))};
 for(const name of ['activeDocsMove','docsStartMove','docsMoveTargets','docsCanConfirmMove','docsConfirmMove'])load(name,context);
 const select=items=>context.docsStartMove(items.map(item=>({item})),'search');
 const root={id:1,folder_id:null},nested={id:2,folder_id:'subfolder'};
 select([root,nested]);assert.equal(context.docsCanConfirmMove(context.docsMove),true);
 await context.docsConfirmMove();assert.deepEqual(writes,[{action:'move_documents',documents:[2],folder:''}]);
 select([root]);assert.equal(context.docsCanConfirmMove(context.docsMove),false);
 select([nested]);context.docsMove.folder='subfolder';assert.equal(context.docsCanConfirmMove(context.docsMove),false);
 select([root,nested]);context.docsMove.folder='subfolder';await context.docsConfirmMove();
 assert.deepEqual(writes[1],{action:'move_documents',documents:[1],folder:'subfolder'});
});

test('reader back preserves a rejected draft until the user confirms leaving its reader',async()=>{
 const reader={doc:{id:7},text:'draft'},S={docReader:reader};
 let keep,leave,opened=0,saves=0,closed=0;
 const context={S,_documentResolveSequence:0,_documentOpenSequence:0,_documentTableAutosaveTimer:null,
  async flushDocument(){saves++;return false;},
  documentLeaveDialog(_saving,onKeep,onLeave){keep=onKeep;leave=onLeave;},closeModal(){closed++;},
  clearTimeout,flushDocumentTableAutosave(){assert.fail('discard must not submit another edit');},
  currentRailRouteValue(){},docsFolderRoute(){},routeWithRailState(){},setAppUrl(){},openDocs(){opened++;}};
 load('teardownDocumentReader',context);
 const back=load('closeDocumentReader',context);
 await back();keep();
 assert.equal(S.docReader,reader);assert.equal(reader.text,'draft');assert.equal(opened,0);
 await back();S.docReader={doc:{id:8}};await leave();
 assert.equal(S.docReader.doc.id,8);assert.equal(opened,0);
 S.docReader=reader;await back();await leave();
 assert.equal(S.docReader,null);assert.equal(opened,1);assert.equal(saves,3);assert.equal(closed,3);
});

test('fresh local revision IDs open through the owning library before route IDs are refreshed',async()=>{
 const doc={id:51,storage_scope:'device',is_current_revision:false};
 const S={localLibrary:{library_id:'library'},docReader:{doc,revisionId:51}};
 const calls=[];
 const context={S,_documentOpenSequence:1,deviceWorkPath:path=>path,docKind:()=>'rich-document',
  docEditable:()=>false,documentReaderRenderContent(){},loadDocumentRevisions(){},
  async api(path){calls.push(path);return {...doc,content:'earlier revision'};},
  async fetch(){throw Error('Expected the local session transport');}};
 load('documentReaderUsesDevice',context);
 await load('loadDocumentReader',context)(doc);
 assert.deepEqual(calls,['/api/device/work/documents/51?historical=1']);
 assert.equal(S.docReader.status,'ready');
 assert.equal(S.docReader.text,'earlier revision');
 assert.equal(S.docReader.editing,false);
});

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
  refreshChatDirectory:async options=>{assert.equal(options.afterMutation,true);calls.push('chats');},
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

test('Trash keeps cached rows readable and restricts actions only for sources that failed to refresh',async()=>{
 const source={items:[]},sources={binding:'local',device:source},S={trashSources:sources};
 const document={id:9,kind:'document'},pipeline={id:9,kind:'pipeline',reference:{source_id:'team'}};
 let fail='';
 const read=(kind,item)=>{if(fail===kind)throw Error('offline');return {items:[item]};};
 const context={S,trashSources:()=>sources,trashBinding:()=>'local',_trashRefreshSequence:0,_trashNextAt:0,
  TRASH_SYNC_INTERVAL_MS:1000,deviceChatRemember(){},api:async()=>read('work',document),
  RunTeamsSourcePipelines:{request:async()=>read('team',pipeline)}};
 for(const name of ['trashItemsSignature','canRestoreTrashSelection','canDeleteTrashSelection','listSelectionActions','refreshTrash'])load(name,context);
 const disabled=(items,action)=>context.listSelectionActions('trash',items.map(item=>({scope:'device',kind:item.kind,item}))).find(([key])=>key===action)[3];
 await context.refreshTrash();
 const confirmed=context.trashItemsSignature(S.trashItems);
 for(fail of ['work','team','']){
  await context.refreshTrash();
  const doc=S.trashItems.find(item=>item.kind==='document'),team=S.trashItems.find(item=>item.kind==='pipeline');
  assert.equal(disabled([doc],'restore'),fail==='work');
  assert.equal(disabled([doc],'delete'),fail==='work');
  assert.equal(disabled([team],'restore'),fail==='team');
  assert.equal(disabled([doc,team],'restore'),!!fail);
  assert.equal(context.trashItemsSignature(S.trashItems)===confirmed,!fail);
 }
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

test('restoring a local team refreshes its standalone discussions',async()=>{
 const {calls,run}=restoreBatch(['pipeline']);
 await run();assert.deepEqual(calls,['trash','employees','identities','pipelines','chats','render']);
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
