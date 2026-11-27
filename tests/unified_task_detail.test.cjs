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
    RunTeamsAssetOverview: {backMarkup: () => ''},
    detailDrawerHeader: (heading, className, actions, back) => heading + back + actions,
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
  Object.assign(context, {
    RunTeamsSourcePipelines: {taskWorkspace: () => ({})},
    RunTeamsWorkRecords: ui,
    RunTeamsConfigurationFields: {bindCredentialEditor() {}},
  });
  vm.runInContext(panels, context);
  const pipeline = context.window.RunTeamsSourcePipelinePanels.workDrawer({type: 'source-pipeline', id: 'work', workflowId: 42, loading: true, recordTitle: 'Original task'});
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

test('failed execution rows preserve diagnostic identifiers and Windows filenames in the preview and tooltip', () => {
  const {ui} = fixture();
  const reason = String.raw`Missing approval_request in C:\QA_资料\工单#2\*.json`;
  const run = {id: 17, state: 'failed', failure_reason: reason};
  const row = ui.attemptsMarkup({snapshot_json: {}}, [run]);
  assert.ok(row.includes(`title="${reason}">${reason}</span>`));
});

test('failed task diagnostics preserve literal text instead of passing paths through Markdown', () => {
  const {context, ui} = fixture();
  context.renderMarkdown = value => '[Markdown] ' + value;
  context.esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  const reason = String.raw`Missing C:\输入 QA\_待复核_\工单 #2.json` + '\nExpected <input> & metadata';
  const view = ui.employeeTaskDrawer(task('failed', [{id: 17, state: 'failed', failure_reason: reason}]));
  const escaped = context.esc(reason);
  assert.ok(view.body.includes('<p class="work-record-failure-reason">' + escaped + '</p>'));
  assert.ok(!view.body.includes('[Markdown] ' + reason));
});

test('formatted execution previews use the Markdown reader’s plain text, including punctuation within code', () => {
  const {context, ui} = fixture();
  const path = String.raw`C:\输入 QA\_待复核_\工单 #2.json`;
  const summary = '**已读入** `' + path + '`';
  context.renderMarkdown = (source, options) => {
    assert.equal(source, summary);
    assert.equal(options.plainText, true);
    return '已读入 ' + path;
  };
  const run = {id: 18, state: 'completed', work_name: '读取文件', output_json: {summary}};
  const row = ui.attemptsMarkup({snapshot_json: {}}, [run]);
  assert.ok(row.includes('title="已读入 ' + path + '">已读入 ' + path + '</span>'));
});

test('pipeline execution badges follow the recorded result regardless of column order', () => {
  const {ui} = fixture();
  const positions = [
    {key: 'design', name: '能量提示物设计'},
    {key: 'review', name: '免费审稿'},
    {key: 'script', name: '口播稿生成器'},
  ];
  const run = {id: 17, position_key: 'review', state: 'completed', output_json: {}};
  const snapshot_json = {pipeline_work: {asset: {pipeline: {positions}}}};
  const badge = (to, when) => {
    const events = to ? [{type: 'workflow.routed', data_json: {employee_run_id: 17, from: 'review', to, when}}] : [];
    return ui.attemptsMarkup({snapshot_json, events}, [run]);
  };

  assert.match(badge('design', 'outcome:locked'), /data-work-state="handed_off"[^>]*>已交接<\/span>/);
  assert.match(badge('script', 'outcome:revise'), /data-work-state="returned"[^>]*>已退回口播稿生成器<\/span>/);
  assert.match(badge('script', 'completed'), /data-work-state="handed_off"/);
  assert.match(badge('script', 'revise'), /data-work-state="returned"/);
  assert.match(badge('abandoned', 'outcome:rejected'), /data-work-state="completed"/);
  assert.match(badge(), /data-work-state="completed"/);
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

test('reopening a report reuses its saved version and loads a newer one when available', async () => {
  const {context, ui} = fixture();
  const html = fs.readFileSync('web/index.html', 'utf8');
  const report = {id: 1, revision: 2, document_key: 'report'};
  const data = () => ({results: [{key: 'report-1', report_document: {...report}}]});
  const selection = context.S.sel = {type: 'core-results', scope: {employee_id: 1},
    status: 'ready', resultKey: 'report-1', data: data()};
  const reads = [];
  const paints = [];
  Object.assign(context, {
    URL, location: {href: 'http://localhost/chats/1'}, RunTeamsWorkRecords: ui,
    RunTeamsEmployeeDirectory: {forPanel: () => ({record: {id: 1}}), employeePanel: () => true, panelReference: () => null},
    selectDetailWorkspace: value => {context.S.sel = value;},
    appRouteLocation: () => new URL(context.location.href), setAppUrl() {}, scheduleResultActionProgress() {},
    closeContextResults() {context.S.sel = null;},
    render() {paints.push(selection.reportDocuments?.[1]?.status);},
    async api(path) {
      reads.push(path);
      return path.startsWith('/api/core/results?') ? data() : {...report, content: 'Saved report'};
    },
  });
  context.S.conversationPanel = {id: 1};
  context.document.querySelector = () => null;
  vm.runInContext(html.slice(html.indexOf('let _contextResultsSequence='), html.indexOf('function revealContextResultReference(')), context);
  await ui.loadReport(selection);
  reads.length = 0;
  paints.length = 0;

  await ui.toggle();
  await ui.toggle();
  assert.equal(context.S.sel, selection);
  assert.deepEqual(reads, ['/api/core/results?employee_id=1']);
  assert.ok(paints.every(status => status === 'ready'));

  report.revision = 3;
  await ui.toggle();
  await ui.toggle();
  assert.equal(selection.reportDocuments[1].doc.revision, 3);
  assert.equal(reads.filter(path => path === '/api/core/documents/1').length, 1);
});
