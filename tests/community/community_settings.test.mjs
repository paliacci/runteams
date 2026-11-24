import {installSharedTransport} from './community_transport_fixture.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';

async function subject(){
 const state={library:'11111111-1111-4111-8111-111111111111',revision:0,settings:{},receipts:new Map(),drop:false,malformed:false,posts:[],backupPosts:[]};
 globalThis.window=globalThis;globalThis.document={getElementById:()=>null,querySelector:()=>null};
 globalThis.fetch=async(path,options={})=>{
  if(path==='/')return new Response('<html></html>');
  if(path==='/api/app-info')return Response.json({native_attachment_picker:false});
  if(path==='/api/library')return Response.json({storage_kind:'local',generation:'test-generation',library_id:state.library});
  if(path==='/api/settings'&&options.method==='POST'){
   const body=JSON.parse(options.body);state.posts.push(body);
   let receipt=state.receipts.get(body.operation_id);
   if(!receipt){
    assert.equal(body.expected_revision,state.revision);
    state.settings={...state.settings,...body.patch};state.revision++;
    receipt={ok:true,library_id:state.library,revision:state.revision,operation_id:body.operation_id,settings:state.settings};state.receipts.set(body.operation_id,receipt);
   }
   if(state.drop){state.drop=false;throw Error('lost response');}
   return Response.json(state.malformed?{...receipt,operation_id:'wrong'}:receipt);
  }
  if(path.startsWith('/api/backups')){state.backupPosts.push(path);return Response.json({state:'completed'});}
  if(path==='/api/settings')return Response.json({library_id:state.library,revision:state.revision,settings:state.settings});
  throw Error('unexpected '+path);
 };
 installSharedTransport(globalThis.fetch);
 const module=await import('../../frontend/community/bootstrap.js?case='+crypto.randomUUID());
 return {module,state};
}

test('lost settings confirmation replays original operation before a read',async()=>{
 const {module,state}=await subject();await module.readSettings();state.drop=true;
 const requested={allow_supplement:false};
 await assert.rejects(module.saveSettings(requested),error=>error.code==='mutation_outcome_unknown');requested.allow_supplement=true;
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');
 await assert.rejects(module.saveSettings({sound:false}),error=>error.code==='mutation_outcome_unknown');
 const confirmed=await module.readSettings();
 assert.deepEqual(state.posts[0],state.posts[1]);assert.equal(state.receipts.size,1);assert.equal(confirmed.revision,1);assert.equal(confirmed.settings.allow_supplement,false);
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'ready');
});

test('malformed confirmation cannot clear the original save or allow close',async()=>{
 const {module,state}=await subject();await module.readSettings();state.malformed=true;
 await assert.rejects(module.saveSettings({sound:false}),error=>error.code==='mutation_outcome_unknown');
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');state.malformed=false;
 const confirmed=await module.readSettings();assert.equal(confirmed.revision,1);assert.equal(state.receipts.size,1);
});

test('native close captures the shared editor before deciding a cleared draft is dirty',async()=>{
 const {module}=await subject();globalThis.location={href:'http://localhost/'};
 const state={conversationPanelDrafts:{}};let captures=0;
 await module.boot({state,render(){},restoreWorkspace(){},restoreDraft(){},loadEmployees:async()=>{},loadPipelines:async()=>{},newConversation:()=>({input:'stale draft'}),loadModels:async()=>({catalog:{channels:[]}}),loadChats:async()=>{},normalize(){},route:()=>({kind:'home'}),restoreSettings(){},captureDraft(){captures++;state.conversationPanel.input='';}});
 assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'ready');assert.equal(captures,1);
});


test('free cold boot restores original windows after library identity and reads pipelines before deep route',async()=>{
 const {module,state}=await subject();globalThis.location={href:'http://localhost/pipelines/local/fixture/entry'};
 const events=[],S={account:{signed_in:false}};let finish;
 const running=module.boot({state:S,render(){},newConversation:()=>({input:''}),restoreDraft(){},
  restoreWorkspace(){assert.equal(S.localLibrary.library_id,state.library);assert.equal(S.account.signed_in,false);events.push('restore');S.workspaceWindows=['original-window'];},
  loadEmployees:async()=>{assert.equal(S.localLibrary.library_id,state.library);events.push('employees');},
  loadPipelines:()=>new Promise(resolve=>{assert.equal(S.localLibrary.library_id,state.library);events.push('pipelines');finish=resolve;}),
  loadModels:async()=>({catalog:{channels:[]}}),loadChats:async()=>{},normalize(){},route:()=>({kind:'source-pipeline'}),
  openRoute:async()=>{assert.deepEqual(S.workspaceWindows,['original-window']);events.push('route');},restoreSettings(){events.push('settings');},captureDraft(){}});
 while(!finish)await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(events,['restore','employees','pipelines']);assert.equal(S.account.signed_in,false);finish();await running;
 assert.deepEqual(events,['restore','employees','pipelines','route','settings']);assert.equal(S.localLibrary.storage_kind,'local');
});

test('backup waits for original work breadcrumb acknowledgement; rejected flush sends no backup',async()=>{
 const {module,state}=await subject();const events=[];let release;
 globalThis.RunTeamsWorkState={pending:true,pendingSave:true,flush:()=>new Promise(resolve=>release=()=>{events.push('saved');globalThis.RunTeamsWorkState.pending=false;globalThis.RunTeamsWorkState.pendingSave=false;resolve();})};
 try{
  const saving=module.request('/api/backups','POST',{});while(!release)await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(events,[]);
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');release();await saving;assert.deepEqual(events,['saved']);assert.deepEqual(state.backupPosts,['/api/backups']);
  globalThis.RunTeamsWorkState={pending:true,flush:async()=>{throw Error('save failed');}};
  await assert.rejects(module.request('/api/backups/restore','POST',{}),/save failed/);assert.deepEqual(events,['saved']);assert.deepEqual(state.backupPosts,['/api/backups']);
 }finally{delete globalThis.RunTeamsWorkState;}
});
test('native close distinguishes an unresolved save from a confirmed rejected unsaved draft',async()=>{
 await subject();globalThis.RunTeamsWorkState={pending:true,pendingSave:true,saveRejected:false};
 try{
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');
  globalThis.RunTeamsWorkState.saveRejected=true;
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'dirty');
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'ready');
 }finally{delete globalThis.RunTeamsWorkState;}
});

