const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.resolve(__dirname, '../web');
const context = {
  S: {docsQuery: '', documentSources: {key: 'library', device: {loaded: true}}},
  documentsReadKey: () => 'library', documentsLocalAvailable: () => true,
  activeDocsMove: () => null, docsListedFolders: () => [], docsBreadcrumbMarkup: () => '',
  docsSortedVisible: () => [], esc: String, ICON: () => '',
  modelChannelText: (_key, fallback) => fallback, channelCardsMarkup: () => '', RunTeamsModelChannels: {definitionError: () => ''},
};
context.window = context;
vm.createContext(context);
for (const file of ['ui/host.js', 'ui/empty-states.js', 'ui/load-failure.js',
                    'ui/page-skeletons.js', 'ui/static-pages.js', 'modules/account.js']) {
  vm.runInContext(fs.readFileSync(path.join(web, file), 'utf8'), context, {filename: file});
}
const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
const start = html.indexOf('function docsListMarkup(');
const end = html.indexOf('function docsMain(', start);
assert.ok(start >= 0 && end > start);
vm.runInContext(html.slice(start, end), context);
assert.match(context.docsListMarkup(), /data-empty-state="documents"/);
context.S.docsQuery = 'missing';
assert.match(context.docsListMarkup(), /data-empty-state="documentsSearch"/);
context.S.documentsError = 'read failed';
assert.doesNotMatch(context.docsListMarkup(), /data-empty-state=/);
assert.match(context.docsListMarkup(), /retryDocumentList/);
context.S.documentsError = '';
context.S.documentSources.device.loaded = false;
context.S.documentsLoading = true;
assert.match(context.docsListMarkup(), /skeleton/);
assert.equal(context.RunTeamsEmptyStates.markup('unknown'), '');
assert.match(context.settingsChannelContents(), /modelChannel.listEmpty/);
context.S.environmentLoading = true;
assert.match(context.settingsChannelContents(), /role="status"/);
context.S.environmentLoading = false;
context.S.channelSettingsError = 'read failed';
assert.match(context.settingsChannelContents(), /role="alert"/);
context.channelCardsMarkup = () => '<button>channel</button>';
context.S.channels = [{id: 1}];
assert.match(context.settingsChannelContents(), /<button>channel/);
