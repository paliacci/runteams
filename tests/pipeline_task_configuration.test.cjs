// Native task-panel save protocol: drafts, conflicts, and unknown receipts.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('web/index.html','utf8');assert.ok(html.indexOf('/ui/configuration-fields.js?')<html.indexOf('/ui/source-pipeline-panels.js?'),'Credential event owner must load before task adapter');
const source=fs.readFileSync('web/ui/source-pipeline-panels.js','utf8');
const part=source.slice(source.indexOf('const taskConfigurationKey='),source.indexOf('function workContent('));
const store=new Map(),calls=[],timers=new Map();let reply,fail,showing=true;
const s={storageScope:'device',reference:{source_id:'fixture'}},selection={id:'work',workflow:{id:1,snapshot_json:{pipeline_visit:1}},taskConfiguration:{editable:true,revision:'a'.repeat(64),values:{backend_url:'https://example.test'},fields:[{key:'app_id',type:'text'},{key:'backend_url',type:'text',visible_to:['build']}]}};
const input={dataset:{key:'app_id'},value:'app-a'};
const form={querySelector:()=>null,querySelectorAll:selector=>selector==='[data-key]'?[input]:[]};
const c={console,structuredClone,requestAnimationFrame:()=>{},ICON:()=>'',csel:()=>'',S:{sel:selection},current:()=>showing?s:null,owned:x=>showing&&x===s,render:()=>{},workText:(_k,f)=>f,
 setTimeout:fn=>{const id=Symbol();timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
 document:{addEventListener(){},getElementById:()=>form},addEventListener(){},readCoreTaskParameters:()=>({app_id:'app-a'}),crypto:{randomUUID:()=>String(calls.length+1)},
 RunTeamsWorkState:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
 host:()=>({sameScope:x=>x===s,request:async(action,data)=>{calls.push({action,data:structuredClone(data)});if(fail)throw fail;return reply;}})};
c.window=c;vm.createContext(c);
for(const name of ['configuration-form','configuration-fields'])vm.runInContext(fs.readFileSync('web/ui/'+name+'.js','utf8'),c);
// The task adapter reads the same frozen feedback/visit state as the full panel.
vm.runInContext(source.slice(source.indexOf('const flowKey='),source.indexOf('async function flow(')),c);
vm.runInContext(part,c);
const grouping=c.taskConfigurationGroups([{key:'a',label:'A',type:'text'},{key:'b',label:'B',type:'text',group:'Pinned title'},{key:'c',label:'C',type:'number'}],{parameters:[{key:'a',type:'text',source:'user',display:'setup',group:'User defined service'},{key:'b',type:'text',source:'user',display:'setup',group:'New title'},{key:'c',type:'text',source:'user',display:'setup',group:'Wrong type'}]});
assert.deepEqual(JSON.parse(JSON.stringify(grouping.map(g=>g.label))),['User defined service','Pinned title','C']);
assert.equal(grouping.flatMap(g=>g.fields).length,3,'Grouping must not add fields from the current pipeline');
(async()=>{
 c.taskConfigurationDraft(form);assert.equal(JSON.parse([...store.values()][0]).draft.app_id,'app-a');
 assert.equal(timers.size,0,'Typing keeps a draft until the change is committed');
 c.taskConfigurationDraft(form,true);
 c.taskConfigurationDraft(form,true);
 assert.equal(timers.size,1,'A second change coalesces with the scheduled save');
 const [timer,save]=[...timers][0];timers.delete(timer);c.S.sel=null;showing=false;
 fail=Error('network lost');await save();assert.equal(calls.at(-1).data.action,'save');const op=calls.at(-1).data.operation_id;
 c.S.sel=selection;showing=true;
 assert.equal(calls.at(-1).data.values.backend_url,'https://example.test','Hidden fields retain their saved values');
 fail=null;reply={status:'unknown'};await c.saveTaskConfiguration();assert.equal(calls.at(-1).data.action,'receipt');assert.equal(calls.at(-1).data.operation_id,op);
 reply={status:'committed',configuration:{...selection.taskConfiguration,revision:'b'.repeat(64),values:calls[0].data.values}};await c.saveTaskConfiguration();assert.equal(calls.at(-1).data.action,'save');assert.equal(calls.at(-1).data.operation_id,op);assert.equal(selection.taskConfiguration.values.app_id,'app-a');
 input.value='changed';
 c.taskConfigurationDraft(form);fail=Object.assign(Error('stale'),{confirmedReply:true,code:'task_configuration_conflict'});await c.saveTaskConfiguration();const n=calls.length;await c.saveTaskConfiguration();assert.equal(calls.length,n,'conflict cannot silently overwrite');
 fail=null;reply={configuration:{...selection.taskConfiguration,revision:'c'.repeat(64),values:{app_id:'other-editor'}}};await c.reloadTaskConfiguration();assert.equal(selection.taskConfiguration.values.app_id,'other-editor');assert.equal(store.size,0);
 // Credential saves use their own endpoint and never join durable drafts or pending requests.
 const credentialOwner={s,selection,w:selection.workflow,c:selection.taskConfiguration,state:s.taskConfigurationStates[1]};
 reply={configuration:{...selection.taskConfiguration,revision:'d'.repeat(64),credential_fields:{APP_RC_SECRET_KEY:{state:'configured',selected:true}}}};
 await c.saveTaskCredential(credentialOwner,'APP_RC_SECRET_KEY','test-secret-not-for-storage',{});
 assert.equal(calls.at(-1).data.action,'credential');
 assert.equal(calls.at(-1).data.field,'APP_RC_SECRET_KEY');
 assert.equal(selection.taskConfiguration.revision,'d'.repeat(64));
 assert.ok(!JSON.stringify([...store.values()]).includes('test-secret-not-for-storage'));
 assert.ok(!JSON.stringify(s.taskConfigurationStates).includes('test-secret-not-for-storage'));
 const count=calls.length;credentialOwner.state.draft={app_id:'changed-project'};
 await c.saveTaskCredential(credentialOwner,'APP_RC_SECRET_KEY','blocked-secret',{});
 assert.equal(calls.length,count,'Unsaved project edits must be saved before credential binding');
 credentialOwner.state.draft=null;
 console.log('Task configuration draft / uncertain save / same-operation retry / conflict / reload passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
