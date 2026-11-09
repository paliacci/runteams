"""Public, bounded storage failures for local reads; never expose SQLite details."""
import sqlite3


def read_failure(error):
    code = getattr(error, 'sqlite_errorcode', None)
    full = (isinstance(code, int) and code & 0xff == sqlite3.SQLITE_FULL
            or code is None and str(error).lower() == 'database or disk is full')
    if full:
        return {'error': '本机存储空间不足，暂时无法读取资料。请释放磁盘空间后重试。',
                'code': 'local_storage_full'}, 507
    return {'error': '暂时无法读取本机资料。请检查磁盘空间和文件访问权限后重试。',
            'code': 'local_storage_read_failed'}, 503
