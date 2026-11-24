const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup({identity={localLibrary:{library_id:'library',generation:'generation-1'}},configure=()=>{}}={}){
 const id='b'.repeat(64),calls=[],storage=new Map(),events={},S={...identity,conversationPanel:{id:1,kind:'employee_design',context:{creator_local_source_id:id}}};let header,respond;
 const files=['project.json','employees/main.json','employees/soul.md'].map(path=>({path,sha256:'hash'}));
 const draft={schema:'runteams.local-source-draft/1',id,scope:'device-source-draft',published:false,cloud_verified:false,project:{name:'SDK source',version:'1'},source:{sha256:id,files}};
 let dialog;
 const context={S,esc:String,ICON:name=>name,AbortController,TextEncoder,Map,Set,crypto:require('node:crypto').webcrypto,btoa:s=>Buffer.from(s,'binary').toString('base64'),console,
  workspaceAccountCacheToken:()=>JSON.stringify([S.localLibrary,S.account]),render:()=>{},draftRuntimeConfig:()=>({channel_id:1,model:'fixture-model',reasoning_effort:'low'}),openDialog:options=>{dialog=options;},replaceDialog:options=>{dialog=options;},closeModal:()=>{dialog=null;},skillsResourceRevealPath:()=>{},selectDetailWorkspace:sel=>S.sel=sel,
  RunTeamsEmployeeDrawerHeader:{mount:(kind,state,options)=>header=options},
  document:{getElementById:()=>null,querySelector:selector=>selector==='.creator-operation-dialog'&&dialog?{}:null},addEventListener:(name,fn)=>events[name]=fn,
  RunTeamsBusinessStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
  fetch:async(path,options)=>{calls.push({path,options});return respond(path,options);}};
 function resource(url){
  if(url.includes('/file?')){
   const filename=new URL(url,'http://fixture').searchParams.get('path');
   const contents={'project.json':JSON.stringify({entrypoints:{employees:['employees/main.json']}}),
    'employees/main.json':JSON.stringify({soul_file:'employees/soul.md'}),'employees/soul.md':'original source'};
   return {sha256:'hash',kind:'text',content:contents[filename]};
  }
  if(url.endsWith('/workspace'))return {revision:id,source:{files}};
  if(url.endsWith('/history'))return {items:[{revision:'previous'}],original_revision:id};
  return draft;
 }
 respond=async url=>({ok:true,json:async()=>resource(url)});
 S.channels=[{id:1,enabled:true,provider:'codex'}];
 context.window=context;vm.createContext(context);
 const load=name=>vm.runInContext(fs.readFileSync(path.join(__dirname,'../../web/ui',name+'.js'),'utf8'),context);
 load('host');configure(context);load('creator-author');
 const defaultRespond=respond;
 return {draft,files,defaultRespond,dialog:()=>dialog,id,S,calls,context,events,author:context.window.RunTeamsCreatorAuthor,setRespond:fn=>respond=fn,header:()=>header};
}

module.exports={setup};
