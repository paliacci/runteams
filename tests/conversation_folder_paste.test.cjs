const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const editor = fs.readFileSync('web/modules/conversation.js', 'utf8');
const shell = fs.readFileSync('web/index.html', 'utf8');

function setup({surface = 'chat', worker = false, native, result = {folder_paths: []}} = {}) {
  const calls = [];
  let attachments = [];
  let selection = {start: 0, end: 0};
  const box = {isConnected: true, isContentEditable: true, value: ''};
  const host = vm.createContext({
    S: {chatId: 'new', chatAttachments: [], conversationPanel: {}},
    window: native ? {webkit: {messageHandlers: {runteamsLocalReferencePaste: {
      postMessage: async request => {
        calls.push({bridge: {...request}});
        return typeof native === 'function' ? native() : native;
      },
    }}}} : {},
    document: {activeElement: box, execCommand: (command, _ui, text) => {
      assert.equal(command, 'insertText');
      calls.push({text});
      box.value = box.value.slice(0, selection.start) + text + box.value.slice(selection.end);
      const end = selection.start + text.length;
      selection = {start: end, end};
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
  vm.runInContext(editor, host);
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
  return {paste, calls, box, host, select: (start, end) => { selection = {start, end}; }, attachments: () => attachments};
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
  test(`pasted directories become only draft text in the ${name} composer`, async () => {
    const page = setup({...options, result: {folder_paths: folderPaths}});
    await page.paste({files: [folderFile], directory: true});
    assert.deepEqual(page.calls, [request, {text: folderPaths.join('\n')}]);
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
    {text: folderPaths.join('\n')},
  ]);
  assert.deepEqual(page.attachments(), []);
});

for (const surface of ['chat', 'panel']) {
  test(`desktop ${surface} handles a directory paste without HTML file types`, async () => {
    const page = setup({surface, native: folderPaths});
    await page.paste({text: '项目目录'});
    assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, {text: folderPaths.join('\n')}]);
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
    assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, fileRequest, {text: folderPaths.join('\n')}]);
  });
}

test('desktop ordinary text still pastes if the folder-only bridge and API are unavailable', async () => {
  const unavailable = () => { throw new Error('Unavailable'); };
  const page = setup({native: unavailable, result: unavailable});
  await page.paste({text: 'ordinary text'});
  assert.deepEqual(page.calls, [{bridge: {folderPathsOnly: true}}, fileRequest, {text: 'ordinary text'}]);
});

test('a folder path replaces the editor selection and remains editable as text', async () => {
  const path = folderPaths[0];
  const page = setup({result: {folder_paths: [path]}});
  page.box.value = '查看占位符里的文档';
  page.select(2, 5);
  await page.paste({files: [folderFile], directory: true});
  assert.equal(page.box.value, `查看${path}里的文档`);
  page.select(2 + path.length - 2, 2 + path.length);
  await page.paste({text: '资料'});
  assert.equal(page.box.value, `查看${path.slice(0, -2)}资料里的文档`);
  assert.deepEqual(page.attachments(), []);
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
  assert.deepEqual(page.calls, [fileRequest, {text: folderPaths.join('\n')}]);
  assert.deepEqual(page.attachments().map(item => item.pickToken), ['file-token']);
});

test('ordinary files in a mixed worker paste still use local references', async () => {
  const references = [{name: 'notes.txt', kind: 'local_asset', local_kind: 'file', grant_id: 1}];
  const page = setup({surface: 'panel', worker: true, result: {folder_paths: folderPaths, references}});
  await page.paste({files: [folderFile, browserFile], directory: true});
  assert.deepEqual(page.calls, [referenceRequest, {text: folderPaths.join('\n')}, {refs: references}]);
});

test('a synthetic folder paste does not read the system clipboard', async () => {
  for (const options of [{}, {native: folderPaths}, {surface: 'panel', worker: true, native: folderPaths}]) {
    const page = setup(options);
    await page.paste({files: [folderFile], directory: true, trusted: false});
    assert.ok(!page.calls.some(call => call.url || call.bridge || call.uploads || call.text));
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
