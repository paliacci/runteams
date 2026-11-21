const {createHash, randomUUID} = require('node:crypto');

const application = 'composio:gmail';
const triageCollection = 'mail_triage';
const legacyCollection = 'mail_followups';
let runtime;

function operation(run) {
  return async input => {
    try {
      const {createRuntime} = await import('./vendor/sdk/runtime/index.js');
      runtime ??= createRuntime(globalThis.runteamsRuntimeHost);
      const value = run(runtime, input);
      return {content: [{type: 'text', text: JSON.stringify(value)}], structuredContent: value};
    } catch (error) {
      const text = error.code === 'application_needs_connection' ? '请在员工设置中连接 Gmail。' : error.message;
      return {isError: true, content: [{type: 'text', text}]};
    }
  };
}

function mailbox(rt) {
  const {binding_key: key} = rt.application.status({application});
  return key ? 'gmail:' + key + ':' : null;
}

function queue(rt, prefix, collection) {
  const rows = [];
  let cursor = prefix;
  do {
    const page = rt.data.query({collection, limit: 30, cursor});
    for (const item of page.items) {
      if (!item.id.startsWith(prefix)) return rows;
      rows.push({key: item.id, revision: Number(item.revision), value: item.value});
    }
    cursor = page.next_cursor;
  } while (cursor);
  return rows;
}

const clip = (value, size) => typeof value === 'string' ? Array.from(value).slice(0, size).join('') : '';
const candidateKey = (prefix, messageId) => prefix + createHash('sha256').update(messageId).digest('hex').slice(0, 56);

function existing(rt, prefix) {
  const rows = new Map(queue(rt, prefix, triageCollection).map(row => [row.key, row]));
  for (const row of queue(rt, prefix, legacyCollection)) {
    if (!row.value.draft.trim()) continue;
    const suffix = row.key.slice(prefix.length);
    const legacyMessageId = /^[a-f0-9]{56}$/.test(suffix) ? '' : suffix;
    const key = legacyMessageId ? candidateKey(prefix, legacyMessageId) : row.key;
    if (!rows.has(key)) rows.set(key, {key, revision: 0, value: {...row.value, message_id: legacyMessageId,
      reason: '已有本机草稿', due_at: '', state: 'review'}});
  }
  return rows;
}

function list(rt) {
  const prefix = mailbox(rt);
  if (!prefix) return {connected: false, items: []};
  const items = [...existing(rt, prefix).values()].filter(row => row.value.state === 'followup' || row.value.state === 'review');
  return {connected: true, items: items.sort((a, b) => a.value.due_at.localeCompare(b.value.due_at)).slice(0, 100)};
}

function scan(rt) {
  const prefix = mailbox(rt);
  if (!prefix) throw Error('请在员工设置中连接 Gmail。');
  const response = rt.application.call({application, tool: 'GMAIL_FETCH_EMAILS', operation_key: randomUUID(),
    arguments: {user_id: 'me', query: 'is:unread in:inbox -category:promotions -category:social', max_results: 10}});
  const emails = response.result?.data?.messages;
  if (response.result?.isError || !Array.isArray(emails)) throw Error('Gmail 暂时无法读取，请检查应用连接。');
  if (mailbox(rt) !== prefix) throw Error('Gmail 账号已变化，请重新检查。');
  const seen = existing(rt, prefix);
  const candidates = new Map();
  for (const email of emails.slice(0, 10)) {
    const message_id = email?.messageId;
    if (typeof message_id !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(message_id)) continue;
    const key = candidateKey(prefix, message_id);
    if (seen.has(key)) continue;
    candidates.set(key, {mailbox: prefix, message_id, sender: clip(email.sender, 480), subject: clip(email.subject, 600),
      snippet: clip(email.preview?.body, 1600), received_at: clip(email.messageTimestamp, 72)});
  }
  return {scanned: Math.min(emails.length, 10), candidates: [...candidates.values()]};
}

function apply(rt, prefix, records, operationKey) {
  if (mailbox(rt) !== prefix) throw Error('Gmail 账号已变化。');
  const {result} = rt.data.mutate({collection: triageCollection, operation_key: operationKey, mutations: records});
  return {ok: result.ok, count: result.records?.length || 0, conflict: !result.ok};
}

function triage(rt, {items, operation_id}) {
  const prefix = mailbox(rt);
  if (!prefix || items.some(({candidate}) => candidate.mailbox !== prefix)) throw Error('候选邮件不属于当前 Gmail。');
  const seen = existing(rt, prefix), pending = new Map();
  for (const {candidate, decision, reason, due_at, draft} of items) {
    const {mailbox: ignored, ...mail} = candidate;
    const key = candidateKey(prefix, mail.message_id);
    if (seen.has(key) || pending.has(key)) continue;
    const needsAction = decision === 'followup';
    const due = due_at ? new Date(due_at) : null;
    if (needsAction && (!reason.trim() || !due || !Number.isFinite(+due))) throw Error('待跟进事项需要原因和有效截止时间。');
    // Ignore promotional/notification text after the decision. Keep a minimal deduplication record.
    const value = needsAction ? {...mail, reason, due_at: due.toISOString(), draft, state: draft.trim() ? 'review' : 'followup'}
      : {message_id: mail.message_id, sender: '', subject: '', snippet: '', received_at: '', reason: '', due_at: '', draft: '', state: 'ignored'};
    pending.set(key, {id: key, base_revision: null, value});
  }
  return pending.size ? apply(rt, prefix, [...pending.values()], operation_id) : {ok: true, count: 0};
}

function update(rt, {key, revision, action, draft, due_at, operation_id}) {
  const prefix = mailbox(rt);
  const row = prefix && existing(rt, prefix).get(key);
  if (!row || row.revision !== revision || !['followup','review'].includes(row.value.state)) return {ok: false, conflict: true};
  const value = {...row.value};
  if (action === 'save') {
    value.draft = draft;
    value.state = draft.trim() ? 'review' : 'followup';
  } else if (action === 'postpone') {
    const date = new Date(due_at);
    if (!Number.isFinite(+date) || +date <= Date.now()) throw Error('请填写未来的跟进时间。');
    value.due_at = date.toISOString();
    value.state = 'followup';
  } else {
    value.state = 'done';
  }
  return apply(rt, prefix, [{id: key, base_revision: revision ? String(revision) : null, value}], operation_id);
}

module.exports = {operation, list, scan, triage, update};
