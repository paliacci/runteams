from .work_identity import principal,collection_namespace
"""Personal typed collections, selected by the host and scoped by admitted work.

Collection IDs are not model authority. Employee calls use a declared field of
the platform-frozen configuration; source text cannot choose another dataset.
"""
import copy
import json
import re
import uuid
from datetime import datetime, timezone

from . import device_data
from .creator_contracts import canonical, digest, strict_json
from .creator_validation import validate_data


def now():
    return datetime.now(timezone.utc).isoformat()


def operation(value):
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('operation_id 必须是小写带连字符的 UUID；请为新操作生成 UUID，核对或重试原操作时沿用原编号。')
    return value


def declaration(binding):
    from .collection_schema import validate_binding as validate_collection_binding
    return validate_collection_binding(binding)


class Collections:
    def __init__(self):
        if not device_data.personal():
            raise PermissionError('请在个人工作区使用本机数据集合。')
        self.scope = device_data.identity()

    def check(self):
        device_data.check(self.scope)
        if not device_data.personal():
            raise PermissionError('本机数据集合的工作区已改变。')

    def _row(self, connection, identifier):
        if not isinstance(identifier, str) or str(uuid.UUID(identifier)) != identifier:
            raise ValueError('数据集合引用无效。')
        row = connection.execute('SELECT * FROM device_collections WHERE id=?', (identifier,)).fetchone()
        if row is None or row['revoked']:
            raise PermissionError('数据集合不存在或已停止授权。')
        if digest(strict_json(row['schema_json'].encode())) != row['schema_sha256']:
            raise ValueError('数据集合结构未能核对。')
        return row

    def select(self, field, selection):
        self.check()
        if not isinstance(selection, dict) or set(selection) != {'collection_id', 'model_sha256', 'access', 'name'}:
            raise ValueError('请通过配置入口选择数据集合。')
        binding = field['binding']
        with device_data.connect(readonly=True) as c:
            row = self._row(c, selection['collection_id'])
            if (row['schema_sha256'] != digest(binding['record_schema'])
                    or selection['model_sha256'] != row['schema_sha256']
                    or selection['access'] != binding['access']):
                raise ValueError('集合结构或读写要求已变化，请重新选择。')
            result = {'collection_id': row['id'], 'name': row['name'],
                      'model_sha256': row['schema_sha256'], 'access': binding['access']}
        self.check()
        return result

    def options(self, field):
        self.check()
        model = digest(field['binding']['record_schema'])
        with device_data.connect(readonly=True) as c:
            rows = c.execute('SELECT id,name,schema_sha256 FROM device_collections WHERE revoked=0 AND schema_sha256=? ORDER BY name,id LIMIT 200', (model,)).fetchall()
        self.check()
        return [{'collection_id': r['id'], 'name': r['name'], 'model_sha256': r['schema_sha256'],
                 'access': field['binding']['access']} for r in rows]

    def input_options(self):
        """Explicit read inputs, independent of an employee CRUD declaration."""
        self.check()
        with device_data.connect(readonly=True) as c:
            rows=c.execute('SELECT id,name,schema_sha256 FROM device_collections WHERE revoked=0 ORDER BY name,id LIMIT 200').fetchall()
            result=[]
            for row in rows:
                self._row(c,row['id'])
                result.append({'collection_id':row['id'],'name':row['name'],'model_sha256':row['schema_sha256']})
        self.check()
        return result

    def select_input(self, selection):
        self.check()
        if (not isinstance(selection,dict) or set(selection)!={'collection_id','model_sha256','name'}):
            raise ValueError('请通过原资料选择入口选择集合。')
        with device_data.connect(readonly=True) as c:
            row=self._row(c,selection['collection_id'])
            if row['schema_sha256']!=selection['model_sha256']:raise ValueError('原集合字段结构已变化。')
            result={'collection_id':row['id'],'name':row['name'],'model_sha256':row['schema_sha256']}
        self.check()
        return result

    def freeze_input(self, selection):
        self.select_input(selection)
        with device_data.connect(readonly=True) as c:
            row=self._row(c,selection['collection_id'])
            if row['schema_sha256']!=selection['model_sha256']:raise ValueError('原集合字段结构已变化。')
            rows=c.execute('SELECT * FROM device_collection_records WHERE collection_id=? ORDER BY record_key',(row['id'],)).fetchall()
            selected={'collection_id':row['id'],'name':row['name'],'model_sha256':row['schema_sha256']}
            versions=[{'key':r['record_key'],'revision':r['revision']} for r in rows]
            raw=self._input_bytes(c,selected,versions)
        self.check()
        return selected,versions,raw

    def _input_bytes(self, connection, selection, versions):
        row=self._row(connection,selection['collection_id'])
        if row['schema_sha256']!=selection['model_sha256']:raise ValueError('原集合字段结构已变化。')
        records=[]
        for version in versions:
            record=connection.execute('SELECT * FROM device_collection_versions WHERE collection_id=? AND record_key=? AND revision=?',
                (row['id'],version['key'],version['revision'])).fetchone()
            if record is None:raise ValueError('原集合记录版本不可用。')
            records.append(self._record(record))
        model=strict_json(row['schema_json'].encode())
        from .creator_validation import validate_values
        validate_values(model,[r['value'] for r in records])
        return canonical({'schema':'runteams.collection-export/1','collection_id':row['id'],'name':selection['name'],
            'record_schema':model,'records':records})

    def export_input(self, selection, versions):
        """Original immutable versions; current rows never substitute newer data."""
        self.check()
        with device_data.connect(readonly=True) as c:raw=self._input_bytes(c,selection,versions)
        self.check()
        return raw

    def create(self, field, name, operation_id):
        self.check(); operation(operation_id)
        model = declaration(field['binding'])
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('请填写80字以内的数据集合名称。')
        request = digest({'name': name.strip(), 'model': model})
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, collection_namespace(self.scope) + ':' + operation_id))
        with device_data.connect() as c:
            old = c.execute('SELECT * FROM device_collections WHERE create_operation=?', (operation_id,)).fetchone()
            if old is not None and old['create_sha256'] != request:
                raise ValueError('同一创建请求不能更换名称或字段结构。')
            if old is None:
                c.execute('INSERT INTO device_collections(id,name,schema_json,schema_sha256,create_operation,create_sha256,created_at) VALUES(?,?,?,?,?,?,?)',
                          (identifier, name.strip(), canonical(model).decode(), digest(model), operation_id, request, now()))
            else:
                identifier = old['id']
            self.check()
        return self.select(field, {'collection_id': identifier, 'name': name.strip(),
                                  'model_sha256': digest(model), 'access': field['binding']['access']})

    def query(self, field, selected, *, limit=50, cursor=''):
        self.select(field, selected)
        if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(cursor, str) or len(cursor) > 240:
            raise ValueError('读取范围无效。')
        with device_data.connect(readonly=True) as c:
            self._row(c, selected['collection_id'])
            rows = c.execute('SELECT * FROM device_collection_records WHERE collection_id=? AND record_key>? ORDER BY record_key LIMIT ?',
                             (selected['collection_id'], cursor, limit + 1)).fetchall()
        self.check()
        items = []; size = 0
        for row in rows[:limit]:
            item = self._record(row); count = len(canonical(item))
            if items and size + count > 256 * 1024: break
            items.append(item); size += count
        return {'items': items, 'next_cursor': items[-1]['key'] if len(rows) > len(items) else None}

    @staticmethod
    def _record(row):
        return {'key': row['record_key'], 'revision': row['revision'],
                'value': strict_json(row['value_json'].encode()), 'updated_at': row['updated_at'],
                'provenance': strict_json(row['provenance_json'].encode())}

    def read(self, field, selected, key):
        self.select(field, selected)
        if not isinstance(key, str) or len(key) > 240:
            raise ValueError('记录引用无效。')
        with device_data.connect(readonly=True) as c:
            self._row(c, selected['collection_id'])
            row = c.execute('SELECT * FROM device_collection_records WHERE collection_id=? AND record_key=?', (selected['collection_id'], key)).fetchone()
        self.check()
        return {'exists': row is not None, 'record': self._record(row) if row else None}

    def upsert(self, field, selected, *, key, value, expected_revision, operation_id, provenance, _validated=False):
        self.select(field, selected); operation(operation_id)
        if selected['access'] != 'read_write':
            raise PermissionError('这项工作只能读取此集合。')
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._/-]{0,239}', key)
                or type(expected_revision) is not int or expected_revision < 0
                or not isinstance(value, dict) or len(canonical(value)) > 65536):
            raise ValueError('记录格式或版本无效。')
        if not _validated:validate_data(field['binding']['record_schema'], value)
        request = digest({'key': key, 'value': value, 'expected_revision': expected_revision,
                          'provenance': provenance})
        identifier = selected['collection_id']
        with device_data.connect() as c:
            self._row(c, identifier)
            old = c.execute('SELECT * FROM device_collection_receipts WHERE collection_id=? AND operation_id=?', (identifier, operation_id)).fetchone()
            if old is not None:
                if old['request_sha256'] != request:
                    raise ValueError('同一操作编号不能保存另一份记录。')
                self.check()
                return strict_json(old['result_json'].encode())
            row = c.execute('SELECT * FROM device_collection_records WHERE collection_id=? AND record_key=?', (identifier, key)).fetchone()
            revision = row['revision'] if row else 0
            if revision != expected_revision:
                return {'ok': False, 'conflict': True, 'current': self._record(row) if row else None}
            # An unchanged repeat is not another revision or another candidate.
            changed = row is None or strict_json(row['value_json'].encode()) != value
            stamp = now()
            if changed:
                revision += 1
                c.execute('INSERT INTO device_collection_records VALUES(?,?,?,?,?,?) ON CONFLICT(collection_id,record_key) DO UPDATE SET revision=excluded.revision,value_json=excluded.value_json,provenance_json=excluded.provenance_json,updated_at=excluded.updated_at',
                          (identifier, key, revision, canonical(value).decode(), canonical(provenance).decode(), stamp))
                c.execute('INSERT INTO device_collection_versions VALUES(?,?,?,?,?,?)',
                          (identifier, key, revision, canonical(value).decode(), canonical(provenance).decode(), stamp))
            result = {'ok': True, 'key': key, 'revision': revision, 'changed': changed}
            c.execute('INSERT INTO device_collection_receipts VALUES(?,?,?,?,?)',
                      (identifier, operation_id, request, canonical(result).decode(), stamp))
            self.check()
        return result

    def receipt(self, field, selected, operation_id):
        self.select(field, selected); operation(operation_id)
        with device_data.connect(readonly=True) as c:
            self._row(c, selected['collection_id'])
            row = c.execute('SELECT result_json FROM device_collection_receipts WHERE collection_id=? AND operation_id=?',
                            (selected['collection_id'], operation_id)).fetchone()
        self.check()
        return {'state': 'confirmed', 'result': strict_json(row[0].encode())} if row else {'state': 'not_found'}

    def import_records(self, field, selected, records, operation_id):
        """Explicit account-owner import. It does not expand employee access."""
        self.select(field, selected); operation(operation_id)
        if (not isinstance(records, list) or not 1 <= len(records) <= 100
                or any(not isinstance(r, dict) or set(r) != {'key', 'value'} for r in records)
                or any(not isinstance(r['key'], str) for r in records)
                or len({r['key'] for r in records}) != len(records)):
            raise ValueError('导入记录必须有唯一名称，且每批不超过100条。')
        request = digest({'kind': 'owner-import', 'records': records})
        owner_field = copy.deepcopy(field); owner_field['binding']['access'] = 'read_write'
        owner_selection = {**selected, 'access': 'read_write'}
        with device_data.connect() as c:
            self._row(c, selected['collection_id'])
            old = c.execute('SELECT * FROM device_collection_receipts WHERE collection_id=? AND operation_id=?', (selected['collection_id'], operation_id)).fetchone()
            if old:
                if old['request_sha256'] != request: raise ValueError('原导入请求不能更换内容。')
                self.check(); return strict_json(old['result_json'].encode())
            results = []
            for record in records:
                current = self.read(field, selected, record['key'])['record']
                results.append(self.upsert(owner_field, owner_selection, key=record['key'], value=record['value'],
                    expected_revision=current['revision'] if current else 0,
                    operation_id=str(uuid.uuid5(uuid.UUID(operation_id), record['key'])),
                    provenance={'source': 'owner-import', 'operation_id': operation_id}))
            result = {'ok': True, 'count': len(results), 'records': results}
            c.execute('INSERT INTO device_collection_receipts VALUES(?,?,?,?,?)',
                      (selected['collection_id'], operation_id, request, canonical(result).decode(), now()))
            self.check()
        return result

    def upsert_many(self, field, selected, *, records, operation_id, provenance):
        self.select(field,selected);operation(operation_id)
        if selected['access']!='read_write':raise PermissionError('此数据集合只读。')
        if (not isinstance(records,list) or not 1<=len(records)<=100 or len(canonical(records))>96*1024
                or any(not isinstance(r,dict) or set(r)!={'key','value','expected_revision'} for r in records)
                or any(not isinstance(r['key'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._/-]{0,239}',r['key'])
                    or type(r['expected_revision']) is not int or r['expected_revision']<0 or not isinstance(r['value'],dict)
                    or len(canonical(r['value']))>65536 for r in records)
                or len({r['key'] for r in records})!=len(records)):
            raise ValueError('批量保存需要唯一记录、当前版本，每批最多100条和96 KB。')
        from .creator_validation import validate_values
        validate_values(field['binding']['record_schema'],[r['value'] for r in records])
        request=digest({'kind':'employee-batch','records':records,'provenance':provenance})
        with device_data.connect() as c:
            old=c.execute('SELECT * FROM device_collection_receipts WHERE collection_id=? AND operation_id=?',
                (selected['collection_id'],operation_id)).fetchone()
            if old:
                if old['request_sha256']!=request:raise ValueError('原批次不能更改内容。')
                return strict_json(old['result_json'].encode())
            conflicts=[]
            for r in records:
                current=self.read(field,selected,r['key'])['record']
                if (current['revision'] if current else 0)!=r['expected_revision']:
                    conflicts.append({'key':r['key'],'current':current})
            if conflicts:return {'ok':False,'conflicts':conflicts}
            results=[self.upsert(field,selected,**r,operation_id=str(uuid.uuid5(uuid.UUID(operation_id),r['key'])),
                provenance=provenance,_validated=True) for r in records]
            result={'ok':True,'count':len(results),'records':results}
            c.execute('INSERT INTO device_collection_receipts VALUES(?,?,?,?,?)',
                (selected['collection_id'],operation_id,request,canonical(result).decode(),now()))
            self.check()
            return result


INPUT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['operation'], 'properties': {
    'operation': {'enum': ['list', 'claim', 'release', 'query', 'read', 'upsert', 'upsert_many', 'receipt']},
    'records': {'type':'array','minItems':1,'maxItems':100,'items':{'type':'object'}},
    'resource': {'type': 'string'}, 'key': {'type': 'string'}, 'value': {'type': 'object'},
    'expected_revision': {'type': 'integer', 'minimum': 0}, 'operation_id': {'type': 'string', 'description': 'Canonical lowercase hyphenated UUID. Generate for a new operation; keep the same UUID for retries and receipt lookup.'},
    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'cursor': {'type': 'string'}}}


