const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const editor = fs.readFileSync('web/modules/conversation.js', 'utf8');
const shell = fs.readFileSync('web/index.html', 'utf8');

function setup({surface = 'chat', worker = false, appInfo, result = {items: []}} = {}) {
  const calls = [];
  let attachments = [];
  const box = {isConnected: true, isContentEditable: true};
  const host = vm.createContext({
    S: {appInfo, chatId: 'new', chatAttachments: [], conversationPanel: {}},
    window: {},
    document: {execCommand: (_command, _ui, text) => calls.push({text})},
    api: async (url, method, body) => {
      calls.push({url, method, keys: Object.keys(body)});
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
  for (const name of ['addConversationPickedAttachments', 'applyConversationPaste', 'readConversationLocalReferenceEvent']) {
    vm.runInContext(shell.match(new RegExp('(?:async )?function ' + name + '\\([^]*?\\n}'))[0], host);
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
  return {paste, calls, box, attachments: () => attachments};
}

const folderFile = {name: 'project.txt', size: 0, type: 'text/plain'};
const folderItem = {token: 'chosen-folder', name: 'project.txt', kind: 'folder', size: 123, file_count: 2};

for (const surface of ['chat', 'panel']) {
  test(`a pasted directory uses normal attachment tokens on first load in the ${surface} composer`, async () => {
    const page = setup({surface, result: {items: [folderItem]}});
    await page.paste({files: [folderFile], directory: true});
    assert.deepEqual(page.calls, [{url: '/api/attachments/paste', method: 'POST', keys: []}]);
    const [attachment] = page.attachments();
    assert.equal(attachment.pickToken, folderItem.token);
    assert.equal(attachment.kind, 'folder');
    assert.equal(attachment.mime_type, 'inode/directory');
    assert.equal(attachment.file_count, 2);
  });
}

test('a missing or unsupported folder cannot become a regular uploaded file', async () => {
  for (const native_attachment_picker of [true, false]) {
    const page = setup({appInfo: {native_attachment_picker}});
    await page.paste({files: [folderFile], directory: true});
    assert.ok(page.calls.some(call => call.error));
    assert.ok(!page.calls.some(call => call.uploads));
    assert.deepEqual(page.attachments(), []);
  }
});

test('normal files and screenshots can still upload, and a path string stays text', async () => {
  const page = setup();
  const typedPath = 'file:///tmp/project.txt';
  await page.paste({text: typedPath, uri: typedPath});
  await page.paste({files: [folderFile]});
  await page.paste({files: [{name: 'screenshot.png', type: 'image/png', size: 100}]});
  assert.deepEqual(page.calls, [
    {text: typedPath},
    {url: '/api/attachments/paste', method: 'POST', keys: []},
    {uploads: ['project.txt']},
    {url: '/api/attachments/paste', method: 'POST', keys: []},
    {uploads: ['screenshot.png']},
  ]);
});

test('worker folder pastes keep the local reference path, with no upload fallback', async () => {
  const page = setup({surface: 'panel', worker: true, result: {empty: true}});
  const typedPath = 'file:///tmp/project.txt';
  await page.paste({text: typedPath, uri: typedPath});
  await page.paste({files: [folderFile], directory: true});
  assert.deepEqual(page.calls, [
    {text: typedPath},
    {url: '/api/local-references/paste', method: 'POST', keys: []},
    {error: 'localReference.pathMissing'},
  ]);
});

test('a synthetic folder paste does not read the system clipboard', async () => {
  const page = setup();
  await page.paste({files: [folderFile], directory: true, trusted: false});
  assert.ok(!page.calls.some(call => call.url || call.uploads));
  assert.deepEqual(page.attachments(), []);
});

test('a pending folder paste does not add an attachment after leaving the composer', async () => {
  let finish;
  const page = setup({result: () => new Promise(resolve => { finish = resolve; })});
  const pasted = page.paste({files: [folderFile], directory: true});
  page.box.isConnected = false;
  finish({items: [folderItem]});
  await pasted;
  assert.deepEqual(page.attachments(), []);
});
