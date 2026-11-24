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

test('missing, mismatched and previous-scope receipts fall back to the directory',async()=>{
 for(const changes of [{authoringEmployeeReference:null},{authoringEmployeeReference:{...reference,employee_source:'other.json'}},
  {storage_scope:'cloud'},{context:{creator_local_scope:'previous',creator_local_source_id:'draft',creator_employee_source:'employees/a.json'}}]){
  const t=openPanel(changes);await t.automation.refresh();
  assert.equal(t.refreshes(),1);assert.deepEqual(t.reads,[]);
 }
});
