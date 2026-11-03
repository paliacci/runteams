"""Full personal execution diagnostics on the executing device, never business state."""
import json
import uuid
from datetime import datetime, timezone

from . import device_data


def _now():
    return datetime.now(timezone.utc).isoformat()


def open_stream(domain, run_id):
    if not device_data.personal():
        raise PermissionError('本机过程记录只用于个人工作区。')
    scope = device_data.identity()
    with device_data.connect() as c:
        row = c.execute('SELECT ref FROM device_activity_streams WHERE scope=? AND domain=? AND run_id=?',
            (scope['cache_scope'], domain, int(run_id))).fetchone()
        ref = row[0] if row else str(uuid.uuid4())
        if not row:
            c.execute('INSERT INTO device_activity_streams(ref,scope,domain,run_id,created_at) VALUES(?,?,?,?,?)',
                (ref, scope['cache_scope'], domain, int(run_id), _now()))
    return {'ref': ref, 'scope': scope, 'domain': domain, 'run_id': int(run_id)}


def append(stream, event):
    device_data.check(stream['scope'])
    with device_data.connect() as c:
        row = c.execute('SELECT 1 FROM device_activity_streams WHERE ref=? AND scope=? AND domain=? AND run_id=?',
            (stream['ref'], stream['scope']['cache_scope'], stream['domain'], stream['run_id'])).fetchone()
        if not row:
            raise ValueError('本机过程记录不存在。')
        return c.execute('INSERT INTO device_activity_events(stream_ref,ts,content_json) VALUES(?,?,?)',
            (stream['ref'], _now(), json.dumps(event, ensure_ascii=False, allow_nan=False))).lastrowid


def events(ref, domain, run_id):
    if not device_data.personal():
        return None
    scope = device_data.identity()
    with device_data.connect(readonly=True) as c:
        row = c.execute('SELECT 1 FROM device_activity_streams WHERE ref=? AND scope=? AND domain=? AND run_id=?',
            (str(ref), scope['cache_scope'], domain, int(run_id))).fetchone()
        if not row:
            return None
        return [{'id': 'device-'+str(row['id']), 'ts': row['ts'], 'kind': 'agent_event',
                 'content': json.loads(row['content_json'])}
            for row in c.execute('SELECT id,ts,content_json FROM device_activity_events WHERE stream_ref=? ORDER BY id', (ref,))]
