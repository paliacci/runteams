const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const editor = fs.readFileSync('web/modules/conversation.js', 'utf8');
const shell = fs.readFileSync('web/index.html', 'utf8');
const capabilityMarkers = shell.match(/^const CAPABILITY_MARKER_OPEN=.*$/m)[0];

function setup({surface = 'chat', worker = false, native, result = {folder_paths: []}} = {}) {
  const calls = [];
  let selection = {start: 0, end: 0};
  const box = {
    isConnected: true, isContentEditable: true, value: '',
  };
  const host = vm.createContext({
    esc: text => String(text).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char])),
    ICON: name => `<svg class="i" data-icon="${name}"></svg>`,
    S: {chatId: 'new', chatAttachments: [], conversationPanel: {}},
    window: native ? {getSelection: () => null, webkit: {messageHandlers: {runteamsLocalReferencePaste: {
      postMessage: async request => {
        calls.push({bridge: {...request}});
        return typeof native === 'function' ? native() : native;
      },
    }}}} : {getSelection: () => null},
    document: {activeElement: box, execCommand: (command, _ui, content) => {
      assert.equal(command, 'insertText');
      const text = content;
      calls.push({text});
      box.value = box.value.slice(0, selection.start) + text + box.value.slice(selection.end);
      const end = selection.start + text.length;
      selection = {start: end, end};
      return true;
    }},
    api: async (url, method, body) => {
      calls.push({url, method, body: JSON.parse(JSON.stringify(body))});
      return typeof result === 'function' ? result() : result;
    },
    normalizedConversationContext: () => worker
      ? {context_type: 'worker', intent: 'work'}
      : {context_type: 'employee', intent: 'create'},
    setConversationAttachments: (surface, value) => {
      if (surface === 'panel') host.S.conversationPanel.attachments = value;
      else host.S.chatAttachments = value;
    },
    refreshConversationDraftItems: () => {},
    rerenderConversation: () => {},
    addConversationFiles: (_surface, files) => calls.push({uploads: Array.from(files, file => file.name)}),
    toast: (_message, _level, key) => calls.push({error: key}),
    prepareConversationLocalReferences: async (_surface, result) => calls.push({refs: result.references}),
  });
  vm.runInContext(capabilityMarkers + "\n" + editor, host);
  host.conversationSelectionOffsets = () => selection;
  for (const name of ['addConversationPickedAttachments', 'applyConversationPaste']) {
    vm.runInContext(shell.match(new RegExp('function ' + name + '\\([^]*?\\n}'))[0], host);
  }
  const paste = ({files = [], directory = false, trusted = true, text = '', uri = ''} = {}) => host.conversationPaste({
    isTrusted: trusted,
    currentTarget: box,
    preventDefault() {},
    clipboardData: {
      files,
      items: directory ? [{kind: 'file', webkitGetAsEntry: () => ({isDirectory: true})}] : [],
      types: files.length ? ['Files'] : uri ? ['text/plain', 'text/uri-list'] : ['text/plain'],
      getData: type => type === 'text/plain' ? text : uri,
    },
  }, surface);
  const attachments = () => JSON.parse(JSON.stringify(host.conversationAttachments(surface)));
  return {paste, calls, box, host, select: (start, end) => { selection = {start, end}; }, selection: () => selection, attachments};
}

const folderFile = {name: 'project.txt', size: 0, type: 'text/plain'};
const folderPaths = ['/Users/example/项目目录', '/Users/example/My Project'];
const browserFile = {name: 'notes.txt', size: 10, type: 'text/plain'};
const screenshot = {name: 'screenshot.png', type: 'image/png', size: 100};
const fileRequest = {url: '/api/attachments/paste', method: 'POST', body: {}};
const referenceRequest = {url: '/api/local-references/paste', method: 'POST', body: {}};

for (const [name, options, request] of [
  ['chat', {}, fileRequest],
  ['create', {surface: 'panel'}, fileRequest],
  ['employee work', {surface: 'panel', worker: true}, referenceRequest],
]) {
  test(`pasted directories become attachment row labels in the ${name} composer`, async () => {
    const page = setup({...options, result: {folder_paths: folderPaths}});
    await page.paste({files: [folderFile], directory: true});
    assert.deepEqual(page.calls, [request]);
    assert.deepEqual(page.attachments().map(item => item.path), folderPaths);
  });
}

