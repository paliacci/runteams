const app = new RunTeamsMCP.App({name: '邮件运营助理', version: '1.0.0'}, {});
const byId = id => document.getElementById(id);
const rows = byId('rows');
const placeholder = byId('mail-loading');
const editor = byId('editor');
const draft = byId('draft');
const save = byId('save');
const refresh = byId('refresh');
const notice = byId('notice');
const draftStatus = byId('draft-status');
const reload = byId('reload');
let items = [], selected = null, pendingSave = null, saving = false, loading = false, connected = false;
let polling, ready = false, conflicted = false;

for (let row = 0; row < 4; row++) placeholder.append(byId('mail-placeholder').content.cloneNode(true));

function listBusy(busy) {
  rows.setAttribute('aria-busy', String(busy));
  placeholder.hidden = !busy || items.length > 0;
}

function id() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte, index) => {
    const value = index === 6 ? (byte & 15) | 64 : index === 8 ? (byte & 63) | 128 : byte;
    return (index === 4 || index === 6 || index === 8 || index === 10 ? '-' : '') + value.toString(16).padStart(2, '0');
  }).join('');
}

async function call(operation, values = {}) {
  const response = await app.callServerTool({name: 'mail_followup_' + operation, arguments: values});
  if (response.isError || !response.structuredContent) {
    throw Error(response.content?.[0]?.text || '工作台暂时未能读取，请重试。');
  }
  return response.structuredContent;
}

function dirty() { return selected && draft.value !== selected.value.draft; }
function controls() {
  refresh.disabled = !ready || loading || saving;
  save.disabled = saving || !dirty() || !connected || conflicted;
  draft.readOnly = saving;
}
function date(value) {
  const raw = /^\d+$/.test(value) ? Number(value) : value;
  const received = new Date(raw);
  return value && Number.isFinite(received.valueOf())
    ? new Intl.DateTimeFormat('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'}).format(received)
    : '';
}

function select(item) {
  if (saving || dirty()) {
    draftStatus.textContent = '请先保存当前草稿。';
    return;
  }
  selected = selected?.key === item.key ? null : item;
  pendingSave = null;
  conflicted = false;
  render();
}

function render() {
  const expanded = selected?.key;
  rows.replaceChildren();
  for (const item of items) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'mail-row';
    row.setAttribute('aria-expanded', String(item.key === expanded));
    row.setAttribute('aria-controls', 'editor');
    const heading = document.createElement('span');
    heading.className = 'row-heading';
    const sender = document.createElement('span');
    sender.className = 'row-name';
    sender.textContent = item.value.sender || '未知发件人';
    const time = document.createElement('span');
    time.className = 'row-time';
    time.textContent = date(item.value.received_at);
    const subject = document.createElement('span');
    subject.className = 'row-subject';
    subject.textContent = item.value.subject || '无主题';
    heading.append(sender, time);
    row.append(heading, subject);
    row.addEventListener('click', () => select(item));
    rows.append(row);
    if (item.key === expanded) rows.append(editor);
  }
  if (!selected) document.querySelector('.queue').append(editor);
  editor.hidden = !selected;
  if (selected) {
    byId('subject').textContent = selected.value.subject || '无主题';
    byId('sender').textContent = selected.value.sender;
    byId('snippet').textContent = RunTeamsMCP.decodeHtmlEntities(selected.value.snippet) || '这封邮件暂无预览。';
    draft.value = selected.value.draft;
    draftStatus.textContent = '';
    reload.hidden = true;
  }
  byId('count').textContent = items.length ? String(items.length) : '';
  controls();
}

async function load({quiet = false, reconcile = false} = {}) {
  if (loading || saving || (quiet && (dirty() || document.hidden || rows.contains(document.activeElement)))) return;
  loading = true;
  controls();
  if (!quiet) {
    notice.textContent = '';
    listBusy(true);
  }
  try {
    const result = await call('list');
    connected = result.connected;
    const key = selected?.key;
    if (!dirty() || reconcile) {
      const changed = JSON.stringify(items) !== JSON.stringify(result.items);
      items = result.items;
      selected = items.find(item => item.key === key) || null;
      if (reconcile) conflicted = false;
      if (changed || reconcile || !quiet) render();
    }
    notice.textContent = !connected ? '请在员工设置中连接 Gmail。'
      : items.length ? '' : '暂无待跟进邮件，可以在员工对话中交办检查新邮件。';
  } catch (error) {
    if (!quiet) notice.textContent = error.message;
  } finally {
    loading = false;
    if (!quiet) listBusy(false);
    controls();
  }
}

refresh.addEventListener('click', () => load());
draft.addEventListener('input', () => { draftStatus.textContent = ''; controls(); });
reload.addEventListener('click', () => {
  pendingSave = null;
  load({reconcile: true});
});
save.addEventListener('click', async () => {
  if (!dirty() || saving) return;
  const value = draft.value;
  if (pendingSave && pendingSave.draft !== value) {
    draftStatus.textContent = '上次保存结果待核对。请载入已保存草稿后再编辑。';
    reload.hidden = false;
    return;
  }
  const args = pendingSave || {key: selected.key, revision: selected.revision, draft: value, operation_id: id()};
  pendingSave = args;
  saving = true;
  controls();
  draftStatus.textContent = '正在保存…';
  try {
    const result = await call('save_draft', args);
    pendingSave = null;
    if (result.conflict) {
      conflicted = true;
      draftStatus.textContent = '草稿已在其他入口更新。请核对已保存版本。';
      reload.hidden = false;
    } else if (result.ok) {
      selected.revision = result.revision;
      selected.value.draft = value;
      draftStatus.textContent = '已保存到 RunTeams';
    }
  } catch (error) {
    draftStatus.textContent = error.message;
    reload.hidden = false;
  } finally { saving = false; controls(); }
});
const theme = context => {
  for (const node of [document.documentElement, document.body]) node.dataset.theme = context?.theme || 'light';
};
app.onhostcontextchanged = theme;
app.connect().then(() => {
  theme(app.getHostContext());
  ready = true;
  load();
  polling = setInterval(() => load({quiet: true}), 5000);
}).catch(() => {
  listBusy(false);
  notice.textContent = '工作台连接失败，请重新打开。';
});
window.addEventListener('pagehide', () => clearInterval(polling), {once: true});
