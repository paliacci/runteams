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
