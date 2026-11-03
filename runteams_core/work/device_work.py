from runteams_core.foundation.resources import root as resource_root
"""Explicit durable storage for concrete work, separate from cloud assets.

Opening this exact device path chooses local work before any network request.
It never falls back from a cloud failure or stores platform authority. The
existing Repository/event and execution contracts can use this provider.
"""
from runteams_core.employees import employee_work_contracts
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import threading
import uuid

from runteams_core.storage import device_data
from runteams_core.foundation.contracts import ContractError

DIRECTORY = 'work'
DATABASE = 'runteams.db'
FILE_PREFIX = 'device-work-file://'
VERSION = 4
ID_MIN = 2**48
ID_MAX = 2**53 - 1
RESOURCES = ('tasks', 'workflow_runs', 'employee_runs', 'artifacts')
_active = ContextVar('device_work_connection', default=None)
_locks = {}
_locks_guard = threading.Lock()


def schema():
    directory = resource_root() / 'contracts'
    return (directory/'device-work.sql').read_text()


def verify_structure(connection):
    from runteams_core.storage.device_schema import expected, structure
    actual, required = structure(connection), expected(schema())
    if any(actual.get(key)!=value for key,value in required.items()) or set(actual)-set(required):
        raise ContractError('本机工作数据结构不受支持，原资料保持不变。')


class _Connection(sqlite3.Connection):
    """Domain methods may declare BEGIN after joining the device transaction."""
    def execute(self, sql, parameters=()):
        if self.in_transaction and str(sql).strip().upper() in ('BEGIN', 'BEGIN IMMEDIATE', 'BEGIN TRANSACTION'):
            return super().execute('SELECT 1')
        storage = getattr(self, 'storage', None)
        if storage is not None:
            storage.check_scope()
            def parameter(value):
                if isinstance(value, str) and value.startswith(('{', '[')):
                    try:
                        decoded = json.loads(value)
                    except ValueError:
                        return value
                    canonical = storage.canonical_data(decoded)
                    return json.dumps(canonical, ensure_ascii=False) if canonical != decoded else value
                return storage.canonical_data(value)
            parameters = {k: parameter(v) for k, v in parameters.items()} if isinstance(parameters, dict) else tuple(parameter(v) for v in parameters)
        cursor = super().execute(sql, parameters)
        if storage is None or not cursor.description or 'ref' not in [column[0] for column in cursor.description]:
            return cursor
        # Reuse the existing row protocol, resolving only typed file refs.
        # Event JSON stays canonical so reading never changes its audit hash.
        from runteams_core.storage.storage_contracts import CloudCursor
        columns = [column[0] for column in cursor.description]
        index = columns.index('ref')
        rows = []
        for row in cursor:
            values = list(row)
            values[index] = storage.file_path(values[index])
            rows.append(values)
        return CloudCursor({'columns': columns, 'rows': rows, 'lastrowid': cursor.lastrowid, 'rowcount': cursor.rowcount})


def _binding(scope):
    if scope.get('storage_kind') == 'local':
        return {key: scope[key] for key in ('storage_kind', 'library_id', 'storage_namespace')}
    return {'account_id': scope['account_id'],
            'deployment_id': scope.get('deployment_id', ''),
            'service_url': scope.get('storage_service_url', scope['service_url']),
            'namespace': scope.get('storage_namespace') or device_data.root().name}


def _directory(path):
    if path.is_symlink():
        raise ContractError('本机工作目录不能是符号链接。')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def database_path():
    if not device_data.personal():
        raise PermissionError('请在个人工作区打开本机工作。')
    return device_data.root() / DIRECTORY / DATABASE


def recognizes(path):
    path = Path(os.path.abspath(path))
    # Reserve only the explicit device-data/<namespace>/work database shape.
    # An ordinary core/cache database never becomes local after a cloud error.
    return (path.name == DATABASE and path.parent.name == DIRECTORY
            and path.parent.parent.parent.name == 'device-data')


