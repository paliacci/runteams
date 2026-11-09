// Configuration panels share composition and transaction semantics, while adapters own scope.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let sequence=0;
const c={structuredClone,console,Set,Map,requestAnimationFrame:fn=>fn(),crypto:{randomUUID:()=>`operation-${++sequence}`},esc:escape,
 ICON:name=>`<svg class="i"><use href="#i-${name}"></use></svg>`,csel:()=>'',
 document:{addEventListener(){}},addEventListener(){},S:{sel:null},
 RunTeamsWorkAuthorization:{settings:()=>''},RunTeamsSkeletons:{region:()=>''}};
c.window=c;vm.createContext(c);
const load=name=>vm.runInContext(fs.readFileSync(`web/ui/${name}.js`,'utf8'),c);
load('configuration-form');load('configuration-fields');
const header=fs.readFileSync('web/ui/employee-drawer-header.js','utf8');
vm.runInContext(header.slice(header.indexOf(' function section('),header.indexOf(' function toggleSection('))+';RunTeamsEmployeeDrawerHeader={section};',c);
const employee=fs.readFileSync('web/ui/employee-configuration.js','utf8');
vm.runInContext(employee.replace('window.RunTeamsEmployeeConfiguration=', 'window.employeeFormParts=formParts;window.employeeTransaction=configurationTransaction;window.installEmployeeSession=s=>{active=s;sessions.set(s.cacheKey,s);};window.RunTeamsEmployeeConfiguration='),c);
const f=c.RunTeamsConfigurationForm,fields=[{key:'app_id',label:'App ID',type:'text',required:true,note:'Service identifier',constraints:{min_length:2,max_length:20}}];
const group={key:'service',label:'Custom service group',fields};
function employeeState(entry={}){return {entry,bindings:{},errors:{},collapsedSections:new Set(),data:{definition:{groups:[group]},values:{},states:{}}};}
const surfaces=[c.employeeFormParts(employeeState()),c.employeeFormParts(employeeState({pipeline_own:true}),{name:'Pipeline'}),c.employeeFormParts({...employeeState(),inlineSelection:{}})];
for(const surface of surfaces){
 assert.match(surface.content,/Custom service group/);assert.match(surface.content,/settings-section-toggle/);
 assert.match(surface.content,/required-mark/);assert.match(surface.content,/#i-info-compact/);
 assert.match(surface.content,/minlength="2"/);assert.match(surface.content,/maxlength="20"/);
 assert.doesNotMatch(surface.content,/使用配置/);
 assert.equal(surface.footer,'');
}
assert.equal(f.footer({state:{draft:{app_id:'edited'}}}),'','Edits must not display manual save controls');
assert.equal(f.footer({state:{saving:true,pending:{operation_id:'saving'}}}),'','An in-flight save must leave no footer');
const pipeline=fs.readFileSync('web/ui/source-pipeline-panels.js','utf8');
const selection={id:'work',workflow:{id:1,snapshot_json:{pipeline_visit:1}},taskConfiguration:{editable:true,fields:[{...fields[0],group:group.label}],values:{}}};
const session={taskConfigurationStates:{1:{}},data:{pipeline:{}}};
Object.assign(c,{current:()=>session,RunTeamsWorkState:{getItem:()=>null},workLabel:(_key,text)=>text,workText:(_key,text)=>text,
 workSection:(_selection,_key,_label,body)=>body});
// The task adapter reads the same frozen feedback/visit state as the full panel.
vm.runInContext(pipeline.slice(pipeline.indexOf('const flowKey='),pipeline.indexOf('async function flow(')),c);
vm.runInContext(pipeline.slice(pipeline.indexOf('const taskConfigurationKey='),pipeline.indexOf('function workContent(')),c);
const position={kind:'employee',key:'store-review'};
const task=c.taskConfigurationMarkup(selection,position);
assert.doesNotMatch(task,/configuration-save|type="submit"/);
const groupBody=html=>html.slice(html.indexOf('<section'),html.indexOf('</section>')+10)
 .replace(/employee_config_|source_task_configuration_/g,'field_')
 .replace(/employee_configuration_form-group-service|source_task_configuration-group-Custom%20service%20group/g,'group')
 .replace(/RunTeamsEmployeeConfiguration.toggleSection|RunTeamsSourcePipelinePanels.toggleTaskConfigurationSection/g,'toggle');
for(const surface of surfaces)assert.equal(groupBody(surface.content),groupBody(task),'All four adapters must render the same field group');
const configuration=selection.taskConfiguration;
configuration.fields[0].visible_to=[position.key];
configuration.fields.push(
 {key:'backend_url',label:'Backend URL',type:'text',group:'Backend',visible_to:['build']},
 {key:'support_url',label:'Support URL',type:'text',group:'Links',visible_to:[]});
const scoped=c.taskConfigurationMarkup(selection,position);
assert.match(scoped,/data-field="app_id"/);
assert.match(scoped,/data-field="support_url"/);
assert.doesNotMatch(scoped,/backend_url|Backend/);
assert.equal(c.taskConfigurationMarkup(selection,{kind:'approval',key:'approval'}),'');
assert.equal(c.taskConfigurationMarkup(selection,undefined),'','State columns have no employee configuration');
configuration.fields.pop();
assert.equal(c.taskConfigurationMarkup(selection,{kind:'employee',key:'demand'}),'');
configuration.editable=false;
for(const reason of ['running','unresolved','finished']){
 configuration.readonly_reason=reason;
 assert.equal(c.taskConfigurationMarkup(selection,position),'');
}
session.taskConfigurationStates[1].pending={operation_id:'unconfirmed'};
const pending=c.taskConfigurationMarkup(selection,undefined);
assert.match(pending,/核对保存结果/);
assert.doesNotMatch(pending,/data-field=|type="submit"/);
const renderer=c.RunTeamsConfigurationFields.create({icon:c.ICON,singleSelect:c.csel});
for(const file of [false,true]){
 const credential={key:'service',label:'Service credential',type:'secret',...(file?{file_input:{accept:'.p8'}}:{})};
 const empty=renderer.field({...credential,localCredential:{state:'missing',selected:false,available:true}},'');
 assert.match(empty,file?/尚未配置/:/输入凭据/);
 assert.match(empty,file?/data-credential-file=/:/type="password"/);
 assert.doesNotMatch(empty,/data-credential-use|data-credential-clear|data-credential-edit/);
 const configured=renderer.field({...credential,localCredential:{state:'configured',selected:true,filename:'Test.p8',mask_length:5}},'');
 assert.match(configured,file?/Test\.p8/:/data-configured-secret[^>]*placeholder="•••••"/);
 assert.match(configured,file?/data-credential-clear/:/data-secret=/);
 if(!file)assert.doesNotMatch(configured,/data-credential-edit|data-credential-clear/);
}
assert.match(renderer.field(fields[0],'x','请填写此项。'),/employeeSettings.fieldError.required/);
const checkbox=renderer.field({key:'enabled',label:'Enabled',type:'checkbox',required:true,note:'Enable service'},false);
assert.match(checkbox,/required-mark/);assert.match(checkbox,/#i-info-compact/);assert.equal((checkbox.match(/type="checkbox"/g)||[]).length,1);
assert.equal(f.draft(fields,{app_id:''},{}),null);
assert.equal(f.draft([],{b:2,a:1},{a:1,b:2}),null,'Object order must not create a dirty draft');
assert.deepEqual(f.draft([{key:'count',type:'number'}],{count:''},{count:3}),{count:null});
assert.equal(f.draft([{key:'count',type:'number'}],{count:''},{}),null);
const collapsed=new Set(['service','other']);f.revealErrors([group],g=>g.key,collapsed,{app_id:'invalid'});
assert.deepEqual([...collapsed],['other']);

let blur,paints=0,bindings=0;
const focusDrawer={contains:target=>target==='save-button'},focusInput={matches:()=>true,selectionStart:0,closest:()=>focusDrawer,addEventListener:(_event,fn)=>{blur=fn;bindings++;}};
f.holdInput(focusInput,()=>true,()=>paints++);f.holdInput(focusInput,()=>true,()=>paints++);assert.equal(bindings,1);
blur({relatedTarget:'save-button'});assert.equal(paints,0,'A blur must not remove a button before its click');
f.holdInput(focusInput,()=>true,()=>paints++);blur({relatedTarget:null});assert.equal(paints,1);

(async()=>{
 let owner=true,response={status:'committed',value:{revision:2}},failure=null,storeFailure=false,acceptFailure=false;
 const sent=[],persisted=[];let accepted=0,prepares=0;
 const state={draft:{app_id:'before'}};
 const adapter={prepare:()=>{prepares++;return {expected_revision:1,values:structuredClone(state.draft)};},
  owned:()=>owner,paint(){},persist:async()=>{if(storeFailure)throw Error('storage unavailable');persisted.push(structuredClone(state));},
  send:async(pending,receipt)=>{sent.push({pending:structuredClone(pending),receipt});if(failure)throw failure;return response;},
  accept:()=>{if(acceptFailure)throw Error('invalid receipt');accepted++;},confirmedError:error=>error.status===409};
 failure=Error('lost response');await f.transact(state,adapter);
 assert.ok(state.pending);assert.equal(state.unknown,true);assert.equal(state.retry,false);
 assert.equal(persisted[0].pending.operation_id,sent[0].pending.operation_id,'Operation must be durable before sending');
 const operation=structuredClone(state.pending);state.draft={app_id:'changed after send'};
 failure=null;response={status:'not_found'};await f.transact(state,adapter,{receipt:true});
 assert.equal(state.retry,true);await f.transact(state,adapter);
 assert.deepEqual(sent.at(-1).pending,operation,'Retry must preserve exact operation and submitted values');
 assert.equal(prepares,1);
 response={status:'committed',value:{revision:2}};await f.transact(state,adapter,{receipt:true});
 assert.equal(state.pending,null);assert.equal(state.draft,null);assert.equal(accepted,1);assert.equal(state.saving,false);
 assert.equal(state.notice,'','A confirmed save must leave no notice');
 state.draft={app_id:'conflict'};failure=Object.assign(Error('changed elsewhere'),{status:409,fields:{app_id:'invalid'}});
 await f.transact(state,adapter);assert.equal(state.pending,null);assert.deepEqual(state.draft,{app_id:'conflict'});assert.equal(state.errors.app_id,'invalid');
 failure=null;storeFailure=true;const count=sent.length;await f.transact(state,adapter);
 assert.equal(sent.length,count,'Storage failure must not send a mutation');assert.equal(state.retry,true);assert.equal(state.saving,false);
 storeFailure=false;acceptFailure=true;await f.transact(state,adapter);
 assert.ok(state.pending);assert.equal(state.unknown,true,'Invalid success payload must remain recoverable');
 acceptFailure=false;adapter.send=async()=>{owner=false;return response;};const before=accepted;await f.transact(state,adapter,{receipt:true});
 assert.equal(accepted,before,'Late result must not enter a different scope');assert.ok(state.pending);assert.equal(state.saving,false);
 owner=true;let release;adapter.send=()=>new Promise(resolve=>{release=resolve;});
 const first=f.transact(state,adapter,{receipt:true});await Promise.resolve();await Promise.resolve();
 await f.transact(state,adapter,{receipt:true});assert.equal(state.saving,true);release(response);await first;
 assert.equal(state.pending,null);assert.equal(accepted,before+1,'Concurrent clicks must submit once');
 // Exercise the real employee adapter too: response loss and exact receipt recovery.
 const cache=new Map(),http=[];let lose=true;
 const native={schema:'runteams.employee-configuration-state/1',reference:{source:'fixture'},revision:0,definition_sha256:'definition',definition:{groups:[group]},values:{},states:{},bindings:{}};
 Object.assign(c,{URLSearchParams,workspaceAccountCacheToken:()=> 'account',RunTeamsHost:{session:{deviceScope:()=> 'device'}},render(){},
  RunTeamsBusinessStorage:{setItem:(key,value)=>cache.set(key,value),removeItem:key=>cache.delete(key)},
  fetch:async(url,options)=>{
   http.push({url,options});
   if(options.method==='POST'){
    const body=JSON.parse(options.body);native.values=body.values;native.bindings=body.bindings;native.revision++;
    if(lose){lose=false;throw Error('response lost');}
   }
   return {ok:true,status:200,json:async()=>String(url).includes('operation_id=')?{state:'confirmed',result:structuredClone(native)}:structuredClone(native)};
  }});
 c.document.querySelector=()=>null;
 const employeeSession={...employeeState({key:'fixture',source:{id:'source',path:'employees/fixture.json'}}),cacheKey:'scope-key',scope:'account',deviceScope:'device',data:structuredClone(native),draft:{app_id:'saved'},bindings:{token:{schema:'runteams.configuration-credential/1',key:'TOKEN_REFERENCE'}}};
 c.installEmployeeSession(employeeSession);c.S.sel={type:'employee-configuration',id:'fixture'};
 await c.employeeTransaction(employeeSession);
 assert.ok(employeeSession.pending);assert.equal(employeeSession.data.revision,0);
 assert.deepEqual(JSON.parse(http[0].options.body).bindings,{token:{key:'TOKEN_REFERENCE'}},'Save contains only the credential binding reference');
 assert.ok(cache.size);await c.employeeTransaction(employeeSession,true);
 assert.equal(employeeSession.pending,null);assert.equal(employeeSession.data.values.app_id,'saved');assert.equal(employeeSession.data.revision,1);assert.equal(cache.size,0);
 assert.equal(http.filter(item=>item.options.method==='POST').length,1,'Receipt recovery must not duplicate a save');
 console.log('Four-panel composition, constraints, draft/focus handling, shared transaction faults and real employee/task adapter recovery passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
