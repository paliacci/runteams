const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const editor = fs.readFileSync('web/modules/conversation.js', 'utf8');
const shell = fs.readFileSync('web/index.html', 'utf8');
const capabilityMarkers = shell.match(/^const CAPABILITY_MARKER_OPEN=.*$/m)[0];

function setup({surface = 'chat', worker = false, native, result = {folder_paths: []}} = {}) {
  const calls = [];
  let attachments = [];
  let selection = {start: 0, end: 0};
  const chips = [];
  const box = {
    isConnected: true, isContentEditable: true, value: '',
    querySelectorAll: () => chips.filter(chip => chip.contentEditable !== 'false'),
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
      let text = content;
      if (command === 'insertHTML') {
        const folders = Array.from(content.matchAll(/data-folder-path="([^"]+)"/g), match => decodeURIComponent(match[1]));
        assert.doesNotMatch(content, /contenteditable|cinline-folder/);
        chips.push(...folders.map(() => ({classList: new Set(), contentEditable: 'inherit'})));
        calls.push({folders});
        text = folders.map(path => host.conversationFolderMarker(path)).join('\n');
      } else {
        assert.equal(command, 'insertText');
        calls.push({text});
      }
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
    setConversationAttachments: (_surface, value) => { attachments = JSON.parse(JSON.stringify(value)); },
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
  return {paste, calls, chips, box, host, select: (start, end) => { selection = {start, end}; }, attachments: () => attachments};
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
  test(`pasted directories become inline draft labels in the ${name} composer`, async () => {
    const page = setup({...options, result: {folder_paths: folderPaths}});
    await page.paste({files: [folderFile], directory: true});
    assert.deepEqual(page.calls, [request, {folders: folderPaths}]);
    assert.deepEqual(page.attachments(), []);
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
    {folders: folderPaths},
  ]);
  assert.deepEqual(page.attachments(), []);
});

for (const surface of ['chat', 'panel']) {
  test(`desktop ${surface} handles a directory paste without HTML file types`, async () => {
    const page = setup({surface, native: folderPaths});
    await page.paste({text: '项目目录'});
    assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, {folders: folderPaths}]);
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
    assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, fileRequest, {folders: folderPaths}]);
  });
}

test('desktop ordinary text still pastes if the folder-only bridge and API are unavailable', async () => {
  const unavailable = () => { throw new Error('Unavailable'); };
  const page = setup({native: unavailable, result: unavailable});
  await page.paste({text: 'ordinary text'});
  assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, fileRequest, {text: 'ordinary text'}]);
});

test('a folder label replaces the selection, preserves surrounding text, and sends the exact path', async () => {
  const path = '/Users/example/<项目 📁>&\u00a0资料';
  const page = setup({result: {folder_paths: [path]}});
  page.box.value = '🔍查看占位符里的文档';
  page.select(4, 7);
  await page.paste({files: [folderFile], directory: true});
  const [chip] = page.chips;
  assert.equal(chip.contentEditable, 'false');
  assert.ok(chip.classList.has('cinline-folder'));
  chip.contentEditable = 'inherit';
  page.host.conversationRestoreFolderChips(page.box, {inputType: 'historyRedo'});
  assert.equal(chip.contentEditable, 'false');
  const marker = page.host.conversationFolderMarker(path);
  assert.equal(page.box.value, `🔍查看${marker}里的文档`);
  const html = page.host.conversationEditorHtml(page.box.value, []);
  assert.match(html, /^🔍查看<span class="cinline-folder" contenteditable="false"/);
  assert.match(html, /data-icon="folder"><\/svg><b lang="zh">&lt;项目 📁&gt;&amp;\u00a0资料<\/b><\/span>里的文档$/);
  const folderRefs = [];
  assert.equal(page.host.conversationMessageFromDraft(page.box.value, [], folderRefs), `🔍查看${path}里的文档`);
  assert.deepEqual(JSON.parse(JSON.stringify(folderRefs)), [{start: 3, end: 3 + [...path].length}]);
  assert.deepEqual(page.attachments(), []);
});

test('folder labels round-trip beside capability labels and a manually entered path', () => {
  const path = '/Users/example/资料\uE000名';
  const {host} = setup();
  const items = [{id: 'example', label: 'Example', mention_id: 'test'}];
  const capability = host.conversationCapabilityMarker('test');
  const label = host.conversationFolderMarker(path);
  const html = host.conversationEditorHtml(`${capability} ${label}\n${path}`, items);
  assert.equal((html.match(/class="cinline-folder"/g) || []).length, 1);
  assert.match(html, /data-capability-mention="test"/);
  assert.ok(html.endsWith('<br>' + path));
  const folderRefs = [];
  const prefix = '[[capability:test]] ';
  assert.equal(host.conversationMessageFromDraft(`${capability} ${label}\n${path}`, items, folderRefs), `${prefix}${path}\n${path}`);
  assert.deepEqual(JSON.parse(JSON.stringify(folderRefs)), [{start: prefix.length, end: prefix.length + [...path].length}]);
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
  assert.deepEqual(page.calls, [fileRequest, {folders: folderPaths}]);
  assert.deepEqual(page.attachments().map(item => item.pickToken), ['file-token']);
});

