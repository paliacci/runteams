"""MCP execution attached to the existing downloaded personal employee work.

Only verified frozen skill attachments are inputs. No HTTP path, model text or
local trust record can acquire an employee or grant cloud business authority.
"""
import base64
from contextvars import ContextVar
from contextlib import contextmanager, nullcontext
import copy
import json
from pathlib import Path
import re
import threading
import time
import uuid

from runteams_core.storage import device_data
from runteams_core.employees import employee_workspaces
from runteams_core.foundation.contracts import ContractError, digest
from runteams_core.authoring.creator_contracts import CreatorContractError
from runteams_core.authoring.definition_contracts import validate_employee_bundles
from runteams_core.storage.device_files import _publish, _read
from runteams_core.foundation.identity.work_identity import work_scope
from runteams_core.foundation.identity.work_identity import principal
from runteams_core.employees.mcp.employee_mcp import EmployeeMCP, WorkBinding, MCPOutcomeUnknown, MCPAppResourceInvalid
from runteams_core.employees.mcp.employee_mcp_package import MCPBundle

ATTACHMENT = 'mcp/employee.mcpb'
FILE = 'mcp-work.json'
_app_grant = ContextVar('employee_mcp_app_grant',default=None)
_read_only_app = ContextVar('employee_mcp_read_only_app',default=False)
WORKBENCH_ID_MIN = 2**49  # The device conversation range ends here.


def is_workbench_id(value):
    return type(value) is int and WORKBENCH_ID_MIN <= value < 2*WORKBENCH_ID_MIN


def bundles(employee):
    """Read a declared attachment in each complete, frozen skill, without execution."""
    if employee.get('local_package'):
        from runteams_core.employees.source_employee_runtime import validate
        validate(employee['local_package'])
    else:
        validate_employee_bundles(employee['active_release']['snapshot_json'])
    return inspect_attachments(employee)


def inspect_attachments(employee):
    """Inspect bundled MCP files on an already verified employee snapshot."""
    result = {}
    for skill in employee['active_release']['snapshot_json']['skill_bundles']:
        for file in skill['files']:
            if file['path'] == ATTACHMENT:
                raw = base64.b64decode(file['content_base64'], validate=True)
                bundle = MCPBundle.inspect(raw)
                result[bundle.digest] = bundle
    return result


