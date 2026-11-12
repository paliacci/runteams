const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync('web/ui/source-pipelines.js', 'utf8');
const records = fs.readFileSync('web/ui/work-records.js', 'utf8');
const panels = fs.readFileSync('web/ui/source-pipeline-panels.js', 'utf8');
const reference = {schema: 'runteams.local-pipeline-reference/1', source_id: 'fixture',
  pipeline_source: 'pipelines/example.json', storage_kind: 'local', library_id: 'library'};

function fixture() {
  const state = {surface: 'assistant', conversationPanel: {id: 7}, sel: null};
  const requests = [];
  const workspace = {runtime: {status: 'running'}, workflows: [{id: 42, state: 'needs_human'}], pipeline: {positions: [], states: []}};
  const work = {id: 42, state: 'needs_human', snapshot_json: {pipeline_visit: 4}};
  const context = vm.createContext({
    S: state, window: {addEventListener() {}}, document: {hidden: false, addEventListener() {}},
    _workspaceBusinessGeneration: 1, workspaceAccountCacheToken: () => 'account',
    workspaceDeviceStorageScope: () => 'library', setInterval() {}, render() {},
    selectDetailWorkspace: selection => {state.sel = selection;},
    RunTeamsSourcePipelinePanels: {mountSigningConfiguration() {}},
    RunTeamsWorkRecords: {currentExecutionOutsideHistory() {}, updateTaskList() {}},
    api: async (path, method, data) => {
      requests.push({path, method, data});
      return path.endsWith('/workspace') ? workspace : {workflow: work};
    },
  });
  vm.runInContext(source, context);
  return {context, state, requests, workspace, work, host: context.window.RunTeamsSourcePipelines};
}

test('employee task details read the original task without switching to the pipeline page', async () => {
  const {host, state, requests, workspace, work} = fixture();
  const back = {selection: {type: 'core-results'}, employeeRecords: true};
  await host.openEmployeeTask(reference, 42, {title: 'Original task', returnToRecords: back});
  assert.equal(state.surface, 'assistant');
  assert.equal(state.conversationPanel.id, 7);
  assert.equal(host.current(), null, 'The board context remains separate');
  assert.equal(state.sel.workflow, work);
  assert.equal(state.sel.returnToRecords, back);
  assert.equal(host.taskWorkspace().data, workspace);
  assert.deepEqual(requests.map(row => row.path.split('/').pop()).sort(), ['work', 'workspace']);
  assert.ok(requests.every(row => row.data.reference === reference));
});

test('execution drill-down keeps the employee task context and another employee cannot inherit it', async () => {
  const {host, state} = fixture();
  await host.openEmployeeTask(reference, 42);
  const task = state.sel, workspace = host.taskWorkspace();
  state.sel = {type: 'core-results', returnTo: task};
  assert.equal(host.taskWorkspace(), workspace);
  state.conversationPanel = {id: 8};
  assert.equal(host.taskWorkspace(), null);
});

test('a late task reply cannot replace the selection after leaving the employee', async () => {
  const {host, state, context} = fixture();
  let finish;
  context.api = path => path.endsWith('/work') ? new Promise(resolve => {finish = resolve;}) : Promise.resolve({workflows: []});
  const opening = host.openEmployeeTask(reference, 42);
  state.conversationPanel = {id: 8};
  const next = state.sel = {type: 'employee-configuration'};
  finish({workflow: {id: 42}});
  await opening;
  assert.equal(state.sel, next);
  assert.equal(host.taskWorkspace(), null);
});

test('record routing opens task-backed records through the unified detail and keeps historical reports separate', () => {
  const {host, context} = fixture();
  context.RunTeamsSourcePipelines = host;
  vm.runInContext(records, context);
  const isTask = context.window.RunTeamsWorkRecords.employeeTaskRecord;
  const selection = {type: 'core-results', scope: {employee_reference: {source_id: 'employee'}}};
  for (const state of ['running', 'needs_human', 'needs_approval', 'blocked', 'failed', 'paused', 'completed', 'canceled']) {
    assert.equal(isTask({workflow_id: 42, pipeline_reference: reference, state}, selection), true, state);
  }
  for (const state of ['recorded']) {
    assert.equal(isTask({workflow_id: 42, pipeline_reference: reference, state}, selection), false, state);
  }
  assert.equal(isTask({workflow_id: 42, state: 'needs_human'}, selection), false);
  assert.equal(isTask({workflow_id: 42, task_kind: 'employee', state: 'completed'}, selection), true);
  assert.equal(isTask({workflow_id: 42, task_kind: 'employee', state: 'completed'}, {type: 'core-results', scope: {workflow_id: 42}}), false);
  assert.equal(isTask({workflow_id: 42, pipeline_reference: reference, state: 'needs_human'}, {...selection, attemptContext: {}}), false);
});

