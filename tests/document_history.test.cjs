const {strict: assert} = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const shell = fs.readFileSync(path.join(__dirname, '../web/ui/shell.js'), 'utf8');

test('dirty editor restores its history entry and only traverses after confirmation', () => {
  const entries = [{}, {}, {}];
  let index = 0, dirty = false, confirmation;
  const requested = [], routed = [], listeners = new Map();
  const history = {
    get state() { return entries[index]; },
    replaceState(state) { entries[index] = state; },
    go(offset) { requested.push(index + offset); },
  };
  const window = {
    history, location: {href: 'http://localhost/'},
    addEventListener(type, listener) { listeners.set(type, listener); },
  };
  vm.runInNewContext(shell, {window, document: {querySelectorAll: () => []}});
  const app = window.RunTeamsShell;
  app.setHistoryGuard({needsSave: () => dirty, confirm(resume, available) { confirmation = {resume, available}; }});
  function deliver(destination) {
    index = destination;
    let stopped = false;
    listeners.get('popstate')({stopImmediatePropagation() { stopped = true; }});
    if (!stopped) routed.push(index);
  }
  for (index = 1; index <= 2; index++) app.recordNavigation(false);
  index = 2;
  dirty = true;
  deliver(0);
  assert.deepEqual(requested, [2]);
  deliver(requested.shift());
  assert.equal(confirmation.available(), true);
  assert.deepEqual(routed, []);
  // Keeping the draft leaves the original cursor and forward range intact.
  assert.equal(history.state.runteamsNavigation.index, 2);
  deliver(1);
  deliver(requested.shift());
  dirty = false;
  confirmation.resume();
  deliver(requested.shift());
  assert.deepEqual(routed, [1]);
  assert.equal(history.state.runteamsNavigation.end, 2);
  dirty = true;
  deliver(2);
  deliver(requested.shift());
  dirty = false;
  confirmation.resume();
  deliver(requested.shift());
  assert.deepEqual(routed, [1, 2]);
  assert.deepEqual(requested, []);
});
