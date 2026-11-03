"""Pipeline-owned adapter over the existing MCP lifetime, approvals and journal.

The owner is the pipeline's own immutable workspace conversation. No employee
identity, employee private directory, execution engine or work ledger is made.
"""
from . import pipeline_references, rented_references
from . import pipeline_chat_binding
import base64
import copy
from contextlib import contextmanager,nullcontext

from . import device_data, source_pipeline_control as control, source_pipeline_work as work
from .creator_contracts import digest, strict_json
from .contracts import ContractError
from .device_employee_mcp import EmployeeMCPWork, FILE
from .employee_workspaces import _directory
from .device_files import _read
from .employee_mcp import PipelineWorkBinding
from .employee_mcp_package import MCPBundle




def _applied_catalog(ref, bundle):
    """Use the complete verified build already shared by every applied role."""
    from .source_employee_runtime import validate, source
    from .creator_local_build import LocalBuilds
    from .creator_definitions import CATALOG_PATH
    role = next(iter(bundle['roles'].values()))
    package = validate(role['package'])
    work.verify_context(role['context'], package, read_build=True)
    if role['context']['asset'] != bundle['asset'] or role['context'].get('source_revision', package['revision']) != bundle['revision']:
        raise ContractError('流水线自身程序与已应用岗位版本不一致。')
    if rented_references.is_rented(ref):
        from .pipeline_context import current
        return current().rented_applied_catalog(ref,bundle['revision'])
    if 'source_revision' in role['context']:
        return work.frozen_catalog(ref, bundle['revision'])
    store, _ = source(package['reference'])
    _, artifacts = LocalBuilds(store, ref['source_id']).artifacts(package['build_operation_key'])
    return strict_json(artifacts[CATALOG_PATH])


