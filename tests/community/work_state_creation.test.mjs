import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
const source=p=>fs.readFileSync(new URL('../../'+p,import.meta.url),'utf8');

async function pendingCreation(createReply,lateChoices,refreshedChoices){
 const records=new Map(),calls=[],modalHost={firstChild:null},library={library_id:'actual-library',generation:'first'};let closed=0,navigated=0;
 const select={value:''};let finishChoices;
 const fields={querySelector:key=>key==='select'&&fields.innerHTML?.includes('<select')?select:null}, submit={setAttribute(name,value){this[name]=value;}}, error={removeAttribute(name){delete this[name];},setAttribute(name,value){this[name]=value;}};
 const controls={'[data-pipeline-create-fields]':fields,'[data-pipeline-create-submit]':submit,'[data-pipeline-create-error]':error};
 const ref={schema:'runteams.local-pipeline-reference/1',storage_kind:'local',library_id:library.library_id,source_id:'a'.repeat(64),pipeline_source:'pipelines/main.json'};
 const c={S:{localLibrary:library,account:{signed_in:false}},_workspaceBusinessGeneration:1,_routeSequence:1,_workspaceSwitchSequence:1,
  workspaceAccountCacheToken:()=>library.library_id,workspaceDeviceStorageScope:()=>JSON.stringify(['library',library.library_id]),workspaceCurrentKey:()=> 'home',
  Map,JSON,Number,String,Promise,Object,Error,crypto:crypto.webcrypto,queueMicrotask,
  RunTeamsSkeletons:{region:()=>''},RunTeamsLoadFailure:{markup:()=>''},
  document:{addEventListener(){},getElementById:id=>id==='modalHost'?modalHost:null},addEventListener(){},setInterval(){},render(){},esc:String,toast:message=>{throw Error(message)},
  btoa:s=>Buffer.from(s,'binary').toString('base64'),unescape,encodeURIComponent,
  openDialog:()=>{modalHost.firstChild={isConnected:true,querySelector:selector=>controls[selector]??null,remove(){this.isConnected=false;if(modalHost.firstChild===this)modalHost.firstChild=null;}};return modalHost;},
  closeModal:()=>{closed++;modalHost.firstChild=null;},setAppUrl:async()=>{},applyAppRoute:async()=>{navigated++;},
  api:async(path,method,body)=>{
   const action=path.split('/').pop();calls.push({action,body:structuredClone(body)});
   if(action==='ui-state-read')return {schema:'runteams.work-ui-state-list/1',items:Object.fromEntries(records)};
   if(action==='ui-state-save'){const revision=(records.get(body.key)?.revision||0)+1;assert.equal(body.expected_revision,revision-1);records.set(body.key,{revision,value:body.value});return {operation_id:body.operation_id,revision};}
   if(action==='creation-choices'){
    if(finishChoices&&refreshedChoices)return {items:refreshedChoices,errors:[]};
    if(lateChoices)await new Promise(resolve=>{finishChoices=resolve;});
    return {items:lateChoices||[],errors:[]};
   }
   if(action==='create')return createReply?createReply():{reference:ref};
   if(action==='catalog')return {items:[{reference:ref,page_id:'1a234567',name:original.name}],errors:[]};
   throw Error('Unexpected '+action);
  }};
 c.window=c;Object.defineProperty(c,'localStorage',{get(){throw Error('browser persistence forbidden');}});
 vm.createContext(c);vm.runInContext(source('web/ui/host.js'),c);vm.runInContext(source('web/ui/work-state.js'),c);vm.runInContext(source('web/ui/source-pipelines.js'),c);
 const store=c.RunTeamsWorkState;await store.connect();
 const original={operation_id:crypto.randomUUID(),name:'Original name',employee_reference:{source_id:'old-source'},source_revision:'saved',skill_key:'review'};
 store.setItem('runteams.pipeline-create:'+c.workspaceDeviceStorageScope(),JSON.stringify(original));await store.flush();
 const ui=c.RunTeamsSourcePipelines,opening=ui.newPipeline();
 if(!lateChoices)await opening;
 assert.equal(submit.textContent,'核对创建结果');assert.equal(submit.disabled,false);assert.equal(calls.filter(c=>c.action==='create').length,0);
 await ui.create();await store.flush();
 if(lateChoices){finishChoices();await opening;}
 return {closed,navigated,modalHost,calls,original,records,error,submit,fields,select};
}

test('original creation can be recovered and dialog closes even if current employee choices disappear',async()=>{
 const {closed,navigated,modalHost,calls,original,records}=await pendingCreation();
 assert.equal(closed,1);assert.equal(navigated,1);assert.equal(modalHost.firstChild,null);
 const sends=calls.filter(c=>c.action==='create');assert.equal(sends.length,1);assert.deepEqual(sends[0].body,original);
 assert.equal(records.get('pipeline-create').value,null);
});

test('validation releases a rejected creation while uncertain replies keep the original operation',async()=>{
 for(const [status,code,rejected] of [[400,'invalid_request',true],[422,'invalid_employee',true],
  [409,'source_revision_conflict',true],[409,'runtime_busy',false],[500,'unknown',false]]){
  for(const thrown of [true,false]){
   const {records,original,closed,error,submit}=await pendingCreation(()=>{
    if(thrown)throw Object.assign(Error(code),{status,code});
    return {error:code,status,code};
   });
   const saved=records.get('pipeline-create').value;
   assert.equal(closed,0);
   if(rejected){
    assert.equal(saved,null);assert.equal(error['data-app-i18n'],code==='source_revision_conflict'?'pipelineCreate.choicesChanged':'pipelineCreate.rejected');
   }else{
    assert.deepEqual(JSON.parse(saved),original);assert.equal(submit.textContent,'核对创建结果');
   }
  }
 }
});

test('late employee choices recover the rejected draft and select only its original skill and revision',async()=>{
 const originalRole={reference:{source_id:'old-source'},revision:'saved',skill_key:'review'};
 const otherRole={...originalRole,revision:'newer'};
 const reject=()=>{throw Object.assign(Error('invalid request'),{status:400});};
 for(const [choices,expected] of [[[otherRole,originalRole],'1'],[[otherRole],'']]){
  const {fields,select}=await pendingCreation(reject,choices);
  assert.match(fields.innerHTML,/value="Original name"/);assert.equal(select.value,expected);
 }
});

test('a source conflict refreshes the roles and ignores an earlier reply with the stale revision',async()=>{
 const row={reference:{source_id:'old-source'},revision:'saved',employee_name:'Old employee',skill_key:'review'};
 const reject=()=>{throw Object.assign(Error('source changed'),{status:409,code:'source_revision_conflict'});};
 const {fields,select,calls}=await pendingCreation(reject,[row],[{...row,revision:'new',employee_name:'Updated employee'}]);
 assert.match(fields.innerHTML,/Updated employee/);assert.doesNotMatch(fields.innerHTML,/Old employee/);
 assert.match(fields.innerHTML,/value="Original name"/);assert.equal(select.value,'');
 assert.equal(calls.filter(r=>r.action==='create').length,1);
});
