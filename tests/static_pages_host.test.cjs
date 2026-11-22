const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../web/ui/static-pages.js'), 'utf8');

function staticPages({routes, url}) {
  const events = new Map();
  const saved = new Map();
  const title = {
    parentElement: {querySelector: () => null, querySelectorAll: () => []},
    getBoundingClientRect: () => ({height: 42}),
  };
  const context = {
    URL,
    location: new URL(url),
    innerWidth: 940,
    document: {querySelector: () => title},
    sessionStorage: {setItem: (key, value) => saved.set(key, value)},
    addEventListener: (event, listener) => events.set(event, listener),
    RunTeamsRoutes: routes,
    RunTeamsDeviceDisplay: {scope: 'device-fixture'},
    RunTeamsSkeletons: {normalize: value => value, workspaceHeader: () => ''},
    RunTeamsHost: {pages: {render: () => null}},
    RunTeamsShell: {pageHeader: heading => heading},
  };
  context.window = context;
  vm.runInNewContext(script, context);
  return {pages: context.RunTeamsStaticPages, pagehide: () => events.get('pagehide')(), saved};
}

test('a website without a route host can leave the page without reading desktop routes', () => {
  const {pages, pagehide, saved} = staticPages({url: 'https://website.test/?chat=1a000000'});
  assert.equal(pages.localConversationRoute(), false);
  assert.doesNotThrow(pagehide);
  assert.equal(saved.size, 0);
  assert.match(pages.page('conversation-new'), /data-app-i18n="newConversation.title"/);
});

test('the desktop route host still unwraps mounted routes and saves welcome dimensions', () => {
  const routes = {unmount: value => new URL(value).pathname.replace(/^\/app/, '')};
  const {pages, pagehide, saved} = staticPages({
    routes,
    url: 'https://desktop.test/app/employees/1a000000/chats/2a000000',
  });
  assert.equal(pages.localConversationRoute(), true);
  pagehide();
  assert.deepEqual(JSON.parse(saved.get('runteams.employee-welcome-size.v1')), {
    key: 'runteams.local-conversation-layout.v1:device-fixture:2a000000',
    width: 940,
    title: 42,
    buttons: [],
  });
});
