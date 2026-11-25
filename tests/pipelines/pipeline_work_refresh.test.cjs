const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const workspace = fs.readFileSync('web/ui/source-pipelines.js', 'utf8');
const panels = fs.readFileSync('web/ui/source-pipeline-panels.js', 'utf8');
const workReaders = workspace.slice(workspace.indexOf(' let activityConnection;'),
  workspace.indexOf(' const operationErrorFallback='));
const flow = panels.slice(panels.indexOf('const flowKey='), panels.indexOf('function inputDraft('));

test('a team discussion retries its original creation and leaves the board only once', async () => {
  const team = {data: {}, reference: {source_id: 'team'}, routeEntry: {page_id: '1atest00'}};
  const attempts = [], opened = [];
  let finish;
  const create = vm.runInNewContext(workspace.slice(workspace.indexOf(' async function newDiscussion('),
    workspace.indexOf(' function header(')) + '\nnewDiscussion', {
    S: {localLibrary: {}}, current: () => team, matches: s => s === team, navigationTicket: () => () => true,
    defaultChatConfig: () => ({}), crypto: require('node:crypto'), render() {}, toast() {},
    request: async (_, body) => {
      attempts.push(body.discussion_id);
      if (attempts.length === 1) throw Error('Receipt lost');
      return new Promise(resolve => { finish = resolve; });
    },
    referenceKey: ref => ref.source_id, deviceChatRemember() {}, openRailConversationSession: id => opened.push(id),
  });
  await create();
  const retry = create();
  await create();
  assert.equal(attempts.length, 2);
  assert.equal(attempts[0], attempts[1]);
  finish({session: {id: 12, public_id: '2btest00', owner_path: '/pipelines/1atest00', storage_scope: 'device',
    context: {source_pipeline_workspace: team.reference, source_pipeline_discussion: attempts[0]}}});
  await retry;
  assert.deepEqual(opened, [12]);
  assert.equal(team.discussionId, undefined);
});

test('changing the model in a team discussion sends only runtime settings', () => {
  const host = vm.createContext({S: {channels: []}, catalogModel: () => null,
    normalizedConversationContext: panel => ({...panel.context, context_type: 'general', intent: 'general'})});
  vm.runInContext(fs.readFileSync('web/modules/conversation.js', 'utf8'), host);
  const panel = {kind: 'general', id: 27, channel_id: 4, model: 'fixture', reasoning_effort: 'low',
    context: {source_pipeline_workspace: {source_id: 'team'}, source_pipeline_discussion: 'planning'}};
  assert.deepEqual({...host.conversationPanelConfig(panel)},
    {channel_id: 4, model: 'fixture', reasoning_effort: 'low', extensions_enabled: false});
  assert.equal(host.conversationPanelConfig({...panel, context: {}}).context.intent, 'general');
});

test('a failed team pause can be retried after active work stops', () => {
  const source = workspace.slice(workspace.indexOf(' function runtimeLabelKey('), workspace.indexOf(' function boardWorkflows('));
  const render = vm.runInNewContext(source + '\nruntimeAction', {ICON: () => ''});
  const runtime = {status: 'pausing', active_workflow_ids: [], pause_error: 'workspace unavailable'};
  const board = {data: {runtime}};
  const retry = render(board, false);
  assert.match(retry, /pipelineBoard\.retryPause/);
  assert.match(retry, /control\('pause'\)/);
  assert.doesNotMatch(retry, /disabled/);
  runtime.active_workflow_ids = [17];
  assert.match(render(board, false), /disabled/);
  runtime.active_workflow_ids = [];
  runtime.pause_error = '';
  assert.match(render(board, false), /disabled/);
  runtime.status = 'paused';
  assert.match(render(board, false), /control\('start'\)/);
});

