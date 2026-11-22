const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../web/modules/conversation.js'), 'utf8');
const formats = source.slice(source.indexOf('const conversationMessageTimeFormats='),
  source.indexOf('/* module-function:conversationMessageActions */'));
const divider = source.slice(source.indexOf('function conversationMessageDate('),
  source.indexOf('function conversationMessageIdentity('));

function render(language) {
  const date = value => value ? new Date(value) : null;
  const esc = value => String(value).replaceAll('"', '&quot;');
  const context = vm.createContext({docParseTime: date, esc});
  vm.runInContext("globalThis.RUNTEAMS_LOCALES={};", context);
  for (const file of ['locale-zh-cn.js', 'locale-en.js']) {
    vm.runInContext(readFileSync(join(__dirname, '../web/ui', file), 'utf8'), context);
  }
  context.RunTeamsLocale = {t(key, vars) {
    return context.RUNTEAMS_LOCALES[language][key].replace(/\{(\w+)\}/g, (_, name) => vars[name]);
  }};
  vm.runInContext(formats + divider, context);
  return context.conversationMessageDate;
}

test('the conversation divider uses today or a full date in the current language', () => {
  const today = new Date();
  today.setHours(13, 37, 0, 0);
  const previousDate = new Date(2021, 5, 23, 13, 37);
  const zh = render('zh-CN');
  const en = render('en');
  const message = ts => ({role: 'user', ts: ts.toISOString()});

  assert.match(zh(message(today)), />今天 13:37</);
  assert.match(en(message(today)), />Today, 1:37 PM</);
  assert.match(zh(message(previousDate)), />2021年6月23日 13:37</);
  assert.match(en(message(previousDate)), />June 23, 2021 at 1:37 PM</);

  const recent = new Date(today.getTime() - 15 * 60 * 1000);
  assert.equal(en(message(today), message(recent)), '');
  assert.equal(en({role: 'bot', ts: today.toISOString()}), '');
});
