const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const draftFunctions = html.slice(html.indexOf('function serializableConversationDraftValue('),
  html.indexOf('/* module:conversation:conversationModeTitle */'));
const operationId = 'bf14b2c1-d096-4776-87e4-efe35ee40012';
const generation = 'library-generation';

function draftsHost(drafts = {}, libraryGeneration = generation) {
  let stored;
  const state = {conversationPanelDrafts: drafts, localLibrary: {generation: libraryGeneration}};
  const host = vm.createContext({
    S: state,
    document: {getElementById: () => null},
    CONVERSATION_DRAFTS_KEY: 'drafts',
    workspaceBusinessStorage: {setItem: (_key, value) => { stored = JSON.parse(value); }},
    conversationPanelDraftKey: panel => 'chat:' + panel.id,
    conversationQueueSnapshot: () => null,
    conversationQueueRestore: () => {},
    conversationRestoreLegacyFolders: value => ({text: value || '', folders: []}),
  });
  vm.runInContext(draftFunctions, host);
  return {host, saved: () => stored};
}

test('pending operation and next draft reopen separately with native file and folder tokens', () => {
  const {host, saved} = draftsHost();
  const pending = {
    input: '原草稿',
    attachments: [
      {kind: 'image', name: '图片.png', pickToken: 'native-image', preview: 'blob:previous-renderer'},
      {kind: 'folder', name: '目录', pickToken: 'native-folder', file_count: 1},
      {kind: 'file', name: 'browser.txt', file: {size: 16}},
    ],
    editRewind: {messageId: 3},
  };
  host.captureConversationPanelDraft({
    panel: {id: 12, input: '下一条', localTurnRecovery: {operationId, generation, draft: pending, checking: true, absent: true}},
    fromState: true,
  });
  const record = saved()['chat:12'];
  assert.equal(record.input, '下一条');
  assert.equal(record.localTurnRecovery.checking, undefined);
  assert.equal(record.localTurnRecovery.absent, undefined);
  assert.equal(record.localTurnRecovery.draft.missingAttachments, true);
  assert.deepEqual(record.localTurnRecovery.draft.attachments, [
    {kind: 'image', name: '图片.png', pickToken: 'native-image'},
    {kind: 'folder', name: '目录', pickToken: 'native-folder', file_count: 1},
  ]);
  const reopened = {id: 12};
  draftsHost(saved()).host.restoreConversationPanelDraft(reopened);
  assert.equal(reopened.input, '下一条');
  assert.equal(reopened.localTurnRecovery.operationId, operationId);
  assert.equal(reopened.localTurnRecovery.draft.input, '原草稿');
  assert.equal(reopened.localTurnRecovery.draft.editRewind.messageId, 3);
  assert.equal(reopened.localTurnRecovery.draft.missingAttachments, true);
});

test('moving a pending operation clears only the original snapshot of the new conversation', () => {
  const key = 'new:global:general:general:default';
  const original = {input: 'original'};
  const fresh = {input: 'separate new conversation'};
  const panel = {id: 12, localTurnRecovery: {operationId, generation, draft: original}};
  const same = draftsHost({[key]: original});
  same.host.captureConversationPanelDraft({panel, replacedDraft: {key, snapshot: original}});
  assert.equal(same.saved()[key], undefined);
  assert.equal(same.saved()['chat:12'].localTurnRecovery.draft.input, 'original');

  const changed = draftsHost({[key]: fresh});
  changed.host.captureConversationPanelDraft({panel, replacedDraft: {key, snapshot: original}});
  assert.deepEqual(changed.saved()[key], fresh);
});

test('a replacement library generation keeps the next draft without restoring an old operation', () => {
  const data = {'chat:12': {input: 'current draft', localTurnRecovery: {
    operationId, generation, draft: {input: 'previous library operation'},
  }}};
  const panel = {id: 12};
  draftsHost(data, 'replacement-generation').host.restoreConversationPanelDraft(panel);
  assert.equal(panel.input, 'current draft');
  assert.equal(panel.localTurnRecovery, undefined);
});