def employee_call(arguments, context):
    """Use only the configuration admitted for the actual stored user request."""
    from runteams_core import product_store
    from jsonschema import Draft202012Validator
    from .employee_context import current as employee_context
    employee_host = employee_context()
    from .configuration_schema import data_fields
    scope = device_data.identity()
    if context.get('actor_id') != principal(scope) or not device_data.personal():
        raise PermissionError('员工数据不属于当前账户。')
    if employee_host.resolve(context) is None:
        raise PermissionError('请在员工工作对话中使用数据集合。')
    if next(Draft202012Validator(INPUT_SCHEMA).iter_errors(arguments), None):
        raise ValueError('数据操作参数无效。')
    session = product_store.get_chat(context['chat_id'])
    if session.get('kind') != 'general':
        raise PermissionError('创作对话不能借用员工工作数据权限。')
    message = next((m for m in reversed(session.get('messages') or []) if m.get('role') == 'user'), None)
    snapshot = context.get('employee_configuration_snapshot')
    if not snapshot or not message or message.get('metadata', {}).get('employee_configuration') != snapshot:
        raise PermissionError('这项工作未取得可核对的数据配置。')
    config = employee_host.configuration(session['id'])
    snapshot = employee_host.validate_configuration_snapshot(config.definition, config.reference, config.definition_revision, snapshot)
    action = arguments['operation']; store = Collections()
    from .configuration_schema import managed_fields
    if managed_fields(config.definition):
        from .managed_employee_data import lease
        owner={'chat_id':session['id'],'message_id':message['id']}
        if action in ('claim','release'):
            if set(arguments)!={'operation'}:raise ValueError('工作租约不接受资源或身份参数。')
            return lease(config.reference,owner,action)
        if action in ('upsert','upsert_many'):
            lease(config.reference,owner,'verify')
    elif action in ('claim','release'):
        raise ValueError('当前员工未声明内部工作数据。')
    return configured_call(arguments, config.definition, snapshot,
        {'employee_reference': config.reference, 'chat_id': session['id'], 'message_id': message['id']})


