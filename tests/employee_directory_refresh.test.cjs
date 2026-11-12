const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/ui/employee-directory.js'), 'utf8');

for (const organization of [false, true]) {
 test(`background employee refresh is scoped and throttled (${organization ? 'organization' : 'personal'})`, async () => {
  let now = 0, scope = 'first', fullReads = 0, localReads = 0, unavailable = false;
  const context = {
   Date: {now: () => now}, S: {booting: true}, _workspaceBusinessGeneration: 1,
   workspaceAccountCacheToken: () => scope, refreshBotList() {}, deviceChatRemember() {}, addEventListener() {},
   RunTeamsHost: {session: {workspace: () => organization, actor: () => scope}},
   api: async url => {
    const local = url.endsWith('?view=local');
    if (local) localReads++;
    else fullReads++;
    return {schema: 'runteams.employee-directory/v1', items: [], activity: {chats: [], workflows: []},
     errors: !local && unavailable ? {assets: {error: 'offline'}} : {}};
   },
  };
  context.window = context;
  vm.runInNewContext(source, context);
  const {refresh} = context.RunTeamsEmployeeDirectory;
  const poll = async () => {
   await refresh({readPriority: 'background'});
   await new Promise(setImmediate);
  };

  await poll();
  now = 60_000;
  await poll();
  assert.equal(fullReads, 1);
  assert.equal(localReads, organization ? 0 : 2);

  await refresh();
  assert.equal(fullReads, 2, 'explicit refresh bypasses the background interval');
  now += 300_000;
  unavailable = true;
  await poll();
  assert.equal(fullReads, 3);
  now += 59_000;
  await poll();
  assert.equal(fullReads, 3);
  now += 1000;
  unavailable = false;
  await poll();
  assert.equal(fullReads, 4, 'failed cloud reads retry after one minute');

  scope = 'second';
  await poll();
  assert.equal(fullReads, 5, 'another account or workspace gets its own initial read');
 });
}
