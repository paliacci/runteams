const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');

const source=fs.readFileSync(path.join(__dirname,'../frontend/community/bootstrap.js'),'utf8')
 .replace(/^import .*;$/gm,'').replace(/export /g,'');

async function start(initial, beforeModelsComplete, desktop=null){
 const location={href:'http://127.0.0.1'+initial};
 const state={}, opened=[];
 let finishModels;
 const sandbox={
  location,URL,window:{},fetch(){},
  console:{error(){}},
  document:{documentElement:{hasAttribute:()=>false},hasFocus:()=>false},
  RunTeamsRequests:{request(){},isRead:()=>true},
  windowsSettingsBridge:()=>desktop,NativeCloseGuard:class{
   constructor(snapshot){this.snapshot=snapshot;}
   checkClose(){const state=this.snapshot();return state.pending?'pending':state.dirty?'dirty':'ready';}
  },
  LocalClient:class{
   libraryId='library';
   async connect(){return {library_id:this.libraryId,generation:'library-generation'};}
   async request(url){
    return url==='/api/settings'?{library_id:this.libraryId,revision:1,settings:{}}:{};
   }
  }
 };
 vm.createContext(sandbox);
 vm.runInContext(source,sandbox);
 const noop=()=>{};
 let restoredDrafts;
 const booting=sandbox.boot({
  state,restoreAppearance:noop,restoreWorkspace(_windows,drafts){
   restoredDrafts=drafts;
   state.conversationPanelDrafts=JSON.parse(drafts??'{}');
  },render:noop,newConversation:()=>({}),restoreDraft:noop,captureDraft:noop,
  restoreSettings:noop,loadChats:async()=>{},normalize:noop,
  loadEmployees:async()=>{},loadPipelines:async()=>{},
  loadModels:()=>new Promise(resolve=>{finishModels=resolve;}),
  route:()=>new URL(location.href).pathname==='/'?{kind:'home'}:{kind:'docs',documentId:80},
  openRoute:()=>opened.push(location.href),
 });
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(state.settingsPreferencesState,'ready');
 beforeModelsComplete?.(location,state);
 finishModels({});
 await booting;
 return {opened,state,restoredDrafts,native:sandbox.window.RunTeamsLocalDesktop};
}

test('startup leaves document history selected when the user navigates before models finish',async()=>{
 const {opened,state}=await start('/',(location,state)=>{
  location.href='http://127.0.0.1/documents/example';
  state.docReader={revisionId:29};
 });
 assert.deepEqual(opened,[]);
 assert.equal(state.docReader.revisionId,29);
});

test('a document deep link is still opened after the initial catalog load',async()=>{
 const url='/documents/example?revision=29';
 const {opened,state}=await start(url);
 assert.deepEqual(opened,['http://127.0.0.1'+url]);
 assert.equal(state.booting,false);
});

test('native quit waits for edits before autosave and until the editor acknowledges the save',async()=>{
 const {state,native}=await start('/');
 for(const pending of [{tableDirty:true},{richDirty:true},{richSaving:Promise.resolve()}]){
  state.docReader={saveStatus:'saved',...pending};
  assert.equal(native.checkClose(),'pending');
 }
 state.docReader={saveStatus:'saved',tableDirty:false,richDirty:false,richSaving:null};
 assert.equal(native.checkClose(),'ready');
});

test('Windows drafts load from the native scope and close waits for the latest acknowledged snapshot',async()=>{
 const prior=JSON.stringify({'chat:17':{input:'persisted at the previous port'}});
 const writes=[];
 const draftRequests={
  get:{},'workspace-boards-read':{boards:{}},'workspace-read':{windows:'[]'},'workspace-drafts-read':{drafts:prior}
 };
 const {state,native,restoredDrafts}=await start('/',null,{postMessage(request){
  if(request.action==='workspace-drafts-write')return new Promise(resolve=>writes.push({request,resolve}));
  return Promise.resolve(draftRequests[request.action]);
 }});
 assert.equal(restoredDrafts,prior);
 assert.equal(native.checkClose(),'ready');
 state.conversationPanelDrafts={'chat:17':{input:'first update'}};
 const first=native.saveDrafts(JSON.stringify(state.conversationPanelDrafts));
 state.conversationPanelDrafts['chat:17'].input='more recent update';
 const latest=JSON.stringify(state.conversationPanelDrafts);
 await native.saveDrafts(latest);
 assert.equal(native.checkClose(),'pending');
 assert.equal(writes.length,1);
 writes[0].resolve({saved:true});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(native.checkClose(),'pending');
 assert.equal(writes[1].request.generation,'library-generation');
 assert.equal(writes[1].request.value,latest);
 writes[1].resolve({saved:true});
 await first;
 assert.equal(native.checkClose(),'ready');
 await native.saveDrafts(latest);
 assert.equal(writes.length,2);
});
