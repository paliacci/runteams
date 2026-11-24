const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const panels = fs.readFileSync('web/ui/source-pipeline-panels.js', 'utf8');
const workspace = fs.readFileSync('web/ui/source-pipelines.js', 'utf8');

function fixture() {
  const env = vm.createContext({esc: String});
  vm.runInContext(panels.slice(panels.indexOf('const defaultTone='), panels.indexOf('function groupMenu(')), env);
  env.RunTeamsSourcePipelinePanels = {columns: env.columns};
  vm.runInContext(workspace.slice(workspace.indexOf(' function boardWorkflows('), workspace.indexOf(' function statusMarkup(')), env);
  const state = {boardPreferences: {}, data: {pipeline: {
    positions: [{key: 'scout', kind: 'employee'}],
    states: [{key: 'empty', kind: 'done', records_only: true},
      {key: 'done', kind: 'done'}, {key: 'dropped', kind: 'dropped'}],
  }, workflows: [
    {id: 1, state: 'completed', cursor_key: 'empty'},
    {id: 2, state: 'running', cursor_key: 'scout'},
    {id: 3, state: 'completed', cursor_key: 'done'},
    {id: 4, state: 'canceled', cursor_key: 'dropped'},
  ]}};
  return {env, state};
}

test('record-only completion has no board card or column, without deleting the record', () => {
  const {env, state} = fixture();
  const before = JSON.stringify(state.data);
  assert.deepEqual(Array.from(env.columns(state), x => x.key), ['scout', 'done', 'dropped']);
  assert.deepEqual(Array.from(env.boardWorkflows(state), x => x.id), [2, 3, 4]);
  assert.equal(JSON.stringify(state.data), before, 'Records and reports keep the original ledger');
  const records = {window: {addEventListener() {}}};
  vm.createContext(records);
  vm.runInContext(fs.readFileSync('web/ui/work-records.js', 'utf8'), records);
  assert.deepEqual(Array.from(records.window.RunTeamsWorkRecords.taskResults(state.data.workflows, {}).results,
    x => x.workflow_id), [4, 3, 2, 1], 'The existing execution-record entry still opens the completed run');
  state.boardPreferences.hidden = ['scout'];
  assert.deepEqual(Array.from(env.columns(state, true), x => x.key), ['scout', 'done', 'dropped'], 'Show all cannot reveal record-only completions');
});

test('an unfinished or failed execution is never concealed by a record-only destination', () => {
  for (const status of ['running', 'needs_human', 'failed', 'canceled']) {
    const {env, state} = fixture();
    state.data.workflows.push({id: 5, state: status, cursor_key: 'empty'});
    assert.ok(env.columns(state).some(x => x.key === 'empty'));
    assert.deepEqual(Array.from(env.boardWorkflows(state), x => x.id), [2, 3, 4, 5]);
  }
});

test('ordinary completions remain visible and the setting is reversible', () => {
  const {env, state} = fixture();
  delete state.data.pipeline.states[0].records_only;
  assert.equal(env.columns(state).length, 4);
  assert.equal(env.boardWorkflows(state).length, 4);
});

test('header status retains work from a position removed in a newer release', () => {
  const source = fs.readFileSync('web/ui/source-pipelines.js', 'utf8');
  const context = {referenceKey: () => 'team', RunTeamsHeaderStatus: {
    phases: {running: [3, '正在处理']}, markup: (_owner, items) => items,
  }};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf(' function statusMarkup('), source.indexOf(' function editName(')), context);
  const state = {reference: {}, data: {runtime: {status: 'running'}, pipeline: {positions: [], states: []},
    workflows: [{id: 1, cursor_key: 'old-position', state: 'running', title: 'Original work'}]}};
  assert.equal(context.statusMarkup(state)[0].id, 1);
  state.data.runtime.status = 'paused';
  assert.equal(context.statusMarkup(state), '');
});

test('paused and failed records show their own execution previews', async () => {
  const reference = {source_id: 'pipeline'};
  const workspace = {reference, data: {workflows: [
    {id: 1, state: 'paused'}, {id: 2, state: 'failed', summary: 'Older task summary'},
    {id: 3, state: 'completed', summary: 'Submitted result'}, {id: 4, state: 'failed'},
    {id: 5, state: 'paused', summary: 'Saved progress'},
  ]}};
  const selection = {type: 'source-pipeline', id: 'settings', activityExpanded: true};
  const attempts = new Map([
    [1, [{id: 3, state: 'completed', output_json: {summary: 'Latest completed step'}},
      {id: 4, state: 'failed', failure_reason: 'Previous failure'}]],
    [2, [{id: 7, state: 'failed', failure_reason: 'Connection interrupted'},
      {id: 6, state: 'completed', output_json: {summary: 'Previous success'}}]],
    [4, [{id: 8, state: 'failed', output_json: {issues: ['请查看原工作对话。']}}]],
  ]);
  const requests = [];
  const replies = new Map();
  let paints = 0;
  const context = vm.createContext({
    window: {addEventListener() {}}, S: {sel: selection}, render() { paints++; }, esc: String, ICON: () => '',
    workRecordStateCopy: value => ({key: 'state.' + value, label: value}), coreWorkflowStateClass: String,
    RunTeamsSourcePipelines: {
      taskWorkspace: () => workspace, referenceKey: ref => ref.source_id,
      request(action, {workflow_id: id}) {
        assert.equal(action, 'work');
        requests.push(id);
        return new Promise(resolve => replies.set(id, () => resolve({pipeline_reference: reference, workflow: {
          id, state: workspace.data.workflows.find(row => row.id === id).state, employee_runs: attempts.get(id),
        }})));
      },
    },
  });
  vm.runInContext(fs.readFileSync('web/ui/work-records.js', 'utf8'), context);
  const records = context.window.RunTeamsWorkRecords;
  let rows;
  function draw(){
    rows=records.taskResults(workspace.data.workflows,reference).results;
    records.activityPreviews(selection,workspace,rows);
  }
  const row = id => records.rowMarkup(rows.find(item => item.workflow_id === id),'open()');
  draw();
  assert.deepEqual(requests, [4, 2, 1]);
  replies.get(1)();
  replies.get(4)();
  await new Promise(setImmediate);
  assert.equal(selection.data, undefined);
  assert.equal(paints, 0);
  replies.get(2)();
  await new Promise(setImmediate);
  assert.equal(paints, 1);
  draw();
  assert.match(row(1), /上次进展：Latest completed step/);
  assert.match(row(2), /Connection interrupted/);
  assert.doesNotMatch(row(2), /Older task summary|Previous success/);
  assert.match(row(3), /Submitted result/);
  assert.doesNotMatch(row(4), /result-delivery-conclusion/);
  assert.match(row(5), /上次进展：Saved progress/);

  draw();
  assert.match(row(1), /上次进展：Latest completed step/);
  assert.deepEqual(requests, [4, 2, 1]);
  workspace.data.workflows[0] = {id: 1, state: 'running'};
  draw();
  assert.doesNotMatch(row(1), /Latest completed step/);
});
