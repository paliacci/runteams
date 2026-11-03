/* Shared product chrome. Business state and navigation stay in index.html. */
(function (global) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));

  function navigationItem({label, icon, action, selected = false, className = '', disabled = false}) {
    return `<button class="rail-primary-action ${escape(className)} ${selected ? 'on' : ''}" type="button" aria-current="${selected ? 'page' : 'false'}" ${disabled?'disabled':`onclick="${escape(action)}"`}>${icon}<span>${escape(label)}</span></button>`;
  }

  function modeTabs(mode, icon, select = 'setRailNavTab') {
    return `<div class="rail-mode-switch" role="tablist" aria-label="侧栏内容" onkeydown="RunTeamsShell.moveMode(event)">${[['team','工作区','flow'], ['bots','员工','users']].map(([key,label,glyph]) => `<button type="button" role="tab" data-rail-tab="${key}" aria-selected="${mode === key}" tabindex="${mode === key ? 0 : -1}" class="${mode === key ? 'on' : ''}" onclick="${select}('${key}')">${icon(glyph)}<span>${label}</span></button>`).join('')}</div>`;
  }

  function moveMode(event) {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const buttons = [...event.currentTarget.querySelectorAll('[role="tab"]')];
    const index = buttons.indexOf(event.target);
    if (index < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 :
      (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    const key = buttons[next].dataset.railTab;
    buttons[next].click();
    requestAnimationFrame(() => document.querySelector(`.rail-mode-switch [data-rail-tab="${key}"]`)?.focus());
  }

  // Only tab-local display counters are retained. Routes and business records
  // continue through the existing router and its normal authorization checks.
  const historyKey = 'runteamsNavigation';
  const historyStorageKey = 'runteams_navigation_history_v1';
  let navigation = null;
  let historyMoving = false;

  function navigationState() {
    if (navigation) return navigation;
    if (!global.history || !global.location) return {index:0, end:0};
    const saved = global.history.state?.[historyKey];
    const valid = saved && typeof saved.id === 'string' && Number.isSafeInteger(saved.index) && saved.index >= 0;
    navigation = valid ? {id:saved.id,index:saved.index,end:saved.end} : {id:global.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,index:0,end:0};
    try {
      const range = JSON.parse(global.sessionStorage.getItem(historyStorageKey) || 'null');
      if (range?.id === navigation.id && Number.isSafeInteger(range.end) && range.end >= navigation.index) navigation.end = range.end;
    } catch (_) {}
    if (!Number.isSafeInteger(navigation.end) || navigation.end < navigation.index) navigation.end = navigation.index;
    saveNavigationState();
    return navigation;
  }

  function saveNavigationState() {
    try {
      global.history.replaceState({...global.history.state,[historyKey]:{...navigation}}, '', global.location.href);
      global.sessionStorage.setItem(historyStorageKey, JSON.stringify({id:navigation.id,end:navigation.end}));
    } catch (_) {}
  }

  function syncHistoryControls() {
    const state = navigationState();
    document.querySelectorAll?.('[data-history-direction]').forEach(button => {
      button.disabled = historyMoving || button.dataset.historyPending === 'true' || (button.dataset.historyDirection === 'back' ? state.index <= 0 : state.index >= state.end);
    });
  }

  function recordNavigation(replace) {
    const state = navigationState();
    if (!replace) { state.index++; state.end = state.index; }
    historyMoving = false;
    saveNavigationState();
    syncHistoryControls();
  }

  function goHistory(direction) {
    const state = navigationState();
    if (historyMoving || ![-1,1].includes(direction) || (direction < 0 ? state.index <= 0 : state.index >= state.end)) return;
    historyMoving = true;
    syncHistoryControls();
    global.history.go(direction);
  }

  function historyActions(icon, pending = false) {
    // Keep the rail's render signature stable as history availability changes.
    // Updating button properties must not remount a scrolled employee list.
    return [['back','后退',-1,'rail-back'],['forward','前进',1,'rail-forward']].map(([key,label,direction,glyph]) => `<button class="rail-window-action rail-history-${key}" type="button" title="${label}" aria-label="${label}" data-history-direction="${key}" data-history-pending="${pending}" disabled onclick="RunTeamsShell.goHistory(${direction})">${icon(glyph)}</button>`).join('');
  }

  function windowActions(content, pending = false) {
    return `<div class="rail-window-actions shell-navigation${pending ? ' boot-window-actions' : ''}">${content}</div>`;
  }

  function settingsToolbar(icon) {
    return windowActions(`<button class="rail-window-action rail-history-back" type="button" title="返回" aria-label="返回" onclick="accountSettingsClose()">${icon('rail-back')}</button>`);
  }

  function topActions(icon, extra = '', options = {}) {
    const pending = options.pending === true;
    return windowActions(`${historyActions(icon,pending)}<button class="rail-window-action rail-top-search" type="button" title="搜索（⌘K）" aria-label="搜索对话、流水线和文档" aria-keyshortcuts="Meta+K" ${pending ? 'disabled' : ''} onclick="openRailSearch()">${icon('search-rail')}</button>${extra}<button class="rail-window-action rail-collapse" type="button" title="折叠侧边栏" aria-label="折叠侧边栏" ${pending ? 'disabled' : ''} onclick="collapseRail()">${icon('rail-panel-close')}</button>`,pending);
  }

  function collapsedActions(icon) {
    return `<div class="rail-collapsed-tools shell-navigation">${historyActions(icon)}<button class="rail-window-action rail-reopen" type="button" title="展开侧边栏" aria-label="展开侧边栏" onclick="expandRail()">${icon('rail-panel-open')}</button></div>`;
  }

  function trashEntry({surface, icon}) {
    return `<nav class="rail-trash-navigation" aria-label="垃圾箱">${navigationItem({label:'垃圾箱',icon:icon('trash'),action:'openTrash()',selected:surface === 'trash',className:'rail-trash'})}</nav>`;
  }

  function footer({account = ''}) {
    return `<div class="rail-bottom"><div class="rail-account-card">${account}</div></div>`;
  }







  let tabsObserver, tabsScroller, tabsScrollState;
  function scrollWindowTabs(event) {
    const scroller = event.currentTarget;
    if (event.ctrlKey || event.shiftKey || event.deltaX || !event.deltaY || scroller.scrollWidth <= scroller.clientWidth) return;
    const before = scroller.scrollLeft;
    scroller.scrollLeft += event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? scroller.clientWidth : 1);
    if (scroller.scrollLeft !== before) event.preventDefault();
  }

  function syncWindowTabs() {
    const scroller = global.document?.querySelector('#rgWorkspaceTabs .workspace-tabs-scroll');
    const prior = tabsScrollState;
    tabsScrollState = null;
    tabsScroller = scroller;
    tabsObserver?.disconnect();
    if (!scroller) return;
    const activeKey = (scroller.querySelector('.workspace-tab.on')?.dataset?.workspaceDisplayKey||scroller.querySelector('.workspace-tab.on')?.dataset?.workspaceKey);
    // Selecting a window already in the header must retain the user's scroll.
    const preserveScroll = prior && (prior.activeKey === activeKey || prior.keys.includes(activeKey));
    if (preserveScroll) scroller.scrollLeft = prior.left;
    const labels = [...scroller.querySelectorAll('.workspace-tab-label')];
    const syncLabels = () => labels.forEach(label => {
      label.classList.toggle('is-overflowing', label.scrollWidth > label.clientWidth);
    });
    const revealActive = () => {
      const tab = scroller.querySelector('.workspace-tab.on');
      if (!tab) return;
      const item = tab.getBoundingClientRect(), viewport = scroller.getBoundingClientRect();
      if (item.left < viewport.left) scroller.scrollLeft += item.left - viewport.left - 10;
      else if (item.right > viewport.right) scroller.scrollLeft += item.right - viewport.right + 10;
    };
    syncLabels();
    if (!preserveScroll) revealActive();
    let viewportWidth = scroller.clientWidth;
    global.document.fonts?.ready.then(() => {
      if (tabsScroller === scroller) syncLabels();
    });
    if (global.ResizeObserver) {
      tabsObserver = new ResizeObserver(entries => {
        syncLabels();
        if (entries.some(entry => entry.target === scroller) && scroller.clientWidth !== viewportWidth) {
          viewportWidth = scroller.clientWidth;
          if (!preserveScroll) revealActive();
        }
      });
      tabsObserver.observe(scroller);
      labels.forEach(label => tabsObserver.observe(label));
    }
  }

  function windowTabs(rows, activeKey, icon, renderIcon = row => icon(row.icon), options = {}) {
    const pending = options.pending === true;
    const priorScroller = global.document?.querySelector?.('#rgWorkspaceTabs .workspace-tabs-scroll');
    // Capture before the host replaces the header. Detached scroll nodes lose their offset.
    if (priorScroller && (priorScroller === tabsScroller || !tabsScrollState)) {
      tabsScrollState = {
        left: priorScroller.scrollLeft,
        activeKey: (priorScroller.querySelector('.workspace-tab.on')?.dataset?.workspaceDisplayKey||priorScroller.querySelector('.workspace-tab.on')?.dataset?.workspaceKey),
        keys: [...priorScroller.querySelectorAll('.workspace-tab')].map(tab => tab.dataset.workspaceDisplayKey||tab.dataset.workspaceKey)
      };
    }
    if (global.requestAnimationFrame) global.requestAnimationFrame(() => {
      if (global.document?.querySelector('#rgWorkspaceTabs .workspace-tabs-scroll') !== tabsScroller) syncWindowTabs();
    });
    return `<div class="workspace-tabs" role="tablist" aria-label="最近工作窗口"><div class="workspace-tabs-scroll" onwheel="RunTeamsShell.scrollWindowTabs(event)"><div class="workspace-tabs-list">${rows.map(row => {
      const active = row.key === activeKey, key = escape(row.key), displayKey = escape(row.displayKey||row.key), title = escape(row.title);
      const rowEvents = pending ? '' : 'onpointerdown="workspaceTabPointerDown(event,this.dataset.workspaceKey)" oncontextmenu="workspaceTabContextMenu(event,this.dataset.workspaceKey)"';
      // Padding belongs to the visible tab. Replay its real button so save
      // protection, keyboard activation and drag suppression share one path.
      const rowClick = pending && options.navigationReady !== true ? '' : `onclick="if(!event.target.closest('button'))this.querySelector('.workspace-tab-main')?.click()"`;
      const mainAction = pending && options.navigationReady !== true ? 'disabled' : 'onclick="if(workspaceTabClickSuppressed(event))return;activateWorkspaceWindow(this.dataset.workspaceKey)"';
      const closeAction = pending ? 'disabled' : 'onclick="event.stopPropagation();closeWorkspaceWindow(this.parentElement.dataset.workspaceKey)"';
      return `<div class="workspace-tab ${active ? 'on' : ''}" data-workspace-key="${key}" data-workspace-display-key="${displayKey}" ${rowEvents} ${rowClick}>${active ? '<span class="workspace-tab-bridge" aria-hidden="true"></span>' : ''}<button type="button" role="tab" aria-selected="${active}" class="workspace-tab-main" data-workspace-key="${key}" title="${title}" ${mainAction}><span class="workspace-tab-icon" aria-hidden="true">${renderIcon(row)}</span><span class="workspace-tab-label">${title}</span></button>${rows.length > 1 ? `<button type="button" class="workspace-tab-close" aria-label="关闭 ${title}" ${closeAction}>${icon('x')}</button>` : ''}</div>`;
    }).join('')}<button type="button" class="workspace-new" aria-label="新建窗口" title="新建窗口" ${pending ? 'disabled' : 'onclick="openDefaultWorkspace()"'}>＋</button></div></div></div>`;
  }

  function patchWindowTabs(host, markup) {
    if (!host) return;
    const next = host.ownerDocument.createElement('div');
    next.innerHTML = markup;
    const list = host.querySelector('.workspace-tabs-list');
    const nextList = next.querySelector('.workspace-tabs-list');
    const current = list && [...list.querySelectorAll('.workspace-tab')];
    const incoming = nextList && [...nextList.querySelectorAll('.workspace-tab')];
    // Membership/order changes use the existing scroll restoration path. A
    // selection or metadata update keeps the scroller, buttons and images alive.
    if (!current || !incoming || current.length !== incoming.length ||
        current.some((tab, i) => (tab.dataset.workspaceDisplayKey||tab.dataset.workspaceKey) !== (incoming[i].dataset.workspaceDisplayKey||incoming[i].dataset.workspaceKey))) {
      host.innerHTML = markup;
      syncWindowTabs();
      return;
    }
    const attributes = (target, source) => {
      for (const attr of [...target.attributes]) if (!source.hasAttribute(attr.name)) target.removeAttribute(attr.name);
      for (const attr of source.attributes) if (target.getAttribute(attr.name) !== attr.value) target.setAttribute(attr.name, attr.value);
    };
    current.forEach((tab, i) => {
      const source = incoming[i];
      attributes(tab, source);
      for (const selector of ['.workspace-tab-main', '.workspace-tab-label', '.workspace-tab-icon', '.workspace-tab-close', '.workspace-tab-bridge']) {
        const target = tab.querySelector(selector), desired = source.querySelector(selector);
        if (!desired) { target?.remove(); continue; }
        if (!target) { tab.insertBefore(desired.cloneNode(true), selector === '.workspace-tab-bridge' ? tab.firstChild : null); continue; }
        attributes(target, desired);
        if (selector === '.workspace-tab-label') {
          if (target.textContent !== desired.textContent) target.textContent = desired.textContent;
        } else if (selector === '.workspace-tab-icon' || selector === '.workspace-tab-close') {
          if (target.innerHTML !== desired.innerHTML) target.innerHTML = desired.innerHTML;
        }
      }
    });
    attributes(list.querySelector('.workspace-new'), nextList.querySelector('.workspace-new'));
    syncWindowTabs();
  }

  function pageHeader(identity, actions, employee) {
    return `<header class="conversation-panel-header${employee ? ' employee-desk' : ''}">${identity}${actions}</header>`;
  }

  function frame({classes = '', columns, railEdge, drawerWidth = '0px', detailOpen = false, rail, tabs, head, content, drawer, controls}) {
    return `<div class="body product-shell ${escape(classes)}" id="rgBody" data-drawer-width="${escape(drawerWidth)}" data-detail-open="${detailOpen}" style="grid-template-columns:${escape(columns)};--rail-edge-x:${escape(railEdge)}">${rail}${tabs}${head}${content}${drawer}${controls}</div>`;
  }

  function accountEntry({icon,...options}){return global.RunTeamsHost.shell.entry?.({icon,...options})||`<div class="railfoot-wrap rail-settings-entry">${navigationItem({label:'设置',icon:icon('settings'),action:"openSettingsPage('general',{returnFocus:this})",className:'rail-settings-button'})}</div>`;}
  global.RunTeamsShell = Object.freeze({navigationItem, historyActions, settingsToolbar, modeTabs, moveMode, topActions, collapsedActions, syncHistoryControls, recordNavigation, goHistory, trashEntry, footer, accountEntry, windowTabs, patchWindowTabs, syncWindowTabs, scrollWindowTabs, pageHeader, frame});
  if (global.history && global.location) {
    navigationState();
    global.addEventListener('popstate', () => {
      const next = global.history.state?.[historyKey];
      if (next?.id === navigation.id && Number.isSafeInteger(next.index) && next.index >= 0) navigation.index = next.index;
      else { navigation = null; navigationState(); }
      historyMoving = false;
      saveNavigationState();
      syncHistoryControls();
    });
  }
})(window);
