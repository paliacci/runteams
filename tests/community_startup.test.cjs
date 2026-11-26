const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');

const source=fs.readFileSync(path.join(__dirname,'../frontend/community/bootstrap.js'),'utf8')
 .replace(/^import .*;$/gm,'').replace(/export /g,'');

async function start(initial, beforeModelsComplete){
 const location={href:'http://127.0.0.1'+initial};
 const state={}, opened=[];
 let finishModels;
 const sandbox={
  location,URL,window:{},fetch(){},
  document:{documentElement:{hasAttribute:()=>false}},
  RunTeamsRequests:{request(){},isRead:()=>true},
  windowsSettingsBridge:()=>null,NativeCloseGuard:class{},
  LocalClient:class{
   libraryId='library';
   async connect(){return {library_id:this.libraryId};}
   async request(url){
    return url==='/api/settings'?{library_id:this.libraryId,revision:1,settings:{}}:{};
   }
  }
 };
 vm.createContext(sandbox);
 vm.runInContext(source,sandbox);
 const noop=()=>{};
 const booting=sandbox.boot({
  state,restoreWorkspace:noop,render:noop,newConversation:()=>({}),restoreDraft:noop,
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
 return {opened,state};
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