class PipelineMCPWork(EmployeeMCPWork):
    trust_namespace = 'pipeline-mcp'
    # Views share the pipeline-owned program; closing one page revokes that
    # bridge only. Explicit pause/disable/logout still closes the shared work.
    retain_app_session = True

    def __init__(self, runtime, core_factory, work_wake=None, *, operation_scope=nullcontext):
        super().__init__(runtime,operation_scope=operation_scope)
        self.core_factory = core_factory
        self.effects = {}
        self.work_requests = set()
        self.work_wake = work_wake

    def notice_context(self, chat):
        from runteams_core import product_store
        ref=pipeline_chat_binding.reference(chat)
        from .device_work import DeviceWorkStorage
        from .repository import current_audit_context
        actor=current_audit_context().get('actor_id')
        from .work_identity import principal
        if actor and str(actor)!=principal(self.scope):raise PermissionError('工作身份已变化。')
        # Opaque change hint only. Use the shared verified read-only connection;
        # no Core construction, write transaction, migration or program load.
        with DeviceWorkStorage().connect(readonly=True) as connection:
            event=connection.execute('SELECT max(id) FROM events WHERE stream=? AND type=?',
                (control.stream(ref),control.STATE_EVENT)).fetchone()[0]
        return product_store.get_chat(chat,include_messages=False), event

    def load(self, chat, *, pin=False):
        self.check()
        ref = pipeline_chat_binding.reference(chat)
        core = self.core_factory(); core._actor()
        saved = control.read(core, ref); bundle = saved['bundle']
        if bundle:
            catalog = _applied_catalog(ref, bundle)
            asset, revision, generation = bundle['asset'], bundle['revision'], bundle['generation']
            config = bundle.get('configuration')
        else:
            # Settings/discovery may inspect a draft, without building a role,
            # applying configuration, enabling code or creating business work.
            from .creator_source_import import validate_source
            from .creator_conversation_assets import compile_catalog
            revisions = work.source(ref)
            with revisions.locked():
                revision = revisions._head(); files = revisions._files(revision)
            catalog = compile_catalog(files, validate_source(files))
            asset = catalog['pipelines'][ref['pipeline_source']]
            generation, config = 0, None
        from .rented_references import is_rented
        attachments = (catalog['pipelines'][ref['pipeline_source']].get('program_bundles', [])
                       if bundle and is_rented(ref) else catalog.get('pipeline_programs', {}).get(ref['pipeline_source'], []))
        from .creator_mcp_source import verify_pipeline_programs
        verify_pipeline_programs(attachments)
        declared = {(row['key'], row['source']) for row in asset.get('programs', [])}
        if declared != {(row['key'], row['source']) for row in attachments}:
            raise ContractError('流水线自身程序附件不完整。')
        packages = {}
        for attachment in attachments:
            package = MCPBundle.inspect(base64.b64decode(attachment['content_base64'], validate=True))
            packages[package.digest] = package
        release = digest({'reference': ref, 'revision': revision, 'generation': generation,
                          'asset': asset, 'programs': attachments, 'configuration': config})
        base = self.root / 'pipeline-workspaces' / device_data.epoch(chat) / release
        if any(path.is_symlink() for path in (base, *base.parents)):
            raise ContractError('流水线程序工作目录无效。')
        _directory(base); _directory(base / '.runteams')
        own = {'reference': ref, 'revision': revision, 'generation': generation,
               'release_digest': release, 'asset': copy.deepcopy(asset), 'configuration': copy.deepcopy(config)}
        path = base / '.runteams' / FILE
        record = {'schema': 'runteams.pipeline-mcp-work/1', 'reference': ref,
                  'revision': revision, 'generation': generation, 'release_digest': release}
        known = path.exists() or path.is_symlink()
        if known:
            if _read(path) != record: raise ContractError('流水线程序原工作绑定已变化。')
        elif ((base/'.runteams/mcp-runtime-state.json').exists() or (base/'.runteams/mcp-calls').exists()):
            raise ContractError('流水线程序原工作引用缺失，请保留原记录并核对。')
        if pin:
            self.check_operation(chat)
            if not known:
                self._write(path, record)
                from runteams_core import product_store
                product_store.set_chat_runtime(chat, '', '')
        self.check()
        return own, packages, base

    def _identity(self, chat):
        own, packages, base = self.load(chat)
        binding = PipelineWorkBinding(self.scope['cache_scope'], digest(own['reference']),
                                      own['release_digest'], device_data.epoch(chat))
        return own, packages, base, binding

    def close_directories(self, chat):
        # A pause stops every pinned generation of this same conversation. It
        # cannot acquire code, renew a rental, apply a revision or enable code.
        self.check()
        ref = pipeline_chat_binding.reference(chat)
        self.core_factory()._actor()
        root = self.root / 'pipeline-workspaces' / device_data.epoch(chat)
        if any(path.is_symlink() for path in (root,*root.parents)):
            raise ContractError('流水线程序工作目录无效。')
        if not root.exists():return []
        from .creator_source_revisions import REV
        result=[]
        for base in sorted(root.iterdir()):
            if (not base.is_dir() or base.is_symlink() or len(base.name)!=64
                    or any(c not in '0123456789abcdef' for c in base.name)):
                raise ContractError('流水线程序工作目录无效。')
            if (base/'.runteams').is_symlink():
                raise ContractError('流水线程序工作目录无效。')
            path=base/'.runteams'/FILE
            if not path.exists() and not path.is_symlink():
                if ((base/'.runteams/mcp-runtime-state.json').exists() or (base/'.runteams/mcp-calls').exists()):
                    raise ContractError('流水线程序原工作引用缺失，请保留原记录并核对。')
                continue
            value=_read(path)
            if (set(value)!={'schema','reference','revision','generation','release_digest'}
                    or value['schema']!='runteams.pipeline-mcp-work/1' or value['reference']!=ref
                    or value['release_digest']!=base.name or type(value['generation']) is not int or value['generation']<0
                    or not isinstance(value['revision'],str)
                    or value['revision']!=ref['source_id'] and not REV.fullmatch(value['revision'])):
                raise ContractError('流水线程序原工作绑定已变化。')
            result.append(base)
        self.check()
        return result

    def state(self, chat):
        result = super().state(chat)
        ref = pipeline_chat_binding.reference(chat); saved = control.read(self.core_factory(), ref)
        result.update(schema='runteams.pipeline-mcp-work/1', reference=ref,
                      applied=saved['bundle'] is not None, pipeline_status=saved['status'])
        return result

    def check_operation(self, chat):
        self.check()
        ref = pipeline_chat_binding.reference(chat); saved = control.read(self.core_factory(), ref)
        if saved['status'] != 'running' or not saved['bundle']:
            raise PermissionError('请先暂停、应用流水线更新并启动，再运行自身程序。')
        self.configuration(chat)

    def enable(self, chat, expected, confirmed):
        self.check_operation(chat)
        self.configuration(chat)
        return super().enable(chat, expected, confirmed)

    def resume(self, chat, expected):
        self.check_operation(chat)
        return super().resume(chat, expected)

    def prepare_start(self, chat, expected):
        """Trusted pipeline control un-parks this exact enabled version only.

        No process starts here. Public resume still requires running; all tool
        calls and discovery remain fenced until the original start commits.
        """
        saved = control.read(self.core_factory(), pipeline_chat_binding.reference(chat))
        if (saved['status'] != 'paused' or not saved['bundle'] or
                saved['quiesced_revision'] != saved['revision']):
            raise PermissionError('流水线尚未确认暂停，不能准备启动自身程序。')
        self.configuration(chat)
        return super().resume(chat, expected)

    def recognizes(self, chat, workspace=''):
        if workspace: return False
        try: pipeline_chat_binding.reference(chat)
        except (PermissionError, ValueError): return False
        return True

    def configuration(self, chat, expected=None):
        own, _, _, binding = self._identity(chat)
        if expected is not None and binding != expected:
            raise PermissionError('流水线程序版本或配置已更新，请重新打开。')
        from .employee_configuration import _validate_snapshot, EMPTY
        from .source_pipeline_settings import OwnConfiguration
        snapshot = own['configuration']
        if snapshot is None:
            snapshot = OwnConfiguration(own['reference'], {'configuration':EMPTY}, own['revision']).snapshot()
        definition = own['asset'].get('configuration', EMPTY)
        snapshot = _validate_snapshot(definition, own['reference'], own['revision'], snapshot)
        from runteams_core import product_store
        from . import local_assets
        for selected in snapshot['bindings'].values():
            if 'grant_id' in selected:
                grant = product_store.get_local_asset_grant(selected['grant_id'])
                if local_assets.fingerprint(grant) != selected.get('fingerprint'):
                    raise PermissionError('流水线授权资料已变化，请重新核对配置。')
        return own, snapshot, binding

    def credential_configuration(self, chat, binding):
        from .employee_configuration import EMPTY
        own,snapshot,_=self.configuration(chat,binding)
        return own['asset'].get('configuration',EMPTY),snapshot

    @contextmanager
    def tool_scope(self, chat, package, binding):
        from .employee_configuration import EMPTY
        from .configuration_schema import managed_fields
        from .managed_employee_data import lease
        own, _, _ = self.configuration(chat, binding)
        managed = bool(managed_fields(own['asset'].get('configuration', EMPTY)))
        owner = {'chat_id': chat, 'program': package, 'binding': digest(binding.__dict__)}
        if managed and not lease(own['reference'], owner, 'claim')['ok']:
            raise PermissionError('流水线业务资料正在处理中，请稍后核对原操作。')
        key = (chat, package, binding)
        with self.lock: self.effects[key] = self.effects.get(key, 0) + 1
        try: yield
        finally:
            with self.lock:
                count = self.effects.get(key, 1) - 1
                if count: self.effects[key] = count
                else: self.effects.pop(key, None)
            if managed:
                try:
                    self.check()
                    lease(own['reference'], owner, 'release')
                except PermissionError:
                    # A departed account cannot mutate its previous workspace;
                    # the original bounded lease still expires normally.
                    pass

    def app_tools(self, chat, package, binding):
        from .pipeline_work_access import READ_TOOL, PROPOSE_TOOL, READ_SCHEMA, PROPOSE_SCHEMA
        return [{'name':READ_TOOL,'description':'Trusted read-only pipeline work progress and exact submitted reports',
                 'inputSchema':copy.deepcopy(READ_SCHEMA),'_meta':{'ui':{'visibility':['app']}}},
                {'name':PROPOSE_TOOL,'description':'Request original native confirmation then use unified work admission; retain operation_id for receipt recovery',
                 'inputSchema':copy.deepcopy(PROPOSE_SCHEMA),'_meta':{'ui':{'visibility':['app']}}}]

    def app_authority(self, chat, package, binding, session):
        self.check()
        _,packages,base,actual=self._identity(chat)
        saved=control.read(self.core_factory(),pipeline_chat_binding.reference(chat))
        if (actual!=binding or package not in packages or not self.enabled(binding,package) or
                self.suspended(base) and saved['status']!='paused'):
            raise PermissionError('原流水线界面或授权已变化。')
        # The trusted work projection remains readable while paused. Author
        # tools still use check_operation and cannot execute or resume here.
        return {'authorized':True,'context_revision':0}

    def app_call(self, chat, package, binding, name, arguments, key, session):
        from .pipeline_work_access import READ_TOOL, PROPOSE_TOOL, read, proposal, committed, dispatch_app
        if name not in (READ_TOOL,PROPOSE_TOOL):
            # The same mounted page may survive a pipeline pause. A new,
            # explicitly started process must still match that exact binding;
            # user-stopped programs and changed releases cannot inherit it.
            self.app_authority(chat,package,binding,session)
            if session.closed:session=self.session(chat,package)
            return super().app_call(chat,package,binding,name,arguments,key,session)
        self.app_authority(chat,package,binding,session)
        core=self.core_factory()
        if name==READ_TOOL:
            from .work_identity import principal
            value=read(core,chat,arguments,actor_id=principal(self.scope))
        else:
            value=committed(core,chat,arguments)
            if value is None:
                if session.closed:session=self.session(chat,package)
                intent=(chat,arguments['operation_id'])
                with self.lock:
                    if intent in self.work_requests:raise ContractError('这项交办正在核对，请保留原编号读取回执。')
                    self.work_requests.add(intent)
                try:
                    prepared=proposal(core,chat,arguments,composer=False)
                    reply=self.ask(chat,'runteams/app-call',{'name':PROPOSE_TOOL,'arguments':arguments},timeout=45)
                    if not reply['accepted']:raise PermissionError('本次交办未获确认。')
                    def guard():
                        self.app_authority(chat,package,binding,session)
                        self.check_operation(chat)
                        if session.closed or self.sessions.get((chat,package)) is not session:
                            raise PermissionError('原流水线程序已关闭，请核对原交办。')
                    def notify():
                        self.check()
                        if self.work_wake is not None:self.work_wake()
                    value=dispatch_app(core,chat,prepared['actions'][0],guard,notify=notify)
                finally:
                    with self.lock:self.work_requests.discard(intent)
        self.check()
        return {'content':[{'type':'text','text':__import__('json').dumps(value,ensure_ascii=False)}],
                'structuredContent':value}

    def program_environment(self, chat, package, binding, base):
        @contextmanager
        def environment():
            from .loopback_rpc import serve_rpc
            from .employee_configuration import _materialize
            own, snapshot, _ = self.configuration(chat, binding)
            mounted = _materialize(snapshot, base)
            for resource in mounted['resources'].values():
                if resource.get('provider') == 'local_collection':
                    resource['tool'] = 'data/call'

            def dispatch(message):
                # Holding the original control transaction across data access
                # prevents a write from crossing a committed pause/update.
                core = self.core_factory()
                with core.repository.connect() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    self.check_operation(chat)
                    current, packages, _, actual = self._identity(chat)
                    if (actual != binding or package not in packages or not self.enabled(binding, package)
                            or self.suspended(base)):
                        raise PermissionError('本流水线程序授权已失效。')
                    self.configuration(chat, binding)
                    if not isinstance(message, dict) or set(message) != {'jsonrpc', 'id', 'method', 'params'} or message['jsonrpc'] != '2.0':
                        raise ValueError('流水线资料请求无效。')
                    method, params = message['method'], message['params']
                    if method == 'configuration/read' and params == {}:
                        value = copy.deepcopy(mounted)
                    elif method == 'data/call':
                        action = params.get('operation') if isinstance(params, dict) else None
                        with self.lock: active = bool(self.effects.get((chat, package, binding)))
                        if action in ('upsert', 'upsert_many', 'claim', 'release') and not active:
                            raise PermissionError('业务写入必须来自当前获准的工具调用。')
                        value = self._data(current, snapshot, chat, package, binding, params)
                    else:
                        raise PermissionError('此宿主只开放本流水线配置和授权业务资料。')
                    self.check()
                    return {'jsonrpc': '2.0', 'id': message['id'], 'result': value}

            with super(PipelineMCPWork,self).program_environment(chat,package,binding,base)() as connections,serve_rpc(dispatch) as (endpoint, capability):
                yield {**connections,'RUNTEAMS_PIPELINE_HOST': endpoint, 'RUNTEAMS_PIPELINE_CAPABILITY': capability}
        return environment

    @staticmethod
    def _data(own, snapshot, chat, package, binding, params):
        from .local_collections import configured_call
        from .employee_configuration import EMPTY
        return configured_call(params, own['asset'].get('configuration', EMPTY), snapshot,
            {'pipeline_reference': own['reference'], 'chat_id': chat,
             'program_sha256': package, 'binding_sha256': digest(binding.__dict__)})


def for_pipeline(server, chat, workspace=''):
    if workspace: return None
    try: pipeline_chat_binding.reference(chat)
    except (PermissionError, ValueError): return None
    return server.pipeline_mcp_work()


def control_programs(host, action, chats):
    """Original pipeline control callback, scoped to its actual owned chats."""
    from runteams_core import product_store
    if action not in ('pause', 'start'):
        raise ValueError('请选择暂停或启动流水线程序。')
    for chat in chats:
        session = product_store.get_chat(chat, include_messages=False)
        own = bool(session and session.get('context', {}).get('source_pipeline_workspace'))
        programs = host.pipeline_mcp_work() if own else host.employee_mcp_work()
        if action == 'pause':
            programs.close_work(chat)
        else:
            state = programs.state(chat)
            if state['available'] and state['enabled']:
                if own: programs.prepare_start(chat, state['binding_sha256'])
                else: programs.resume(chat, state['binding_sha256'])
