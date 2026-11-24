const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

test('overview can use a matching live chat receipt until its directory is authoritative',async()=>{
 const c={S:{},_workspaceBusinessGeneration:1,workspaceAccountCacheToken:()=>'actor',
  RunTeamsHost:{session:{workspace:()=>false,deviceScope:()=>'scope',actor:()=>''}},
  addEventListener(){},deviceChatRemember(){},api:async()=>({schema:'runteams.employee-directory/v1',items:[],activity:{chats:[],workflows:null}})};
 c.window=c;vm.runInNewContext(fs.readFileSync('web/ui/employee-directory.js','utf8'),c);
 const directory=c.RunTeamsEmployeeDirectory;
 const ref={schema:'runteams.local-employee-reference/1',source_id:'draft',employee_source:'a.json',account_id:'a',deployment_id:'d',storage_namespace:'s'};
 const employee={key:'source:draft:a.json',record:{name:'A'},source:{id:'draft',path:'a.json',reference:ref}};
 const panel={storage_scope:'device',kind:'employee_design',context:{creator_local_scope:'scope',creator_local_source_id:'draft',creator_employee_source:'a.json'}};
 c.S.conversationPanel=panel;
 for(const invalid of [{...employee,trashed:true},{...employee,key:'different'},{...employee,source:{...employee.source,path:'b.json'}}]){
  directory.rememberSessionEntry(panel,invalid);assert.equal(directory.overviewEntry(),null);
 }
 directory.rememberSessionEntry(panel,employee);
 assert.equal(directory.forPanel(),null);assert.equal(directory.overviewEntry(),employee);
 c._workspaceBusinessGeneration++;assert.equal(directory.overviewEntry(),null);
 directory.rememberSessionEntry(panel,employee);
 panel.context.creator_local_scope='other';assert.equal(directory.overviewEntry(),null);
 panel.context.creator_local_scope='scope';assert.equal(directory.overviewEntry(),employee);
 c.S.booting=true;c.S.localLibrary={cache_scope:'scope',library_id:'local'};
 assert.equal(directory.overviewEntry(),null);
 await directory.refresh({localFirst:true});delete c.S.localLibrary;
 assert.equal(directory.overviewEntry(),null);
});