def configured_call(arguments, definition, snapshot, provenance):
    """Shared alias-based CRUD. Only trusted adapters supply the checked snapshot."""
    from jsonschema import Draft202012Validator
    from .configuration_schema import data_fields
    scope = device_data.identity()
    if next(Draft202012Validator(INPUT_SCHEMA).iter_errors(arguments), None):
        raise ValueError('数据操作参数无效。')
    index = {f['key']: f for f in data_fields(definition)
             if f.get('binding', {}).get('provider') == 'local_collection' and f['key'] in snapshot['bindings']}
    action = arguments['operation']; store = Collections()
    if action in ('claim', 'release'):
        raise ValueError('工作租约必须由当前资产的受控调用处理。')
    if action == 'list':
        if set(arguments) != {'operation'}:
            raise ValueError('列出数据集合不接受其他参数。')
        return {'resources': [{'resource': key, 'label': f['label'], 'access': snapshot['bindings'][key]['access'],
                               'record_schema': copy.deepcopy(f['binding']['record_schema'])} for key, f in index.items()]}
    field = index.get(arguments.get('resource'))
    if field is None:
        raise PermissionError('这项工作未选择此数据集合。')
    selected = snapshot['bindings'][field['key']]
    common = {'operation', 'resource'}
    allowed = {'query': {'limit', 'cursor'}, 'read': {'key'},
               'upsert': {'key', 'value', 'expected_revision', 'operation_id'},
               'upsert_many':{'records','operation_id'}, 'receipt': {'operation_id'}}[action]
    required = {'query': set(), 'read': {'key'}, 'upsert': allowed,'upsert_many':allowed, 'receipt': allowed}[action]
    if set(arguments) - common - allowed or not required <= set(arguments):
        raise ValueError('数据操作参数不完整或包含多余字段。')
    kwargs = {k: v for k, v in arguments.items() if k not in common}
    if action in ('upsert','upsert_many'):
        kwargs['provenance'] = copy.deepcopy(provenance)
    result = getattr(store, action)(field, selected, **kwargs)
    device_data.check(scope)
    return result