test('only the exact execution that supplied the current pending result moves to the heading', () => {
  const env = vm.createContext({window: {addEventListener() {}}});
  vm.runInContext(fs.readFileSync('web/ui/work-records.js', 'utf8'), env);
  const currentExecution = env.window.RunTeamsWorkRecords.currentExecutionOutsideHistory;
  const source = {id: 10, state: 'completed', position_key: 'store', output_json: {summary: 'Draft saved'}};
  const older = {id: 9, state: 'completed', position_key: 'store'};
  const work = {state: 'needs_human', cursor_key: 'store', employee_runs: [source, older], snapshot_json: {
    pipeline_waiting: {kind: 'result', state: 'needs_human', position_key: 'store', source_run_id: 10,
      result: {summary: 'Draft saved'}}}};
  assert.equal(currentExecution(work), source);
  const waitingSource = {...source, state: 'needs_human'};
  assert.equal(currentExecution({...work, employee_runs: [waitingSource, older]}), waitingSource);
  assert.equal(currentExecution({...work, cursor_key: 'review'}), null);
  assert.equal(currentExecution({...work, employee_runs: [older]}), null);
  assert.equal(currentExecution({...work, state: 'needs_approval'}), null);
});

function fixture() {
  const work = {id: 42, state: 'needs_human', updated_at: 'old',
    snapshot_json: {pipeline_visit: 5, pipeline_waiting: {configuration_before: 'original'}}};
  const owner = {type: 'source-pipeline', id: 'work', workflowId: 42, workflow: work, workScroll: 140,
    returnToRecords: {id: 'records'}, workSections: {deliveries: true}};
  const pipeline = {scope: 'fixture', reference: {source_id: 'fixture'}};
  const state = {sel: owner};
  const requests = [];
  const store = new Map();
  const context = {
    S: state,
    current: () => pipeline,
    taskWorkspace: () => pipeline,
    ownsTask: candidate => candidate === pipeline,
    owned: candidate => candidate === pipeline,
    matches: candidate => candidate === pipeline,
    activeTaskConfiguration: () => null,
    render() {},
    refresh: async () => true,
    select: (id, properties) => { state.sel = {id, ...properties}; },
    RunTeamsSourcePipelinePanels: {mountSigningConfiguration() {}},
    RunTeamsWorkRecords: {refreshOpenAttempt() {}, currentExecutionOutsideHistory() {}},
    RunTeamsWorkState: {
      getItem: key => store.get(key),
      setItem: (key, value) => store.set(key, value),
      removeItem: key => store.delete(key),
    },
    crypto: {randomUUID: () => 'test-operation'},
    document: {getElementById: () => null, querySelector: () => null},
    request: async (action, data) => {
      requests.push(action);
      return context.reply(action, data);
    },
    host: () => ({
      workCommitted() {},
      request: context.request,
      refresh: context.refresh,
      applyWorkReply: context.applyWorkReply,
      openWork: context.openWork,
    }),
  };
  vm.createContext(context);
  vm.runInContext(workReaders + flow, context);
  return {context, owner, work, pipeline, requests};
}

test('a confirmed continue keeps the drawer and applies the receipt before background reads', async () => {
  const {context, owner, work, pipeline, requests} = fixture();
  const ready = {...work, state: 'ready', updated_at: 'submitted', snapshot_json: {pipeline_visit: 6}};
  context.reply = action => {
    assert.equal(action, 'flow');
    return {status: 'committed', result: {workflow: ready, task_configuration: {editable: true}}};
  };
  await context.flow('respond');
  assert.deepEqual(requests, ['flow']);
  assert.equal(context.S.sel, owner);
  assert.equal(owner.workflow, ready);
  assert.equal(owner.workScroll, 140);
  assert.equal(owner.returnToRecords.id, 'records');
  assert.equal(owner.workSections.deliveries, true);
  assert.equal(owner.taskConfiguration.editable, true);

  context.reply = () => { throw Error('temporary read failure'); };
  await context.refreshOpenWork(pipeline, owner);
  assert.equal(owner.workflow, ready);
  assert.equal(owner.error, '');

  const running = {...ready, state: 'running', updated_at: 'claimed'};
  context.reply = () => ({workflow: running});
  await context.refreshOpenWork(pipeline, owner);
  assert.equal(owner.workflow, running);
  assert.equal(owner.error, '');
});

