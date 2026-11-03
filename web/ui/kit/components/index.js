import {element, button, icon, nextId} from './internal/dom.js';
export {createDrawerHeader} from './internal/panel-header.js';

/** A collapsible section with an independent full-view action and arbitrary content. */
export function createSection({document: doc = globalThis.document, title, summary = '', content, expanded = true, onOpenFull}) {
  if (!doc || !title || !content || content.ownerDocument !== doc) throw new TypeError('A title and content node from this document are required');
  const root = element(doc, 'section', 'rt-section');
  const heading = element(doc, 'div', 'rt-section-heading');
  const headingLabel = element(doc, 'h3', 'rt-section-heading-label');
  const toggle = button(doc, '', 'rt-section-toggle');
  const name = element(doc, 'span', 'rt-section-title', title);
  const description = element(doc, 'span', 'rt-section-summary', summary);
  toggle.append(name, description);
  toggle.id = nextId();
  headingLabel.append(toggle);
  const body = element(doc, 'div', 'rt-section-body');
  body.id = nextId();
  body.setAttribute('role', 'region');
  body.setAttribute('aria-labelledby', toggle.id);
  toggle.setAttribute('aria-controls', body.id);
  const open = button(doc, '', 'rt-icon-button');
  open.append(icon(doc, 'expand'));
  open.setAttribute('aria-label', `打开${title}完整视图`);
  open.title = '打开完整视图';
  open.hidden = !onOpenFull;
  heading.append(headingLabel, open);
  body.append(content);
  root.append(heading, body);
  let disposed = false;
  function setExpanded(value) {
    if (disposed) return;
    expanded = Boolean(value);
    if (!expanded && body.contains(doc.activeElement)) toggle.focus();
    toggle.setAttribute('aria-expanded', String(expanded));
    body.hidden = !expanded;
  }
  const toggleClick = () => setExpanded(!expanded);
  const openClick = () => onOpenFull?.();
  toggle.addEventListener('click', toggleClick);
  open.addEventListener('click', openClick);
  setExpanded(expanded);
  return {
    element: root, body, toggle, openButton: open,
    get expanded() { return expanded; },
    setExpanded,
    setSummary(value) { description.textContent = value; },
    dispose() { disposed = true; toggle.removeEventListener('click', toggleClick); open.removeEventListener('click', openClick); }
  };
}

/** Full-workspace composition; content is still owned by the caller. */
export function createFullView({document: doc = globalThis.document, title, employeeName = '', onReturn}) {
  const root = element(doc, 'section', 'rt-full-view');
  const header = element(doc, 'header', 'rt-full-header');
  const back = button(doc, '', 'rt-back-button');
  back.append(icon(doc, 'back'));
  back.setAttribute('aria-label', '返回抽屉');
  back.title = '返回抽屉';
  back.hidden = !onReturn;
  const navigation = element(doc, 'nav', 'rt-full-navigation');
  navigation.setAttribute('aria-label', '工作视图路径');
  const path = element(doc, 'ol', 'rt-breadcrumb');
  const employeeItem = element(doc, 'li', 'rt-breadcrumb-item');
  const employee = onReturn ? button(doc, employeeName, 'rt-breadcrumb-employee')
    : element(doc, 'span', 'rt-breadcrumb-label', employeeName);
  if (onReturn) employee.setAttribute('aria-label', `返回${employeeName}抽屉`);
  employeeItem.append(employee);
  employeeItem.hidden = !employeeName;
  const currentItem = element(doc, 'li', 'rt-breadcrumb-item');
  const separator = icon(doc, 'back');
  separator.classList.add('rt-breadcrumb-separator');
  separator.style.display = employeeName ? '' : 'none';
  const current = element(doc, 'span', 'rt-breadcrumb-current', title);
  current.setAttribute('aria-current', 'page');
  currentItem.append(separator, current);
  path.append(employeeItem, currentItem);
  navigation.append(back, path);
  const heading = element(doc, 'h2', 'rt-full-title', title);
  heading.tabIndex = -1;
  const body = element(doc, 'div', 'rt-full-body');
  header.append(navigation, heading);
  root.append(header, body);
  const goBack = () => onReturn?.();
  back.addEventListener('click', goBack);
  if (onReturn) employee.addEventListener('click', goBack);
  return {element: root, body, heading, backButton: back, employeeButton: onReturn && employeeName ? employee : null,
    dispose() { back.removeEventListener('click', goBack); employee.removeEventListener('click', goBack); }};
}

