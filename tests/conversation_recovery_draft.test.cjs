const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const draftFunctions = html.slice(html.indexOf('function serializableConversationDraftValue('),
  html.indexOf('/* module:conversation:conversationModeTitle */'));
const draftLoader = html.match(/^function loadConversationPanelDrafts[^\n]+/m)[0];
const operationId = 'bf14b2c1-d096-4776-87e4-efe35ee40012';
const generation = 'library-generation';

function draftsHost(drafts = {}, libraryGeneration = generation) {
  let stored, desktop;
  const state = {conversationPanelDrafts: drafts, localLibrary: {generation: libraryGeneration}};
  const host = vm.createContext({
    S: state,
    document: {getElementById: () => null},
    CONVERSATION_DRAFTS_KEY: 'drafts',
    workspaceBusinessStorage: {setItem: (_key, value) => { stored = JSON.parse(value); }},
    RunTeamsHost: {workspace: {saveDrafts: value => { desktop = JSON.parse(value); }}},
    conversationPanelDraftKey: panel => 'chat:' + panel.id,
    conversationQueueSnapshot: () => null,
    conversationQueueRestore: () => {},
    conversationRestoreLegacyFolders: value => ({text: value || '', folders: []}),
  });
  vm.runInContext(draftFunctions, host);
  return {host, saved: () => stored, desktop: () => desktop};
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

test('capturing the same conversation draft keeps a stable snapshot for desktop close', () => {
  const {host, saved, desktop} = draftsHost();
  const panel = {id: 21, input: '未发送', localTurnRecovery: {operationId, generation, accepted: true}};
  host.captureConversationPanelDraft({panel, fromState: true});
  const original = host.S.conversationPanelDrafts['chat:21'];
  host.captureConversationPanelDraft({panel, fromState: true});
  assert.equal(host.S.conversationPanelDrafts['chat:21'], original);
  assert.deepEqual(desktop(), saved());
});

test('an unsent edit reopens at its original message and keeps the preceding history', () => {
  const {host, saved} = draftsHost();
  host.captureConversationPanelDraft({panel:{id:21, input:'新正文', editRewind:{messageId:13}}, fromState:true});
  const history = [{id:11,role:'user'}, {id:12,role:'bot'}, {id:13,role:'user'}, {id:14,role:'bot'}];
  const reopened = {id:21, messages:history};
  draftsHost(saved()).host.restoreConversationPanelDraft(reopened);
  assert.equal(reopened.input, '新正文');
  assert.equal(reopened.editRewind.messageId, 13);
  assert.deepEqual(reopened.messages, history.slice(0,2));
  assert.equal(history.length, 4);

  // Keep the original target if another window has already replaced it.
  // The send must still be validated as an edit by the service.
  const changed = {id:21, messages:[{id:15,role:'user'}]};
  draftsHost(saved()).host.restoreConversationPanelDraft(changed);
  assert.equal(changed.editRewind.messageId, 13);
  assert.deepEqual(changed.messages, [{id:15,role:'user'}]);
});

test('the next draft typed during a running edit does not inherit the replacement target', () => {
  const {host, saved} = draftsHost();
  host.captureConversationPanelDraft({panel:{id:21, input:'下一条', busy:true, editRewind:{messageId:13}}, fromState:true});
  const reopened = {id:21, messages:[{id:13,role:'user'}]};
  draftsHost(saved()).host.restoreConversationPanelDraft(reopened);
  assert.equal(reopened.editRewind, undefined);
  assert.equal(reopened.messages.length, 1);
  assert.equal(reopened.input, '下一条');
});

test('a confirmed empty desktop snapshot does not revive the old port mirror', () => {
  const previous = {'chat:12': {input: 'stale mirror'}};
  const host = vm.createContext({
    CONVERSATION_DRAFTS_KEY: 'drafts', CONVERSATION_DRAFT_TTL: 1000,
    workspaceBusinessStorage: {getItem: () => JSON.stringify(previous)},
  });
  vm.runInContext(draftLoader, host);
  assert.equal(JSON.stringify(host.loadConversationPanelDrafts('{}')), '{}');
  assert.equal(JSON.stringify(host.loadConversationPanelDrafts(null)), JSON.stringify(previous));
});
