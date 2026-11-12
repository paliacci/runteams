const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const panels = fs.readFileSync('web/ui/source-pipeline-panels.js', 'utf8');
const addStage = panels.slice(panels.indexOf('async function addStageMenu('), panels.indexOf('const defaultTone='));

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