/** Two presentation slots, one live content node. No SDK or platform dependency. */
export function createModuleTemplate({document: doc = globalThis.document, title, employeeName, summary, content, expanded = true, onRequestMode}) {
  const section = createSection({document: doc, title, summary, content, expanded,
    onOpenFull: onRequestMode ? () => onRequestMode('full') : undefined});
  content.dataset.presentation = 'panel';
  const full = createFullView({document: doc, title, employeeName, onReturn: onRequestMode ? () => onRequestMode('panel') : undefined});
  full.element.hidden = true;
  let mode = 'panel';
  let disposed = false;
  const scrollPositions = new Map();
  const contentScrollPositions = new Map();
  const errors = [section.element, full.body].map(parent => {
    const message = element(doc, 'p', 'rt-error');
    message.setAttribute('role', 'alert');
    message.hidden = true;
    if (parent === section.element) parent.insertBefore(message, section.body);
    else parent.prepend(message);
    return message;
  });
  return {
    section, full,
    get mode() { return mode; },
    setMode(next) {
      if (disposed) throw new Error('Module template disposed');
      if (next !== 'panel' && next !== 'full') throw new TypeError('Unknown presentation mode');
      if (next === mode) return;
      const active = doc.activeElement;
      const focusedContent = content.contains(active) ? active : null;
      const selection = focusedContent && typeof focusedContent.selectionStart === 'number'
        ? [focusedContent.selectionStart, focusedContent.selectionEnd] : null;
      // Preserve each presentation's scroll position; the application owns data/drafts.
      const oldBody = mode === 'panel' ? section.body : full.body;
      scrollPositions.set(mode, [oldBody.scrollLeft, oldBody.scrollTop]);
      const newBody = next === 'panel' ? section.body : full.body;
      const innerScroll = [content, ...content.querySelectorAll('*')]
        .filter(node => node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth || node.scrollTop || node.scrollLeft)
        .map(node => [node, node.scrollLeft, node.scrollTop]);
      contentScrollPositions.set(mode, innerScroll);
      const targetScroll = contentScrollPositions.get(next) || innerScroll;
      newBody.append(content);
      section.element.hidden = next === 'full';
      full.element.hidden = next === 'panel';
      mode = next;
      content.dataset.presentation = mode;
      for (const [node, x, y] of targetScroll) {
        if (node === content || content.contains(node)) { node.scrollLeft = x; node.scrollTop = y; }
      }
      const [x, y] = scrollPositions.get(mode) || [0, 0];
      newBody.scrollLeft = x; newBody.scrollTop = y;
      if (focusedContent && (mode === 'full' || section.expanded)) {
        focusedContent.focus({preventScroll: true});
        if (selection) focusedContent.setSelectionRange(...selection);
      } else (mode === 'full' ? full.heading : (section.openButton.hidden ? section.toggle : section.openButton)).focus({preventScroll: true});
    },
    setPending(value) {
      section.openButton.disabled = value;
      full.backButton.disabled = value;
      if (full.employeeButton) full.employeeButton.disabled = value;
      section.openButton.setAttribute('aria-busy', String(value));
      full.backButton.setAttribute('aria-busy', String(value));
    },
    setError(message = '') {
      for (const node of errors) { node.textContent = message; node.hidden = !message; }
    },
    dispose() { disposed = true; scrollPositions.clear(); contentScrollPositions.clear(); section.dispose(); full.dispose(); }
  };
}
