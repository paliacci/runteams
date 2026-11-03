"""Employee declarations and personal defaults, separate from asset/work authority.

Ordinary values and explicit resource selections use their original mechanisms.
Runtime conditions are observed by the existing native hosts. Resource/connection/
credential authority never comes from a text value or client ready flag.
"""
from contextlib import contextmanager
import copy
import json
import re
import uuid


from . import device_data, configuration_runtime, configuration_documents, configuration_collections, configuration_credentials, configuration_connections
from . import configuration_schema as _configuration_schema
from .creator_contracts import digest, strict_json

SCHEMA = 'runteams.employee-configuration/1'
STATE = 'runteams.employee-configuration-state/1'
SNAPSHOT = 'runteams.employee-configuration-snapshot/1'
EMPTY = {'schema': SCHEMA, 'groups': []}


class ConfigurationConflict(ValueError):
    """A stale write, never permission to overwrite or retry with a new ID."""


class ConfigurationInvalid(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('配置需要修改，请核对对应项目。')


def validate_values(definition, values, *, complete=True):
    if not isinstance(values, dict) or len(values) > 128:
        raise ConfigurationInvalid({'_form': '配置格式无效。'})
    index = {f['key']: f for f in _configuration_schema.fields(definition)}
    if set(values) - set(index):
        raise ConfigurationInvalid({'_form': '包含当前员工没有声明的配置。'})
    errors = {}
    for key, value in values.items():
        problem = _configuration_schema._value_error(index[key], value)
        if problem:
            errors[key] = problem
    if complete:
        for key, field in index.items():
            if field['type'] not in _configuration_schema.PRIVATE and field.get('required') and key not in values:
                errors[key] = '请填写此项。'
    if errors:
        raise ConfigurationInvalid(errors)
    return copy.deepcopy(values)


def local_binding(field, selection, *, reference=None, revision=None, connection_asset=None):
    """Reuse a real grant; neither a filesystem path nor ready=true is accepted."""
    if configuration_connections.supports(field):return configuration_connections.select(field,selection,reference,revision,connection_asset)
    if configuration_credentials.supports(field):return configuration_credentials.select(field,selection)
    if configuration_documents.supports(field):return configuration_documents.select(field,selection)
    if configuration_collections.supports(field):return configuration_collections.select(field,selection)
    if field.get('type') == 'resource' and field['binding']['provider'] == 'local_collection':
        from .local_collections import Collections
        return Collections().select(field, selection)
    import product_store
    from . import local_assets
    if (field['type'] != 'resource' or field['binding']['provider'] != 'local_asset'
            or not isinstance(selection, dict)
            or set(selection) not in ({'grant_id'}, {'grant_id', 'name', 'kind', 'identity'})
            or type(selection.get('grant_id')) is not int or selection['grant_id'] < 1):
        raise ValueError('请通过资料选择入口选择已授权的文件或文件夹。')
    grant = product_store.get_local_asset_grant(selection['grant_id'])
    ok, reason = local_assets.preflight(grant, field['label'])
    if not ok:
        raise ValueError(reason)
    from pathlib import Path
    kind = 'file' if Path(grant['path']).is_file() else 'folder'
    if kind != field['binding']['resource_kind']:
        raise ValueError('所选资料类型与此项要求不符。')
    identity = digest({key: grant.get(key) for key in
                       ('id', 'path', 'dev', 'ino', 'is_git', 'git_root_commit', 'excluded')})
    result = {'grant_id': grant['id'], 'name': grant['name'], 'kind': kind, 'identity': identity}
    if 'identity' in selection and any(selection[k] != result[k] for k in ('grant_id', 'kind', 'identity')):
        raise ValueError('所选资料或授权范围已变化，请重新选择。')
    return result


def for_package(package):
    """An existing work uses its exact source version, never the editing head."""
    from .source_employee_runtime import validate, package_asset
    package = validate(package)
    employee = package_asset(package)['employee']
    store = ConfigurationStore(package['reference'], employee.get('configuration', EMPTY), package['revision'],connection_asset=configuration_connections.package_asset_binding(package))
    store.employee = profile(employee)
    return store


def profile(employee):
    soul = str(employee.get('soul') or '')
    paragraphs = [p.strip() for p in soul.split('\n\n') if p.strip() and not p.lstrip().startswith(('#', '>'))]
    return {'name': employee['name'], 'avatar': employee['avatar'],
            'description': paragraphs[0][:500] if paragraphs else ''}


def for_chat(chat_id):
    import product_store
    from .employee_binding import resolve
    session = product_store.get_chat(chat_id, include_messages=False)
    binding = resolve(session)
    if binding['package']:
        return for_package(binding['package'])
    from .employee_context import current
    return current().acquired_configuration(chat_id,binding)




def for_work_settings(chat_id):
    """Independent saved work settings, not a reusable asset or position scope."""
    import product_store
    session=product_store.get_chat(chat_id,include_messages=False)
    context=(session or {}).get('context') or {}
    if (not session or session.get('kind')!='general' or session.get('subject_type')!='employee'
            or context.get('pipeline_work') or context.get('source_pipeline_workspace')):
        raise PermissionError('请在原员工工作或流水线岗位设置中配置。')
    return for_chat(chat_id)


def acquired_admission(session):
    """The original pinned acquired context owns its configuration snapshot."""
    context = (session or {}).get('context') or {}
    config = for_chat(session['id'])
    if not _configuration_schema.data_fields(config.definition):
        return None
    fixed = context.get('employee_configuration_snapshot')
    if fixed is not None:
        return _validate_snapshot(config.definition, config.reference, config.definition_revision, fixed,connection_asset=config.connection_asset)
    return config.snapshot()



def admission(session):
    """Freeze at message/work admission. Opening a chat does not freeze defaults."""
    context = (session or {}).get('context') or {}
    package = context.get('local_employee_package')
    if package is None:
        if not context.get('creator_work_binding'):
            return None
        return acquired_admission(session)
    from .source_employee_runtime import for_chat, package_asset
    employee = for_chat(session['id'])
    definition = package_asset(employee['local_package'])['employee'].get('configuration')
    if not definition or not _configuration_schema.data_fields(definition):
        return None
    fixed = context.get('employee_configuration_snapshot')
    if fixed is not None:
        return validate_snapshot(employee['local_package'], fixed)
    return for_package(employee['local_package']).snapshot()


def validate_snapshot(package, snapshot):
    from .source_employee_runtime import package_asset
    definition = package_asset(package)['employee'].get('configuration', EMPTY)
    return _validate_snapshot(definition, package['reference'], package['revision'], snapshot,connection_asset=configuration_connections.package_asset_binding(package))


def verify_snapshot_record(definition, reference, revision, snapshot, scope):
    """Validate portable facts; backup verification grants no current access."""
    if (not isinstance(snapshot, dict)
            or set(snapshot) != {'schema', 'reference', 'revision', 'definition_sha256', 'definition_revision', 'values', 'states', 'bindings'}
            or snapshot.get('schema') != SNAPSHOT
            or snapshot.get('reference') != reference
            or snapshot.get('definition_revision') != revision
            or snapshot.get('definition_sha256') != digest(definition)):
        raise PermissionError('工作配置与原员工版本不符。')
    validate_values(definition, snapshot.get('values'))
    bindings = snapshot.get('bindings', {})
    index = {f['key']: f for f in _configuration_schema.data_fields(definition)}
    if (not isinstance(bindings, dict) or set(bindings) - set(index)
            or not isinstance(snapshot.get('states'), dict) or set(snapshot['states']) != set(index)):
        raise ValueError('工作资料快照无效。')
    configuration_connections.checked_scope(reference,scope)
    if type(snapshot.get('revision')) is not int or snapshot['revision']<0:raise ValueError('工作配置版本无效。')
    if any(state not in {'configured','missing','unverified','unavailable','needs_review'} for state in snapshot['states'].values()):raise ValueError('工作配置状态无效。')
    for field in index.values():
        key=field['key'];selected=bindings.get(key);state=snapshot['states'][key]
        if field.get('required') and state!='configured':raise ConfigurationInvalid({key:'此项还需配置。'})
        if field['type'] not in _configuration_schema.PRIVATE:
            if selected is not None:raise ValueError('普通配置不能持有资料授权。')
            continue
        if (field.get('required') or state=='configured') and selected is None:raise ValueError('原配置缺少平台核对记录。')
        if selected is None:continue
        if state!='configured':raise ValueError('配置状态与原记录不符。')
        if configuration_connections.supports(field):configuration_connections.verify_record(field,selected,scope,reference,revision)
        elif configuration_credentials.supports(field):configuration_credentials.verify_record(field,selected,scope)
        elif field['type']=='runtime':configuration_runtime.verify_record(field,selected,scope)
        elif configuration_documents.supports(field):configuration_documents.verify_record(selected,scope)
        elif configuration_collections.supports(field):configuration_collections.verify_record(selected,scope)
        elif field['type']=='resource' and field['binding']['provider']=='local_collection':
            if (not isinstance(selected,dict) or set(selected)!={'collection_id','model_sha256','access','name'}
                    or not isinstance(selected.get('collection_id'),str) or str(uuid.UUID(selected['collection_id']))!=selected['collection_id']
                    or selected['model_sha256']!=digest(field['binding']['record_schema']) or selected['access']!=field['binding']['access']):raise ValueError('原集合记录无效。')
        elif field['type']=='resource' and field['binding']['provider']=='local_asset':
            if (not isinstance(selected,dict) or set(selected)!={'grant_id','name','kind','identity','fingerprint'}
                    or type(selected['grant_id']) is not int or selected['grant_id']<1 or selected['kind']!=field['binding']['resource_kind']
                    or not isinstance(selected['identity'],str) or not re.fullmatch('[a-f0-9]{64}',selected['identity'])
                    or not isinstance(selected['fingerprint'],dict) or selected['fingerprint'].get('mode') not in ('git','file','snapshot')):raise ValueError('原文件资料记录无效。')
        else:raise ValueError('此配置尚无可核对的接入记录。')
    return copy.deepcopy(snapshot)


def _validate_snapshot(definition, reference, revision, snapshot, *, connection_asset=None):
    verify_snapshot_record(definition,reference,revision,snapshot,device_data.identity())
    bindings=snapshot['bindings']
    for field in _configuration_schema.data_fields(definition):
        if field['type'] in _configuration_schema.PRIVATE:
            selected = bindings.get(field['key'])
            if (field['type']=='runtime' or configuration_documents.supports(field)) and snapshot['states'][field['key']]=='configured' and selected is None:
                raise ValueError('原运行条件缺少平台核对记录。')
            if field.get('required') and selected is None:
                raise ConfigurationInvalid({field['key']: '此项还需配置。'})
            if selected is not None:
                if field['type']=='runtime':
                    if snapshot['states'][field['key']]!='configured':raise ValueError('原运行条件状态与核对记录不符。')
                    configuration_runtime.verify(field, selected)
                elif configuration_documents.supports(field):
                    if snapshot['states'][field['key']]!='configured':raise ValueError('原文档状态与版本记录不符。')
                    configuration_documents.verify(field,selected)
                elif configuration_collections.supports(field):configuration_collections.verify(field,selected)
                elif configuration_credentials.supports(field):
                    try:configuration_credentials.select(field,selected)
                    except ValueError:raise ConfigurationInvalid({field['key']:'本机凭据已不可用，请重新核对。'}) from None
                else:local_binding(field, {k: v for k, v in selected.items() if k != 'fingerprint'},reference=reference,revision=revision,connection_asset=connection_asset)
                if field['key'] in {f['key'] for f in _configuration_schema.managed_fields(definition)}:
                    from .managed_employee_data import verify
                    verify(reference,field,selected)
    return copy.deepcopy(snapshot)


def materialize_snapshot(package, snapshot, workspace):
    """Mount authorized read copies; do not pass original writable paths to AI."""
    snapshot = validate_snapshot(package, snapshot)
    return _materialize(snapshot, workspace)


def materialize_for_chat(chat_id, snapshot, workspace):
    config = for_chat(chat_id)
    return _materialize(_validate_snapshot(config.definition, config.reference, config.definition_revision, snapshot,connection_asset=config.connection_asset), workspace)


def _materialize(snapshot, workspace):
    import product_store
    import tempfile
    from pathlib import Path
    from . import local_assets
    resources = {}
    directory = Path(workspace) / '.runteams' / 'configuration'
    for parent in (directory.parent, directory):
        if parent.is_symlink():
            raise ValueError('工作配置目录无效。')
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for key, selected in snapshot.get('bindings', {}).items():
        if selected.get('schema')==configuration_connections.SCHEMA:
            resources[key]={'provider':'sdk_connection','connection':selected['connection'],'origin':selected['origin'],'scopes':selected['scopes'],'authorization':'required_at_use'}
            continue
        if selected.get('schema')==configuration_credentials.SCHEMA:
            # Secrets are not materialized as model instructions/files/resources.
            continue
        if selected.get('schema')==configuration_runtime.SCHEMA:
            resources[key]={'provider':'runtime','runtime':selected['key'],'status':'ready'}
            continue
        if selected.get('schema')==configuration_documents.SNAPSHOT:
            resources[key]=configuration_documents.materialize(selected,directory)
            continue
        if selected.get('schema')==configuration_collections.SNAPSHOT:
            resources[key]=configuration_collections.materialize(selected,directory)
            continue
        if 'collection_id' in selected:
            resources[key] = {**copy.deepcopy(selected), 'provider': 'local_collection',
                              'tool': 'runteams_employee_data', 'resource': key}
            marker='employee-managed-data:'+digest(snapshot['reference'])+':'+key+':'+selected['model_sha256']
            with device_data.connect(readonly=True) as c:
                row=c.execute('SELECT value FROM device_settings WHERE key=?',(marker,)).fetchone()
            if row:
                state=strict_json(row[0].encode())
                resources[key]['maintenance']={name:state[name] for name in ('seed_status','seed_count')}
            continue
        grant = product_store.get_local_asset_grant(selected['grant_id'])
        ok, reason = local_assets.preflight(grant, key)
        if not ok or local_assets.fingerprint(grant) != selected.get('fingerprint'):
            raise ConfigurationInvalid({key: reason or '资料内容已变化，请重新核对这次工作。'})
        destination = Path(tempfile.mkdtemp(prefix='input-', dir=directory))
        record, before = local_assets.mount(grant, destination)
        if before != selected['fingerprint']:
            raise ConfigurationInvalid({key: '资料在准备过程中发生变化。'})
        resources[key] = {'name': selected['name'], 'path': str(destination), 'access': 'read-copy', 'content': record}
    return {'values': snapshot['values'], 'states': snapshot['states'], 'resources': resources}


class ConfigurationStore:
    """Trusted callers supply verified identity; this class grants no authority."""
    def __init__(self, reference, definition, definition_revision, *, connection_asset=None):
        self.scope = device_data.identity()
        if not device_data.personal():
            raise PermissionError('使用配置保存在当前使用者的本机工作区。')
        self.reference = copy.deepcopy(reference)
        self.connection_asset = copy.deepcopy(connection_asset)
        self.definition = _configuration_schema.validate_declaration(definition)
        self.definition_revision = definition_revision
        self.definition_sha256 = digest(self.definition)
        self.key = 'employee-configuration:' + digest(self.reference)
        self.receipt_prefix = 'employee-configuration-receipt:'

    def _check(self):
        device_data.check(self.scope)
        if not device_data.personal():
            raise PermissionError('请在原使用者的本机工作区配置。')

    def _load(self, connection):
        row = connection.execute('SELECT value FROM device_settings WHERE key=?', (self.key,)).fetchone()
        if row is None:
            return {'revision': 0, 'values': {}, 'types': {}, 'retained': {}, 'bindings': {}}
        value = strict_json(row[0].encode())
        if (not isinstance(value, dict)
                or set(value)-{'managed_seeds'} not in ({'schema', 'reference', 'revision', 'definition_sha256', 'values', 'types', 'retained'},
                                     {'schema', 'reference', 'revision', 'definition_sha256', 'values', 'types', 'retained', 'bindings'})
                or value.get('reference') != self.reference or value.get('schema') != STATE
                or type(value['revision']) is not int or value['revision'] < 1
                or any(not isinstance(value[k], dict) for k in ('values', 'types', 'retained'))):
            raise ValueError('已保存配置的身份无效，原值保持不变。')
        value.setdefault('bindings', {})
        if not isinstance(value['bindings'], dict):
            raise ValueError('资料配置无效，原值保持不变。')
        if not isinstance(value.get('managed_seeds',{}),dict):raise ValueError('内部资料迁移记录无效。')
        return value

    def _runtime_states(self):
        states={}
        for field in _configuration_schema.fields(self.definition):
            if configuration_runtime.supports(field):
                try:configuration_runtime.observe(field);states[field['key']]='configured'
                except (ValueError,PermissionError,OSError,RuntimeError):states[field['key']]='unavailable'
        return states

    def _project(self, row, runtime_states=None):
        if runtime_states is None:runtime_states=self._runtime_states()
        values, retained, review = {}, copy.deepcopy(row['retained']), []
        index = {f['key']: f for f in _configuration_schema.fields(self.definition)}
        for key, old in row['values'].items():
            field = index.get(key)
            if (field is None or row['types'].get(key) != field['type']
                    or _configuration_schema._value_error(field, old)):
                retained[key] = copy.deepcopy(old)
                if field is not None:
                    review.append(key)
            else:
                values[key] = copy.deepcopy(old)
        for field in index.values():
            if field['type'] not in _configuration_schema.PRIVATE and field['key'] not in values and 'default' in field:
                values[field['key']] = copy.deepcopy(field['default'])
        states = {}
        for key, field in index.items():
            if key in review:
                states[key] = 'needs_review'
            elif field['type'] in _configuration_schema.PRIVATE:
                # No read of an employee declaration can grant/confirm access.
                states[key] = 'unverified'
                if configuration_runtime.supports(field):
                    states[key]=runtime_states.get(key,'unavailable')
                if configuration_connections.supports(field) or configuration_credentials.supports(field) or field['type'] == 'resource' and (field['binding']['provider'] in ('local_asset', 'local_collection') or configuration_documents.supports(field) or configuration_collections.supports(field)):
                    selected = row.get('bindings', {}).get(key)
                    if selected is None:
                        states[key] = 'missing'
                    else:
                        try:
                            local_binding(field, selected,reference=self.reference,revision=self.definition_revision,connection_asset=self.connection_asset)
                            states[key] = 'configured'
                        except (ValueError, PermissionError):
                            states[key] = 'unavailable'
            else:
                current = values.get(key)
                missing = current is None or isinstance(current, str) and not current.strip() or isinstance(current, list) and not current
                states[key] = 'missing' if missing else 'configured'
        ready = not review and all(states[f['key']] == 'configured' for f in index.values() if f.get('required'))
        return values, retained, states, ready

    def _view(self, row, runtime_states=None):
        values, retained, states, ready = self._project(row, self._runtime_states() if runtime_states is None else runtime_states)
        return {'schema': STATE, 'reference': copy.deepcopy(self.reference),
                'revision': row['revision'], 'definition_revision': self.definition_revision,
                'definition_sha256': self.definition_sha256, 'definition': copy.deepcopy(self.definition),
                'values': values, 'states': states, 'ready': ready,
                'connection_fields':self.connection_fields(),
                'credential_fields':{field['key']:{'available':configuration_credentials.available(field)} for field in _configuration_schema.fields(self.definition) if configuration_credentials.supports(field)},
                'runtime_fields':[field['key'] for field in _configuration_schema.fields(self.definition) if configuration_runtime.supports(field)],
                'bindings': {key: copy.deepcopy(value) for key, value in row.get('bindings', {}).items()
                             if any(f['key'] == key and (f['type'] == 'resource' or configuration_credentials.supports(f) or configuration_connections.supports(f)) for f in _configuration_schema.fields(self.definition))},
                'employee': copy.deepcopy(getattr(self, 'employee', {})),
                'retained_keys': sorted(retained)}

    def connection_fields(self):
        if not any(configuration_connections.supports(f) for f in _configuration_schema.fields(self.definition)):return {}
        try:return configuration_connections.options(self.reference,self.definition_revision,self.definition,self.connection_asset)
        except (ValueError,PermissionError,OSError):return {}

    def read(self):
        self._check()
        with device_data.connect(readonly=True) as connection:
            row = self._load(connection)
        # A missing/revoked selection is an unavailable field, not a failed
        # outer read transaction. Resolve grants after capturing stored values.
        result = self._view(row)
        self._check()
        return result

    def credential(self, *, field, definition_sha256, value):
        self._check()
        if definition_sha256!=self.definition_sha256:raise ConfigurationConflict('配置定义已更新，请重新核对。')
        selected=next((f for f in _configuration_schema.fields(self.definition) if f['key']==field),None)
        if selected is None:raise ValueError('凭据配置项已变化。')
        result=configuration_credentials.update(selected,value)
        self._check();return result

    def receipt(self, operation_id):
        self._check()
        if not isinstance(operation_id, str) or not re.fullmatch('[0-9a-f-]{36}', operation_id):
            raise ValueError('配置保存编号无效。')
        with device_data.connect(readonly=True) as connection:
            row = connection.execute('SELECT value FROM device_settings WHERE key=?',
                                     (self.receipt_prefix + operation_id,)).fetchone()
            if row is None:
                return {'state': 'not_found'}
            result = strict_json(row[0].encode())['result']
            if result['reference'] != self.reference:
                raise PermissionError('保存回执不属于这名员工。')
        return {'state': 'confirmed', 'result': result}

    def save(self, *, operation_id, expected_revision, definition_sha256, values, bindings=None):
        self._check()
        if (not isinstance(operation_id, str) or not re.fullmatch('[0-9a-f-]{36}', operation_id)
                or str(uuid.UUID(operation_id)) != operation_id or type(expected_revision) is not int or expected_revision < 0):
            raise ValueError('配置保存请求无效。')
        request = {'reference': self.reference, 'expected_revision': expected_revision,
                   'definition_sha256': definition_sha256, 'values': values}
        if bindings is not None:
            request['bindings'] = bindings
        fingerprint = digest(request)
        receipt_key = self.receipt_prefix + operation_id
        # CLI catalog reads must not hold the personal SQLite write transaction.
        runtime_states=self._runtime_states()
        with device_data.connect() as connection:
            previous = connection.execute('SELECT value FROM device_settings WHERE key=?', (receipt_key,)).fetchone()
            if previous:
                receipt = strict_json(previous[0].encode())
                if receipt['request_sha256'] != fingerprint:
                    raise ConfigurationConflict('同一保存编号不能用于另一份配置。')
                return receipt['result']
            if definition_sha256 != self.definition_sha256:
                raise ConfigurationConflict('配置定义已更新，请保留输入并重新核对。')
            row = self._load(connection)
            if row['revision'] != expected_revision:
                raise ConfigurationConflict('配置已被修改，请保留输入并重新核对。')
            checked = validate_values(self.definition, values)
            selected = row.get('bindings', {}) if bindings is None else bindings
            if not isinstance(selected, dict) or len(selected) > 128:
                raise ConfigurationInvalid({'_form': '资料配置格式无效。'})
            index = {f['key']: f for f in _configuration_schema.fields(self.definition)}
            resolved = {}
            for key, selection in selected.items():
                if key not in index:
                    if bindings is None:
                        continue
                    raise ConfigurationInvalid({'_form': '资料项已变化，请重新选择。'})
                try:
                    resolved[key] = local_binding(index[key], selection,reference=self.reference,revision=self.definition_revision,connection_asset=self.connection_asset)
                except (ValueError, PermissionError) as error:
                    raise ConfigurationInvalid({key: str(error)}) from error
            # Only scalar retention is needed here. The newly resolved grants
            # replace old selections; preflighting stale grants would poison
            # this save transaction even when the user has repaired them.
            _, retained, _, _ = self._project({**row, 'bindings': {}}, runtime_states)
            result_row = {'schema': STATE, 'reference': self.reference, 'revision': row['revision'] + 1,
                          'definition_sha256': self.definition_sha256, 'values': checked,
                          'types': {f['key']: f['type'] for f in _configuration_schema.fields(self.definition) if f['key'] in checked},
                          'retained': retained, 'bindings': resolved}
            managed_keys={f['key'] for f in _configuration_schema.managed_fields(self.definition)}
            seeds={**row.get('managed_seeds',{}),**{key:value for key,value in row.get('bindings',{}).items() if key in managed_keys}}
            if seeds:result_row['managed_seeds']=seeds
            result = self._view(result_row, runtime_states)
            for key, value in ((self.key, result_row), (receipt_key, {'request_sha256': fingerprint, 'result': result})):
                connection.execute('INSERT INTO device_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                   (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
            self._check()
        return result

    def snapshot(self):
        """Admission may freeze this result; it neither starts nor resumes work."""
        value = self.read()
        if not value['ready']:
            raise ConfigurationInvalid({key: '此项还需核对。' for key, state in value['states'].items()
                                        if state != 'configured'})
        bindings = {}
        for field in _configuration_schema.fields(self.definition):
            if field['type']=='runtime' and value['states'][field['key']]=='configured':
                try:bindings[field['key']]=configuration_runtime.observe(field)
                except (ValueError,PermissionError,OSError,RuntimeError):
                    if field.get('required'):raise ConfigurationInvalid({field['key']:'运行环境暂不可用，请重新核对。'}) from None
                    value['states'][field['key']]='unavailable'
            if value['states'][field['key']] == 'configured' and field['key'] in value['bindings']:
                from . import local_assets
                import product_store
                selected = local_binding(field, value['bindings'][field['key']],reference=self.reference,revision=self.definition_revision,connection_asset=self.connection_asset)
                if configuration_documents.supports(field):selected=configuration_documents.freeze(field,selected)
                if configuration_collections.supports(field):selected=configuration_collections.freeze(field,selected)
                if field['binding']['provider'] == 'local_asset':
                    selected['fingerprint'] = local_assets.fingerprint(product_store.get_local_asset_grant(selected['grant_id']))
                bindings[field['key']] = selected
        states=copy.deepcopy(value['states'])
        if _configuration_schema.managed_fields(self.definition):
            from .managed_employee_data import provision
            for field in _configuration_schema.managed_fields(self.definition):
                bindings[field['key']]=provision(self,field)
                states[field['key']]='configured'
        self._check()
        return {'schema': SNAPSHOT, 'reference': value['reference'], 'revision': value['revision'],
                'definition_sha256': value['definition_sha256'],
                'definition_revision': value['definition_revision'], 'values': value['values'],
                'states': states, 'bindings': bindings}


@contextmanager
def for_source(reference):
    """Hold the original source lock across declaration reads and config writes."""
    from .source_employee_runtime import source
    from .creator_definitions import validate_author
    store, revisions = source(reference)
    with revisions.locked():
        head = revisions._head()
        files = revisions._files(head)
        project = strict_json(files['project.json'])
        if reference['employee_source'] not in project['entrypoints']['employees']:
            raise PermissionError('员工源码入口已变化。')
        employee = validate_author('employee', strict_json(files[reference['employee_source']]))
        value = ConfigurationStore(reference, employee.get('configuration', EMPTY), head)
        soul = files.get(employee['soul_file'], b'').decode('utf-8')
        value.employee = profile({**employee, 'soul': soul})
        yield value
        store.check_scope()


def source_receipt(reference, operation_id):
    """Recover a saved result even if the current declaration no longer compiles."""
    from .source_employee_runtime import source
    store, _ = source(reference)
    if not isinstance(operation_id, str) or not re.fullmatch('[0-9a-f-]{36}', operation_id):
        raise ValueError('配置保存编号无效。')
    with device_data.connect(readonly=True) as connection:
        row = connection.execute('SELECT value FROM device_settings WHERE key=?',
                                 ('employee-configuration-receipt:' + operation_id,)).fetchone()
        if row is None:
            return {'state': 'not_found'}
        result = strict_json(row[0].encode())['result']
        if result['reference'] != reference:
            raise PermissionError('保存回执不属于这名员工。')
    store.check_scope()
    return {'state': 'confirmed', 'result': result}