test('worker desktop paste reads paths once and asks the server to handle pasted paths', async () => {
  const page = setup({
    surface: 'panel', worker: true, native: folderPaths,
    result: {folder_paths: folderPaths, references: []},
  });
  await page.paste({text: '项目目录'});
  assert.deepEqual(page.calls, [
    {bridge: {}},
    {url: '/api/local-references/prepare', method: 'POST', body: {paths: folderPaths, paste: true}},
  ]);
  assert.deepEqual(page.attachments().map(item => item.path), folderPaths);
});

for (const surface of ['chat', 'panel']) {
  test(`desktop ${surface} handles a directory paste without HTML file types`, async () => {
    const page = setup({surface, native: folderPaths});
    await page.paste({text: '项目目录'});
    assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}]);
    assert.deepEqual(page.attachments().map(item => item.path), folderPaths);
  });
}

test('a missing directory path cannot become an uploaded file', async () => {
  const page = setup();
  await page.paste({files: [folderFile], directory: true});
  assert.deepEqual(page.calls, [fileRequest, {error: 'localReference.pathMissing'}]);
  assert.deepEqual(page.attachments(), []);
});

test('normal files and screenshots can still upload, and a path string stays text', async () => {
  const page = setup();
  const typedPath = 'file:///tmp/project.txt';
  await page.paste({text: typedPath, uri: typedPath});
  await page.paste({files: [browserFile]});
  await page.paste({files: [screenshot]});
  assert.deepEqual(page.calls, [
    {text: typedPath},
    fileRequest,
    {uploads: ['notes.txt']},
    fileRequest,
    {uploads: ['screenshot.png']},
  ]);
});

test('desktop ordinary text pastes normally when there are no directories', async () => {
  const page = setup({native: []});
  await page.paste({text: 'ordinary text'});
  assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, {text: 'ordinary text'}]);
});

for (const surface of ['chat', 'panel']) {
  test(`older desktop shells let ${surface} paste folders through the local API`, async () => {
    const page = setup({surface, native: () => { throw new Error('Unavailable'); }, result: {folder_paths: folderPaths}});
    await page.paste({text: '项目目录'});
    assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, fileRequest]);
    assert.deepEqual(page.attachments().map(item => item.path), folderPaths);
  });
}

test('desktop ordinary text still pastes if the folder-only bridge and API are unavailable', async () => {
  const unavailable = () => { throw new Error('Unavailable'); };
  const page = setup({native: unavailable, result: unavailable});
  await page.paste({text: 'ordinary text'});
  assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, fileRequest, {text: 'ordinary text'}]);
});

test('a folder label preserves the draft selection and shows its exact path on hover', async () => {
  const path = '/Users/example/<项目 📁>&\u00a0资料';
  const page = setup({result: {folder_paths: [path]}});
  page.box.value = '🔍查看占位符里的文档';
  page.select(4, 7);
  await page.paste({files: [folderFile], directory: true});
  assert.equal(page.box.value, '🔍查看占位符里的文档');
  assert.deepEqual(page.selection(), {start: 4, end: 7});
  assert.equal(page.host.conversationEditorHtml(page.box.value, []), page.box.value);
  const [item] = page.attachments();
  assert.equal(item.kind, 'folder_path');
  assert.equal(item.path, path);
  assert.equal(item.name, '<项目 📁>&\u00a0资料');
  const html = page.host.conversationDraftItemsHtml('chat');
  assert.match(html, /^<div class="cattachment draft" title="\/Users\/example\/&lt;项目 📁&gt;&amp;\u00a0资料"/);
  assert.match(html, /data-icon="folder"><\/svg><span><b lang="zh">&lt;项目 📁&gt;&amp;\u00a0资料<\/b>/);
  assert.ok(html.includes(`removeConversationAttachment('chat','${item.localId}')`));
});

test('folder labels persist with other draft attachments and can be removed independently', async () => {
  const page = setup({surface: 'panel', result: {folder_paths: folderPaths}});
  const {host} = page;
  vm.runInContext(shell.match(/^function removeConversationAttachment.*$/m)[0], host);
  vm.runInContext(shell.match(/^function serializableConversationDraft(?:Value|Attachment).*$/gm).join('\n'), host);
  const file = {name: 'notes.txt', kind: 'file', size: 10, localId: 'file-1', pickToken: 'file-token'};
  host.setConversationAttachments('panel', [file]);
  await page.paste({files: [folderFile], directory: true});
  const items = page.attachments();
  assert.deepEqual(JSON.parse(JSON.stringify(items.map(host.serializableConversationDraftAttachment))), items);
  host.removeConversationAttachment('panel', items[1].localId);
  assert.deepEqual(page.attachments(), [file, items[2]]);
});