test('ordinary files in a mixed worker paste still use local references', async () => {
  const references = [{name: 'notes.txt', kind: 'local_asset', local_kind: 'file', grant_id: 1}];
  const page = setup({surface: 'panel', worker: true, result: {folder_paths: folderPaths, references}});
  await page.paste({files: [folderFile, browserFile], directory: true});
  assert.deepEqual(page.calls, [referenceRequest, {folders: folderPaths}, {refs: references}]);
});

test('a synthetic folder paste does not read the system clipboard', async () => {
  for (const options of [{}, {native: folderPaths}, {surface: 'panel', worker: true, native: folderPaths}]) {
    const page = setup(options);
    await page.paste({files: [folderFile], directory: true, trusted: false});
    assert.ok(!page.calls.some(call => call.url || call.bridge || call.uploads || call.text || call.folders));
    assert.deepEqual(page.attachments(), []);
  }
});

for (const [name, moveOn] of [
  ['composer removal', page => { page.box.isConnected = false; }],
  ['conversation change', page => { page.host.S.chatId = 'existing'; }],
  ['focus change', page => { page.host.document.activeElement = null; }],
  ['draft edits', page => { page.box.value = 'typing'; }],
  ['selection change', page => { page.select(1, 3); }],
]) {
  test(`a pending directory paste cannot insert a path after ${name}`, async () => {
    let finish;
    const page = setup({result: () => new Promise(resolve => { finish = resolve; })});
    const pasted = page.paste({files: [folderFile], directory: true});
    moveOn(page);
    finish({folder_paths: folderPaths});
    await pasted;
    assert.deepEqual(page.calls, [fileRequest]);
    assert.deepEqual(page.attachments(), []);
  });
}

function setupFolderMessage() {
  const {host} = setup();
  host.restoredAgentTrace = () => null;
  host.ICON = name => `<svg aria-hidden="true" data-icon="${name}"></svg>`;
  host.esc = text => String(text).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  return host;
}

test('folder ranges preserve exact paths in sent text and restore only original chips', () => {
  const host = setupFolderMessage();
  const path = '/path/带空格 📁 <样例>';
  const folder = host.conversationFolderMarker(path);
  const prefix = `📂 普通文字 ${path}\n已粘贴：`;
  const draft = `${prefix}${folder} 及 ${folder}`;
  const refs = [];
  const text = host.conversationMessageFromDraft(draft, [], refs);
  const start = Array.from(prefix).length;
  const end = start + Array.from(path).length;
  const next = end + Array.from(' 及 ').length;
  assert.equal(text, `${prefix}${path} 及 ${path}`);
  assert.deepEqual(JSON.parse(JSON.stringify(refs)), [
    {start, end}, {start: next, end: next + Array.from(path).length},
  ]);

  const metadata = JSON.parse(JSON.stringify(host.conversationFolderSendFields(refs)));
  const saved = host.storedConversationMessage({id: 23, role: 'user', text, metadata});
  const html = host.chatMessageText(saved.text, saved.capabilities, saved.metadata.folder_refs);
  assert.equal((html.match(/class="cinline-folder"/g) || []).length, 2);
  assert.match(html, /普通文字 \/path\/带空格 📁 &lt;样例&gt;/);
  assert.match(html, /<b lang="zh">带空格 📁 &lt;样例&gt;<\/b>/);
  assert.equal(host.conversationDraftFromMessage(saved.text, saved.capabilities, saved.metadata.folder_refs), draft);
  assert.equal(host.conversationDraftFromMessage(text, []), text);
  assert.doesNotMatch(host.chatMessageText(text, []), /class="cinline-folder"/);

  const generatedPrefix = '创建智能体团队：';
  const generated = host.conversationFolderSendFields(refs, generatedPrefix.length);
  assert.equal(host.conversationDraftFromMessage(generatedPrefix + text, [], generated.folder_refs), generatedPrefix + draft);
});

test('a restored queued message previews and edits with the original folder chip', () => {
  const host = setupFolderMessage();
  const path = '/tmp/local folder';
  const draft = `先查看 ${host.conversationFolderMarker(path)} 后处理 ${path}`;
  host.S.chatId = 34;
  host.S.chatBusy = true;
  const owner = host.conversationQueueOwner('chat');
  host.conversationQueueRestore(owner, {items: [{id: 'queue-1', text: draft}]});

  const preview = host.conversationQueueMarkup('chat');
  assert.equal((preview.match(/class="cinline-folder"/g) || []).length, 1);
  assert.match(preview, /后处理 \/tmp\/local folder/);
  assert.equal(host.conversationQueueSnapshot(owner).items[0].text, draft);

  const queue = host.conversationQueueState('chat');
  queue.editing = 'queue-1';
  const editor = host.conversationQueueMarkup('chat');
  assert.match(editor, /data-queue-editor class="ccomposer-editor"/);
  assert.equal((editor.match(/class="cinline-folder"/g) || []).length, 1);
  assert.match(editor, /后处理 \/tmp\/local folder/);
});
