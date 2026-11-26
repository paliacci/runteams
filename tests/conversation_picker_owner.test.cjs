const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const shell = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const picker = shell.slice(shell.indexOf('async function openConversationAttachmentPicker('),
  shell.indexOf('function removeConversationAttachment('));
const draft = shell.slice(shell.indexOf('function serializableConversationDraftValue('),
  shell.indexOf('function clearConversationPanelDraft('));

function setup() {
  let complete;
  const origin = {draftKey: 'ordinary', input: '原始草稿', attachments: []};
  const other = {draftKey: 'employee', input: '新草稿', attachments: []};
  const state = {conversationPanel: origin, activeWorkspaceKey: 'chat:new', chatId: null,
    workspaceWindows: [{key: 'chat:new'}, {key: 'chat:new:create-employee'}],
    appInfo: {native_attachment_picker: true}, conversationPanelDrafts: {}};
  const snapshots = new Map([['chat:new', {conversationPanel: origin}]]);
  const renders = [], errors = [], writes = [];
  const host = vm.createContext({
    S: state, _workspaceBusinessGeneration: 1, _workspaceStateByKey: snapshots,
    closePop() {}, toast: (...args) => errors.push(args),
    api: () => new Promise(resolve => { complete = resolve; }),
    conversationAttachments: () => state.conversationPanel.attachments,
    setConversationAttachments: (_, items) => { state.conversationPanel.attachments = items; },
    rerenderConversation: surface => renders.push(surface),
    conversationPanelDraftKey: panel => panel.draftKey,
    conversationInputValue: () => other.input,
    document: {getElementById: () => ({})}, conversationQueueSnapshot: () => null,
    workspaceBusinessStorage: {setItem: (_, value) => writes.push(JSON.parse(value))},
    CONVERSATION_DRAFTS_KEY: 'drafts',
  });
  vm.runInContext(picker + draft, host);
  function switchDraft() {
    state.conversationPanel = other;
    state.activeWorkspaceKey = 'chat:new:create-employee';
  }
  async function finish(pending) {
    complete({items: [{token: 'token', name: '资料', kind: 'folder', file_count: 2}]});
    await pending;
  }
  return {host, state, origin, other, snapshots, renders, errors, writes, switchDraft, finish};
}

test('a delayed native picker adds to its original open draft without repainting the visible draft', async () => {
  const {host, origin, other, renders, writes, switchDraft, finish} = setup();
  const pending = host.openConversationAttachmentPicker('panel');
  switchDraft();
  await finish(pending);
  assert.equal(origin.attachments[0].pickToken, 'token');
  assert.equal(origin.attachments[0].file_count, 2);
  assert.deepEqual(other.attachments, []);
  assert.deepEqual(renders, []);
  assert.equal(writes[0].ordinary.input, '原始草稿');
  assert.equal(writes[0].ordinary.attachments[0].pickToken, 'token');
});

for (const departure of ['closed tab', 'changed library']) {
  test('a delayed native picker leaves the drafts alone after a ' + departure, async () => {
    const {host, state, origin, other, renders, writes, switchDraft, finish} = setup();
    const pending = host.openConversationAttachmentPicker('panel');
    switchDraft();
    if (departure === 'closed tab') state.workspaceWindows.shift();
    else host._workspaceBusinessGeneration++;
    await finish(pending);
    assert.deepEqual(origin.attachments, []);
    assert.deepEqual(other.attachments, []);
    assert.deepEqual(writes, []);
    assert.deepEqual(renders, []);
  });
}