class EmployeeMCPWork:
    trust_namespace = 'employee-mcp'

    retain_app_session = False

    def __init__(self, runtime, *, operation_scope=nullcontext):
        self.scope, self.root = device_data.identity(), device_data.root()
        self.runtime = runtime
        self.operation_scope=operation_scope
        self.lock = threading.RLock()
        self.sessions, self.pending, self.turns = {}, {}, {}
        self.views = {}
        self.connection_calls, self.connection_requests = {}, {}
        self.closed = False
        self.notice_epoch = uuid.uuid4().hex
        self.notice_revision = 0
        self.observation_cache = {}
        self.workbenches = {}
        self._inspection = threading.local()

    def prepare_workbench(self, data):
        """Select a local employee revision without creating a conversation."""
        from runteams_core.employees import employee_references, source_employee_runtime as runtime
        if (not isinstance(data,dict) or set(data) not in ({'reference','revision'}, {'reference','revision','prefer_summary'})
                or 'prefer_summary' in data and data['prefer_summary'] is not True):
            raise ValueError('工作台请求无效。')
        self.check()
        ref = employee_references.checked_reference(data['reference'])
        if ref['schema'] != employee_references.SOURCE_SCHEMA:
            raise PermissionError('请选择本机源码员工。')
        revision = data['revision']
        if revision is not None and (not isinstance(revision,str) or not re.fullmatch(r'(?:r-)?[0-9a-f]{64}',revision)):
            raise ValueError('员工版本无效。')
        _, revisions = runtime.source(ref)
        if revision is None:
            revision = revisions.current()['revision']
        if data.get('prefer_summary'):
            from runteams_core.employees.employee_workbench_summary import eva_summary
            summary = eva_summary(ref, revision)
            if summary is not None:
                self.check()
                return {'reference':ref,'revision':revision,'summary':summary}
        asset_id = digest({'reference':ref,'revision':revision})
        identifier = WORKBENCH_ID_MIN + int(asset_id[:12],16)
        with self.lock:
            previous = self.workbenches.get(identifier)
            if previous is not None:
                if previous['reference'] != ref or previous['revision'] != revision:
                    raise PermissionError('工作台引用冲突。')
                return {'id':identifier,'revision':revision,'reference':ref}
        package = runtime.prepare(ref,str(uuid.uuid5(uuid.NAMESPACE_URL,'employee-workbench:'+asset_id)),revision=revision)
        self.check()
        with self.lock:
            previous = self.workbenches.setdefault(identifier,package)
            if previous['reference'] != ref or previous['revision'] != revision:
                raise PermissionError('工作台引用冲突。')
        return {'id':identifier,'revision':revision,'reference':ref}

    def authoring_programs(self, session, *, cancel=None, notify=None):
        """Only expose programs the user has already enabled for this source revision."""
        from runteams_core.employees.employee_directory import for_session
        from runteams_core.authoring.creator_local_authoring import source
        try:
            entry = for_session(session)
            if not entry['record'].get('local_mcp'):
                return nullcontext({}), ''
            handle = self.prepare_workbench({'reference': entry['source']['reference'],
                                             'revision': source(session).current()['revision']})
            identifier = handle['id']
            if self.state(identifier)['enabled']:
                return self.runtime_scope(identifier, cancel=cancel, notify=notify), ''
            return nullcontext({}), '当前员工版本的随包程序尚未启用。如果工作必须使用它，请在当前对话说明，可在员工工作台启用这个版本后继续。'
        except (ValueError, OSError, RuntimeError) as error:
            # A broken program must remain editable in its original conversation.
            return nullcontext({}), '本轮无法加载员工随包程序：' + str(error)

    def _workbench(self, identifier):
        self.check()
        with self.lock:
            package = self.workbenches.get(identifier)
        if package is None:
            raise PermissionError('工作台已失效，请重新打开。')
        return package

    def _workbench_subject(self, identifier):
        from runteams_core.employees.source_employee_runtime import employee
        item = employee(self._workbench(identifier))
        return item, self._workbench_directory(identifier)

    def _work_id(self, chat):
        if not is_workbench_id(chat):
            return device_data.epoch(chat)
        package = self._workbench(chat)
        asset_id = digest({'reference':package['reference'],'revision':package['revision']})
        return str(uuid.uuid5(uuid.NAMESPACE_URL,'employee-workbench:'+asset_id))

    def _workbench_directory(self, identifier):
        return employee_workspaces._directory(
            employee_workspaces._directory(self.root / employee_workspaces.WORKSPACES) / self._work_id(identifier))

    def check(self):
        device_data.check(self.scope)
        if self.closed or not device_data.personal() or device_data.root() != self.root:
            raise PermissionError('本机员工工作已关闭或账户已变化。')

    def _notice_changed(self):
        with self.lock:
            self.notice_revision += 1

    def notice_context(self, chat):
        if is_workbench_id(chat):
            return {}, digest(self._workbench(chat))
        from runteams_core.storage import product_store
        session=product_store.get_chat(chat,include_messages=False)
        if (not product_store.device_chat(chat) or not session or
                session['kind']!='general' or session['subject_type']!='employee'):
            raise PermissionError('请打开本机员工工作对话。')
        return session, None

    def observe(self, chat):
        """A change hint only: never packages, arguments, consent or execution.

        The following full state read and every tool keep their original complete
        verification. No asset, enabled state or authorization is cached here.
        """
        self.check()
        # Cache ONLY a change hint, never enabled state, packages, permissions
        # or consent. Any database/WAL replacement or write invalidates it.
        # Full reads, mounts and tools still perform complete verification.
        import stat
        stamps=[]
        for name in ('personal.sqlite3','personal.sqlite3-wal','work/runteams.db','work/runteams.db-wal'):
            path=self.root/name
            if any(parent.is_symlink() for parent in (path,*path.parents)):
                raise PermissionError('本机资料路径已变化。')
            try:
                info=path.stat()
                if not stat.S_ISREG(info.st_mode):raise PermissionError('本机资料路径无效。')
                stamps.append((name,info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns))
            except FileNotFoundError:stamps.append((name,None))
        from runteams_core.storage.repository import current_audit_context
        actor=current_audit_context().get('actor_id')
        if actor and str(actor)!=principal(self.scope):raise PermissionError('账户已变化。')
        with self.lock:
            cached=self.observation_cache.get(chat)
            if cached is None or cached[0]!=stamps:
                session,external=self.notice_context(chat)
                marker=(self._work_id(chat),external,session.get('runtime_generation'),session.get('employee_release_digest'))
                if len(self.observation_cache)>=64:self.observation_cache.clear()
                self.observation_cache[chat]=(stamps,marker)
            else:marker=cached[1]
            pending=any(row['chat']==chat and not row['done'].is_set() for row in self.pending.values())
            live=[(package,client.closed,client.process.poll() if client.process else None)
                  for (cid,package),client in self.sessions.items() if cid==chat]
            version=digest([self.notice_epoch,self.notice_revision,marker,live])
        self.check()
        return {'schema':'runteams.mcp-observation/1','chat_id':chat,
                'owner':'pipeline' if self.trust_namespace=='pipeline-mcp' else 'employee',
                'version':version,'pending':pending}

    def _write(self, path, value):
        self.check()
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('工作授权记录路径无效。')
        employee_workspaces._directory(path.parent)
        if path.is_symlink(): raise ValueError('工作授权记录无效。')
        with device_data.connect():
            self.check()
            _publish(self.root, path, json.dumps(value, ensure_ascii=False, sort_keys=True).encode())
        self._notice_changed()

    def _session(self, chat):
        from runteams_core.storage import product_store as store
        self.check()
        session = store.get_chat(chat,include_messages=False)
        if (not session or not store.device_chat(chat) or session.get('kind') != 'general'
                or session.get('subject_type') != 'employee' or not (session.get('employee_id') or session.get('context',{}).get('local_employee_package'))):
            raise PermissionError('请打开本机员工工作对话。')
        return session

    def _work_record(self, chat, work):
        path = work / '.runteams' / FILE
        if path.exists() or path.is_symlink():
            value = _read(path)
            if (set(value) != {'scope','chat_identity','employee'} or value['scope'] != work_scope(self.scope)
                    or value['chat_identity'] != self._work_id(chat)):
                raise PermissionError('本机员工工作引用已变化。')
            return value
        if ((work/'.runteams/mcp-runtime-state.json').exists() or (work/'.runteams/mcp-calls').exists()):
            raise ContractError('程序的原工作引用缺失，请保留文件并核对。')
        return None

    def load(self, chat, *, pin=False):
        if is_workbench_id(chat):
            item, work = self._workbench_subject(chat)
            packages = inspect_attachments(item)
            record = self._work_record(chat,work)
            if record is not None and record['employee']['active_release']['digest'] != item['active_release']['digest']:
                raise ContractError('工作台运行版本已变化，请重新打开。')
            if pin and packages and record is None:
                self._write(work/'.runteams'/FILE, {'scope':work_scope(self.scope),
                            'chat_identity':self._work_id(chat),'employee':item})
            return item, packages, work
        from runteams_core.storage import product_store as store
        session = self._session(chat)
        work = employee_workspaces.workspace(chat)
        path = work / '.runteams' / FILE
        value = self._work_record(chat, work)
        known = value is not None
        local_package = session.get('context',{}).get('local_employee_package')
        if local_package:
            from runteams_core.employees.source_employee_runtime import employee as from_package
            employee = from_package(local_package)
            if known and value['employee'] != employee:raise ContractError('原员工运行包已变化。')
            packages = inspect_attachments(employee)
        else:
            from runteams_core.employees.employee_context import current
            owner = current()
            employee = value['employee'] if known else owner.work_employee(session)
            owner.verify_work_employee(employee,session)
            packages = bundles(employee)
        if not packages and not known:return employee,packages,work
        if not packages:raise ContractError('本机员工程序引用缺失。')
        release = employee['active_release']
        if not employee.get('local_package') and (release['id'] != session['employee_release_id'] or release['digest'] != session['employee_release_digest']):
            raise ContractError('员工工作版本已变化，请重新核对。')
        if pin and packages and not path.exists():
            self._write(path, {'scope':work_scope(self.scope), 'chat_identity':device_data.epoch(chat), 'employee':employee})
            # Establish new MCP work without inheriting a legacy all-access thread.
            store.set_chat_runtime(chat,'','')
        self.check()
        return employee, packages, work

    def _identity(self, chat):
        inspection = getattr(self._inspection,'work',None)
        if inspection is not None and inspection[0] == chat:
            self.check()
            return inspection[1]
        employee, packages, work = self.load(chat)
        release = employee['active_release']['digest']
        binding = WorkBinding(self.scope['cache_scope'], str(employee['id']), release, self._work_id(chat))
        return employee, packages, work, binding

    @contextmanager
    def inspect_work(self, chat):
        """Share package verification only within this synchronous host operation."""
        identity = self._identity(chat)
        previous = getattr(self._inspection,'work',None)
        self._inspection.work = (chat,identity)
        try:
            yield identity
        finally:
            self._inspection.work = previous

    def _trust_path(self, binding, package):
        # Host credentials are intentionally absent from portable work backups.
        key = digest({'binding':self._trust_binding(binding), 'package':package})
        from runteams_core.storage import local_database
        path=Path(local_database.DB_PATH).resolve().parent / 'host-credentials' / self.trust_namespace / self.scope['cache_scope'] / (key+'.json')
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('本机授权路径无效。')
        return path

    @staticmethod
    def _trust_binding(binding):
        return {k:v for k,v in binding.__dict__.items() if k!='work_id'}

    def enabled(self, binding, package):
        self.check()
        path = self._trust_path(binding, package)
        if not path.exists() and not path.is_symlink(): return False
        return _read(path) == {'binding':self._trust_binding(binding), 'package':package, 'enabled':True}

    def has_pending_approval(self, chat):
        self.check()
        with self.lock:
            return any(row['chat'] == chat and not row['done'].is_set() for row in self.pending.values())

    @staticmethod
    def _authorization_digest(chat, binding, packages):
        if is_workbench_id(chat):
            return digest({'binding': binding.__dict__, 'packages': sorted(packages)})
        return digest(binding.__dict__)

    def state(self, chat):
        notification_version=self.observe(chat)['version']
        with self.inspect_work(chat) as (employee, packages, work, binding):
            services = self.connection_services(chat,employee,packages)
        with self.lock:
            self.check()
            approvals = [copy.deepcopy(row['public']) for row in self.pending.values()
                         if row['chat'] == chat and not row['done'].is_set()]
        journal = work / '.runteams' / 'mcp-calls'
        calls = [_read(p) for p in sorted(journal.glob('*.json'))] if journal.exists() else []
        # Full arguments/results remain device diagnostics, not the settings page.
        return {'schema':'runteams.employee-mcp-work/1', 'chat_id':chat, 'binding_sha256':self._authorization_digest(chat,binding,packages),
            'available':bool(packages), 'enabled':bool(packages) and all(self.enabled(binding,p) for p in packages),
            'running':any(cid==chat and s.process is not None and s.process.poll() is None for (cid,_),s in self.sessions.items()),
            'suspended':self.suspended(work),
            'runtime_available':self.runtime is not None,
            'notification_version':notification_version,
            'connection_services':services,
            'subject':employee.get('name') or employee.get('asset',{}).get('pipeline',{}).get('name',''),
            'packages':[{'name':p.manifest.get('display_name') or p.manifest['name'], 'version':p.manifest['version'],'credential_keys':list(p.credential_names())}
                        for p in packages.values()], 'approvals':approvals,
            'calls':[{'id':r['id'],'tool':r['tool'],'state':'unknown' if r['state']=='pending' else r['state']}
                     for r in calls]}

    def connection_services(self,chat,employee,packages):
        ref=employee.get('reference') or (employee.get('local_package') or {}).get('reference',{})
        if not self.scope.get('library_id') or ref.get('schema') not in ('runteams.local-employee-reference/1','runteams.local-pipeline-reference/1'):return []
        from runteams_core.work.work_connections import WorkConnections
        from runteams_core.configuration.configuration_schema import data_fields
        if employee.get('local_package'):
            from runteams_core.employees.source_employee_runtime import package_asset
            definition=package_asset(employee['local_package'])['employee'].get('configuration',{})
        else:definition=employee.get('asset',{}).get('configuration',{})
        fields = data_fields(definition) if definition else ()
        connections={f['binding']['key']:f for f in fields if f.get('binding',{}).get('provider')=='sdk_connection'}
        if not connections:return []
        required={key for key,field in connections.items() if field.get('required')}
        provider=WorkConnections(self);result=[]
        for package in packages:
            state=provider.state(chat,package)
            state['connections']=[{**row,'required':row['key'] in required} for row in state['connections']]
            if state['connections']:result.append({**state,'program_name':packages[package].manifest.get('display_name') or packages[package].manifest['name']})
        return result

    def enable(self, chat, expected, confirmed):
        with self.lock:
            self.check()
            employee, packages, work, binding = self._identity(chat)
            if expected != self._authorization_digest(chat,binding,packages) or confirmed is not True or not packages:
                raise PermissionError('请核对当前版本并确认运行授权。')
            if self.runtime is None: raise ValueError('本机运行资源尚未随应用提供。')
            self.runtime.verify()
            self.load(chat, pin=True)
            for package in packages:
                self._write(self._trust_path(binding,package), {'binding':self._trust_binding(binding), 'package':package,'enabled':True})
            self.resume(chat,expected)
        return self.state(chat)

    def disable(self, chat, expected):
        with self.lock:
            _, packages, _, binding = self._identity(chat)
            if expected != self._authorization_digest(chat,binding,packages): raise PermissionError('员工版本已变化。')
            for package in packages:
                self._write(self._trust_path(binding,package), {'binding':self._trust_binding(binding), 'package':package,'enabled':False})
            chats={cid for (cid,_),session in self.sessions.items() if self._trust_binding(session.binding)==self._trust_binding(binding)}|{chat}
        for cid in chats:self.close_work(cid)
        return self.state(chat)

    def authorize_runtime(self, chat, *, cancel=None, notify=None):
        """Ask at first use, bound to the exact work/version, before author code."""
        _, packages, _, binding = self._identity(chat)
        if not packages or all(self.enabled(binding, p) for p in packages):
            return
        self._approval(chat, 'runteams/work-authorization', {}, trust=True,
                       cancel=cancel, notify=notify)
        _, current, _, actual = self._identity(chat)
        if actual != binding or current.keys() != packages.keys() or not all(self.enabled(actual,p) for p in current):
            raise PermissionError('本次工作尚未获得运行授权。')

    def ask(self, chat, method, params, *, cancel=None, timeout=180, notify=None):
        return self._approval(chat, method, params, cancel=cancel, timeout=timeout, notify=notify)

    def _approval(self, chat, method, params, *, trust=False, cancel=None, timeout=180, notify=None):
        from runteams_core.agents.language_policy import system_text
        policy = getattr(cancel, 'language_policy', None)
        self.check()
        _, packages, _, binding = self._identity(chat)
        if not packages or not trust and not all(self.enabled(binding,p) for p in packages):
            raise PermissionError(system_text('authorization_required', policy))
        key = uuid.uuid4().hex
        public = {'id':key, 'method':method, 'params':copy.deepcopy(params)}
        try:
            if not trust:approval_response(method,params,'accept')
            public['can_accept']=True
        except ValueError:public['can_accept']=False
        row = {'chat':chat,'binding':binding,'authorization':self._authorization_digest(chat,binding,packages),'done':threading.Event(),'public':public,'decision':None,'trust':trust}
        with self.lock: self.check(); self.pending[key] = row; self._notice_changed()
        if notify is not None:notify()
        end = time.monotonic()+timeout
        try:
            while not row['done'].wait(.1):
                self.check()
                if cancel is not None and cancel.is_set(): raise PermissionError(system_text('approval_stopped', policy))
                if time.monotonic() >= end: raise TimeoutError(system_text('approval_expired', policy))
            self.check()
            if not all(self.enabled(binding,p) for p in packages): raise PermissionError(system_text('authorization_revoked', policy))
            return {'accepted': row['decision']=='accept'} if trust else approval_response(method,params,row['decision'])
        finally:
            with self.lock: self.pending.pop(key,None); self._notice_changed()

    def answer(self, chat, expected, key, decision):
        with self.lock:
            _, packages, _, binding = self._identity(chat)
            row = self.pending.get(key)
            if (expected != self._authorization_digest(chat,binding,packages) or row is None or row['chat'] != chat
                    or row['binding'] != binding or row['authorization'] != expected or decision not in ('accept','decline','cancel')):
                raise PermissionError('本次确认已失效，请核对当前工作。')
            if row['done'].is_set() and row['decision'] != decision: raise ValueError('本次确认已经处理。')
            if row.get('trust') and decision == 'accept' and not row['done'].is_set():
                self.enable(chat, expected, True)
            row['decision'] = decision; row['done'].set(); self._notice_changed()
        return {'answered':True}

    def check_operation(self, chat):
        if is_workbench_id(chat):
            self._workbench(chat)
            return
        from runteams_core.pipelines.source_pipeline_control import check_chat_operation
        check_chat_operation(chat)

    def tool_scope(self, chat, package, binding):
        return nullcontext()

    def program_environment(self, chat, package, binding, work):
        from runteams_core.work.work_connection_calls import environment
        from runteams_core.pipelines.pipeline_task_configuration import credential_scopes
        @contextmanager
        def bound():
            with environment(self,chat,package,binding) as values:
                _,packages,_,actual=self._identity(chat)
                if actual!=binding or package not in packages:raise PermissionError('程序工作身份已变化。')
                scopes=credential_scopes(chat,packages[package].credential_names())
                yield {**values,'RUNTEAMS_TASK_CREDENTIAL_SCOPES':json.dumps(scopes)}
        return bound

    def credential_configuration(self, chat, binding):
        if is_workbench_id(chat):
            from runteams_core.configuration.employee_configuration import for_package
            config = for_package(self._workbench(chat))
            return config.definition, config.snapshot()
        from runteams_core.storage import product_store
        from runteams_core.configuration.employee_configuration import for_chat, admission
        session=product_store.get_chat(chat,include_messages=False)
        config=for_chat(chat)
        snapshot=admission(session)
        if snapshot is None:raise PermissionError('本次工作没有已确认的凭据配置。')
        return config.definition,snapshot

    def program_credentials(self, chat, package, binding):
        from runteams_core.pipelines.pipeline_task_configuration import credential_lease
        @contextmanager
        def bound(actual,package_digest,required):
            if actual!=binding or package_digest!=package:raise PermissionError('程序凭据的工作身份已变化。')
            def check():
                self.check_operation(chat)
                _,packages,_,current=self._identity(chat)
                if current!=binding or package not in packages or not self.enabled(binding,package):raise PermissionError('原本机程序已停用。')
            check()
            from runteams_core.configuration.employee_configuration import ConfigurationInvalid
            def shared():
                try:return self.credential_configuration(chat,binding)
                except ConfigurationInvalid:raise PermissionError('请先核对本次工作的凭据配置。') from None
            with credential_lease(chat,required,check,shared) as values:yield values
        return bound

    def session(self, chat, package):
        self.check_operation(chat)
        with self.lock:
            _, packages, work, binding = self._identity(chat)
            if package not in packages or not self.enabled(binding,package): raise PermissionError('请先确认本次工作的运行授权。')
            if self.suspended(work):raise PermissionError('本次运行已关闭，请明确继续运行。')
            key = (chat,package)
            session = self.sessions.get(key)
            if session is not None and session.binding != binding:
                session.close(); session = None
            if session is not None and session.closed:
                # A failed OS stop remains revoked and must be reaped before
                # another process may take ownership of this work.
                session.close(); session = None
            if session is None:
                if self.runtime is None: raise ValueError('本机运行资源尚未提供。')
                self.load(chat,pin=True)
                bundle = packages[package]
                root = bundle.materialize(self.root / 'employee-mcp-packages')
                def authorize(current, package_digest, action, detail):
                    try:self.check_operation(chat)
                    except PermissionError:return False
                    _, current_packages, _, active = self._identity(chat)
                    if current != active or package_digest not in current_packages or not self.enabled(current,package_digest): return False
                    if action == 'tool' and detail['source'] == 'app':
                        return _app_grant.get()==(current,package_digest,detail['name'],digest(detail['arguments']))
                    return True
                session = EmployeeMCP(runtime=self.runtime,bundle=bundle,package_root=root,
                    work_root=work,binding=binding,authorize=authorize,
                    environment_scope=self.program_environment(chat,package,binding,work),
                    credential_scope=self.program_credentials(chat,package,binding),
                    invocation_scope=lambda:self.connection_invocation(chat,package,binding))
                self.sessions[key] = session
            return session

    @contextmanager
    def connection_invocation(self,chat,package,binding):
        # Entered only after original tool identity/visibility/consent checks.
        key=(chat,package,binding)
        with self.lock:parent=self.connection_requests.get(key)
        if parent is None:yield;return
        with self.lock:self.connection_calls[key]=(parent,_read_only_app.get())
        try:yield
        finally:
            with self.lock:self.connection_calls.pop(key,None)

    def call(self, chat, package, name, arguments, key, *, source='agent', expected_session=None):
        self.check_operation(chat)
        employee, packages, work, binding = self._identity(chat)
        if package not in packages or not self.enabled(binding,package):raise PermissionError('本次工作尚未获得运行授权。')
        request = {'package':package,'tool':name,'arguments':arguments}
        path = work / '.runteams/mcp-calls' / (digest({'key':key})+'.json')
        with self.lock:
            if path.exists():
                previous=_read(path)
                if previous['request']!=request:raise ValueError('调用编号内容已变化。')
                if previous['state']=='completed':return previous['result']
                if previous['state']=='rejected':raise PermissionError('原操作未获授权。')
                raise MCPOutcomeUnknown('mcp_call_outcome_unknown')
        read_only = False
        if source=='app':
            tool = next((tool for tool in expected_session.tool_catalog() if tool['name']==name),None) if expected_session else None
            read_only = (bool(tool and tool.get('_meta',{}).get('runteams/employeeSdkReadOnly') is True
                              and tool.get('annotations',{}).get('readOnlyHint') is True)
                         and not packages[package].credential_names()
                         and self.sdk_configuration(chat, binding, employee) is not None)
        if source=='app' and not read_only:
            reply=self.ask(chat,'runteams/app-call',{'name':name,'arguments':arguments},timeout=45)
            if not reply['accepted']:raise PermissionError('本次操作未获授权。')
        with self.lock:
            self.check()
            if expected_session is not None and (expected_session.closed or self.sessions.get((chat,package)) is not expected_session):
                raise PermissionError('原工作程序已关闭，请重新打开工作界面。')
            if path.exists():
                previous = _read(path)
                if previous['request'] != request: raise ValueError('调用编号内容已变化。')
                if previous['state'] == 'completed': return previous['result']
                raise MCPOutcomeUnknown('mcp_call_outcome_unknown')
            # Reconnecting an official Runtime must not resend an unresolved
            # identical operation under a new transport request number.
            for prior in path.parent.glob('*.json'):
                old = _read(prior)
                if old['request'] == request and old['state'] in ('pending','unknown'):
                    raise MCPOutcomeUnknown('mcp_call_outcome_unknown')
            session = self.session(chat,package)
            row = {'id':path.stem,'binding':binding.__dict__,'request':request,'tool':name,'state':'pending'}
            self._write(path,row)
        returned=False
        try:
            grant=_app_grant.set((binding,package,name,digest(arguments)) if source=='app' else None)
            mode=_read_only_app.set(read_only)
            try:
                with session.lock:
                    if session.tools is None:session.list_tools()
                    with self.tool_scope(chat,package,binding):
                        with self.lock:self.connection_requests[(chat,package,binding)]=path.stem
                        try:result = session.call_tool(name,arguments,source=source)
                        finally:
                            with self.lock:self.connection_requests.pop((chat,package,binding),None)
            finally:
                _read_only_app.reset(mode)
                _app_grant.reset(grant)
            returned=True
            self._write(path,{**row,'state':'completed','result':result})
            return result
        except BaseException as error:
            # A denial before dispatch is conservative here; no guessed failure
            # is used to authorize retry after a lost process or acknowledgement.
            try: self._write(path,{**row,'state':'rejected' if isinstance(error,PermissionError) and not returned else 'unknown'})
            except Exception: pass
            if returned:raise MCPOutcomeUnknown('mcp_call_outcome_unknown') from error
            raise

    @contextmanager
    def runtime_scope(self, chat, *, cancel=None, notify=None):
        """Expose the same work-owned clients to the complete official Runtime."""
        from runteams_core.foundation.transport.loopback_rpc import serve_rpc
        from contextlib import ExitStack
        _, packages, _, binding = self._identity(chat)
        if not packages: yield {}; return
        self.authorize_runtime(chat, cancel=cancel, notify=notify)
        if self._identity(chat)[3] != binding:raise PermissionError('工作版本已变化，请重新开始。')
        self.resume(chat,self._authorization_digest(chat,binding,packages))
        node, worker = self.runtime.verify()
        with ExitStack() as stack:
            with self.lock:
                if chat in self.turns:raise ValueError('这次工作已有运行中的对话。')
                self.turns[chat]=cancel
            def retire_turn():
                with self.lock:
                    self.turns.pop(chat,None)
                    if cancel is not None and cancel.is_set() or not self.views.get(chat):self.close_work(chat)
            stack.callback(retire_turn)
            config = {}
            for package in packages:
                # A new proxy's namespace never makes an old unknown call retryable.
                transport = uuid.uuid4().hex
                def dispatch(message, package=package, transport=transport):
                    self.check()
                    try:
                        if cancel is not None and cancel.is_set():raise PermissionError('原官方运行已停止。')
                        method, params = message['method'], message.get('params') or {}
                        session = self.session(chat,package)
                        if method == 'tools/list': value = {'tools':session.list_tools()}
                        elif method == 'tools/call': value = self.call(chat,package,params['name'],params.get('arguments',{}),transport+':'+str(message['id']))
                        else: raise PermissionError('员工工具请求无效。')
                        return {'jsonrpc':'2.0','id':message['id'],'result':value}
                    except Exception:
                        return {'jsonrpc':'2.0','id':message.get('id'),'error':{'code':-32000,'message':'Employee tool unavailable or outcome unknown; do not retry an effect.'}}
                endpoint, token = stack.enter_context(serve_rpc(dispatch))
                config['runteams_employee_'+package[:16]] = {'command':str(node),'args':[str(worker),'--employee-proxy',endpoint],
                    'env':{'RUNTEAMS_EMPLOYEE_PROXY':token},'startup_timeout_sec':20,'tool_timeout_sec':70,
                    'default_tools_approval_mode':'approve','required':True}
            yield {'mcp_servers':config,'on_approval':lambda method,params:self.ask(chat,method,params,cancel=cancel,notify=notify)}

    def recognizes(self, chat, workspace='', *, owns_empty=None):
        from runteams_core.storage import product_store as store
        if workspace or not device_data.personal() or not store.device_chat(chat): return False
        session=store.get_chat(chat,include_messages=False)
        if not session or session.get('subject_type')!='employee' or session.get('kind')!='general': return False
        employee, packages, _ = self.load(chat)
        return (bool(packages) or bool(session.get('context',{}).get('local_employee_package'))
                or (owns_empty is not None and owns_empty(employee)))

    def sdk_configuration(self, chat, binding, employee):
        if not isinstance(binding, WorkBinding):
            return None
        package = employee.get('local_package')
        if package:
            from runteams_core.configuration.employee_configuration import for_package
            return for_package(package)
        if employee.get('market_delivery') or employee.get('sdk_asset'):
            from runteams_core.employees.employee_context import current
            context = current()
            acquired = context.acquired_binding(self._session(chat))
            pinned = acquired['employee']
            if (pinned['active_release']['digest'] == binding.release_digest
                    and pinned.get('sdk_asset') == employee.get('sdk_asset')):
                return context.acquired_configuration(chat, acquired)
        return None

    def app_tools(self, chat, package, binding):
        return []

    def app_authority(self, chat, package, binding, session):
        return session.authority()

    def app_call(self, chat, package, binding, name, arguments, key, session):
        return self.call(chat,package,name,arguments,key,source='app',expected_session=session)

    def discover_for_chat(self, chat_id):
        items=[]
        with self.inspect_work(chat_id) as (_,packages,work,binding):
            if not self.suspended(work):
                for package in packages:
                    if not self.enabled(binding,package):continue
                    tools=self.session(chat_id,package).list_tools()
                    views = []
                    for tool in tools:
                        meta = tool.get('_meta', {})
                        ui = meta.get('ui', {})
                        if not ui.get('resourceUri') or 'app' not in ui.get('visibility', ['model', 'app']):
                            continue
                        view = {'id': digest({'tool': tool['name']}), 'title': tool.get('title') or tool['name'],
                                'capabilities': ['mcp.tools.call']}
                        views.append(view)
                    if views:items.append({'installation_id':str(uuid.uuid5(uuid.NAMESPACE_URL,digest(binding.__dict__)+package)),
                        'release_digest':binding.release_digest,'views':views})
        return {'items':items,'authority':'device-owned-mcp-work','chat_id':chat_id}

    def native_owner(self):
        with self.lock:
            self.check()
            if not hasattr(self,'owner'):self.owner=_MCPOwner(self)
            return self.owner

    @staticmethod
    def suspended(work):
        path=work/'.runteams/mcp-runtime-state.json'
        if not path.exists() and not path.is_symlink():return False
        value=_read(path)
        if not isinstance(value,dict) or set(value)!={'suspended'} or type(value['suspended']) is not bool:
            raise ValueError('本机运行状态记录无效。')
        return value['suspended']

    def resume(self,chat,expected):
        _,packages,work,binding=self._identity(chat)
        if expected!=self._authorization_digest(chat,binding,packages) or not all(self.enabled(binding,p) for p in packages):
            raise PermissionError('请核对当前员工版本与启用状态。')
        # A fresh work can inherit this version's explicit program trust.
        # Pin its validated owner before writing the first runtime marker.
        if not (work/'.runteams'/FILE).exists():self.load(chat,pin=True)
        self._write(work/'.runteams/mcp-runtime-state.json',{'suspended':False})

    def close_directories(self, chat):
        # Stopping a pinned owned program needs its original identity, not a
        # fresh rental/execution grant. This path never loads or starts code.
        if is_workbench_id(chat):
            work = self._workbench_directory(chat)
            return [work] if self._work_record(chat,work) is not None else []
        session = self._session(chat)
        work = employee_workspaces.workspace(chat)
        record = self._work_record(chat, work)
        if record is None:return []
        employee = record['employee']
        package = session.get('context',{}).get('local_employee_package')
        if package is not None:
            from runteams_core.employees.employee_references import checked_reference
            checked_reference(package['reference'])
            if (employee.get('local_package') != package
                    or employee.get('active_release',{}).get('digest') != digest(package)):
                raise ContractError('原员工运行包已变化。')
        else:
            from runteams_core.employees.employee_context import current
            current().verify_work_employee(employee,session)
        self.check()
        return [work]

    def retain_view(self, chat):
        with self.lock:self.views[chat] = self.views.get(chat, 0) + 1

    def release_view(self, chat):
        with self.lock:
            self.views[chat] = max(0, self.views.get(chat, 0) - 1)
            if not self.views[chat] and chat not in self.turns:self.close_work(chat)

    def close_work(self, chat):
        error=None
        if not self.closed:
            try:
                for work in self.close_directories(chat):
                    self._write(work/'.runteams/mcp-runtime-state.json',{'suspended':True})
            except Exception as failure:error=failure
        with self.lock:
            cancel=self.turns.get(chat)
            if cancel is not None:cancel.set()
            sessions = [s for (cid,_),s in self.sessions.items() if cid == chat]
            for row in self.pending.values():
                if row['chat'] == chat: row['decision']='cancel'; row['done'].set()
        for session in sessions: session.close()
        if error is not None:raise error

    def close(self):
        with self.lock:
            self.closed = True
            for cancel in self.turns.values():
                if cancel is not None:cancel.set()
            for row in self.pending.values(): row['decision']='cancel'; row['done'].set()
            sessions = list(self.sessions.values())
        for session in sessions: session.close()
        owner=getattr(self,'owner',None)
        if owner is not None:owner.close()