test('opening a record sets its durable detail URL after the previous drawer has left', () => {
  const events = [], employee = {schema: 'employee', source_id: 'employee'};
  const result = {key: 'workflow-42', workflow_id: 42, state: 'needs_human', pipeline_reference: reference};
  const owner = {type: 'core-results', scope: {employee_reference: employee}, data: {results: [result]}, resultKey: ''};
  const context = vm.createContext({
    S: {sel: owner, conversationPanel: {id: 7}}, window: {addEventListener() {}},
    URL, location: {href: 'http://localhost/chats/7?results=1'},
    document: {querySelector: () => ({scrollTop: 150})},
    workspaceAccountCacheToken: () => 'account',
    contextResultsRoute: () => '/chats/7?results=1',
    setAppUrl: value => events.push(value),
    RunTeamsEmployeeDirectory: {forPanel: () => ({}), employeePanel: () => true, panelReference: () => employee, referenceKey: JSON.stringify},
    RunTeamsSourcePipelines: {referenceKey: JSON.stringify, openEmployeeTask: (ref, id, options) => {
      assert.equal(id, 42);assert.equal(ref, reference);
      assert.equal(options.returnToRecords.selection, owner);
      events.push('select-task-and-clear-old-query');
    }},
  });
  vm.runInContext(records, context);
  context.window.RunTeamsWorkRecords.openEmployeeTask('workflow-42');
  assert.deepEqual(events, ['select-task-and-clear-old-query', '/chats/7?results=1&delivery=workflow-42']);
  assert.equal(owner.recordPositions.list, 150);
});

test('another open pipeline refreshes the same task after a committed change and ignores other owners', async () => {
  const updates = source.slice(source.indexOf(' const workUpdateOwner='), source.indexOf(' let activityConnection;'));
  const workspace = {reference}, owner = {type: 'source-pipeline', id: 'work', workflowId: 42};
  let boardReads = 0, taskReads = 0;
  const context = vm.createContext({
    workspaceAccountCacheToken: () => 'account', workspaceDeviceStorageScope: () => 'library',
    S: {sel: owner}, window: {}, document: {hidden: false},
    referenceKey: ref => JSON.stringify(ref), taskWorkspace: () => workspace,
    ownsTask: value => value === workspace,
    refresh: async () => {boardReads++;},
    refreshOpenWork: async (value, selection, options) => {
      assert.equal(value, workspace); assert.equal(selection, owner); assert.equal(options.force, true); taskReads++;
    },
  });
  vm.runInContext(updates, context);
  await context.receiveWorkUpdate({owner: JSON.stringify(['other', 'library']), reference, workflowId: 42});
  assert.equal(boardReads, 0);
  await context.receiveWorkUpdate({owner: JSON.stringify(['account', 'library']), reference, workflowId: 42});
  assert.equal(boardReads, 1);
  assert.equal(taskReads, 1);
});

test('confirming from the employee commits once and updates another open pipeline task', async () => {
  const channels = [];
  class Channel {
    constructor() {channels.push(this);}
    postMessage(data) {for (const other of channels) if (other !== this) other.onmessage?.({data});}
  }
  const actor = fixture(), board = fixture();
  let work = {id: 42, state: 'needs_human', cursor_key: 'review', updated_at: 'waiting', snapshot_json: {pipeline_visit: 4}};
  let commits = 0;
  for (const value of [actor, board]) {
    value.context.BroadcastChannel = Channel;
    value.context.api = async (path, method, command) => {
      if (path.endsWith('/flow')) {
        assert.equal(command.workflow_id, 42);
        assert.equal(command.expected_visit, 4);
        commits++;
        work = {...work, state: 'ready', updated_at: 'confirmed', snapshot_json: {pipeline_visit: 5}};
        return {status: 'committed', result: {workflow: structuredClone(work)}};
      }
      if (path.endsWith('/workspace')) return {runtime: {status: 'running'}, pipeline: {positions: [], states: []}, workflows: [structuredClone(work)]};
      return {workflow: structuredClone(work)};
    };
    vm.runInContext(source, value.context);
    value.host = value.context.window.RunTeamsSourcePipelines;
  }
  await actor.host.openEmployeeTask(reference, 42);
  board.state.surface = 'source-pipeline';
  board.state.sourcePipelineWorkspace = {scope: JSON.stringify([1, 'account', 'library']), reference, view: 'board',
    data: {runtime: {status: 'running'}, workflows: [structuredClone(work)]}};
  board.state.sel = {type: 'source-pipeline', id: 'work', workflowId: 42, workflow: structuredClone(work)};
  const original = actor.state.sel, store = new Map();
  Object.assign(actor.context, {
    current: () => actor.host.taskWorkspace(), owned: s => actor.host.taskWorkspace() === s,
    host: () => actor.host, activeTaskConfiguration: () => null,
    crypto: {randomUUID: () => 'original-operation'},
    RunTeamsWorkState: {getItem: key => store.get(key), setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key)},
  });
  actor.context.document.querySelector = selector => selector.includes('source_pipeline_choice') ? {value: '5 minutes'} : null;
  actor.context.document.getElementById = () => null;
  vm.runInContext(panels.slice(panels.indexOf('const flowKey='), panels.indexOf('function inputDraft(')), actor.context);
  await Promise.all([actor.context.flow('respond'), actor.context.flow('respond')]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(commits, 1);
  assert.equal(actor.state.sel, original);
  assert.equal(actor.state.surface, 'assistant');
  assert.equal(original.workflow.state, 'ready');
  assert.equal(board.state.sel.workflow.state, 'ready');
  assert.equal(board.state.sourcePipelineWorkspace.data.workflows[0].state, 'ready');
});
