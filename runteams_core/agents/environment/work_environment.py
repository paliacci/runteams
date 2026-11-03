"""Durable work-level Python selection. Discovery never executes project code.

Actual verification/execution happens in agent_python, invoked through the
official CLI's terminal and therefore subject to its existing execution policy.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

from runteams_core.agents.environment import agent_environment

SCHEMA = 'runteams.work-environment/1'
_HASH = re.compile(r'^[a-f0-9]{64}$')


class EnvironmentError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def chat_work(chat_id):
    from runteams_core.storage import product_store as store
    from runteams_core.storage import device_data
    if store.device_chat(chat_id):
        return {'root': str(device_data.root() / 'work-environments'),
                'key': digest(['conversation', device_data.epoch(chat_id)])}
    if int(chat_id) >= device_data.LOCAL_CHAT_ID_MIN:
        raise PermissionError('当前账户没有这段本机对话。')
    session = store.get_chat(chat_id, include_messages=False)
    if not session:
        raise EnvironmentError('工作对话已不可用。')
    return {'root': str(Path(store.core_data_root()) / 'work-environments'),
            'key': digest(['conversation', str(chat_id), session.get('created_at')])}


def workflow_work(workspace, workflow_id):
    workspace = Path(workspace)
    if (workspace.name != 'workspace' or workspace.parent.name != 'workflow-' + str(workflow_id)
            or workspace.parent.parent.name != 'workspaces'):
        raise EnvironmentError('流水线工作目录与运行身份不一致。')
    return {'root': str(workspace.parents[2] / 'work-environments'),
            'key': digest(['workflow', str(workflow_id)])}


def directory_identity(path):
    p = Path(path)
    stat = p.stat()
    if not p.is_dir():
        raise EnvironmentError('原工作目录已不可用，请重新确认工作目录。')
    return {'realpath': str(p.resolve()), 'device': stat.st_dev, 'inode': stat.st_ino}


def file_identity(path):
    p = Path(path)
    return {'realpath': str(p.resolve(strict=True)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def python_identity(python):
    executable = python.get('executable')
    if not executable or not os.access(executable, os.X_OK):
        raise EnvironmentError('绑定的 Python 不可用；不会自动改用其他版本。')
    result = {'executable': file_identity(executable)}
    if python.get('environment'):
        cfg = Path(python['environment']) / 'pyvenv.cfg'
        result['configuration'] = file_identity(cfg) if cfg.is_file() else None
    elif python.get('source') == 'managed':
        current = agent_environment.managed_python()
        if current.get('status') != 'ready' or current.get('executable') != executable:
            raise EnvironmentError('绑定的托管 Python 已失效；不会自动换版本。')
        result['manifest'] = file_identity(agent_environment.runtime_root() / 'runtime.json')
    return result


def launcher(record, binding_id):
    args = ([sys.executable, '--runteams-python'] if getattr(sys, 'frozen', False)
            else [sys.executable, '-m', 'runteams_core.agents.environment.agent_python'])
    return args + ['--record', str(record), '--binding-id', binding_id]


def _directory(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise EnvironmentError('工作环境记录路径无效。')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


class BindingStore:
    def __init__(self, root, key):
        if not _HASH.fullmatch(str(key)):
            raise EnvironmentError('工作环境身份无效。')
        if Path(root).is_symlink():
            raise EnvironmentError('工作环境记录目录不能是符号链接。')
        self.root = Path(root).resolve()
        self.key = key
        self.path = self.root / (key + '.json')
        self.claim = self.root / (key + '.claim')

    @classmethod
    def reference(cls, reference):
        return cls(reference['root'], reference['key'])

    @classmethod
    def record(cls, record):
        path = Path(record).absolute()
        if path.suffix != '.json':
            raise EnvironmentError('工作环境记录格式无效。')
        return cls(path.parent, path.stem)

    @contextmanager
    def locked(self, readonly=False):
        import fcntl
        if not readonly:
            _directory(self.root)
        lock = self.root / (self.key + '.lock')
        if readonly and not lock.exists():
            # Restored records do not carry ephemeral lock files. Atomic JSON
            # reads plus a read-only claim lock need no metadata creation.
            lock = self.claim
        descriptor = os.open(lock,
            (os.O_RDONLY if readonly else os.O_CREAT | os.O_RDWR) | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH if readonly else fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def load(self):
        if (self.claim.is_symlink() or not self.claim.is_file() or self.claim.stat().st_size != 64
                or self.claim.read_text() != self.key):
            raise EnvironmentError('工作环境身份记录缺失，不能自动重选。')
        if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > 2 * 1024 * 1024:
            raise EnvironmentError('原工作环境记录缺失或损坏，不能自动重选。')
        try:
            value = json.loads(self.path.read_text())
            contract = value['contract']
            if (value['schema'] != SCHEMA or contract['work_key'] != self.key
                    or digest(contract) != value['binding_id']):
                raise ValueError('binding mismatch')
            return value
        except (ValueError, KeyError, TypeError):
            raise EnvironmentError('原工作环境记录损坏，不能自动重选。') from None

    def save(self, value):
        tmp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex)
        descriptor = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def _new(self, cwd, source=None, previous=None, reason='initial_selection', executable=None):
        discovered = agent_environment.describe(cwd)
        selected = discovered['python']
        if source == 'managed':
            selected = discovered['managed_python']
        elif source == 'project' and selected.get('source') != 'project':
            raise EnvironmentError('当前工作目录没有可选择的项目 Python。')
        elif source == 'explicit':
            path = Path(executable or '')
            if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
                raise EnvironmentError('明确选择的 Python 必须是可用的绝对路径。')
            selected = {'source': 'explicit', 'status': 'detected', 'verified': False, 'executable': str(path)}
            if (path.parent.parent / 'pyvenv.cfg').is_file():
                selected['environment'] = str(path.parent.parent)
        contract = {'work_key': self.key, 'cwd': str(Path(cwd).absolute()),
                    'directory': directory_identity(cwd), 'python': deepcopy(selected),
                    'requirements': discovered['project_requirement'], 'generation': uuid.uuid4().hex}
        try:
            contract['identity'] = python_identity(selected)
        except (OSError, ValueError, RuntimeError):
            contract['identity'] = None
        return {'schema': SCHEMA, 'binding_id': digest(contract), 'contract': contract,
                'verification': None, 'history': (previous.get('history', []) + [{
                    'binding_id': previous['binding_id'], 'contract': previous['contract'],
                    'reason': reason, 'changed_at': time.time()}])[-32:] if previous else []}

    def bind(self, cwd):
        with self.locked():
            if self.path.exists() or self.path.is_symlink():
                record = self.load()
                if record['contract']['cwd'] != str(Path(cwd).absolute()):
                    raise EnvironmentError('此工作的执行目录已绑定，不能自动迁移环境。')
            else:
                if self.claim.exists() or self.claim.is_symlink():
                    raise EnvironmentError('原工作环境记录已丢失，不能自动重选。')
                record = self._new(cwd)
                descriptor = os.open(self.claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor, 'w') as stream:
                    stream.write(self.key); stream.flush(); os.fsync(stream.fileno())
                self.save(record)
            return self.present(record)

    def check(self, record):
        contract = record['contract']
        try:
            if directory_identity(contract['cwd'])['realpath'] != contract['directory']['realpath']:
                raise EnvironmentError('原工作目录已指向其他位置，请重新确认。')
            if python_identity(contract['python']) != contract['identity'] or contract['identity'] is None:
                raise EnvironmentError('绑定的 Python 已变化；请明确重新选择环境。')
            if agent_environment.describe(contract['cwd'])['project_requirement'] != contract['requirements']:
                raise EnvironmentError('项目 Python 版本约定已变化，请明确重新选择环境。')
            for item in (record.get('observed_runtime') or record.get('verification') or {}).get('runtime_files', []):
                if file_identity(item['origin']) != item['identity']:
                    raise EnvironmentError('Python 运行库已变化，请明确重新选择环境。')
        except (OSError, ValueError, RuntimeError) as error:
            raise EnvironmentError(str(error) or '绑定的 Python 已失效。') from None

    def current(self):
        # Writers replace a complete JSON document atomically. Readers need
        # neither metadata writes nor a wait behind a long first-use probe.
        return self.present(self.load())

    def present(self, record):
        contract = record['contract']
        python = deepcopy(contract['python'])
        try:
            self.check(record)
            python.update(status='bound', verified=False)
            verified = record.get('verification')
            if verified and verified.get('status') == 'failed':
                python.update(status='validation_failed', reason=verified.get('reason'))
            if verified and verified.get('status') == 'passed':
                modules = {}
                for name, item in verified.get('modules', {}).items():
                    try:
                        if item.get('origin') and file_identity(item['origin']) != item['identity']:
                            continue
                        modules[name] = True
                    except (OSError, ValueError):
                        continue
                python.update(status='ready', verified=True, version=verified['version'],
                              modules=modules,
                              project_compatibility='verified')
        except EnvironmentError as error:
            python.update(status='invalid', verified=False, reason=str(error))
        python['launcher_argv'] = launcher(self.path, record['binding_id'])
        receipt = deepcopy(record.get('verification'))
        if receipt and receipt.get('status') == 'passed':
            receipt = {key: receipt[key] for key in ('status', 'version', 'checked_at', 'last_failure') if key in receipt}
            receipt['modules'] = sorted(python.get('modules', {})) if python['status'] == 'ready' else []
        return {'schema': 'runteams.workspace-environment/1', 'cwd': contract['cwd'],
                'python': python, 'project_requirement': contract['requirements'],
                'binding': {'schema': SCHEMA, 'id': record['binding_id'], 'work_key': self.key,
                            'record': str(self.path)}, 'verification': receipt}

    def select(self, expected, source, reason, executable=None):
        if source not in ('project', 'managed', 'explicit') or not str(reason).strip() or len(str(reason)) > 1000:
            raise EnvironmentError('切换环境需要明确来源和原因。')
        with self.locked():
            previous = self.load()
            if previous['binding_id'] != expected:
                raise EnvironmentError('环境已被其他操作更新，请读取当前绑定后再决定。')
            cwd = previous['contract']['cwd']
            if directory_identity(cwd)['realpath'] != previous['contract']['directory']['realpath']:
                raise EnvironmentError('原工作目录已指向其他位置，请开始新工作。')
            record = self._new(cwd, source, previous, reason, executable)
            self.save(record)
            return self.present(record)


def snapshot(source, destination, scope, check):
    root = Path(source) / 'work-environments'
    if not root.exists():
        return
    if root.is_symlink():
        raise EnvironmentError('工作环境备份路径无效。')
    target = Path(destination) / 'work-environments'
    target.mkdir(mode=0o700)
    for path in root.iterdir():
        if path.suffix == '.lock' and _HASH.fullmatch(path.stem):
            continue
        if path.suffix == '.claim' and _HASH.fullmatch(path.stem):
            continue
        if re.fullmatch(r'[a-f0-9]{64}\.json\.[a-f0-9]{32}', path.name):
            continue
        store = BindingStore.record(path)
        with store.locked():
            store.load(); check()
            shutil.copy2(path, target / path.name)
            shutil.copy2(store.claim, target / store.claim.name)
            check()
