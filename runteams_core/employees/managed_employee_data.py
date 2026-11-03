"""Employee-owned typed data, provisioned at work admission rather than by forms.

Stable actor/employee/alias/schema identities survive chats and source revisions.
An old user-selected dataset may seed the employee's private copy; its original
rights and records are never expanded or rewritten.
"""
import copy
import json
import uuid
from runteams_core.storage import device_data
from runteams_core.authoring.creator_contracts import digest
from runteams_core.assets.collections.local_collections import Collections
from runteams_core.foundation.identity.work_identity import collection_namespace


def creation(reference, field):
    return str(uuid.uuid5(uuid.NAMESPACE_URL,'runteams:managed-data:'+digest(reference)+':'+field['key']+':'+digest(field['binding']['record_schema'])))


def expected_id(reference, field):
    return str(uuid.uuid5(uuid.NAMESPACE_URL,collection_namespace(device_data.identity())+':'+creation(reference,field)))


def verify(reference, field, selected):
    if selected['collection_id']!=expected_id(reference,field):
        raise PermissionError('工作数据不属于这名员工。')
    return Collections().select(field,selected)


def provision(config, field):
    store=Collections();operation=creation(config.reference,field)
    marker='employee-managed-data:'+digest(config.reference)+':'+field['key']+':'+digest(field['binding']['record_schema'])
    with device_data.connect() as c:
        selected=store.create(field,field['label'],operation)
        saved=c.execute('SELECT value FROM device_settings WHERE key=?',(marker,)).fetchone()
        if saved:
            state=json.loads(saved[0])
            if state['selection']!=selected:raise PermissionError('员工工作数据身份已变化。')
            verify(config.reference,field,selected)
            return selected
        row=config._load(c);previous=row.get('managed_seeds',{}).get(field['key']) or row.get('bindings',{}).get(field['key'])
        status='no_previous_binding';count=0
        if previous:
            if previous.get('model_sha256')!=digest(field['binding']['record_schema']):
                status='previous_schema_incompatible'
            else:
                original=copy.deepcopy(field);original['binding']['access']=previous['access']
                # select validates actual account, revocation and source model.
                # An unavailable source is not silently treated as an empty set.
                try:store.select(original,previous)
                except (PermissionError,ValueError):
                    store.check()
                    previous=None
                    status='previous_source_unavailable'
                cursor=''
                while previous:
                    page=store.query(original,previous,limit=100,cursor=cursor)
                    for item in page['items']:
                        if selected['access']!='read_write':raise ValueError('内部工作数据需要可维护权限。')
                        result=store.upsert(field,selected,key=item['key'],value=item['value'],expected_revision=0,
                            operation_id=str(uuid.uuid5(uuid.UUID(operation),'seed:'+item['key'])),
                            provenance={'source':'employee-managed-seed','employee_reference':config.reference,
                                'original_provenance':item['provenance'],'source_revision':item['revision']})
                        if not result['ok']:raise ValueError('原工作资料已变化，请重试核对。')
                        count+=1
                    cursor=page['next_cursor']
                    if not cursor:break
                if previous:status='copied_previous_binding'
        state={'selection':selected,'seed_status':status,'seed_count':count,'schema':1}
        c.execute('INSERT INTO device_settings(key,value) VALUES(?,?)',(marker,json.dumps(state,ensure_ascii=False)))
        store.check()
        return selected


def writer_busy(reference):
    """Read-only scheduling hint; never claims, renews or releases a lease.

    The schedule host supplies its already validated employee reference. The
    ordinary work admission and data tool remain the authority for writes.
    """
    import time
    key = 'employee-managed-lease:' + digest(reference)
    with device_data.connect(readonly=True) as c:
        row = c.execute('SELECT value FROM device_settings WHERE key=?', (key,)).fetchone()
        return bool(row and json.loads(row[0])['expires_at'] > time.time())


def lease(reference, owner, action):
    """One active writer per managed employee; a lease is never business authority."""
    import time
    key='employee-managed-lease:'+digest(reference)
    with device_data.connect() as c:
        row=c.execute('SELECT value FROM device_settings WHERE key=?',(key,)).fetchone()
        previous=json.loads(row[0]) if row else None
        stamp=time.time();held=previous and previous['expires_at']>stamp
        mine=held and previous['owner']==owner
        if action=='release':
            if mine:c.execute('DELETE FROM device_settings WHERE key=?',(key,))
            return {'ok':True,'released':bool(mine)}
        if held and not mine:return {'ok':False,'busy':True,'retry_after':int(previous['expires_at']-stamp)+1}
        if action=='verify' and not mine:raise PermissionError('请先取得这名员工的工作写入租约。')
        value={'owner':owner,'expires_at':stamp+900}
        c.execute('INSERT INTO device_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))
        return {'ok':True,'expires_at':value['expires_at']}


def release_turn(cancel_event):
    held = getattr(cancel_event, 'employee_data_lease', None)
    if held:
        try:
            from runteams_core.employees.managed_employee_data import lease
            lease(held[0], held[1], 'release')
        except Exception:
            # Cleanup failure must not mask the original outcome. The lease
            # still expires; never clear another request's writer ownership.
            import logging
            logging.getLogger(__name__).exception('Employee data lease cleanup failed')
