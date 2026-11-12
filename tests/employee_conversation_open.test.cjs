const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

test('employee click paints the chosen conversation layout before opening it', async () => {
  const reference = {schema:'runteams.business-reference/v1', deployment_id:'device',
    workspace_id:'owner', data_epoch:'employee', resource:'employees', id:7};
  const empty = {id:12, updated_at:'2026-11-13', storage_scope:'device', last_message_id:null};
  const entry = {key:'employee', record:{name:'Employee'}, reference,
    work:{id:7}, conversation:empty, open:{employee_id:7}};
  const state = {chats:[], localLibrary:{library_id:'fixture'}};
  const layouts = [];
  const host = {
    S:state, _workspaceBusinessGeneration:1, _detailOpenSequence:0,
    workspaceAccountCacheToken:()=> 'owner',
    RunTeamsHost:{session:{workspace:()=>false}},
    api:async()=>({schema:'runteams.employee-directory/v1', items:[entry], activity:{chats:[],workflows:[]}}),
    deviceChatRemember(){}, addEventListener(){}, render(){},
    workspaceBeginEmployeeOpen(key, layout){
      assert.equal(key, entry.key);
      layouts.push(layout);
      return state.workspaceSwitchPending = {employeeOpen:{}};
    },
    workspaceFinishSwitchPending(){ state.workspaceSwitchPending = null; },
    async openBotConversation(id){ assert.equal(id, 7); },
  };
  host.window = host;
  vm.runInNewContext(fs.readFileSync('web/ui/employee-directory.js', 'utf8'), host);
  const directory = host.RunTeamsEmployeeDirectory;
  await directory.refresh();
  assert.equal(directory.workConversation(entry).id, empty.id);
  await directory.open(entry.key);

  const history = {id:10, kind:'general', employee_id:7, last_message_id:1,
    updated_at:'2026-11-12', storage_scope:'device', context:{context_type:'worker', employee_reference:reference}};
  state.chats.push(history);
  assert.equal(directory.workConversation(entry).id, history.id);
  await directory.open(entry.key);
  await directory.newSession(entry.key);
  assert.deepEqual(layouts, ['employee', 'history', 'employee']);

  directory.forgetConversation(empty.id);
  state.chats = [];
  assert.equal(directory.workConversation(entry), null);
});
