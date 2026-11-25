const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const panels = fs.readFileSync('web/ui/source-pipeline-panels.js', 'utf8');
const addStage = panels.slice(panels.indexOf('async function addStageMenu('), panels.indexOf('const defaultTone='));

test('stage menu waits for both settings and employee choices already being read', async () => {
  const workspace = {reference: {}}, panel = {}, requests = [];
  const context = vm.createContext({
    S: {sel: {type: 'source-pipeline', id: 'settings'}},
    current: () => workspace, owned: value => value === workspace, state: () => panel, render() {},
    host: () => ({request(action, body) {
      return new Promise(resolve => requests.push({action, body, resolve}));
    }}),
  });
  vm.runInContext(panels.slice(panels.indexOf('async function read(s='), panels.indexOf('function draft()')) +
    panels.slice(panels.indexOf('async function readEmployeeChoices()'), panels.indexOf('function employeeChoicesStatus')), context);
  const settings = context.read(), choices = context.readEmployeeChoices();
  const fromMenu = Promise.all([context.read(), context.readEmployeeChoices()]).then(() => {
    assert.equal(panel.data.source_revision, 'revision');
    assert.equal(panel.choices.length, 1);
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests.map(r => r.action), ['settings', 'creation-choices']);
  assert.equal(requests[0].body.include_configuration, true);
  requests[0].resolve({source_revision: 'revision', configuration_states: {}});
  requests[1].resolve({items: [{skill_key: 'review'}]});
  await Promise.all([settings, choices, fromMenu]);
  assert.equal(panel.loading, false);
  assert.equal(panel.choicesLoading, false);
});

test('new-stage recovery opens settings and retains unfinished changes', async () => {
  for (const field of ['draft', 'pending', 'saving', 'commitRefresh']) {
    const panel = {[field]: {operation_id: 'existing-operation'}};
    const before = JSON.stringify(panel);
    const workspace = {data: {ui: {mode: 'creator'}}, view: 'board'};
    let settingsOpened = 0;
    const context = vm.createContext({
      current: () => workspace,
      owned: candidate => candidate === workspace,
      state: () => panel,
      document: {getElementById: () => null},
      settings: () => {settingsOpened++;},
    });
    vm.runInContext(addStage, context);
    await context.addStageMenu({});
    assert.equal(settingsOpened, 1, field);
    assert.equal(JSON.stringify(panel), before, field + ' must survive recovery');
  }
});