class _WorkLock:
    def __init__(self):
        self.lock = threading.RLock()
        self.local = threading.local()

    @contextmanager
    def hold(self, storage, filename='.writer.lock'):
        with self.lock:
            storage.check_scope()
            if getattr(self.local, 'depth', 0):
                self.local.depth += 1
                try:
                    yield
                    storage.check_scope()
                finally:
                    self.local.depth -= 1
                return
            path = Path(storage.path).parent / filename
            _directory(path.parent)
            if path.is_symlink():
                raise ContractError('本机工作锁路径无效。')
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            with os.fdopen(fd, 'a+b') as handle:
                if os.name == 'nt':
                    import msvcrt
                    if path.stat().st_size == 0:
                        handle.write(b'0'); handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                self.local.depth = 1
                try:
                    yield
                    storage.check_scope()
                finally:
                    self.local.depth = 0
                    if os.name == 'nt':
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class DeviceWorkStorage:
    """Personal work data only; no cloud attribute, credentials or business API."""
    def __init__(self, path=None):
        self.scope = device_data.identity()
        expected = database_path()
        self.path = str(Path(os.path.abspath(path)) if path is not None else expected)
        if Path(self.path) != expected:
            raise PermissionError('本机工作属于其他账户或服务。')
        self.binding = _binding(self.scope)
        with _locks_guard:
            self._lock = _locks.setdefault(self.path, _WorkLock())

    def check_scope(self):
        device_data.check(self.scope)
        if not device_data.personal() or Path(self.path) != database_path():
            raise PermissionError('账户或工作区已变化，请重新打开本机工作。')
        parent = Path(self.path).parent
        for path in (parent, Path(self.path), Path(self.path + '-wal'), Path(self.path + '-shm')):
            if path.is_symlink():
                raise ContractError('本机工作数据路径无效。')

    def definition_lock(self):
        return self._lock.hold(self)

    def confirmation_lock(self, key):
        # Remote asset receipts must not hold the work writer lock: Agents
        # continue appending local events while a confirmation waits on cloud.
        import hashlib
        name = '.confirmation-' + hashlib.sha256(str(key).encode()).hexdigest() + '.lock'
        with _locks_guard:
            lock = _locks.setdefault(self.path + ':' + name, _WorkLock())
        return lock.hold(self, name)

    def initialize(self):
        self.check_scope()
        with self.definition_lock():
            _directory(Path(self.path).parent)
            connection = sqlite3.connect(self.path, timeout=30)
            Path(self.path).chmod(0o600)
            try:
                version = connection.execute('PRAGMA user_version').fetchone()[0]
                if version == 3:
                    self._verify_scope(connection)
                    connection.execute('BEGIN IMMEDIATE')
                    connection.execute('DROP TABLE IF EXISTS document_native_links')
                    verify_structure(connection)
                    connection.execute('PRAGMA user_version=' + str(VERSION))
                    self.check_scope()
                    connection.commit()
                    version = VERSION
                if version == VERSION:
                    verify_structure(connection)
                    self._verify_scope(connection)
                    return
                if version != 0 or connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
                    raise ContractError('本机工作数据版本不受支持，原数据保持不变。')
                connection.execute('PRAGMA journal_mode=WAL')
                # Every table and the identity marker commit together. A crash
                # cannot publish an unowned half-initialized work database.
                connection.execute('BEGIN IMMEDIATE')
                from runteams_core.storage.device_schema import execute
                execute(connection,schema())
                connection.execute('INSERT INTO device_work_scope VALUES(1,?,?)',
                    (json.dumps(self.binding, sort_keys=True), str(uuid.uuid4())))
                for table in (*RESOURCES, 'events', 'employee_releases'):
                    connection.execute('INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)',
                        (table, ID_MIN + secrets.randbelow(2**40)))
                connection.execute('PRAGMA user_version=' + str(VERSION))
                self.check_scope()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _verify_scope(self, connection):
        row = connection.execute('SELECT binding_json,data_epoch FROM device_work_scope WHERE singleton=1').fetchone()
        if row is None or json.loads(row[0]) != self.binding:
            raise PermissionError('本机工作数据属于其他账户或服务。')
        if str(uuid.UUID(row[1])) != row[1]:
            raise ContractError('本机工作身份无效。')
        return row[1]

    @contextmanager
    def connect(self, *, readonly=False):
        self.check_scope()
        active = _active.get()
        if active is not None and active['path'] == self.path:
            try:
                if active['readonly'] and not readonly:
                    raise ContractError('本机工作读取事务不能升级为写入。')
                yield active['connection']
                self.check_scope()
            except BaseException:
                active['failed'] = True
                raise
            return
        if readonly:
            # A reader must not acquire the definition/writer lock or create
            # an empty database. Verify the same schema and owner in its WAL
            # snapshot; initialization/migration remains a writer operation.
            connection = sqlite3.connect(Path(self.path).as_uri()+'?mode=ro', uri=True,
                                         timeout=30, factory=_Connection)
        else:
            self.initialize()
            connection = sqlite3.connect(self.path, timeout=30, factory=_Connection)
        connection.storage = self
        connection.row_factory = sqlite3.Row
        changed = False
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            if readonly:
                connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN' if readonly else 'BEGIN IMMEDIATE')
            if readonly:
                if connection.execute('PRAGMA user_version').fetchone()[0] != VERSION:
                    raise ContractError('本机工作数据版本不受支持，原资料保持不变。')
                verify_structure(connection)
            self._verify_scope(connection)
            state = {'path': self.path, 'connection': connection, 'readonly': readonly, 'failed': False}
            token = _active.set(state)
            try:
                yield connection
                self.check_scope()
                if state['failed']:
                    raise ContractError('本机工作事务未完成，请重新读取。')
                connection.commit()
                changed = not readonly and connection.total_changes > 0
            finally:
                _active.reset(token)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if changed:
            from runteams_core.storage.storage_context import notify_saved
            notify_saved(self.scope)

    def data_epoch(self):
        with self.connect(readonly=True) as connection:
            return self._verify_scope(connection)

    def recovery_ids(self, domain):
        if domain != 'workflow_runs':
            raise ContractError('不支持的本机恢复范围。')
        with self.connect(readonly=True) as connection:
            return [row[0] for row in connection.execute(
                "SELECT id FROM workflow_runs WHERE state='running' "
                "AND NOT EXISTS(SELECT 1 FROM device_work_restore_barriers b WHERE b.workflow_run_id=workflow_runs.id) ORDER BY id")]

    def assert_executable(self, workflow_run_id):
        with self.connect(readonly=True) as connection:
            if connection.execute("SELECT 1 FROM device_work_restore_barriers b JOIN workflow_runs w "
                    "ON w.id=b.workflow_run_id WHERE b.workflow_run_id=? AND w.state NOT IN ('completed','canceled')",
                    (int(workflow_run_id),)).fetchone():
                raise ContractError('这是从备份恢复的工作，请先核对原工作与外部操作结果再继续。')

    def canonical_data(self, value):
        self.check_scope()
        if isinstance(value, dict):
            return {key: self.canonical_data(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.canonical_data(item) for item in value]
        if isinstance(value, str) and value.startswith(str(Path(self.path).parent) + os.sep) and not any(c in value for c in ('\n', '\r', '\0')):
            relative = Path(value).relative_to(Path(self.path).parent).as_posix()
            from runteams_core.assets.cloud_files import safe_relative
            safe_relative(relative)
            return FILE_PREFIX + relative
        return value

    def file_path(self, reference):
        if not isinstance(reference, str) or not reference.startswith(FILE_PREFIX):
            return reference
        from runteams_core.assets.cloud_files import safe_relative
        relative = safe_relative(reference[len(FILE_PREFIX):])
        self.check_scope()
        root = Path(self.path).parent
        path = root / relative
        if root not in path.resolve().parents or any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ContractError('本机工作文件引用无效。')
        return str(path)

    def allocate_id(self, connection, table):
        if table not in (*RESOURCES, 'events', 'employee_releases'):
            raise ContractError('不支持的本机工作编号。')
        self.check_scope()
        value = connection.execute('SELECT seq+1 FROM sqlite_sequence WHERE name=?', (table,)).fetchone()[0]
        if value > ID_MAX:
            raise ContractError('本机工作编号已达上限。')
        return value

    def public_id(self, resource, identifier):
        if resource not in RESOURCES or type(identifier) is not int or not ID_MIN <= identifier <= ID_MAX:
            raise ContractError('本机工作引用无效。')
        with self.connect() as connection:
            if connection.execute('SELECT 1 FROM ' + resource + ' WHERE id=?', (identifier,)).fetchone() is None:
                raise ContractError('本机工作记录不存在。')
            row = connection.execute('SELECT identity FROM device_work_resources WHERE resource=? AND id=?',
                (resource, identifier)).fetchone()
            identity = row[0] if row else str(uuid.uuid4())
            if row is None:
                connection.execute('INSERT INTO device_work_resources VALUES(?,?,?)',
                    (resource, identifier, identity))
        return 'local-' + identity.replace('-', '')


def snapshot(source, destination, scope, check):
    """One verified local work database and all its input/output/work files."""
    source = Path(source) / DIRECTORY
    if not source.exists() and not source.is_symlink():
        return
    target = Path(destination) / DIRECTORY
    path = source / DATABASE
    storage = DeviceWorkStorage(path)
    with storage.definition_lock():
        check()
        if any(p.is_symlink() for p in source.rglob('*')):
            raise ContractError('本机工作备份不能包含符号链接。')
        target.mkdir(mode=0o700)
        with storage.connect():
            # Hold the same SQLite writer gate as actual work updates, and
            # copy through a separate reader (backup on the writer would wait
            # for its own transaction). File verification remains inside it.
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as original, sqlite3.connect(target / DATABASE) as copied:
                original.backup(copied)
                copied.execute('PRAGMA journal_mode=DELETE')
        # Work files are mutable while an Agent writes. Compare source and
        # destination trees; never certify a torn file snapshot as complete.
            import hashlib
            def files():
                if any(p.is_symlink() for p in source.rglob('*')):
                    raise ContractError('本机工作备份不能包含符号链接。')
                return {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in source.rglob('*') if p.is_file()
                    and p.relative_to(source).parts[0] not in (DATABASE, DATABASE+'-wal', DATABASE+'-shm', '.writer.lock')}
            before = files()
            for name in before:
                original = source / name
                if original.is_symlink():
                    raise ContractError('本机工作备份不能包含符号链接。')
                copied = target / name
                copied.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copyfile(original, copied)
            after = files()
            if before != after or any(hashlib.sha256((target / name).read_bytes()).hexdigest() != value
                                      for name, value in before.items()):
                raise ContractError('本机工作文件正在变化，请稍后重新备份。')
        check()
        verify(destination, scope)


def verify(directory, scope):
    path = Path(directory) / DIRECTORY / DATABASE
    if not path.exists() and not path.is_symlink():
        if path.parent.exists():
            raise ContractError('本机工作备份缺少数据库。')
        return
    if path.parent.is_symlink() or path.is_symlink() or any(p.is_symlink() for p in path.parent.rglob('*')):
        raise ContractError('本机工作备份路径无效。')
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        if (connection.execute('PRAGMA user_version').fetchone()[0] != VERSION
                or connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok'
                or connection.execute('PRAGMA foreign_key_check').fetchone()):
            raise ContractError('本机工作备份数据库无效。')
        verify_structure(connection)
        row = connection.execute('SELECT binding_json,data_epoch FROM device_work_scope WHERE singleton=1').fetchone()
        # Backup manifests use the original storage URL, even after transport
        # changes; account/deployment/namespace remain the durable identity.
        binding = json.loads(row[0]) if row else {}
        if scope.get('storage_kind')=='local':
            expected=_binding(scope)
            if binding!=expected:raise PermissionError('工作备份属于其他资料库。')
            if connection.execute('SELECT 1 FROM employee_releases LIMIT 1').fetchone():raise ContractError('本机资料库不包含官方冻结资产。')
        else:
            expected = {'account_id': scope['account_id'], 'deployment_id': scope.get('deployment_id', ''),
                        'service_url': scope.get('storage_service_url', scope['service_url'])}
            if any(binding.get(k) != value for k, value in expected.items()):
                raise PermissionError('本机工作备份属于其他账户或服务。')
            if scope.get('storage_namespace') and binding.get('namespace') != scope['storage_namespace']:
                raise PermissionError('本机工作备份范围不一致。')
            if not scope.get('storage_namespace'):
                import hashlib
                namespace = hashlib.sha256((expected['service_url'] + '\n' + expected['account_id']).encode()).hexdigest()
                if binding.get('namespace') != namespace:
                    raise PermissionError('本机工作备份范围不一致。')
        if row is None or str(uuid.UUID(row[1])) != row[1]:
            raise ContractError('本机工作备份身份无效。')
        from runteams_core.authoring.definition_contracts import validate_definition
        from runteams_core.foundation.contracts import digest
        for employee, digest_value, raw, source_ref in connection.execute(
                'SELECT employee_id,digest,snapshot_json,source_ref_json FROM employee_releases'):
            frozen = validate_definition('employee_release', json.loads(raw))
            reference = json.loads(source_ref)
            source_id = employee
            if 'native_asset' in reference:
                from runteams_core.employees.native_employee_references import source_employee_id
                source_id = source_employee_id(reference['native_asset'], employee,
                                               expected['account_id'], expected['deployment_id'])
                if reference['native_asset']['release_reference']['id'] != reference.get('release_id'):
                    raise ContractError('本机工作备份的冻结发布引用不一致。')
            if (frozen['schema'] != 'runteams.employee-release/v4' or frozen['employee']['id'] != source_id
                    or digest(frozen) != digest_value or reference.get('employee_id') != employee
                    or any(reference.get(k) != value for k, value in expected.items())):
                raise ContractError('本机工作备份的冻结资产无效。')
        from runteams_core.storage.repository import Repository
        previous = None
        connection.row_factory = sqlite3.Row
        from runteams_core.employees.employee_work_contracts import SCHEMA as SOURCE_WORK
        from runteams_core.employees.employee_work_contracts import verify_frozen
        for identifier,task_reference,raw in connection.execute('SELECT wr.id,t.employee_reference,wr.snapshot_json FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id WHERE t.employee_reference IS NOT NULL'):
            value=verify_frozen(json.loads(raw),scope)
            if value['employee_reference']!=json.loads(task_reference):raise ContractError('员工工作与任务归属不一致。')
            for version in [value]+[item['snapshot'] for item in value.get('pipeline_history',[])]:
                from runteams_core.employees.employee_context import current as employee_context
                if version['package']['schema'] == employee_work_contracts.ACQUIRED_PACKAGE:
                    employee_context().verify_package_archive(directory, scope, version['package'])
                if version.get('pipeline_work'):
                    from runteams_core.pipelines.source_pipeline_flow import verify_links
                    verify_links(connection,identifier,version,history=value.get('pipeline_history',[]))
                if not version.get('employee_run_id'):continue
                run=connection.execute('SELECT workflow_run_id,employee_release_id,input_json,position_key FROM employee_runs WHERE id=?',(version['employee_run_id'],)).fetchone()
                if run is None or run[0]!=identifier or run[1] is not None:raise ContractError('员工工作执行引用无效。')
                order=json.loads(run[2])
                if version.get('pipeline_work'):verify_links(connection,identifier,version,order,history=value.get('pipeline_history',[]))
                if order.get('schema')!='runteams.employee-chat-order/v1' or order.get('package')!=version['package'] or order.get('employee_reference')!=version['employee_reference'] or order.get('chat_id')!=version['work_chat_id']:
                    raise ContractError('员工工作冻结执行内容不一致。')
                if (order.get('pipeline_work') != version.get('pipeline_work') or
                        version.get('pipeline_work') and (run[3] != version['pipeline_work']['position_key'] or
                        order.get('pipeline_generation')!=version.get('pipeline_generation') or order.get('pipeline_visit')!=version.get('pipeline_visit'))):
                    raise ContractError('流水线岗位执行归属不一致。')
            if value.get('pipeline_work'):
                for run_id in value.get('pipeline_lineage',[]):
                    owner=connection.execute('SELECT workflow_run_id FROM employee_runs WHERE id=?',(run_id,)).fetchone()
                    if owner is None or owner[0]!=identifier:raise ContractError('交接记录引用了其他工作。')
        from runteams_core.work.work_connection_calls import verify as verify_connection_calls
        verify_connection_calls(connection,scope,directory)
        for event in connection.execute('SELECT * FROM events ORDER BY id'):
            if event['type']=='pipeline.runtime_state':
                from runteams_core.pipelines.source_pipeline_control import verify_state
                runtime_state=json.loads(event['data_json']);verify_state(runtime_state,scope)
                from runteams_core.employees.employee_context import current as employee_context
                for role in (runtime_state.get('bundle') or {}).get('roles', {}).values():
                    if role['package']['schema'] == employee_work_contracts.ACQUIRED_PACKAGE:
                        employee_context().verify_package_archive(directory, scope, role['package'])
                expected_stream='source-pipeline-runtime:'+runtime_state['reference']['source_id']+':'+runtime_state['reference']['pipeline_source']
                if event['stream']!=expected_stream:raise ContractError('流水线运行回执归属不一致。')
            calculated = Repository._event_hash(**{key: event[key] for key in
                ('stream', 'data_json', 'created_at', 'actor_id', 'correlation_id', 'source', 'schema_version')},
                event_id=event['id'], event_type=event['type'], prev_hash=previous)
            if event['prev_hash'] != previous or event['event_hash'] != calculated:
                raise ContractError('本机工作备份事件记录校验失败。')
            previous = event['event_hash']


def quarantine_restored(directory):
    """Preserve restored work without automatically replaying an older run."""
    path = Path(directory) / DIRECTORY / DATABASE
    if not path.exists():
        return 0
    from runteams_core.storage.repository import utc_now
    with sqlite3.connect(path) as connection:
        connection.execute('INSERT OR IGNORE INTO device_work_restore_barriers(workflow_run_id,restored_at) '
            'SELECT id,? FROM workflow_runs', (utc_now(),))
        return connection.execute('SELECT COUNT(*) FROM device_work_restore_barriers').fetchone()[0]
