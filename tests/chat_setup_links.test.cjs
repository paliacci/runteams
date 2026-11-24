const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function discussionFixture() {
 const reference = {schema: 'runteams.rented-pipeline-reference/1', source_id: 'team'};
 const panel = {id: 15, context: {source_pipeline_workspace: reference}};
 const state = {conversationPanel: panel};
 const opened = [];
 const requests = [];
 let completeSettings;
 const settings = new Promise(resolve => { completeSettings = resolve; });
 const context = vm.createContext({
  window: {addEventListener() {}},
  S: state,
  RunTeamsSourcePipelines: {
   taskWorkspace: () => null,
   request: (action, args) => {
    requests.push({action, ...args});
    return settings;
   },
  },
  RunTeamsEmployeeConfiguration: {open: (entry, options) => opened.push({entry, ...options})},
  RunTeamsConfigurationFields: {bindCredentialEditor() {}},
 });
 vm.runInContext(fs.readFileSync('web/ui/source-pipeline-panels.js', 'utf8'), context);
 const complete = () => completeSettings({
  asset: {pipeline: {name: 'App team', positions: [
   {key: 'scout', kind: 'employee', employee_ref: 'reviewer'},
  ]}},
  employees: [{member_ref: 'reviewer', name: 'Demand scout', source: 'employees/scout.json', field_count: 0}],
 });
 return {panel, state, opened, requests, complete, configure: context.window.RunTeamsSourcePipelinePanels.configureChat};
}

test('a standalone discussion opens the requested role settings without a board or fields', async () => {
 const {panel, opened, requests, complete, configure} = discussionFixture();
 const result = configure(panel, 'scout', () => true);
 complete();
 assert.equal(await result, true);
 assert.equal(requests[0].action, 'settings');
 assert.equal(requests[0].reference, panel.context.source_pipeline_workspace);
 assert.equal(opened[0].entry.source.path, 'employees/scout.json');
 assert.equal(opened[0].entry.pipeline_reference, panel.context.source_pipeline_workspace);
 assert.equal(opened[0].returnToChat, true);
});

test('a role settings response cannot replace a different conversation after navigation', async () => {
 const {panel, state, opened, complete, configure} = discussionFixture();
 const result = configure(panel, 'scout', () => true);
 state.conversationPanel = {id: 16};
 complete();
 assert.equal(await result, false);
 assert.equal(opened.length, 0);
});
