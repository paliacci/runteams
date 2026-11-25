const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('web/ui/employee-automation.js','utf8');
const reference={schema:'runteams.local-employee-reference/1',source_id:'draft',employee_source:'employees/a.json',account_id:'a',deployment_id:'d',storage_namespace:'n'};

function openPanel(changes={}){
 const ctx={creator_local_scope:'scope',creator_local_source_id:'draft',creator_employee_source:'employees/a.json'};
 const panel={id:7,kind:'employee_design',storage_scope:'device',context:ctx,authoringEmployeeReference:reference,...changes};
 let refreshes=0,reads=[];
 const c={S:{conversationPanel:panel,sel:{}},_workspaceBusinessGeneration:1,workspaceAccountCacheToken:()=>'a',workspaceDeviceStorageScope:()=>'scope',
  RunTeamsHost:{session:{ready:()=>true,workspace:()=>false,deviceScope:()=>'scope'}},
  RunTeamsEmployeeDirectory:{forPanel:()=>null,panelReference:()=>null,employeePanel:()=>false,referenceKey:r=>r?JSON.stringify(r):'',refresh:async()=>{refreshes++}},
  RunTeamsAssetOverview:{active:()=>true,loadingSection:()=>''},RunTeamsWorkState:{ready:true,getItem:()=>null},
  document:{},render(){},addEventListener(){},queueMicrotask(){},
  api:async path=>{
   const url=new URL(path,'http://localhost');reads.push(url.pathname);
   assert.deepEqual(JSON.parse(url.searchParams.get('reference')),reference);
   return url.pathname.endsWith('/employee-schedules')?{reference,items:[{id:7}],skills:[]}:{reference,revision:'v1',templates:[],imported_ids:[]};
  }};
 c.window=c;vm.runInNewContext(script,c);
 const automation=c.RunTeamsEmployeeAutomation;automation.overviewSection();
 return {automation,reads,refreshes:()=>refreshes};
}

test('automation reads the bound employee before the directory has loaded',async()=>{
 const t=openPanel();await t.automation.refresh();
 assert.equal(t.refreshes(),0);
 assert.deepEqual(t.reads,['/api/device/employee-schedules','/api/device/asset-automation-templates']);
 assert.equal(t.automation.current().items[0].id,7);
});

test('failed schedule history shows completion only for its own recovered team task',async()=>{
 const owner={pipeline:true,owner:{data:{workflows:[{id:9,state:'completed'},{id:10,state:'failed'}]}}};
 const item={id:2,name:'Daily review',runs:[]};
 let body;
 const records=vm.runInNewContext(
  script.slice(script.indexOf(' async function records(id)'),script.indexOf(' function closeRecords(id)'))+'\nrecords',
  {current:()=>owner,refresh:async()=>{},document:{getElementById:()=>null},find:()=>item,
   copy:key=>key,runState:status=>[status],esc:s=>s,vars:()=>'',automationRunTimeMarkup:()=>'',
   openDialog:options=>{body=options.body;return {querySelector:()=>null}}}
 );
 for(const [pipeline,status,id,showCompletion] of [
  [true,'failed',9,true],[true,'failed',10,false],[true,'failed',11,false],
  [true,'completed',9,false],[false,'failed',9,false]
 ]){
  owner.pipeline=pipeline;
  item.runs=[{status,workflow_id:id}];
  await records(item.id);
  assert.equal(body.includes('scheduledAutomation.linkedTaskCompleted'),showCompletion);
  assert.ok(body.includes('<b>'+status+'</b>'));
 }
});

test('missing, mismatched and previous-scope receipts fall back to the directory',async()=>{
 for(const changes of [{authoringEmployeeReference:null},{authoringEmployeeReference:{...reference,employee_source:'other.json'}},
  {storage_scope:'cloud'},{context:{creator_local_scope:'previous',creator_local_source_id:'draft',creator_employee_source:'employees/a.json'}}]){
  const t=openPanel(changes);await t.automation.refresh();
  assert.equal(t.refreshes(),1);assert.deepEqual(t.reads,[]);
 }
});

test('switching repeat modes validates the visible fields and preserves saved timing',()=>{
 const fields={time:{value:'19:42'},interval:{value:'0'}};
 const item={interval_sec:900,schedule:{time:'08:15',weekdays:[1],timezone:'Asia/Shanghai'}};
 let kind='weekly',days=[0,4];
 const value=vm.runInNewContext(
  script.slice(script.indexOf(' function scheduleValue()'),script.indexOf(' function editOptions('))+'\nscheduleValue',
  {scheduleKind:()=>kind,field:name=>fields[name],form:{item},localError:key=>new Error(key),
   document:{querySelectorAll:()=>days.map(value=>({value:String(value)}))}}
 );
 const weekly=value();
 assert.equal(weekly.interval_sec,900);
 assert.equal(weekly.schedule.time,'19:42');
 assert.deepEqual(Array.from(weekly.schedule.weekdays),[0,4]);
 days=[];
 assert.throws(value,/chooseDay/);
 kind='daily';
 fields.time.value='24:01';
 assert.throws(value,/invalidTime/);
 kind='interval';
 assert.throws(value,/invalidInterval/);
 fields.interval.value='7';
 const interval=value();
 assert.equal(interval.interval_sec,420);
 assert.equal(interval.schedule.time,'08:15');
 assert.deepEqual(Array.from(interval.schedule.weekdays),[1]);
 assert.equal(interval.schedule.timezone,'Asia/Shanghai');
});
