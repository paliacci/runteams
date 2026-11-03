"""Keep personal native-thread references with their verified device transcript.

No native Runtime directories, credentials, tools or external effects are copied.
Only references already persisted with this conversation are backed up.
"""


def verify(connection):
    from .device_data import SCHEMA_VERSION,schema
    from .device_schema import verify as verify_schema
    if connection.execute('PRAGMA user_version').fetchone()[0]!=SCHEMA_VERSION:
        raise ValueError('备份本机数据版本不受支持。')
    verify_schema(connection,schema())
    rows = connection.execute('SELECT r.chat_id,r.generation,r.provider,r.thread_id,c.runtime_generation,c.runtime_provider,i.chat_id '
        'FROM device_chat_runtime_links r LEFT JOIN chats c ON c.id=r.chat_id '
        'LEFT JOIN device_chat_index i ON i.chat_id=r.chat_id').fetchall()
    for chat_id,generation,provider,thread_id,current_generation,current_provider,owned in rows:
        if (type(chat_id) is not int or type(generation) is not int or generation<0
                or owned is None or generation != current_generation or provider != current_provider
                or not isinstance(provider,str) or not isinstance(thread_id,str)
                or bool(provider) != bool(thread_id)):
            raise ValueError('备份中的 Agent 线程关联无效。')