test('topic approval uses candidates from the exact source run and submits the chosen ID', async () => {
  const {context, work, requests} = fixture();
  work.state = 'needs_approval';
  work.cursor_key = 'choose-topic';
  work.snapshot_json.pipeline_work = {asset: {key: 'production'}};
  work.snapshot_json.pipeline_waiting = {kind: 'approval', source_run_id: 10};
  work.employee_runs = [
    {id: 9, position_key: 'topic', output_json: {output: {topic_brief: {
      candidates: [{id: 'C', title: '旧题'}], recommended_id: 'C',
    }}}},
    {id: 10, position_key: 'topic', output_json: {output: {topic_brief: {
      candidates: [{id: 'A', title: '首推题'}, {id: 'B', title: '另一个题'}], recommended_id: 'A',
    }}}},
  ];
  const choices = context.topicApprovalChoices(work);
  assert.deepEqual(Array.from(choices, choice => [choice.label, choice.recommended]), [
    ['A · 首推题', true], ['B · 另一个题', false],
  ]);
  assert.equal(context.topicApprovalChoices({...work, cursor_key: 'review'}).length, 0);

  context.workText = (_key, fallback) => fallback;
  context.document.getElementById = () => ({value: '退回时再改'});
  await context.flow('decide', 'approved');
  assert.deepEqual(requests, []);

  let command;
  context.reply = (_action, data) => {
    command = data;
    return {status: 'committed', result: {workflow: {...work, updated_at: 'decided'}}};
  };
  context.document.querySelector = () => ({value: 'B · 另一个题'});
  await context.flow('decide', 'approved');
  assert.equal(command.note, 'B');
  assert.equal(command.decision, 'approved');
  await context.flow('decide', 'rejected');
  assert.equal(command.note, '退回时再改');
  assert.equal(command.decision, 'rejected');
});

test('an older read cannot overwrite a newer confirmed drawer state', async () => {
  const {context, owner, work, pipeline} = fixture();
  owner.workflow = {...work, state: 'ready'};
  let respond;
  context.reply = () => new Promise(resolve => { respond = resolve; });
  const pending = context.refreshOpenWork(pipeline, owner);
  const latest = {...work, state: 'completed', updated_at: 'finished'};
  context.applyWorkReply(owner, {workflow: latest});
  respond({workflow: {...work, state: 'running', updated_at: 'stale'}});
  await pending;
  assert.equal(owner.workflow, latest);
});

test('a running drawer applies new activity and saved revisions without a workflow timestamp change', async () => {
  const {context, owner, work, pipeline} = fixture();
  owner.workflow = {...work, state: 'running', snapshot_json: {employee_run_id: 6},
    employee_runs: [{id: 6, state: 'running'}], artifacts: []};
  let paints = 0;
  context.render = () => { paints++; };
  context.refresh = () => assert.fail('A detail-only change does not need a board read');
  const active = {...owner.workflow, employee_runs: [{id: 6, state: 'running',
    live_activity: {notes: ['Checked the store requirements']}}]};
  context.reply = () => ({workflow: active});
  await context.refreshOpenWork(pipeline, owner);
  await context.refreshOpenWork(pipeline, owner);
  assert.equal(owner.workflow, active);
  assert.equal(paints, 1);
  const saved = {...active, artifacts: [{id: 23, meta_json: {revision: 1}}]};
  context.reply = () => ({workflow: saved});
  await context.refreshOpenWork(pipeline, owner);
  assert.equal(owner.workflow, saved);
  assert.equal(paints, 2);
});

test('the initial open still offers a retry when no task details have loaded', async () => {
  const {context} = fixture();
  context.reply = () => { throw Error('initial read failed'); };
  await context.openWork(42);
  assert.equal(context.S.sel.loading, false);
  assert.equal(context.S.sel.error, 'initial read failed');
  assert.equal(context.S.sel.workflow, undefined);
});

