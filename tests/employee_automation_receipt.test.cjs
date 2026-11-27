const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('web/ui/employee-automation.js','utf8');
test('submitting a calendar draft keeps the timezone displayed in its editor',()=>{
 const start=script.indexOf('function scheduleValue()'),end=script.indexOf('function editOptions(',start);
 const read=vm.runInNewContext('('+script.slice(start,end).trim()+')',{
  form:{item:null,timezone:'America/New_York'},scheduleKind:()=>'daily',field:()=>({value:'07:15'}),
  Intl:{DateTimeFormat:()=>({resolvedOptions:()=>({timeZone:'Asia/Shanghai'})})}
 });
 assert.equal(read().schedule.timezone,'America/New_York');
});

test('calendar schedules retain their zone and repeated local hours identify distinct runs',()=>{
 const source=fs.readFileSync('web/index.html','utf8'),start=source.indexOf('function automationClockLabel(');
 class NewYorkDate extends Date{
  toLocaleString(locale,options){return super.toLocaleString(locale,{...options,timeZone:'America/New_York'});}
 }
 const locale={language:'en'},ctx={window:{RunTeamsLocale:locale},Date:NewYorkDate};
 vm.runInNewContext(source.slice(start,source.indexOf('window.addEventListener',start)),ctx);
 for(const language of ['en','zh-CN']){
  locale.language=language;
  const early=ctx.automationRunTime('2027-11-07T05:30:00Z'),late=ctx.automationRunTime('2027-11-07T06:30:00Z');
  for(const time of [early,late]){assert.match(time,/2027/);assert.match(time,/1:30/);}
  assert.match(early,/GMT-4/);assert.match(late,/GMT-5/);
  const schedule={time:'09:15',weekdays:[1],timezone:'Asia/Kathmandu'};
  for(const kind of ['daily','weekly'])assert.match(ctx.automationListSchedule({schedule_kind:kind,schedule}),/09:15 · Asia\/Kathmandu/);
  assert.doesNotMatch(ctx.automationListSchedule({schedule_kind:'interval',interval_sec:3600,schedule}),/Kathmandu/);
 }
 assert.equal(ctx.automationRunTime(null),'—');assert.equal(ctx.automationRunTime('unknown'),'unknown');
});

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

test('automation row waits for the updated revision before enabling actions',()=>{
 const row=vm.runInNewContext(
  script.slice(script.indexOf(' const vars=name=>'),script.indexOf(" window.addEventListener('runteams:languagechange'"))+'\nrow',
  {esc:String,copy:key=>key,ICON:()=>'',automationListSchedule:()=>'',pending:()=>null}
 );
 const plan={id:1,name:'Daily review',enabled:true,runs:[]};
 const disabledControls=state=>Array.from(row(plan,state).matchAll(/<button\b[^>]*>/g),
  ([tag])=>[tag.match(/data-schedule-control="([^"]+)"/)[1],/\sdisabled\b/.test(tag)]);
 assert.deepEqual(disabledControls({loading:true,busy:false}),[['toggle',true],['history',false],['menu',true]]);
 assert.deepEqual(disabledControls({loading:false,error:'Read failed'}),[['toggle',true],['history',false],['menu',true]]);
 assert.deepEqual(disabledControls({loading:false,busy:false}),[['toggle',false],['history',false],['menu',false]]);
});

function historyDialog(){
 const owner={pipeline:true,owner:{data:{workflows:[{id:9,state:'completed'},{id:10,state:'failed'}]}}};
 const item={id:2,name:'Daily review',runs:[]};
 let body;
 const records=vm.runInNewContext(
  script.slice(script.indexOf(' const runStates='),script.indexOf(' const copy='))+
  script.slice(script.indexOf(' async function records(id)'),script.indexOf(' function closeRecords(id)'))+'\nrecords',
  {current:()=>owner,refresh:async()=>{},document:{getElementById:()=>null},find:()=>item,
   copy:key=>key,esc:s=>s,vars:()=>'',automationRunTimeMarkup:()=>'',
   openDialog:options=>{body=options.body;return {querySelector:()=>null}}}
 );
 return async(pipeline,run)=>{
  owner.pipeline=pipeline;item.runs=[run];
  await records(item.id);
  return body;
 };
}

test('failed schedule history shows completion only for its own recovered team task',async()=>{
 const render=historyDialog();
 for(const [pipeline,status,id,showCompletion] of [
  [true,'failed',9,true],[true,'failed',10,false],[true,'failed',11,false],
  [true,'completed',9,false],[false,'failed',9,false]
 ]){
  const body=await render(pipeline,{status,workflow_id:id});
  assert.equal(body.includes('scheduledAutomation.linkedTaskCompleted'),showCompletion);
  assert.ok(body.includes('<b>automationList.'+status+'</b>'));
 }
});

test('team history names an outstanding decision and preserves the generic blocked state',async()=>{
 const render=historyDialog();
 for(const state of ['needs_approval','needs_human']){
  assert.ok((await render(true,{status:'blocked',workflow_state:state})).includes('<b>workRecords.state.'+state+'</b>'));
 }
 assert.ok((await render(true,{status:'blocked'})).includes('<b>scheduledAutomation.needsAttention</b>'));
});

test('employee and team history translate a user-skipped occurrence and retain other reasons',async()=>{
 const render=historyDialog();
 const trashed=await render(true,{status:'skipped',reason:'触发时智能体团队已在垃圾箱，本次未创建工作。'});
 assert.ok(trashed.includes('scheduledAutomation.skippedInTrash'));
 const employee=await render(false,{status:'skipped',reason:'员工已在垃圾箱，本次未创建工作。'});
 assert.ok(employee.includes('scheduledAutomation.employeeInTrash'));
 for(const pipeline of [false,true]){
  const manual=await render(pipeline,{status:'skipped',reason:'用户已跳过这一次定时。'});
  assert.ok(manual.includes('scheduledAutomation.skippedByUser'));
  const other=await render(pipeline,{status:'skipped',reason:'Custom skip reason'});
  assert.ok(other.includes('Custom skip reason'));
  assert.ok(!other.includes('scheduledAutomation.skippedByUser'));
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
  {scheduleKind:()=>kind,field:name=>fields[name],form:{item,timezone:item.schedule.timezone},localError:key=>new Error(key),
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
