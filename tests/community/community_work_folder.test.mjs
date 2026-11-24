import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function subject(){
 const S={localLibrary:{library_id:'library-a'},account:null,conversationPanel:{kind:'general',id:null,input:'keep draft',attachments:[],capabilities:[]}};
 let finish;const calls=[],folder={id:'selected',path:'/tmp/Project',display_path:'/tmp/Project',name:'Project',available:true,custom:true};
 const context={S,window:{addEventListener(){}},_workspaceBusinessGeneration:0,workspaceAccountCacheToken:()=>S.localLibrary?.library_id||'',esc:String,ICON:()=>'<svg></svg>',queueMicrotask,document:{querySelectorAll:()=>[]},toast(){},closePop(){},render(){},conversationDraftValue:()=>S.conversationPanel.input,conversationAttachments:()=>[],conversationCapabilities:()=>[],api:async(path,method,body)=>{calls.push({path,method,body});if(!method)return new Promise(resolve=>{finish=resolve;});return {folder};}};
 context.window=context;context.addEventListener=()=>{};
 vm.createContext(context);
 const load=name=>vm.runInContext(fs.readFileSync(new URL('../../web/ui/'+name+'.js',import.meta.url),'utf8'),context);
 load('host');
 load('work-folder');
 return {S,context,feature:context.window.RunTeamsWorkFolders,calls,folder,resolve:()=>finish({folder})};
}

test('unsigned local library uses the same folder prepare and binding flow',async()=>{
 const s=subject();assert.match(s.feature.markup('panel'),/data-work-folder="panel"/);await Promise.resolve();
 const waiting=s.feature.prepare('panel');s.resolve();const selection=await waiting;
 assert.equal(selection.selection_id,'selected');assert.match(s.feature.markup('panel'),/>Project</);
 await s.feature.bind(41,selection);assert.equal(s.calls.at(-1).path,'/api/work-folders/bind');
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls.at(-1).body)),{chat_id:41,selection_id:'selected'});
 assert.equal(s.S.account,null);assert.equal(s.S.conversationPanel.input,'keep draft');
});

test('library switch rejects stale selection and protected contexts stay hidden',async()=>{
 const s=subject();const waiting=s.feature.prepare('panel');s.S.localLibrary={library_id:'library-b'};s.resolve();assert.equal(await waiting,false);
 s.S.conversationPanel={kind:'employee_design'};assert.equal(s.feature.markup('panel'),'');
 s.S.conversationPanel={kind:'general',scope_pipeline_id:2};assert.equal(s.feature.markup('panel'),'');
 s.S.conversationPanel={kind:'general'};s.context.RunTeamsHost.configure({session:{workspace:state=>state.workspaceOpen}});s.S.workspaceOpen=true;assert.equal(s.feature.markup('panel'),'');
 s.S.workspaceOpen=false;s.S.localLibrary=null;assert.equal(s.feature.markup('panel'),'');
});

test('returning after clear keeps the original frozen project controls usable',async()=>{
 const s=subject(),original=s.S.conversationPanel;const ready=s.feature.prepare('panel');s.resolve();await ready;
 const managed={...s.folder,id:'managed',custom:false};
 s.context.RunTeamsEmployeeDirectory={employeePanel:()=>false};
 s.context.newRailChat=async()=>{s.S.conversationPanel={kind:'general',id:null,input:'',attachments:[],capabilities:[]};};
 s.context.api=async(path,method)=>method?{folder:managed,new_conversation:true}:{folder:managed};
 await s.feature.clear({preventDefault(){},stopPropagation(){}},'panel');
 assert.notEqual(s.S.conversationPanel,original);assert.equal(s.S.conversationPanel.input,'keep draft');
 s.S.conversationPanel=original;const restored=s.feature.markup('panel');
 assert.match(restored,/>Project</);assert.doesNotMatch(restored,/disabled/);
});
