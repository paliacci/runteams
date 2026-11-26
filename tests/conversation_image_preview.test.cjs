const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/modules/conversation.js'), 'utf8');
const handlers = source.slice(source.indexOf('function chatAttachmentUrl('),
  source.indexOf('\n/* module-function:', source.indexOf('function chatMessageAttachments(')));
const issue = {id: 'a'.repeat(24), kind: 'image', name: '图 "&".png'};
const url = '/api/chat/1/attachment/' + issue.id;
const esc = value => String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

test('the Windows desktop opens a dialog for a sent image and browsers keep the attachment link', () => {
  const host = vm.createContext({esc, S: {chatId: 1}});
  vm.runInContext(handlers, host);
  const link = host.chatMessageAttachments([issue], 1);
  assert.ok(link.includes('href="' + url + '" target="_blank"'));
  host.chrome = {webview: {}};
  const desktop = host.chatMessageAttachments([issue], 1);
  assert.match(desktop, /<button[^>]+aria-haspopup="dialog"[^>]+previewChatImageAttachment/);
  assert.ok(desktop.includes('src="' + url + '" alt="图 &quot;&amp;&quot;.png"'));
  assert.doesNotMatch(desktop, /target="_blank"/);
});

test('a pending native attachment shows sending while the folder keeps its file count', () => {
  const host = vm.createContext({esc, ICON: () => '', formatFileSize: () => '74 B', S: {chatId: 1}});
  vm.runInContext(handlers, host);
  const items = [{...issue, id: 'pending-image'}, {id: 'pending-folder', kind: 'folder', name: '目录', file_count: 2}];
  const sending = host.chatMessageAttachments(items, 1, true);
  assert.match(sending, /data-app-i18n="conversationQueue.sending"/);
  assert.match(sending, /2 个文件/);
  assert.doesNotMatch(sending, /conversationAttachment.unavailable/);
  assert.doesNotMatch(sending, /\/api\/chat\//);
  assert.match(host.chatMessageAttachments(items, null), /conversationAttachment.unavailable/);
  assert.match(host.chatMessageAttachments([{...items[0], preview: 'blob:local-preview'}], 1, true),
    /src="blob:local-preview"/);
});

test('attachment preview uses the original image URL and the shared focus-managed dialog', () => {
  const imageEvents = {}, dialogEvents = {}, error = {hidden: true};
  const image = {addEventListener: (name, listener) => { imageEvents[name] = listener; }};
  let options, inserted, closed = false;
  const dialog = {
    querySelector: selector => selector === '[role="alert"]' ? error : {prepend(node) { inserted = node; }},
    addEventListener: (name, listener) => { dialogEvents[name] = listener; },
  };
  const host = vm.createContext({
    esc, RunTeamsLocale: {t: (_, _vars, text) => text, apply() {}},
    document: {createElement: () => image},
    openChildDialog: value => { options = value; return dialog; },
    closeChildDialog: () => { closed = true; },
  });
  vm.runInContext(handlers, host);
  host.previewChatImageAttachment({querySelector: () => ({alt: issue.name, currentSrc: url})});
  assert.equal(options.manageFocus, true);
  assert.equal(options.title, issue.name);
  assert.equal(inserted, image);
  assert.equal(image.src, url);
  imageEvents.error();
  assert.equal(error.hidden, false);
  assert.equal(image.hidden, true);
  dialogEvents.keydown({key: 'Escape', preventDefault() {}, stopPropagation() {}});
  assert.equal(closed, true);
});