test('a restored panel draft moves old directory markers into the attachment row', () => {
  const {host} = setup({surface: 'panel'});
  const [path] = folderPaths;
  const pathText = '查看 ' + path;
  host.S.conversationPanel.id = 'saved';
  host.S.conversationPanelDrafts = {
    'chat:saved': {input: pathText + `\uE002${encodeURIComponent(path)}\uE003`, attachments: []},
  };
  host.conversationPanelDraftKey = panel => 'chat:' + panel.id;
  vm.runInContext(shell.match(/^function serializableConversationDraftValue.*$/m)[0], host);
  vm.runInContext(shell.match(/^function restoreConversationPanelDraft[^]*?^}/m)[0], host);
  assert.equal(host.restoreConversationPanelDraft(), true);
  assert.equal(host.S.conversationPanel.input, pathText);
  assert.match(host.conversationDraftItemsHtml('panel'), /cattachment draft[^>]*title="\/Users\/example\/项目目录"/);
});

test('worker screenshot still uploads if there is no native path', async () => {
  const browser = setup({surface: 'panel', worker: true, result: {folder_paths: [], empty: true}});
  await browser.paste({files: [screenshot]});
  assert.deepEqual(browser.calls, [referenceRequest, {uploads: ['screenshot.png']}]);
  const desktop = setup({surface: 'panel', worker: true, native: []});
  await desktop.paste({files: [screenshot]});
  assert.deepEqual(desktop.calls, [{bridge: {}}, {uploads: ['screenshot.png']}]);
});

test('ordinary files in a mixed paste still use attachment tokens in chat', async () => {
  const page = setup({
    result: {folder_paths: folderPaths, items: [{token: 'file-token', name: 'notes.txt', kind: 'file', size: 10}]},
  });
  await page.paste({files: [folderFile, browserFile], directory: true});
  assert.deepEqual(page.calls, [fileRequest]);
  assert.deepEqual(page.attachments().map(item => item.path || item.pickToken), [...folderPaths, 'file-token']);
});

test('ordinary files in a mixed worker paste still use local references', async () => {
  const references = [{name: 'notes.txt', kind: 'local_asset', local_kind: 'file', grant_id: 1}];
  const page = setup({surface: 'panel', worker: true, result: {folder_paths: folderPaths, references}});
  await page.paste({files: [folderFile, browserFile], directory: true});
  assert.deepEqual(page.calls, [referenceRequest, {refs: references}]);
  assert.deepEqual(page.attachments().map(item => item.path), folderPaths);
});

test('a synthetic folder paste does not read the system clipboard', async () => {
  for (const options of [{}, {native: folderPaths}, {surface: 'panel', worker: true, native: folderPaths}]) {
    const page = setup(options);
    await page.paste({files: [folderFile], directory: true, trusted: false});
    assert.ok(!page.calls.some(call => call.url || call.bridge || call.uploads || call.text || call.folders));
    assert.deepEqual(page.attachments(), []);
  }
});

for (const [name, moveOn, added] of [
  ['composer removal', page => { page.box.isConnected = false; }, false],
  ['conversation change', page => { page.host.S.chatId = 'existing'; }, false],
  ['focus change', page => { page.host.document.activeElement = null; }, true],
  ['draft edits', page => { page.box.value = 'typing'; }, true],
  ['selection change', page => { page.select(1, 3); }, true],
]) {
  test(`a pending directory paste ${added ? "completes" : "is discarded"} after ${name}`, async () => {
    let finish;
    const page = setup({result: () => new Promise(resolve => { finish = resolve; })});
    const pasted = page.paste({files: [folderFile], directory: true});
    moveOn(page);
    finish({folder_paths: folderPaths});
    await pasted;
    assert.deepEqual(page.calls, [fileRequest]);
    assert.deepEqual(page.attachments().map(item => item.path), added ? folderPaths : []);
  });
}

