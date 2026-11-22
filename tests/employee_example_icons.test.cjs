const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

test('employee suggestions keep their asset icons when reordered and older examples can omit one', () => {
  const model = JSON.parse(fs.readFileSync('contracts/product-model-v2.json', 'utf8'));
  const schema = model.$defs.work_example;
  const sprites = fs.readFileSync('web/index.html', 'utf8');
  const symbols = new Set(Array.from(sprites.matchAll(/<symbol id="([^"]+)"/g), match => match[1]));
  for (const icon of schema.properties.icon.enum) assert.ok(symbols.has('i-' + icon), icon);
  assert.ok(!schema.required.includes('icon'));

  const host = {
    document: {getElementById: id => symbols.has(id) ? {localName:'symbol'} : null},
    RunTeamsEmployeeDirectory: {forPanel: () => null},
    workExampleItems: works => works.flatMap(work => work.examples),
    workExamplePreview: text => text,
  };
  vm.runInNewContext(fs.readFileSync('web/modules/conversation.js', 'utf8'), host);
  host.conversationNewAction = (title, action, icon) => title + '/' + icon;
  host.conversationNewEmpty = ({actions}) => actions;
  function render(examples) {
    return host.conversationEmployeeEmpty({}, {employee:{skills:[{examples}]}}, '');
  }
  const draft = {title:'Write', prompt:'Write a summary', icon:'edit'};
  const lookup = {title:'Find', prompt:'Find the report', icon:'search'};
  const legacy = {title:'Help', prompt:'Help with a task'};
  assert.equal(render([draft, legacy, lookup]), 'Write/editHelp/sparkFind/search');
  assert.equal(render([lookup, draft, legacy]), 'Find/searchWrite/editHelp/spark');
  assert.equal(render([{...lookup, icon:'unknown-icon'}]), 'Find/spark你能帮我做什么？/briefcase');
  assert.equal(render([]), '你能帮我做什么？/briefcase我需要先准备哪些资料？/doc');
  assert.equal(render([draft,draft,lookup]), 'Write/editFind/search');
  assert.equal(render([draft,legacy,lookup,{title:'Fourth',prompt:'Fourth item'}]), 'Write/editHelp/sparkFind/search');
});
