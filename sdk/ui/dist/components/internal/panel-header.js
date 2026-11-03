import {element, button, icon} from './dom.js';

function normalizeExtras({text = '', actions = []} = {}) {
  if (typeof text !== 'string' || !Array.isArray(actions)) throw new TypeError('Header extras require text and an actions array');
  const ids = new Set();
  const copies = Array.from(actions, action => {
    if (!action || typeof action.id !== 'string' || !action.id.trim() || ids.has(action.id) ||
        typeof action.label !== 'string' || !action.label.trim() || typeof action.onPress !== 'function' ||
        (action.disabled !== undefined && typeof action.disabled !== 'boolean')) {
      throw new TypeError('Each header action requires a unique id, a label, an onPress callback and optional boolean disabled');
    }
    ids.add(action.id);
    return {...action};
  });
  return {text, actions: copies};
}

/** Fixed drawer toolbar: collapse control stays outside author extension regions. */
export function createDrawerHeader({document: doc = globalThis.document, onCollapse, extras = {}}) {
  if (!doc || typeof onCollapse !== 'function') throw new TypeError('A document and host onCollapse callback are required');
  const initial = normalizeExtras(extras);
  const header = element(doc, 'header', 'rt-drawer-header');
  const collapseButton = button(doc, '', 'rt-drawer-collapse');
  collapseButton.append(icon(doc, 'collapse'));
  collapseButton.setAttribute('aria-label', '折叠抽屉');collapseButton.title = '折叠抽屉';
  const collapse = () => {if (!disposed) onCollapse();};
  collapseButton.addEventListener('click', collapse);
  const extension = element(doc, 'div', 'rt-drawer-extras');
  const text = element(doc, 'span', 'rt-drawer-text');
  const actions = element(doc, 'div', 'rt-drawer-actions');
  extension.append(text, actions);header.append(collapseButton, extension);
  let disposed = false;
  const entries = new Map();
  function remove(entry) {
    entry.node.removeEventListener('click', entry.listener);
    entry.node.remove();
  }
  function setExtras(value = {}) {
    if (disposed) return;
    // Validate the whole update before modifying the visible header.
    const next = normalizeExtras(value);
    const focused = doc.activeElement;
    const ownedFocus = [...entries.values()].some(entry => entry.node === focused);
    if (text.textContent !== next.text) text.textContent = next.text;
    text.title = next.text;text.hidden = !next.text;
    const wanted = new Set(next.actions.map(action => action.id));
    for (const [id, entry] of entries) if (!wanted.has(id)) {remove(entry);entries.delete(id);}
    for (const [index, action] of next.actions.entries()) {
      let entry = entries.get(action.id);
      if (!entry) {
        const node = button(doc, action.label, 'rt-drawer-action');
        entry = {node, action, listener: null};
        entry.listener = event => {if (!disposed && !entry.node.disabled) entry.action.onPress(event);};
        node.addEventListener('click', entry.listener);
        entries.set(action.id, entry);
      }
      entry.action = action;
      if (entry.node.textContent !== action.label) entry.node.textContent = action.label;
      entry.node.title = action.label;entry.node.disabled = !!action.disabled;
      if (actions.children[index] !== entry.node) actions.insertBefore(entry.node, actions.children[index] || null);
    }
    actions.hidden = next.actions.length === 0;
    extension.hidden = text.hidden && actions.hidden;
    // Reordering keeps the same keyed node; removing/disabling the focused action
    // returns focus to the persistent collapse control.
    const oldEntry = [...entries.values()].find(entry => entry.node === focused);
    if (ownedFocus) {
      if (oldEntry && !oldEntry.node.disabled) oldEntry.node.focus({preventScroll: true});
      else collapseButton.focus({preventScroll: true});
    }
  }
  setExtras(initial);
  return {element: header, collapseButton, setExtras, dispose() {
    if (disposed) return;
    disposed = true;
    collapseButton.removeEventListener('click', collapse);collapseButton.disabled = true;
    for (const entry of entries.values()) {entry.node.removeEventListener('click', entry.listener);entry.node.disabled = true;}
    entries.clear();
  }};
}
