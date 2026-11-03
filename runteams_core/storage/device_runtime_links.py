"""A device native handle belongs to exactly one current chat generation.

Changing the conversation branch or purpose retires the old handle in the same
transaction. Maintenance may remove only well-formed, owned handles already
made unreachable by a later generation with no active provider. It never
selects a replacement thread or changes a conversation's generation.
"""


def reset(connection, chat_id):
    if not connection.execute('SELECT 1 FROM device_chat_index WHERE chat_id=?',
                              (chat_id,)).fetchone():
        raise ValueError('本机对话不存在。')
    changed = connection.execute("UPDATE chats SET runtime_provider='',"
        'runtime_generation=runtime_generation+1 WHERE id=?', (chat_id,)).rowcount
    if changed != 1:
        raise ValueError('本机对话不存在。')
    connection.execute('DELETE FROM device_chat_runtime_links WHERE chat_id=?', (chat_id,))


def retire_superseded(connection):
    """Writer-transaction maintenance; leave every ambiguous mapping to validation.

    The stored generation is the authority. A lower generation cannot be used
    by get_chat; an empty current provider confirms there is no active handle
    to repair or reactivate. No chat IDs, asset kinds, or legacy formats enter
    this rule. Same-generation conflicts and future generations stay invalid.
    """
    rows = connection.execute('SELECT r.chat_id,r.generation,r.provider,r.thread_id,'
        'c.runtime_generation,c.runtime_provider FROM device_chat_runtime_links r '
        'JOIN chats c ON c.id=r.chat_id JOIN device_chat_index i ON i.chat_id=r.chat_id '
        "WHERE r.generation<c.runtime_generation AND c.runtime_provider=''").fetchall()
    removed = 0
    for chat_id, generation, provider, thread_id, current_generation, _ in rows:
        if (type(chat_id) is not int or type(generation) is not int or generation < 0
                or type(current_generation) is not int
                or not isinstance(provider, str) or not isinstance(thread_id, str)
                or bool(provider) != bool(thread_id)):
            continue
        removed += connection.execute('DELETE FROM device_chat_runtime_links '
            'WHERE chat_id=? AND generation=? AND provider=? AND thread_id=?',
            (chat_id, generation, provider, thread_id)).rowcount
    return removed
