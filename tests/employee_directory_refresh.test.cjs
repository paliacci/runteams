const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/ui/employee-directory.js'), 'utf8');

test('global and employee searches keep their results during IME selection and cancellation', () => {
 const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
 const functions = ['bindSearchInput', 'searchKeyComposing', 'railSearchInput', 'botListSearchInput', 'botListSearchKeydown'];
 let searches = 0;
 const context = {S: {railQuery: ''}, _botListQuery: '', document: {querySelector: () => null},
  searchRailDocuments: () => searches++, refreshBotList: () => searches++};
 for (const name of functions) {
  const start = html.indexOf('function ' + name + '(');
  assert.notEqual(start, -1);
  vm.runInNewContext(html.slice(start, html.indexOf('\n}', start) + 2), context);
 }
 for (const update of [context.railSearchInput, context.botListSearchInput]) {
  searches = 0;
  const input = Object.assign(new EventTarget(), {value: '', dataset: {}});
  context.bindSearchInput(input, update);
  context.bindSearchInput(input, update);
  input.dispatchEvent(new Event('compositionstart'));
  input.value = "ni'hao";
  input.dispatchEvent(new Event('input'));
  assert.equal(context.searchKeyComposing({target: input}), true);
  context.botListSearchKeydown({key: 'Escape', target: input});
  assert.equal(searches, 0);
  input.value = '你好';
  input.dispatchEvent(new Event('compositionend'));
  input.dispatchEvent(new Event('input'));
  assert.equal(searches, 1);
  input.dispatchEvent(new Event('compositionstart'));
  input.value += 'zai';
  input.dispatchEvent(new Event('input'));
  input.value = '你好';
  input.dispatchEvent(new Event('compositionend'));
  assert.equal(searches, 1);
  assert.equal(context.searchKeyComposing({keyCode: 229, target: input}), true);
  input.value = '';
  input.dispatchEvent(new Event('input'));
  assert.equal(searches, 2);
 }
});