function setupFolderMessage() {
  const {host} = setup();
  host.restoredAgentTrace = () => null;
  host.formatFileSize = size => String(size);
  host.ICON = name => `<svg aria-hidden="true" data-icon="${name}"></svg>`;
  host.esc = text => String(text).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  return host;
}

test('send appends folder paths with exact ranges and history restores only those paths as labels', () => {
  const host = setupFolderMessage();
  const path = '/path/带空格 📁 <样例>';
  const otherPath = '/second/项目';
  const draft = `📂 普通文字 ${path}`;
  const refs = [];
  const folders = [path, otherPath].map(host.conversationFolderDraftAttachment);
  const text = host.conversationMessageFromDraft(draft, [], refs, folders);
  const start = Array.from(draft).length + 1;
  const end = start + Array.from(path).length;
  assert.equal(text, `${draft}\n${path}\n${otherPath}`);
  assert.deepEqual(JSON.parse(JSON.stringify(refs)), [
    {start, end}, {start: end + 1, end: end + 1 + Array.from(otherPath).length},
  ]);

  const metadata = JSON.parse(JSON.stringify(host.conversationFolderSendFields(refs)));
  const saved = host.storedConversationMessage({id: 23, role: 'user', text, metadata});
  const restored = host.conversationDraftFromMessage(saved.text, saved.capabilities, saved.metadata.folder_refs);
  assert.equal(restored.text, draft);
  assert.deepEqual(Array.from(restored.folders, item => item.path), [path, otherPath]);
  assert.equal(host.conversationDraftFromMessage(text, []).text, text);
  const files = [{name: '说明.txt', kind: 'file', size: 42}, ...restored.folders];
  const labels = host.chatMessageAttachments(files);
  assert.equal((labels.match(/class="cmessage-files"/g) || []).length, 1);
  assert.match(labels, /说明\.txt/);
  assert.match(labels, /<b>带空格 📁 &lt;样例&gt;<\/b>/);

  const generatedPrefix = '创建智能体团队：';
  const generated = host.conversationFolderSendFields(refs, generatedPrefix.length);
  assert.equal(host.conversationDraftFromMessage(generatedPrefix + text, [], generated.folder_refs).text, generatedPrefix + draft);

  const legacy = `查看 ${path}，继续处理 ${path}`;
  const legacyStart = Array.from('查看 ').length;
  const legacyDraft = host.conversationDraftFromMessage(legacy, [], [{start: legacyStart, end: legacyStart + Array.from(path).length}]);
  assert.equal(legacyDraft.text, `查看 ，继续处理 ${path}`);
  assert.deepEqual(Array.from(legacyDraft.folders, item => item.path), [path]);
});

test('folder-only queue entries survive restoration and show the folder during editing', () => {
  const host = setupFolderMessage();
  const path = '/tmp/local folder';
  host.S.chatId = 34;
  host.S.chatBusy = true;
  const owner = host.conversationQueueOwner('chat');
  host.serializableConversationDraftAttachment = item => item;
  const folder = host.conversationFolderDraftAttachment(path);
  host.conversationQueueRestore(owner, {items: [
    {id: 'queue-1', text: '', folders: [folder]},
    {id: 'queue-2', text: `先查看 \uE002${encodeURIComponent(path)}\uE003\n后处理 ${path}`},
  ]});

  const preview = host.conversationQueueMarkup('chat');
  assert.equal((preview.match(/class="cmessage-file folder"/g) || []).length, 2);
  assert.match(preview, /后处理 \/tmp\/local folder/);
  const [queued, legacy] = host.conversationQueueSnapshot(owner).items;
  assert.equal(queued.text, '');
  assert.equal(queued.folders[0].path, path);
  assert.equal(legacy.folders[0].path, path);

  const queue = host.conversationQueueState('chat');
  queue.editing = 'queue-1';
  const editor = host.conversationQueueMarkup('chat');
  assert.match(editor, /<textarea data-queue-editor/);
  assert.match(editor, /data-queue-action="save" +onclick/);
  assert.equal((editor.match(/class="cmessage-file folder"/g) || []).length, 2);
  const refs = [];
  assert.equal(host.conversationMessageFromDraft('', [], refs, queued.folders), path);
  assert.deepEqual(JSON.parse(JSON.stringify(refs)), [{start: 0, end: path.length}]);
});

