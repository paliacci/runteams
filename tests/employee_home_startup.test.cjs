const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync('web/ui/source-pipelines.js', 'utf8');

for (const outcome of ['opened', 'directory unavailable', 'account changed']) {
  test('employee home sidebar ordering when ' + outcome, async () => {
    const requests = [];
    let finishRoute;
    const host = {
      S: {}, location: {href: 'http://localhost/employees/example'},
      _workspaceBusinessGeneration: 0,
      workspaceAccountCacheToken: () => 'account',
      workspaceDeviceStorageScope: () => 'library',
      RunTeamsHost: {session: {ready: () => true, actor: () => 'account'}},
      RunTeamsRoutes: {preview: () => ({kind: 'employee-work'})},
      RunTeamsRequests: {finishPage() {}},
      document: {addEventListener() {}}, addEventListener() {}, setInterval() {},
      loadWorkspaceWindows: () => [], loadConversationPanelDrafts: () => ({}),
      restoreModelCatalogDisplay() {}, render() {},
      accountSettingsReadPreferences: async () => ({}),
      modelChannelData: () => ({configuration: async () => ({})}),
      applyAppRoute() {
        requests.push('employee');
        return new Promise(resolve => { finishRoute = resolve; });
      },
      async refreshDeviceDirectory() { requests.push('chats'); },
      async refreshWorkspaceNavigation(options) { requests.push(options.employees); },
      renderBootShell(route, error) { throw error; },
    };
    host.window = host;
    vm.runInNewContext(source, host);
    const boot = host.RunTeamsSourcePipelines.boot(Promise.resolve(), {});
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(requests, ['employee']);
    host.S.coreTeamLoaded = outcome === 'opened';
    if (outcome === 'account changed') host._workspaceBusinessGeneration++;
    finishRoute();
    await boot;
    assert.deepEqual(requests, outcome === 'account changed' ? ['employee']
      : ['employee', 'chats', outcome === 'directory unavailable']);
  });
}