for (const organization of [false, true]) {
 test(`background employee refresh is scoped and throttled (${organization ? 'organization' : 'personal'})`, async () => {
  let now = 0, scope = 'first', fullReads = 0, localReads = 0, unavailable = false;
  const context = {
   Date: {now: () => now}, S: {booting: true}, _workspaceBusinessGeneration: 1,
   workspaceAccountCacheToken: () => scope, refreshBotList() {}, deviceChatRemember() {}, addEventListener() {},
   RunTeamsHost: {session: {workspace: () => organization, actor: () => scope}},
   api: async url => {
    const local = url.includes('?view=');
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

test('employee link waits for the existing cloud directory read', async () => {
 let releaseCloud, fullReads = 0;
 const reference = (id, workspace_id = 'example-workspace') => ({
  schema: 'runteams.business-reference/v1', deployment_id: 'https://example.invalid/auth/v1',
  workspace_id, data_epoch: 'example-epoch', resource: 'employees', id,
 });
 const employee = {key: 'employee:51', record: {name: 'Target employee'}, asset: {id: 51, reference: reference(51)}, open: {employee_id: 51}};
 const local = {key: 'work:51', record: {name: 'Different employee'}, work: {id: 51}, open: {employee_id: 51}};
 const receipt = (items, errors = {}) => ({
  schema: 'runteams.employee-directory/v1', items, errors, activity: {chats: [], workflows: []},
 });
 const context = {
  S: {booting: true}, _workspaceBusinessGeneration: 1, workspaceAccountCacheToken: () => 'actor',
  deviceChatRemember() {}, addEventListener() {}, refreshBotList() {},
  RunTeamsHost: {assets: {remember() {}}, session: {workspace: () => false, actor: () => 'actor', ready: () => true}},
  api: async url => {
   if (url.includes('?view=')) return receipt([]);
   fullReads++;
   return new Promise(resolve => { releaseCloud = resolve; });
  },
 };
 context.window = context;
 vm.runInNewContext(source, context);
 const directory = context.RunTeamsEmployeeDirectory;

 await directory.refresh({localFirst: true});
 let resolved = false;
 const route = directory.resolveAsset(reference(51)).then(entry => { resolved = true; return entry; });
 await new Promise(setImmediate);
 assert.equal(resolved, false);
 assert.equal(fullReads, 1);
 releaseCloud(receipt([local, employee]));
 assert.equal(await route, employee);
 assert.equal(await directory.resolveAsset(reference(51)), employee);
 assert.equal(fullReads, 1);

 const unavailable = directory.resolveAsset(reference(52));
 releaseCloud(receipt([employee], {assets: {error: 'offline'}}));
 await assert.rejects(unavailable, /offline/);
 const retry = directory.resolveAsset(reference(51, 'different-workspace'));
 releaseCloud(receipt([employee]));
 assert.equal(await retry, null);

 const previousAccount = directory.resolveAsset(reference(52));
 context._workspaceBusinessGeneration++;
 directory.reset();
 releaseCloud(receipt([{...employee, asset: {id: 52, reference: reference(52)}}]));
 assert.equal(await previousAccount, null);
 assert.equal(directory.current().length, 0);
});

test('installation labels require a directory that includes downloads for this account', async () => {
 let account = 'first', errors = {downloads: {error: 'offline'}};
 const context = {
  S: {booting: true, localLibrary: {library_id: 'library'}}, _workspaceBusinessGeneration: 1,
  workspaceAccountCacheToken: () => account, deviceChatRemember() {}, addEventListener() {},
  RunTeamsHost: {session: {workspace: () => false}},
  api: async () => ({schema: 'runteams.employee-directory/v1', items: [], activity: {chats: [], workflows: []}, errors}),
 };
 context.window = context;
 vm.runInNewContext(source, context);
 const directory = context.RunTeamsEmployeeDirectory;
 assert.equal(directory.downloadsReady(), false);
 await directory.refresh();
 assert.equal(directory.downloadsReady(), false);
 errors = {};
 await directory.refresh();
 assert.equal(directory.downloadsReady(), true, 'a confirmed empty directory counts');
 account = 'second';
 assert.equal(directory.downloadsReady(), false);
});

test('employee sidebar waits for a confirmed directory outcome', () => {
 const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
 const start = html.indexOf('function botListRowsMarkup()');
 const render = html.slice(start, html.indexOf('\n}', start) + 2);
 const startup = html.slice(html.indexOf('function botListStartupError()'), html.indexOf('async function retryBotList()'));
 let reading = false;
 const context = {
  S: {coreTeamLoaded: false, coreTeamError: ''},
  RunTeamsEmployeeDirectory: {current: () => [], pinnedKeys: () => [], isLoading: () => reading},
  RunTeamsHost: {}, botListVisibleEmployees: () => [], botListEmployeeRows: () => '',
  botListSearchQuery: () => '', railListSkeleton: () => 'loading',
  RunTeamsLoadFailure: {pending: () => '', markup: ({error}) => error},
  RunTeamsEmptyStates: {markup: () => 'empty'},
 };
 vm.runInNewContext(startup + render, context);
 assert.equal(context.botListRowsMarkup(), 'loading');
 reading = true;
 assert.equal(context.botListRowsMarkup(), 'loading');
 reading = false;
 context.S.coreTeamError = 'offline';
 assert.equal(context.botListRowsMarkup(), 'offline');
 context.S.coreTeamError = '';
 context.S.workspaceStartup = {pending: true, errorStage: 'account', error: 'session unavailable'};
 assert.equal(context.botListRowsMarkup(), 'session unavailable');
 context.S.workspaceStartup = null;
 context.S.coreTeamLoaded = true;
 assert.equal(context.botListRowsMarkup(), 'empty');
});

test('first personal roster includes cloud employees before painting or revalidating', async () => {
 const asset = {key:'cloud', record:{name:'Cloud'}, asset:{}, open:{}};
 const local = {key:'local', record:{name:'Local'}, open:{}};
 for (const checked of [true, false]) {
  const paths = [];
  const context = {S:{booting:true}, _workspaceBusinessGeneration:1, workspaceAccountCacheToken:()=>'account',
   RunTeamsHost:{session:{workspace:()=>false,actor:()=>'account'}}, deviceChatRemember(){}, addEventListener(){},
   api:async url=>{
    paths.push(url);
    const startup = url.endsWith('?view=startup');
    return {schema:'runteams.employee-directory/v1', items:startup?[local,asset]:[local], catalog_refresh_in_ms:checked?10000:null,
     activity:{chats:[],workflows:[]}, errors:startup?{}:{assets:{error:'offline'}}};
   }};
  context.window=context;
  vm.runInNewContext(source,context);
  await context.RunTeamsEmployeeDirectory.refresh({localFirst:true});
  await new Promise(setImmediate);
  assert.equal(paths[0],'/api/employee-directory?view=startup');
  assert.equal(paths.length,checked?1:2);
  assert.deepEqual(Array.from(context.RunTeamsEmployeeDirectory.current(),row=>row.key),['local','cloud']);
  if (!checked) assert.equal(context.S.coreTeamError,'offline');
 }
});
