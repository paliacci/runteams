const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function fixture() {
  const context = vm.createContext({
    window: {addEventListener() {}}, S: {sel: null},
    document: {addEventListener() {}, getElementById: () => null}, requestAnimationFrame() {},
    esc: value => String(value ?? ''), ICON: () => '', renderMarkdown: String,
    workspaceAccountCacheToken: () => 'owner', _workspaceBusinessGeneration: 1, workspaceDeviceStorageScope: () => 'library',
    workRecordStateCopy: value => ({key: 'state.' + value, label: value}), coreWorkflowStateClass: value => value,
    detailDrawerHeading: (title, description, metadata) => `<h2>${title}</h2>${metadata}`,
    detailDrawerHeader: (heading, className, actions, unused, back) => heading + back + actions,
    detailDrawerShell: options => options, detailDrawerActions: actions => `<actions>${actions}</actions>`,
    RunTeamsSkeletons: {drawerHeading: () => 'loading title', region: () => 'loading body'},
    RunTeamsEmployeeDrawerHeader: {section: options => `<section id="${options.id}">${options.title}${options.body}</section>`},
    RunTeamsLoadFailure: {markup: options => 'retry:' + options.retry},
  });
  vm.runInContext(fs.readFileSync('web/ui/work-records.js', 'utf8'), context);
  return {context, ui: context.window.RunTeamsWorkRecords};
}

function task(state, runs = []) {
  return {type: 'core-workflow', id: 42, workflow: {id: 42, state,
    task: {title: 'Original task', payload_json: {objective: 'Original instructions'}},
    snapshot_json: {schema: 'runteams.employee-chat-work/v1', work_chat_id: 7}, employee_runs: runs, artifacts: []}};
}

test('independent and pipeline tasks use the same task shell while loading', () => {
  const {context, ui} = fixture();
  const independent = ui.employeeTaskDrawer({type: 'core-workflow', id: 42, loading: true, recordTitle: 'Original task'});
  const panels = fs.readFileSync('web/ui/source-pipeline-panels.js', 'utf8');
  Object.assign(context, {current: () => ({}), RunTeamsWorkRecords: ui, workText: (key, fallback) => fallback});
  vm.runInContext(panels.slice(panels.indexOf('function workDrawer('), panels.indexOf('\nfunction closeHistory(')), context);
  const pipeline = context.workDrawer({type: 'source-pipeline', id: 'work', workflowId: 42, loading: true, recordTitle: 'Original task'});
  assert.equal(independent.className, pipeline.className);
  assert.equal(independent.bodyClass, pipeline.bodyClass);
  assert.equal(independent.attrs, pipeline.attrs);
  assert.equal(independent.header, pipeline.header);
  assert.equal(independent.body, pipeline.body);
});

test('a completed independent task shows the latest result with no conversation or continue action', () => {
  const {ui} = fixture();
  const selection = task('completed', [
    {id: 1, state: 'completed', output_json: {summary: 'Older result'}},
    {id: 2, state: 'completed', output_json: {summary: 'Current result'}},
  ]);
  const view = ui.employeeTaskDrawer(selection);
  assert.match(view.className, /unified-task-detail-drawer/);
  assert.match(view.body, /source-work-context.*Current result/);
  assert.match(view.body, /pipelineWork.objective/);
  assert.doesNotMatch(view.body, /查看对话|继续处理|确认并继续|continueEmployeeTask/);
});

test('running and waiting independent tasks expose only their actual supported actions', () => {
  const {ui} = fixture();
  const running = ui.employeeTaskDrawer(task('running', [{id: 1, state: 'running', output_json: {}}]));
  assert.match(running.body, /cancelCoreWorkflow\(42/);
  assert.match(running.body, /等待员工发出首条工作进展/);
  assert.doesNotMatch(running.body, /continueEmployeeTask|确认并继续/);
  const waiting = ui.employeeTaskDrawer(task('needs_human', [{id: 1, state: 'needs_human', output_json: {issues: ['Need source material']}}]));
  assert.match(waiting.body, /Need source material/);
  assert.match(waiting.body, /continueEmployeeTask/);
  assert.doesNotMatch(waiting.body, /source_pipeline_choice|确认并继续|cancelCoreWorkflow/);
});

test('an outdated independent task read cannot replace a newer selection', async () => {
  const {context, ui} = fixture();
  const selection = task('running');selection.employeeTask = true;
  context.S.sel = selection;ui.employeeTaskDrawer(selection);
  let finish;
  context.api = () => new Promise(resolve => {finish = resolve;});
  const pending = ui.refreshEmployeeTask(selection);
  const next = context.S.sel = {type: 'employee-configuration'};
  finish({...selection.workflow, state: 'completed'});
  await pending;
  assert.equal(context.S.sel, next);
  assert.equal(selection.workflow.state, 'running');
});
