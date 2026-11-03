"""Current library asset and interaction-store validation shared by both editions."""
from contextlib import closing
import uuid
from . import backup_files as disk
from .local_json import strict_json
from .local_library import scope_for


def verify(directory, library_id, names=('library-assets.sqlite3','interaction-settings.sqlite3')):
    from .device_schema import verify as schema_verify
    from .library_assets import SCHEMA as asset_schema, _hash, _encoded, KINDS
    from .library_settings import SCHEMA as settings_schema
    from .interaction_settings import validate
    scope=scope_for(library_id)
    for name in names:
        with closing(disk.readonly_database(directory/name)) as connection:
            if name=='library-assets.sqlite3':
                schema_verify(connection,asset_schema)
                if connection.execute('PRAGMA user_version').fetchone()[0]!=1 or connection.execute('SELECT library_id FROM library_meta').fetchall()!=[(scope['library_id'],)]:raise ValueError('资产与资料库身份不一致。')
                if connection.execute('SELECT 1 FROM revisions WHERE length(CAST(source_json AS BLOB))>33554432 LIMIT 1').fetchone():raise ValueError('本机资产源码过大。')
                for identifier,kind,head in connection.execute('SELECT * FROM assets'):
                    if str(uuid.UUID(identifier))!=identifier or kind not in KINDS:raise ValueError('本机资产身份无效。')
                    count,first,last=connection.execute('SELECT count(*),min(revision),max(revision) FROM revisions WHERE asset_id=?',(identifier,)).fetchone()
                    if type(head) is not int or head<1 or (count,first,last)!=(head,1,head):raise ValueError('本机资产修订不完整。')
                    for revision,name,raw,sha in connection.execute('SELECT revision,name,source_json,sha256 FROM revisions WHERE asset_id=? ORDER BY revision',(identifier,)):
                        source=strict_json(raw.encode())
                        if not isinstance(source,dict) or _hash(_encoded({'name':name,'source':source}))!=sha:raise ValueError('本机资产内容校验失败。')
            else:
                schema_verify(connection,settings_schema)
                rows=connection.execute('SELECT library_id,revision,value FROM settings').fetchall()
                if connection.execute('PRAGMA user_version').fetchone()[0]!=1 or len(rows)!=1 or rows[0][0]!=scope['library_id']:raise ValueError('设置与资料库身份不一致。')
                validate(strict_json(rows[0][2].encode()))
