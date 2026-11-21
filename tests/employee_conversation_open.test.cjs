const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

test('employee click paints the chosen conversation layout before opening it', async () => {
  const reference = {schema:'runteams.business-reference/v1', deployment_id:'device',
    workspace_id:'owner', data_epoch:'employee', resource:'employees', id:7};
  const empty = {id:12, updated_at:'2026-11-13', storage_scope:'device', last_message_id:null};
  const entry = {key:'employee', page_id:'4a7v9bn2', record:{name:'Employee'}, reference,
    work:{id:7}, conversation:empty, open:{employee_id:7}};
  const state = {chats:[], localLibrary:{library_id:'fixture'}};
  const layouts = [];
  const host = {
    S:state, _workspaceBusinessGeneration:1, _detailOpenSequence:0,
    workspaceAccountCacheToken:()=> 'owner',
    RunTeamsHost:{session:{workspace:()=>false}},
    api:async()=>({schema:'runteams.employee-directory/v1', items:[entry], activity:{chats:[],workflows:[]}}),
    deviceChatRemember(){}, addEventListener(){}, render(){},
    workspaceBeginEmployeeOpen(key, layout, route){
      assert.equal(key, entry.key);
      assert.equal(route, '/employees/'+entry.page_id);
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

test('employee page refresh keeps the welcome layout until its session is ready', () => {
  const host = {
    S:{conversationPanel:null},
    parseAppRoute:()=>({kind:'employee-work'}),
    conversationDebugDescriptor:()=>null, conversationDebugPanel:panel=>panel,
    railConversationIsVisible:panel=>!!panel, conversationHeaderMarkup:()=>'',
    RunTeamsStaticPages:{localConversationRoute:()=>false, conversationWelcome:kind=>kind, composer:()=>''},
    RunTeamsLoadFailure:{pending:()=>null}, localConversationLayout:()=>'',
    RunTeamsHost:{pages:{}},
  };
  host.window = host;
  vm.createContext(host);
  vm.runInContext(fs.readFileSync('web/ui/page-skeletons.js', 'utf8'), host);
  host.bootSkeletonKind = host.RunTeamsSkeletons.normalize;
  const html = fs.readFileSync('web/index.html', 'utf8');
  const render = html.match(/^function railConversation\(options=\{\}\)\{[\s\S]*?^\}/m)[0];
  vm.runInContext(render, host);

  assert.equal(host.railConversation(), 'employee');
  host.S.conversationPanel = {id:12, loading:true, loadingLayout:'employee'};
  assert.equal(host.railConversation(), 'employee');
  host.S.conversationPanel.loadingLayout = 'history';
  assert.match(host.railConversation(), /data-skeleton-region="conversation-messages"/);
  host.localConversationLayout = ()=>'history';
  host.S.conversationPanel.loadingLayout = 'employee';
  assert.match(host.railConversation(), /data-skeleton-region="conversation-messages"/);
});