def approval_response(method, params, decision):
    if method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):
        return {'decision':'accept' if decision=='accept' else 'decline' if decision=='decline' else 'cancel'}
    if method == 'mcpServer/elicitation/request':
        # This segment supports confirmation forms, not invented form values or
        # external URL completion. Unsupported requests remain explicitly denied.
        schema = params.get('requestedSchema') or params.get('request',{}).get('requestedSchema') or {}
        if decision == 'accept' and (schema.get('properties') or params.get('mode') == 'url'):
            raise ValueError('此确认需要的表单尚未接通。')
        return {'action':decision,'content':{} if decision=='accept' else None}
    if method in ('item/tool/requestUserInput','tool/requestUserInput'):
        answers = {}
        for question in params.get('questions',[]):
            options = question.get('options') or []
            wanted = {'accept':('accept','approve'),'decline':('decline','deny'),'cancel':('cancel',)}[decision]
            label = next((o['label'] for o in options if o.get('label','').lower() in wanted),None)
            if label is None: raise ValueError('此问题需要的选项尚未接通。')
            answers[question['id']] = {'answers':[label]}
        return {'answers':answers}
    if method == 'runteams/app-call': return {'accepted':decision=='accept'}
    raise ValueError('此官方交互尚未接通，操作未获授权。')


