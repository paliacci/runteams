"""Compose shared attachment normalization with one durable local acceptance."""
from dataclasses import dataclass
from contextlib import nullcontext
from pathlib import Path
import hashlib
import json


@dataclass(frozen=True)
class ConversationFile:
    path: Path
    name: str
    mime: str


def request_digest(data):
    # Retrying an operation must preserve every input, not just the message.
    relevant = {key: data.get(key) or ([] if key != 'message' else '') for key in
                ('message', 'attachments', 'attachment_tokens', 'reuse_attachment_ids', 'capabilities')}
    relevant['rewind_message_id'] = data.get('rewind_message_id') or None
    return hashlib.sha256(json.dumps(relevant, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def prepare(runtime, chat, data, operation, digest, *, capabilities=None, rewind_source=None, employee_configuration=None):
    from runteams_core import chat_attachments as attachments
    uploads, tokens, reuse = (data.get(key) or [] for key in
                             ('attachments', 'attachment_tokens', 'reuse_attachment_ids'))
    if not all(isinstance(value, list) for value in (uploads, tokens, reuse)):
        raise ValueError('附件列表无效。')
    if any(not isinstance(item, dict) for item in uploads) or any(not isinstance(v, str) for v in tokens + reuse):
        raise ValueError('附件内容或引用无效。')
    source_messages = [rewind_source] if rewind_source else chat['messages']
    known = {item['id']: item for m in source_messages for item in m.get('attachments') or []}
    if len(set(reuse)) != len(reuse) or set(reuse) - known.keys():
        raise ValueError('只能引用当前对话已保存的附件。')
    reused = [known[key] for key in reuse]
    uploaded = []
    committed = False
    message_id = None
    superseded = {}
    if rewind_source:
        for message in chat['messages']:
            if message['id'] < rewind_source['id']:continue
            metadata = message.get('metadata') or {}
            superseded.update(metadata.get('superseded_local_turns') or {})
            if message['role']=='user' and metadata.get('local_turn_id'):
                superseded[metadata['local_turn_id']] = metadata.get('local_turn_request_sha256')
    def admit(picked):
        nonlocal committed, message_id
        from runteams_core import local_references
        items=local_references.with_input_bindings(reused+uploaded+picked+local_references.references(data.get('local_asset_ids') or []),data.get('local_asset_bindings'))
        if len(items) > attachments.MAX_FILES:
            raise ValueError('每次最多添加 10 个附件。')
        if sum(int(item.get('size') or 0) for item in items) > attachments.MAX_TOTAL_BYTES:
            raise ValueError('附件总大小不能超过 25 MB。')
        # Resolve all original/derived files before accepting a model turn.
        attachments.prompt_context(chat['id'], items)
        try:
            from . import device_data
            # Removing a branch and saving its replacement share the same
            # existing device transaction. A rejected write keeps the old chat.
            with device_data.connect() if rewind_source else nullcontext():
                if rewind_source:runtime.store.rewind_chat(chat['id'], rewind_source['id'])
                message_id = runtime.store.add_chat_message(chat['id'], 'user', data.get('message') or '',
                    attachments=items, capabilities=capabilities or [],
                    metadata={'local_turn_id': operation, 'local_turn_request_sha256': digest,
                        **({'employee_configuration':employee_configuration} if employee_configuration is not None else {}),
                        **({'superseded_local_turns': superseded} if rewind_source else {})})
        except Exception as error:
            try:
                saved = runtime.store.get_chat(chat['id'])
                confirmed = next((m for m in saved['messages'] if m.get('metadata', {}).get('local_turn_id') == operation), None)
            except Exception:
                raise attachments.AttachmentCommitUnknown('消息保存结果待确认，请重新打开原对话核对。') from error
            if confirmed is None:
                raise
            if confirmed['metadata'].get('local_turn_request_sha256') != digest:
                raise ValueError('原操作内容不能改变。') from None
            message_id = confirmed['id']
        committed = True
        return items
    try:
        uploaded = attachments.save(chat['id'], uploads)
        if tokens:
            # The finalizer commits the message before one-use tokens disappear.
            budget = attachments.MAX_TOTAL_BYTES - sum(int(item['size']) for item in uploaded + reused)
            items = attachments.consume_native_to(attachments._chat_dir(chat['id']), tokens,
                                                   max_total_bytes=budget, finalize=admit)
        else:
            items = admit([])
        return message_id, items
    except BaseException as error:
        # A lost post-commit result must not delete an accepted file tree.
        saved = runtime.store.get_chat(chat['id'])
        confirmed = any(m.get('metadata', {}).get('local_turn_id') == operation for m in saved['messages'])
        if not committed and not confirmed:
            attachments.discard(chat['id'], uploaded)
        if isinstance(error, ImportError):
            raise RuntimeError('附件解析组件尚未准备好，请安装所需依赖或重新构建本机版。') from error
        raise


def file_for(runtime, chat_id, attachment_id):
    from runteams_core import chat_attachments as attachments
    runtime.chat(chat_id)
    item = runtime.store.find_chat_attachment(chat_id, attachment_id)
    if not item or item.get('kind') in ('folder', 'local_asset'):
        raise KeyError('附件不存在。')
    return ConversationFile(Path(attachments.path_for(chat_id, item)), item['name'], item['mime_type'])