for (const surface of ['chat', 'panel']) {
  test(`${surface} sends directories as text with file upload kept separate and restores both on failure`, async () => {
    const host = setupFolderMessage();
    const path = '/目录/Research 📂';
    const folder = host.conversationFolderDraftAttachment(path);
    const file = {kind: 'file', name: 'example.txt', file: {name: 'example.txt'}, localId: 'file-1'};
    const uploads = [], requests = [];
    const panel = {id: 23, input: '', attachments: [folder, file], messages: []};
    Object.assign(host.S, {chatId: 23, chatDraft: '', chatAttachments: [folder, file], chatMsgs: [], chatCfg: {}, conversationPanel: panel, conversationPanelDrafts: {}});
    Object.assign(host, {
      _workspaceBusinessGeneration: 1,
      _conversationPanelDraftSaveTimer: null,
      clearTimeout: () => {},
      readChatFile: async item => { uploads.push(item); return {name: item.name}; },
      streamApi: async (url, body) => { requests.push({url, body}); throw Error('rejected'); },
      api: async () => ({}),
      conversationChatDirectory: async () => ({chats: []}),
      conversationEmployeeAssetMissing: () => false,
      conversationEmployeeGuidance: () => null,
      conversationExampleBindings: () => ({}),
      validateConversationExampleMaterials: () => true,
      conversationViewContext: () => ({}),
      captureConversationPanelDraft: () => {},
      conversationPanelDraftKey: () => 'test',
      conversationPanelIsVisibleHere: () => true,
      rememberConversationPanel: () => {},
      saveConversationPanelDrafts: () => {},
      serializableConversationDraftAttachment: item => item,
      serializableConversationDraftValue: item => item,
      RunTeamsEmployeeConfiguration: {prepareApplications: async () => {}},
      conversationPanelSendConfig: () => ({}),
      handleAgentChannelError: () => false,
      render: () => {},
      requestAnimationFrame: () => {},
      scrollConversationPanel: () => {},
      scrollChat: () => {},
    });
    host.conversationRuntimeReady = () => true;
    host.conversationCapabilitiesForSend = () => [];
    host.document.getElementById = () => ({});
    host.conversationInputValue = () => '';
    host.newLiveAgentMessage = () => ({role: 'bot'});
    vm.runInContext(shell.match(/async function sendConversationPanel\(options=\{\}\)\{[^]*?\n\}/)[0], host);

    const result = await (surface === 'panel' ? host.sendConversationPanel() : host.sendChat());
    assert.equal(result.accepted, false);
    assert.deepEqual(uploads, [file]);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].body.message, path);
    assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body.folder_refs)), [{start: 0, end: Array.from(path).length}]);
    assert.deepEqual(Array.from(requests[0].body.attachments, item => item.name), [file.name]);
    assert.equal(requests[0].body.attachment_tokens.length, 0);
    assert.deepEqual(Array.from(host.conversationAttachments(surface)), [folder, file]);
  });
}

test('sending a folder as a supplement clears it only after a confirmed receipt', async () => {
  const host = setupFolderMessage();
  const path = '/目录/补充 📂';
  const folder = host.conversationFolderDraftAttachment(path);
  const requests = [];
  Object.assign(host.S, {chatId: 23, chatAttachments: [folder], chatMsgs: [], chatCanSteer: true});
  Object.assign(host, {
    conversationInputElement: () => ({}),
    conversationInputValue: () => '',
    conversationCapabilitiesForSend: () => [],
    setConversationDraftValue: () => {},
    setConversationInputValue: () => {},
    conversationSyncSendState: () => {},
    render: () => {},
    api: async (_url, _method, body) => {
      requests.push(body);
      if (requests.length === 1) return {error: 'rejected'};
      return {accepted: true, message_id: 99, text: body.message, folder_refs: body.folder_refs};
    },
  });
  await host.conversationSteer('chat');
  assert.equal(host.S.chatAttachments[0], folder);
  await host.conversationSteer('chat');
  assert.equal(host.S.chatAttachments.length, 0);
  assert.equal(requests.length, 2);
  assert.equal(requests[1].message, path);
  assert.deepEqual(JSON.parse(JSON.stringify(requests[1].folder_refs)), [{start: 0, end: Array.from(path).length}]);
  assert.equal(host.S.chatMsgs[0].metadata.folder_refs, requests[1].folder_refs);
});
