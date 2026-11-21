const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/index.html','utf8');
function fn(name){const start=source.search(new RegExp('^(?:async )?function '+name+'\\(','m'));assert(start>=0);const tail=source.slice(start+1),next=tail.search(/\n(?:(?:async )?function |(?:const|let|class) )/);return next<0?source.slice(start):source.slice(start,start+1+next);}
function fixture(){
 const host={},c={window:host,console,Map,Set,Error,Promise};
 vm.runInNewContext(fs.readFileSync('web/ui/load-failure.js','utf8'),c);
 Object.assign(c,{RunTeamsLoadFailure:host.RunTeamsLoadFailure,S:{chats:[{id:1,title:'Keep original conversation'}],booting:false},_workspaceBusinessGeneration:1,
  workspaceAccountCacheToken:()=> 'same-scope',RunTeamsHost:{session:{workspace:()=>false},lifecycle:{}},updateWorkspaceNavigationError:()=>{},render:()=>{},railRecentChats:()=>c.S.chats,
  api:async()=>({error:'private internal path',code:'local_storage_full'})});
 vm.runInNewContext(fn('refreshChatDirectory')+'\n'+fn('railNavigationFailure'),c);return c;
}
test('storage-full failures retain known chats and show the actionable cause without raw internals',async()=>{
 const c=fixture(),original=c.S.chats;await assert.rejects(c.refreshChatDirectory());
 assert.equal(c.S.chats,original);assert.equal(c.S.chatDirectoryErrorCode,'local_storage_full');
 const html=c.railNavigationFailure();assert.match(html,/磁盘空间不足/);assert.match(html,/仍显示上次读取的对话/);assert.doesNotMatch(html,/private internal/);
 assert.equal((html.match(/data-read-retry=/g)||[]).length,1);
});
test('a successful original read clears the cause and replaces the list with confirmed data',async()=>{
 const c=fixture();await assert.rejects(c.refreshChatDirectory());const confirmed=[{id:2,title:'Confirmed conversation'}];c.api=async()=>({chats:confirmed});
 await c.refreshChatDirectory();assert.equal(c.S.chats,confirmed);assert.equal(c.S.chatDirectoryErrorCode,'');assert.equal(c.S.chatDirectoryError,'');assert.equal(c.railNavigationFailure(),'');
});
test('an obsolete scope cannot project a storage failure into the next workspace',async()=>{
 const c=fixture();let finish;c.api=()=>new Promise(resolve=>finish=resolve);const pending=c.refreshChatDirectory();c._workspaceBusinessGeneration++;
 finish({error:'full',code:'local_storage_full'});await pending;assert.notEqual(c.S.chatDirectoryErrorCode,'local_storage_full');assert.equal(c.S.chats[0].id,1);
});

function streamFixture(){
 const c=fixture(),listeners=new Map();
 Object.assign(c.window,{location:{origin:'http://localhost'},
  RunTeamsPageRouteContract:JSON.parse(fs.readFileSync('contracts/page-routes.json','utf8')),
  addEventListener:(name,listener)=>listeners.set(name,listener)});
 c.URL=URL;
 vm.runInNewContext(fs.readFileSync('web/ui/page-routes.js','utf8'),c);
 c.RunTeamsRoutes=c.window.RunTeamsRoutes;
 c.RunTeamsStaticPages={rememberConversationLayouts(){}};
 vm.runInNewContext(['deviceChatKnown','deviceChatRemember','streamApi'].map(fn).join('\n'),c);
 return {c,changeWorkspace(){c._workspaceBusinessGeneration++;listeners.get('runteams:business-scope-changed')();}};
}

const link={resource:'documents',id:'123',public_id:'local-'+'a'.repeat(32)};
test('normal and recovered stream results register the document URL before delivery',async()=>{
 const {LocalClient}=await import('../frontend/community/client.js');
 for(const recover of [false,true]){
  const {c}=streamFixture();
  let operationId,posts=0,reads=0;
  const client=new LocalClient({
   fetcher:async(_path,options)=>{
    posts++;operationId=JSON.parse(options.body).operation_id;
    if(recover)throw Error('stream disconnected');
    return new Response(JSON.stringify({type:'result',device_page_ids:[link]})+'\n');
   },
   request:async()=>{
    reads++;
    return {status:200,text:JSON.stringify({messages:[
     {role:'user',id:1,metadata:{local_turn_id:operationId}},
     {role:'bot',id:2,metadata:{local_turn_id:operationId}}
    ],device_page_ids:[link]})};
   }
  });
  c.RunTeamsHost.lifecycle.stream=(...args)=>client.stream(...args);
  let resultCount=0;
  await c.streamApi('/api/chat/7/stream',{},event=>{
   if(event.type!=='result')return;
   resultCount++;
   const url='/documents/'+link.public_id;
   assert.equal(c.RunTeamsRoutes.toPublic('/docs/123'),url);
   assert.equal(c.RunTeamsRoutes.resolve(url).documentId,123);
  });
  assert.deepEqual([resultCount,posts,reads],[1,1,Number(recover)]);
 }
});

test('a late result does not add a device link to the next workspace',async()=>{
 const {c,changeWorkspace}=streamFixture();
 c.RunTeamsHost.lifecycle.stream=async(_path,_body,deliver)=>{
  changeWorkspace();
  deliver({type:'result',device_page_ids:[link]});
 };
 await c.streamApi('/api/chat/7/stream',{},()=>{});
 assert.throws(()=>c.RunTeamsRoutes.toPublic('/docs/123'),{code:'page_ids_missing'});
});

