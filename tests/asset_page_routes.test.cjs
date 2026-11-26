const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

test('reopening a chat reads a background delivery and keeps a live local turn attached', async () => {
  const source = fs.readFileSync('web/index.html', 'utf8');
  const start = source.indexOf('function readConversationSession(');
  const end = source.indexOf('function restoreConversationWorkspace(', start);
  const stale = {id: 42, messages: []};
  const delivered = {id: 42, messages: [{role: 'bot', text: 'Delivered'}]};
  const state = {chats: [{id: 42}], conversationPanel: stale};
  const calls = [];
  const context = {
    S: state, cachedConversationPanel: () => stale,
    _workspaceStateByKey: new Map(), _conversationPanelLoadSequence: 0,
    RunTeamsEmployeeDirectory: {employeePanel: () => false, forPanel: () => null, entryFor: () => null},
    workspaceEmployeeWindowIdentity: () => null, hostConversationInRail() {}, closePop() {},
    captureConversationPanelDraft() {}, rememberConversationPanel() {}, restoreConversationPanelDraft() {},
    conversationPanelLoadingState: value => value, conversationPanelFromSession: value => value,
    api: async (url, method, body, options) => { calls.push([url, options.readCurrent]); return delivered; },
  };
  vm.runInNewContext(source.slice(start, end), context);
  const options = {readCurrent: true, focus: false, render: false};
  assert.equal(await context.loadConversationPanelSession(42, options), delivered);
  assert.deepEqual(calls, [['/api/chat/42?messages_limit=30', true]]);
  state.conversationPanel = {id: 42, busy: true, messages: []};
  const live = state.conversationPanel;
  assert.equal(await context.loadConversationPanelSession(42, options), live);
  assert.equal(calls.length, 1);
});

test('employee and pipeline links identify their objects on cold load and after loading chat IDs', () => {
  const host = {
    location: {origin: 'http://localhost'},
    RunTeamsPageRouteContract: JSON.parse(fs.readFileSync('contracts/page-routes.json')),
    RunTeamsHost: {routes: {preview: () => null, resolve: () => null}},
  };
  vm.runInNewContext(fs.readFileSync('web/ui/page-routes.js', 'utf8'), {window: host, URL});
  const routes = host.RunTeamsRoutes;
  const id = '4a7v9bn2';
  const employee = '/employees/' + id, pipeline = '/pipelines/' + id;
  const owners = ['', employee, pipeline];
  const chats = owners.map((owner_path, i) => ({
    resource: 'chats', id: String(42 + i), owner_path, public_id: '8c' + String(i).repeat(6),
  }));
  for (const row of chats) {
    const path = row.owner_path + '/chats/' + row.public_id;
    assert.equal(routes.preview(path).ownerPath, row.owner_path);
  }
  routes.installDevice(chats, 'test-library');
  routes.installDevice([{resource: 'chats', id: chats[1].id, public_id: chats[1].public_id}]);
  for (const row of chats) {
    const path = row.owner_path + '/chats/' + row.public_id;
    assert.equal(routes.toPublic('/chat/' + row.id), path);
    assert.equal(routes.resolve(path).id, Number(row.id));
    assert.equal(routes.resolve(path).ownerPath, row.owner_path);
    assert.equal(routes.toPublic(routes.toInternal(path).href), path);
    for (const wrong of owners.filter(owner => owner !== row.owner_path)) {
      assert.throws(() => routes.toInternal(wrong + '/chats/' + row.public_id));
    }
  }
  for (const parent of ['/chats/new', employee, pipeline]) {
    const retiredQuery = parent + '?chat=' + chats[1].public_id;
    assert.equal(routes.preview(retiredQuery).kind, 'invalid');
    assert.throws(() => routes.toPublic(retiredQuery));
  }
  assert.equal(routes.resolve(employee).kind, 'employee-work');
  assert.equal(routes.resolve(pipeline).kind, 'source-pipeline');
  assert.equal(routes.resolve('/pipelines/new').kind, 'source-pipeline-new');
  const retired = '/pipelines/local/' + 'a'.repeat(64) + '/cGlwZWxpbmVzL21haW4uanNvbg';
  assert.equal(routes.preview(retired).kind, 'invalid');
  assert.throws(() => routes.toPublic(retired));
});

test('opening an employee keeps the employee URL, selecting a conversation opens its own URL', async () => {
  const source = fs.readFileSync('web/index.html', 'utf8');
  const start = source.indexOf('async function openRailConversationSession(');
  const end = source.indexOf('function openConversationSession(', start);
  const employee = '/employees/' + '4a7v9bn2';
  const panel = {id: 42, owner_path: employee};
  const locations = [];
  const context = {
    S: {surface: 'team', conversationPanel: panel},
    workspaceEmployeeWindowIdentity: () => true,
    RunTeamsEmployeeDirectory: {entryFor: key => key, pageRoute: () => employee},
    requestRailReveal() {}, syncRailWidthForMode() {}, saveRailLayout() {},
    setAppUrl: path => locations.push(path),
    loadConversationPanelSession: async () => panel,
  };
  vm.runInNewContext(source.slice(start, end), context);
  for (const [employeeHome, expected] of [[true, employee], [false, employee + '/chats/42']]) {
    locations.length = 0;
    await context.openRailConversationSession(panel.id, {employeeKey: 'source', employeeHome});
    assert.ok(locations.length);
    assert.ok(locations.every(path => path === expected));
  }
});

test('a document revision keeps its version when converted between public and internal routes', () => {
  const host = {
    location: {origin: 'http://localhost'},
    RunTeamsPageRouteContract: JSON.parse(fs.readFileSync('contracts/page-routes.json')),
    RunTeamsHost: {routes: {preview: () => null, resolve: () => null}},
  };
  vm.runInNewContext(fs.readFileSync('web/ui/page-routes.js', 'utf8'), {window: host, URL});
  const routes = host.RunTeamsRoutes;
  const publicId = 'local-' + 'f'.repeat(32);
  routes.installDevice([{resource: 'documents', id: '79', public_id: publicId}], 'test-library');
  const path = '/documents/' + publicId + '?revision=80#section';
  assert.equal(routes.toPublic('/docs?document=79&revision=80#section'), path);
  assert.equal(routes.resolve(path).documentId, 79);
  assert.equal(routes.resolve(path).revisionId, 80);
  assert.equal(routes.resolve(path).anchor, 'section');
  assert.equal(routes.isDeviceRoute(path), true);
  assert.throws(() => routes.resolve(path.replace('revision=80', 'revision=0')));
  assert.throws(() => routes.resolve(path.replace('revision=80', 'revision=80&revision=81')));
});
