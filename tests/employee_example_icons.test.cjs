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

test('switching the interface language updates employee suggestions in place and preserves the draft', () => {
  const example = {
    title: '查找报告', prompt: '请查找这份报告。', skill_key: 'reports', requirements: [{name: 'brief'}],
    translations: {
      en: {title: 'Find the report', prompt: 'Find the report. Include its date.'},
      'zh-CN': {title: '检索报告', prompt: '请检索这份报告。'},
    },
  };
  const legacy = {title: '旧版标题', prompt: '旧版问题'};
  const incomplete = {...legacy, translations: {en: {title: 'Incomplete'}}};
  const panel = {input: 'My draft', attachments: [{name: 'Notes'}]};
  const buttons = [];
  let changes;
  let draftSaves = 0;
  const locale = {
    language: 'zh-CN',
    onChange: listener => { changes ||= listener; },
    t: (key, _vars, fallback) => locale.language === 'en' ? ({
      'employeeChat.canHelp': 'What can you help me with?',
      'employeeChat.whatToSend': 'What should I prepare?',
    }[key] ?? fallback) : fallback,
  };
  const host = vm.createContext({
    RunTeamsLocale: locale,
    RunTeamsEmployeeDirectory: {forPanel: () => null},
    S: {conversationPanel: panel},
    document: {getElementById: () => null, querySelectorAll: () => buttons},
    scheduleConversationPanelDraftSave: () => { draftSaves++; },
    render: () => {},
    ICON: () => '',
    esc: value => value.replaceAll('&', '&amp;').replaceAll('"', '&quot;'),
  });
  const shell = fs.readFileSync('web/index.html', 'utf8');
  for (const name of ['workExampleItems', 'workExamplePreview']) {
    vm.runInContext(shell.match(new RegExp('function '+name+'\\([^]*?\\n}'))[0], host);
  }
  vm.runInContext(fs.readFileSync('web/modules/conversation.js', 'utf8'), host);
  const guidance = {employee: {skills: [{key: 'reports', examples: [example], assets: [{name: 'brief'}]}]}};
  const rendered = host.conversationEmployeeEmpty(panel, guidance, '');
  assert.match(rendered, /检索报告.*请检索这份报告。/);
  assert.match(rendered, /data-work-example=.*translations/);
  const [authored, fallback] = host.conversationEmployeeExamples(panel, guidance);
  const button = (value, nodes = {}) => ({
    dataset: {workExample: JSON.stringify(value)},
    querySelector: selector => nodes[selector],
  });
  const heading = {}, preview = {};
  const chat = button(authored, {'.conversation-new-action-heading b': heading, '.conversation-new-action-description': preview});
  const overview = button(authored);
  const builtIn = button(fallback);
  const untranslated = button(legacy);
  const partial = button(incomplete);
  buttons.push(chat, overview, builtIn, untranslated, partial);

  locale.language = 'en';
  changes({language: 'en', previousLanguage: 'zh-CN'});
  assert.equal(heading.textContent, 'Find the report');
  assert.equal(preview.textContent, 'Find the report.');
  assert.equal(overview.textContent, 'Find the report');
  assert.equal(builtIn.textContent, 'What can you help me with?');
  assert.equal(untranslated.textContent, legacy.title);
  assert.equal(partial.textContent, legacy.title);
  assert.equal(panel.input, 'My draft');
  assert.equal(panel.attachments[0].name, 'Notes');
  assert.equal(draftSaves, 0);
  assert.match(host.conversationEmployeeEmpty(panel, guidance, ''), />Find the report<\/b>/);
  const unconfigured = {employee: {skills: [
    {name: '研究目标', objective: '请研究这个目标。'},
    {name: '核对摘要', summary: '请核对这个摘要。', examples: []},
  ]}};
  const generic = host.conversationEmployeeEmpty(panel, unconfigured, '');
  assert.match(generic, /What can you help me with\?.*What should I prepare\?/);
  assert.doesNotMatch(generic, /研究目标|核对摘要/);

  host.conversationPanelWorkExample(chat);
  assert.equal(panel.input, 'Find the report. Include its date.');
  assert.equal(panel.example_materials.skill_key, 'reports');
  assert.equal(panel.example_materials.requirements[0].name, 'brief');
  locale.language = 'zh-CN';
  changes({language: 'zh-CN', previousLanguage: 'en'});
  assert.equal(heading.textContent, example.translations['zh-CN'].title);
  assert.equal(preview.textContent, example.translations['zh-CN'].prompt);
  assert.equal(panel.input, 'Find the report. Include its date.');
  host.conversationPanelWorkExample(overview);
  assert.equal(panel.input, example.translations['zh-CN'].prompt);
  host.conversationPanelWorkExample(builtIn);
  assert.equal(panel.input, '你能帮我做什么？');
  assert.equal(panel.example_materials, null);
});