async function sidebarFixture(){
 const {LocalClient}=await import('../frontend/community/client.js');
 const c=fixture(),attempts=new Map(),delays=[];
 const pipeline={page_id:'4a7v9bn2',name:'Saved pipeline',reference:{schema:'runteams.local-pipeline-reference/1',storage_kind:'local',library_id:'library',source_id:'sample',pipeline_source:'sample'}};
 Object.assign(c,{URL,AbortController,Event,clearTimeout,setInterval(){},document:{addEventListener(){}},
  setTimeout(callback,ms){if(ms===2000){delays.push(callback);return;}return setTimeout(callback,ms);},
  workspaceDeviceStorageScope:()=> 'library',S:{booting:true,localLibrary:{library_id:'library'}}});
 Object.assign(c.window,{addEventListener(){},dispatchEvent(){},fetch:async(path)=>{
  attempts.set(path,(attempts.get(path)||0)+1);
  if(c.offline)throw new TypeError('connection reset');
  if(c.storageFull)return {status:507,text:async()=>JSON.stringify({error:'Storage full',code:'local_storage_full'})};
  const value=path.includes('/chats')?{chats:[{id:1}]}:{items:[pipeline],errors:[]};
  return {status:200,text:async()=>JSON.stringify(value)};
 }});
 vm.runInNewContext(fs.readFileSync('web/ui/requests.js','utf8'),c);
 const transport=c.window.RunTeamsRequests;
 const client=new LocalClient({fetcher:c.window.fetch,request:transport.request});
 c.api=client.request.bind(client);
 vm.runInNewContext(fs.readFileSync('web/ui/source-pipelines.js','utf8'),c);
 const pipelines=c.window.RunTeamsSourcePipelines;
 const refresh=()=>Promise.allSettled([c.refreshChatDirectory({readPriority:'background'}),pipelines.refreshCatalog({readPriority:'background'})]);
 return {c,attempts,delays,refresh,pipelines,transport};
}
test('background directory refresh retains confirmed data during disconnect and reports only a failed retry',async()=>{
 const {c,refresh,attempts,delays,pipelines}=await sidebarFixture();
 c.offline=true;await refresh();
 assert.equal(delays.length,0);assert.ok(c.S.chatDirectoryError);assert.ok(pipelines.catalogState().failed);
 c.offline=false;await refresh();
 for(const recover of [true,false]){
  const previous=c.S.chats;
  attempts.clear();c.offline=true;
  const pending=refresh(),joined=refresh();
  await new Promise(setImmediate);
  assert.equal(delays.length,2);assert.equal(c.S.chats,previous);
  assert.equal(c.S.chatDirectoryError,'');assert.equal(pipelines.catalogState().failed,false);
  c.offline=!recover;delays.splice(0).forEach(resume=>resume());
  await Promise.all([pending,joined]);
  assert.deepEqual([...attempts.values()],[2,2]);
  assert.equal(Boolean(c.S.chatDirectoryError),!recover);assert.equal(pipelines.catalogState().failed,!recover);
  if(!recover)assert.equal(c.S.chats,previous);
  assert.equal(pipelines.items()[0].name,'Saved pipeline');
 }
 c.offline=false;await refresh();assert.equal(c.S.chatDirectoryError,'');assert.equal(pipelines.catalogState().failed,false);
});
test('confirmed storage errors on a cached background refresh remain immediately actionable',async()=>{
 const {c,refresh,attempts,delays,pipelines}=await sidebarFixture();
 await refresh();attempts.clear();c.storageFull=true;await refresh();
 assert.deepEqual([...attempts.values()],[1,1]);assert.equal(delays.length,0);
 assert.match(c.railNavigationFailure(),/磁盘空间不足/);assert.equal(pipelines.catalogState().failed,true);
});
test('a workspace reset cancels delayed retries and write requests never retry a disconnect',async()=>{
 const {c,refresh,attempts,delays,transport}=await sidebarFixture();
 await refresh();attempts.clear();c.offline=true;
 const pending=refresh();await new Promise(setImmediate);assert.equal(delays.length,2);
 c._workspaceBusinessGeneration++;transport.reset();await pending;
 assert.deepEqual([...attempts.values()],[1,1]);assert.equal(c.S.chatDirectoryError,'');
 const write='/api/conversations';
 await assert.rejects(transport.request(write,{device:true,method:'POST',retryOnDisconnect:true}),/connection reset/);
 assert.equal(attempts.get(write),1);
});

test('schedule startup reads current recovery state when another device request invalidates the first read',async()=>{
 const read='/api/device/work/source-pipelines/ui-state-read', scope='test-library';
 let release,reads=0;
 const first=new Promise(resolve=>{release=resolve;});
 const window={fetch:async path=>{
  if(path!==read)return new Response('{}');
  const attempt=++reads;
  if(attempt===1)await first;
  const items={'employee-schedule-operation:key':{revision:attempt,value:JSON.stringify(attempt)}};
  return new Response(JSON.stringify({schema:'runteams.work-ui-state-list/1',items}));
 }};
 const context=vm.createContext({window,URL,AbortController,setTimeout,clearTimeout,
  _workspaceBusinessGeneration:1,workspaceAccountCacheToken:()=>scope,workspaceDeviceStorageScope:()=>scope});
 vm.runInContext(fs.readFileSync('web/ui/requests.js','utf8'),context);
 context.api=async(path,method,body,options)=>{
  const reply=await window.RunTeamsRequests.request(path,{method,body:JSON.stringify(body),device:true,...options},scope);
  return JSON.parse(reply.text);
 };
 vm.runInContext(fs.readFileSync('web/ui/work-state.js','utf8'),context);
 const state=window.RunTeamsWorkState,loading=state.connect();
 await context.api('/api/device/work/source-pipelines/asset-knowledge','POST',{});
 release();await loading;
 assert.equal(reads,2);
 assert.equal(state.getItem('runteams.employee-schedule-operation:'+scope+':key'),'2');
});