test('native close includes shared configuration draft and unresolved resource or save state',async()=>{
 await subject();let captures=0;const configuration={dirty:true,pending:false};
 globalThis.RunTeamsEmployeeConfiguration={closeState(){captures++;return configuration;}};
 try{
  assert.equal(window.RunTeamsLocalDesktop.prepareClose(),'dirty');
  configuration.pending=true;assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'pending');
  configuration.pending=false;assert.equal(window.RunTeamsLocalDesktop.prepareClose(true),'ready');
  assert.equal(captures,3);
 }finally{delete globalThis.RunTeamsEmployeeConfiguration;}
});


test('employee creation cold boot restores purpose and its draft before the first render',async()=>{
 const {module}=await subject();globalThis.location={href:'http://localhost/chats/new?purpose=create-employee'};
 const S={railNavTab:'bots'},frames=[];
 await module.boot({state:S,render(){frames.push({purpose:S.conversationPanel.context.purpose,input:S.conversationPanel.input,tab:S.railNavTab});},
  restoreWorkspace(){S.conversationPanelDrafts={employee:'员工草稿',general:'通用草稿'};},
  newConversation:purpose=>({context:{context_type:'general',purpose},input:''}),
  restoreDraft:panel=>{panel.input=S.conversationPanelDrafts[panel.context.purpose==='create-employee'?'employee':'general'];},
  loadEmployees:async()=>{},loadPipelines:async()=>{},loadModels:async()=>({catalog:{channels:[]}}),loadChats:async()=>{},normalize(){},
  route:()=>({kind:'chat-new',purpose:'create-employee'}),restoreSettings(){},openRoute(){throw Error('No second router for welcome');}});
 assert(frames.length);for(const frame of frames)assert.deepEqual(frame,{purpose:'create-employee',input:'员工草稿',tab:'bots'});
});


test('saved chat cold boot does not paint a generic draft before its own route loads',async()=>{
 const {module}=await subject();globalThis.location={href:'http://localhost/chats/local-test'};
 const S={};let opened=false,painted=0;
 await module.boot({state:S,render(){assert(opened,'painted a generic placeholder for a saved chat');painted++;},restoreWorkspace(){},restoreDraft(){},
  newConversation:()=>({context:{context_type:'general'},input:''}),loadEmployees:async()=>{},loadPipelines:async()=>{},loadModels:async()=>({catalog:{channels:[]}}),loadChats:async()=>{},normalize(){},
  route:()=>({kind:'chat'}),restoreSettings(){},openRoute:async()=>{opened=true;}});
 assert(opened);assert.equal(painted,1);
});


test('cold boot preserves either saved sidebar selection independently of page purpose',async()=>{
 for(const saved of ['team','bots'])for(const route of [{kind:'chat-new'},{kind:'chat-new',purpose:'create-employee'},{kind:'chat'}]){
  const {module}=await subject();globalThis.location={href:'http://localhost/'+(route.kind==='chat'?'chats/local-test':'chats/new'+(route.purpose?'?purpose='+route.purpose:''))};
  const S={railNavTab:saved},frames=[];
  await module.boot({state:S,render(){frames.push(S.railNavTab);},restoreWorkspace(){},restoreDraft(){},
   newConversation:purpose=>({context:{context_type:'general',purpose},input:''}),loadEmployees:async()=>{},loadPipelines:async()=>{},loadModels:async()=>({catalog:{channels:[]}}),loadChats:async()=>{},normalize(){},
   route:()=>route,restoreSettings(){},openRoute:async()=>{frames.push(S.railNavTab);}});
  assert.equal(S.railNavTab,saved,JSON.stringify({saved,route}));assert(frames.every(tab=>tab===saved),JSON.stringify({saved,route,frames}));
 }
});


test('background boot renders keep the URL page until its route is ready',async()=>{
 for(const kind of ['docs','trash','chat','source-pipeline']){
  const {module}=await subject();globalThis.location={href:'http://localhost/'+(kind==='docs'?'documents':kind==='trash'?'trash':kind==='chat'?'chats/local-test':'pipelines/local/test')};
  const S={},frames=[];let opened=false;
  const render=()=>frames.push({booting:S.booting,route:S.bootRoute?.kind,surface:S.surface,opened});
  const open=async()=>{S.surface=kind;render();await new Promise(setImmediate);render();opened=true;};
  await module.boot({state:S,render,restoreWorkspace(){},restoreDraft(){},newConversation:()=>({context:{},input:''}),
   loadChats:async()=>{render();},loadEmployees:async()=>{render();},loadPipelines:async()=>{render();},
   loadModels:async()=>({catalog:{channels:[]}}),normalize(){render();},route:()=>({kind}),
   openDocuments:open,openTrash:open,openRoute:open,restoreSettings(){}});
  assert(frames.length);for(const frame of frames){
   if(frame.booting)assert.equal(frame.route,kind,JSON.stringify({kind,frame}));
   else{assert(frame.opened,JSON.stringify({kind,frame}));assert.equal(frame.surface,kind);}
  }
  assert.equal(S.booting,false);assert.equal(frames.at(-1).surface,kind);
 }
});
