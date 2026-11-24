import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createLocalClient} from './community_transport_fixture.mjs';
const ROOT=new URL('../../',import.meta.url);
const source=name=>fs.readFileSync(new URL(name,ROOT),'utf8');
const library={storage_kind:'local',library_id:'a1111111-1111-4111-8111-111111111111',cache_scope:'actual-library',generation:'generation-one'};
const reference={schema:'runteams.local-employee-reference/1',source_id:'a'.repeat(64),employee_source:'employees/main.json',storage_kind:'local',library_id:library.library_id};

test('same settings page reads and saves through generation-bound local client with no GET body',async()=>{
 const requests=[],entry={key:'source:'+reference.source_id+':'+reference.employee_source,source:{id:reference.source_id,path:reference.employee_source},record:{name:'员工'}};
 const state={schema:'runteams.employee-configuration-state/1',reference,revision:0,definition:{schema:'runteams.employee-configuration/1',groups:[{key:"defaults",fields:[{key:"note",type:"text"}]}]},definition_sha256:'hash',values:{note:'original'},states:{note:'configured'},bindings:{},ready:true};
 const S={localLibrary:library,account:{signed_in:false},sel:null,conversationPanel:{id:41}};
 const input={dataset:{key:'note'},value:'original'},form={querySelectorAll:()=>[input]};
 const client=createLocalClient(async(path,options)=>{
  requests.push({path,options});
  assert.equal(options.headers['X-RunTeams-Library'],library.library_id);
  assert.equal(options.headers['X-RunTeams-Library-Generation'],library.generation);
  if(options.method==='GET'){assert.equal(options.body,undefined);return Response.json(state);}
  const operation=JSON.parse(options.body);assert.equal(operation.expected_revision,0);
  assert.equal(operation.values.note,'updated');return Response.json({...state,revision:1,values:operation.values});
 });
 client.libraryId=library.library_id;client.generation=library.generation;
 const c={S,structuredClone,URLSearchParams,crypto:{randomUUID:()=> 'b1111111-1111-4111-8111-111111111111'},console,
  workspaceAccountCacheToken:()=>S.localLibrary.library_id+':'+S.localLibrary.generation,
  document:{addEventListener:()=>{},getElementById:id=>id==='employee_configuration_form'?form:null,querySelector:()=>null},selectDetailWorkspace:value=>{S.sel=value;},render:()=>{},
  RunTeamsBusinessStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},
  api:client.request.bind(client),
  ICON:()=>'',csel:()=>'',addEventListener:()=>{}};
 c.window=c;vm.createContext(c);
 for(const name of ['host','configuration-fields','configuration-form','employee-configuration'])vm.runInContext(source('web/ui/'+name+'.js'),c);
 await c.window.RunTeamsEmployeeConfiguration.open(entry);
 assert.equal(requests.length,1);assert.match(requests[0].path,/\/api\/creator-source\/drafts\/[a-f0-9]{64}\/configuration\?employee_source=/);
 const settings=c.RunTeamsEmployeeConfiguration;
 input.value='updated';settings.capture();await settings.save();
 assert.equal(settings.current().data.revision,1);assert.equal(settings.current().draft,null);
 assert.deepEqual(requests.map(r=>r.options.method),['GET','POST']);S.localLibrary={...library,generation:'generation-two'};assert.equal(c.window.RunTeamsEmployeeConfiguration.current(),null);
});