def for_employee(server,chat,workspace='',*,owns_empty=None):
    """Leave all unrelated personal, cloud and organization owners untouched."""
    from runteams_core.storage import product_store as store
    if workspace or not device_data.personal():return None
    try:device_data.identity()
    except PermissionError:return None
    if is_workbench_id(chat):
        host=server.employee_mcp_work()
        host._workbench(chat)
        return host
    if not store.device_chat(chat):return None
    session=store.get_chat(chat,include_messages=False)
    if not session or session.get('kind')!='general' or session.get('subject_type')!='employee':return None
    factory=getattr(server,'employee_mcp_work',None)
    if factory is None:return None
    host=factory()
    return host if host.recognizes(chat,workspace,owns_empty=owns_empty) else None


from runteams_core.work.hosts.native_work_owner import NativeWorkOwner


class _MCPOwner(NativeWorkOwner):
    """The existing native owner/router opens the employee's MCP Apps."""
    def __init__(self, host):self.host=host;self._initialize()

    def _call(self, workspace, action):
        from runteams_core.conversations.workspace_context import use
        if workspace:raise PermissionError('本机员工工作不属于组织执行。')
        with self.host.operation_scope(),use(''):
            self.host.check();value=action();self.host.check();return value

    def discover(self, chat_id, workspace=''):
        return self._call(workspace,lambda:self.host.discover_for_chat(chat_id))

    def _close_work(self,chat):
        if self.host.closed:return self.host.close_work(chat)
        return self._call('',lambda:self.host.release_view(chat))

    def _bridge(self, installation, chat, payload):
        with self.host.inspect_work(chat) as (_,packages,_,binding):
            return self._open_view(installation,chat,payload,packages,binding)

    def _open_view(self, installation, chat, payload, packages, binding):
        from runteams_core.employees.mcp.employee_mcp_native import EmployeeMCPBridge
        for package in packages:
            if installation!=str(uuid.uuid5(uuid.NAMESPACE_URL,digest(binding.__dict__)+package)):continue
            session=self.host.session(chat,package)
            for tool in session.tool_catalog():
                if digest({'tool':tool['name']})!=payload['view']:continue
                bridge_key=uuid.uuid4().hex
                counter=iter(range(1,1000000))
                self.host.retain_view(chat)
                try:
                    return EmployeeMCPBridge(session,tool['name'],payload['input'],
                        invoke=lambda name,args:self._call('',lambda:self.host.app_call(chat,package,binding,name,args,bridge_key+':'+str(next(counter)),session)),
                        host_tools=self.host.app_tools(chat,package,binding),
                        authority=lambda:self._call('',lambda:self.host.app_authority(chat,package,binding,session)),
                        close_session=False, on_close=lambda:self._close_work(chat))
                except MCPAppResourceInvalid as error:
                    # No bridge/origin was created; this is a definite view
                    # rejection, not an uncertain tool or transport outcome.
                    raise CreatorContractError('mcp_app_resource_invalid') from error
        raise PermissionError('当前员工界面已变化。')