const poll = workspace.slice(workspace.indexOf(' async function pollWorkspace('),
  workspace.indexOf(' setInterval(()=>void pollWorkspace()'));
const refresh = workspace.slice(workspace.indexOf(' async function refresh('),
  workspace.indexOf(' // The board uses the same immutable workspace chat'));

test('board polling keeps running with task, records and settings drawers open', async () => {
  for (const selected of [null, {type: 'source-pipeline', id: 'settings'},
    {type: 'core-results'}, {type: 'source-pipeline', id: 'work'}]) {
    const {context, pipeline} = fixture();
    context.opening = false;
    context.S.sel = selected;
    pipeline.view = 'board';
    pipeline.data = {runtime: {status: 'running'}, workflows: []};
    let reads = 0;
    context.refresh = async options => {
      reads++;
      assert.equal(options.silent, true);
    };
    vm.runInContext(poll, context);
    await context.pollWorkspace();
    assert.equal(reads, 1);
    assert.equal(context.S.sel, selected);
    assert.equal(pipeline.pollingWorkspace, false);
  }
});

test('a waiting drawer follows a task resumed from another entry point', async () => {
  const {context, pipeline, owner, work} = fixture();
  context.opening = false;
  pipeline.view = 'board';
  pipeline.data = {runtime: {status: 'running'}, workflows: []};
  let updates = 0;
  context.refresh = async () => {
    updates++;
    pipeline.data.workflows = [{id: 42, state: 'running', cursor_key: 'store'}];
  };
  const running = {...work, state: 'running', cursor_key: 'store', updated_at: 'resumed'};
  context.reply = () => ({workflow: running});
  vm.runInContext(poll, context);
  await context.pollWorkspace();
  assert.equal(owner.workflow, running);
  assert.ok(updates >= 1);
  assert.equal(context.S.sel, owner);
});

test('a settled drawer does not stop later board synchronization', async () => {
  const {context, pipeline, owner, work} = fixture();
  context.opening = false;
  pipeline.view = 'board';
  pipeline.data = {runtime: {status: 'running'}, workflows: []};
  owner.workflow = {...work, state: 'running', cursor_key: 'store'};
  let reads = 0;
  context.refresh = async () => {
    reads++;
    if (reads === 1) return false;
    pipeline.data.workflows = [{id: 42, state: 'needs_human', cursor_key: 'store'}];
    return true;
  };
  const blocked = {...work, cursor_key: 'store', updated_at: 'waiting'};
  context.reply = () => ({workflow: blocked});
  vm.runInContext(poll, context);
  await context.pollWorkspace();
  assert.equal(owner.workflow, blocked);
  await context.pollWorkspace();
  assert.equal(pipeline.data.workflows[0].state, 'needs_human');
  assert.equal(owner.workflow, blocked);
});

test('background workspace reads preserve the board on failure and skip unchanged paints', async () => {
  const {context, pipeline} = fixture();
  context.reading = false;
  context.window = {RunTeamsWorkRecords: {updateTaskList() {}}};
  pipeline.data = {runtime: {status: 'running'}, workflows: [{id: 42, state: 'running'}]};
  let paints = 0;
  context.render = () => { paints++; };
  context.reply = () => { throw Error('temporary read failure'); };
  vm.runInContext(refresh, context);
  await context.refresh({silent: true});
  assert.equal(pipeline.data.workflows[0].state, 'running');
  assert.equal(pipeline.error, undefined);
  assert.equal(paints, 0);

  context.reply = () => structuredClone(pipeline.data);
  await context.refresh({silent: true});
  assert.equal(paints, 0);
  context.reply = () => ({runtime: {status: 'running'}, workflows: [{id: 42, state: 'needs_human'}]});
  await context.refresh({silent: true});
  assert.equal(pipeline.data.workflows[0].state, 'needs_human');
  assert.equal(paints, 1);
});

