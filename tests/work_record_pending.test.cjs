const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync('web/index.html', 'utf8');
const render = source.slice(source.indexOf('function contextResultDetailMarkup('), source.indexOf('function resultEvidenceFiles('));
function detail(state, scope = {}, origin = {kind: 'employee_chat', chat_id: 7}) {
  const context = vm.createContext({
    esc: String, renderMarkdown: String,
    contextResultDocumentMarkup: () => '', resultActionMarkup: () => '',
    RunTeamsWorkRecords: {reportMarkup: () => '<p>Saved report</p>', originTaskPending: () => false},
  });
  vm.runInContext(render, context);
  return context.contextResultDetailMarkup({key: 'workflow-42', state, origin, report_document: {id: 10}}, {scope});
}

test('employee records retain the report without a generic pending card or conversation action', () => {
  const html = detail('needs_human');
  assert.match(html, /Saved report/);
  assert.doesNotMatch(html, /work-record-pending|data-record-origin|查看工作对话/);
});

test('pipeline records keep their task action for outstanding approval', () => {
  const html = detail('needs_approval', {source_pipeline_reference: {source_id: 'fixture'}});
  assert.match(html, /work-record-pending/);
  assert.match(html, /workRecordDetail.openPipelineTask/);
  assert.match(html, /Saved report/);
});

test('historical report content remains read-only after task routing', () => {
  const html = detail('completed');
  assert.match(html, /Saved report/);
  assert.doesNotMatch(html, /work-record-pending/);
});