test('typing a note keeps the selected option and choosing an option keeps the note', () => {
  const {context, owner} = fixture();
  const notes = panels.slice(panels.indexOf('function answer('), panels.indexOf('function retryFlow('));
  context.requestAnimationFrame = callback => callback();
  vm.runInContext(notes, context);
  context.answer('这里有新的政策网址', '先补政策和支持页');
  context.answer('这里有新的政策网址和补充说明');
  assert.equal(context.flowState(context.current(), 42).choice, '先补政策和支持页');
  context.answer('这里有新的政策网址和补充说明', '补齐全部材料后继续复核');
  const saved = context.flowState(context.current(), 42);
  assert.equal(saved.choice, '补齐全部材料后继续复核');
  assert.equal(saved.response, '这里有新的政策网址和补充说明');
  assert.equal(saved.feedbackVisit, owner.workflow.snapshot_json.pipeline_visit);
});

test('typed options keep separate text drafts and merge route and option fields', () => {
  const {context, owner, work} = fixture();
  owner.humanRequest = {options: [
    {label: '提交核验资料', input_mode: 'fields_and_text', configuration_fields: ['extra']},
    {label: '仅确认', input_mode: 'none'},
  ]};
  work.snapshot_json.pipeline_waiting.configuration_fields = ['required'];
  context.requestAnimationFrame = callback => callback();
  vm.runInContext(panels.slice(panels.indexOf('function answer('), panels.indexOf('function retryFlow(')), context);
  context.answer('', '提交核验资料');
  context.answer('刚核验的记录');
  assert.deepEqual(Array.from(context.feedbackConfigurationFields(owner)), ['required', 'extra']);
  context.answer('刚核验的记录', '仅确认');
  assert.deepEqual(Array.from(context.feedbackConfigurationFields(owner)), ['required']);
  const state = context.flowState(context.current(), 42);
  assert.equal(state.response, '');
  context.answer('', '提交核验资料');
  assert.equal(state.response, '刚核验的记录');
});

test('a choice-based wait shows configuration only within its selected response', () => {
  const {context, owner, work} = fixture();
  context.RunTeamsWorkRecords = {hasFailureReason: () => false, missingFailureReason: () => '',
    prose: value => value, executionSectionMarkup: () => ''};
  context.workLabel = (_key, fallback) => fallback;
  context.detailDrawerActions = () => '';
  context.taskDeliveriesMarkup = () => '';
  context.taskConfigurationMarkup = () => '<all-configuration-fields>';
  context.feedbackConfigurationFields = () => [];
  context.esc = value => value;
  vm.runInContext(panels.slice(panels.indexOf('function feedbackBlocker('), panels.indexOf('function workDrawer(')), context);
  owner.humanRequest = {question: '补哪一项？', options: [{label: '政策', configuration_fields: ['privacy_url']}]};
  const definition = {positions: []};
  const render = response => context.workContent(owner, work, definition, new Map(), response, '', null, null, null);
  assert.doesNotMatch(render('<choice-inputs>'), /all-configuration-fields/);
  assert.match(render('<selected-policy-field>'), /selected-policy-field/);
  work.snapshot_json.pipeline_waiting.result = {summary: '登录已失效'};
  const form = context.workContent(owner, work, definition, new Map(), '<choice-inputs>', '', null, null, null,
    false, undefined, true);
  assert.match(form, /id="source_pipeline_question">登录已失效.*<choice-inputs>/);
  assert.doesNotMatch(form, /查看原问题|source-work-feedback-context/);
  owner.humanRequest = null;
  assert.match(render(''), /all-configuration-fields/);
});

test('a parked result shows its summary once and retains the execution and earlier summaries', () => {
  const workerRecords = fs.readFileSync('web/ui/work-records.js', 'utf8');
  const no = () => '';
  const env = vm.createContext({
    window: {addEventListener() {}}, S: {sel: {type: 'source-pipeline', workflowId: 42}}, esc: String,
    renderMarkdown: String, ICON: no, workLabel: (_key, fallback) => fallback,
    detailDrawerActions: no, taskConfigurationMarkup: no, taskDeliveriesMarkup: no,
    workRecordStateCopy: state => ({key: state, label: state}), coreWorkflowStateClass: no,
    RunTeamsEmployeeDrawerHeader: {section: ({body}) => body},
  });
  vm.runInContext(workerRecords, env);
  env.RunTeamsWorkRecords = env.window.RunTeamsWorkRecords;
  vm.runInContext(panels.slice(panels.indexOf('function parkedExecution('), panels.indexOf('function workDrawer(')), env);
  const summary = '公开隐私政策仍需补充核验。';
  const run = {id: 7, state: 'completed', position_key: 'review', work_name: '复核资料',
    output_json: {schema: 'runteams.work-result/v1', summary}};
  const prior = {...run, id: 6, output_json: {...run.output_json, title: '上次核验', summary: '已经读取应用资料。'}};
  const definition = {positions: [{key: 'review'}], states: [{key: 'pool', kind: 'pool'}]};
  const work = {id: 42, state: 'blocked', cursor_key: 'pool', employee_runs: [run, prior],
    snapshot_json: {employee_run_id: 7, pipeline_applied_result: true, pipeline_work: {position_key: 'review'}}};
  const render = () => env.workContent({}, work, definition, new Map(), '', '', null, null, env.parkedExecution(work, definition));
  const markup = render();
  assert.equal(markup.replace(/<[^>]*>/g, '').split(summary).length - 1, 1);
  assert.match(markup, /data-attempt-id="7".*复核资料/);
  assert.match(markup, /data-attempt-id="6".*已经读取应用资料。/);
  work.launch_error = '运行环境不可用';
  assert.match(render(), /data-attempt-id="7".*公开隐私政策仍需补充核验/);
});

test('a rejected operation on an old visit reloads the current task without resubmitting', async () => {
  const {context, owner, work, requests} = fixture();
  const updated = {...work, state: 'ready', snapshot_json: {pipeline_visit: 6}};
  context.reply = action => {
    if (action === 'flow') {
      throw Object.assign(Error('rejected'), {code: 'workflow_visit_changed', confirmedReply: true});
    }
    assert.equal(action, 'work');
    return {workflow: updated};
  };
  await context.flow('respond');
  assert.deepEqual(requests, ['flow', 'work']);
  assert.equal(context.S.sel, owner);
  assert.equal(owner.workflow, updated);
  assert.equal(context.flowState(context.current(), work.id).error.key, 'flowMoved');
});

test('a missing response checks the original operation receipt without issuing another write', async () => {
  const {context, owner, work, requests} = fixture();
  const updated = {...work, state: 'ready', snapshot_json: {pipeline_visit: 6}};
  let submitted;
  context.reply = (action, data) => {
    if (action === 'flow') {
      submitted = data;
      throw Error('connection closed');
    }
    assert.equal(action, 'flow-operation');
    assert.equal(data, submitted);
    return {status: 'committed', result: {workflow: updated}};
  };
  await context.flow('respond');
  assert.deepEqual(requests, ['flow', 'flow-operation']);
  assert.equal(owner.workflow, updated);
  assert.equal(context.flowState(context.current(), work.id).pending, null);
});

test('all team cards open one task document regardless of layout and progress', () => {
  const env = vm.createContext({
    workLabel: (_key, fallback) => fallback, workText: (_key, fallback) => fallback,
    RunTeamsWorkRecords: {
      deliveryRowMarkup: (file, options) => file.name + ' ' + options.action,
      taskSection: (_selection, _id, _label, body) => body,
    },
  });
  vm.runInContext(panels.slice(panels.indexOf('function finalDeliveryRow('), panels.indexOf('function signingEntry(')), env);
  for (const state of ['running', 'completed', 'canceled']) {
    const html = env.taskDeliveriesMarkup({workflow: {id: 42, state, task: {title: 'Original card'}}});
    assert.equal(html.split('openTaskReport(this)').length - 1, 1);
    assert.match(html, /Original card/);
  }
});
