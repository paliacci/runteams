"""Local MCP lifetime bound to an authorized employee work.

Official SDK owns MCP protocol. The host supplies current identity/enablement
and native approval callbacks; this module cannot manufacture either. This is
ordinary-user local extension execution, not a malicious-code sandbox.
"""
from dataclasses import dataclass, asdict
from contextlib import ExitStack,nullcontext
import json
import os
from pathlib import Path
import queue
import signal
import stat
import subprocess
import sys
from runteams_core.foundation.resources import root as resource_root
import threading

from runteams_core.authoring.creator_contracts import strict_json
from runteams_core.configuration.credentials.credential_redaction import redact_value
from types import MappingProxyType
from runteams_core.employees.mcp.employee_mcp_package import MCPBundle, MCPPackageError, sha256

MAX_FRAME = 4 * 1024 * 1024


class MCPError(RuntimeError):
    pass


class MCPAppResourceInvalid(MCPError):
    """A completed resource reply was rejected before a view could exist."""


class MCPOutcomeUnknown(MCPError):
    """Request was dispatched; callers must not automatically repeat it."""


@dataclass(frozen=True, repr=False)
class MCPBoundCredentials:
    """Host-only lease; values never form a public configuration/authority record."""
    values: dict
    check: object

    def __post_init__(self):
        if not isinstance(self.values,dict) or not callable(self.check):raise TypeError('trusted_mcp_credentials_required')
        object.__setattr__(self,'values',MappingProxyType(dict(self.values)))

    def verify(self):
        try:allowed=self.check()
        except Exception:raise PermissionError('mcp_credentials_not_bound') from None
        if allowed is not True:raise PermissionError('mcp_credentials_not_bound')


@dataclass(frozen=True)
class WorkBinding:
    account_scope: str
    employee_id: str
    release_digest: str
    work_id: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in asdict(self).values()):
            raise ValueError('invalid_mcp_work_binding')


@dataclass(frozen=True)
class PipelineWorkBinding:
    account_scope: str
    pipeline_id: str
    release_digest: str
    work_id: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in asdict(self).values()):
            raise ValueError('invalid_mcp_pipeline_binding')


@dataclass(frozen=True)
class ManagedMCPRuntime:
    root: Path
    manifest_sha256: str

    def verify(self):
        root = Path(self.root).absolute()
        if any(p.is_symlink() for p in (root, *root.parents)):
            raise MCPError('mcp_runtime_integrity')
        manifest = root / 'runtime.json'
        if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 8192:
            raise MCPError('mcp_runtime_missing')
        raw = manifest.read_bytes()
        if sha256(raw) != self.manifest_sha256:
            raise MCPError('mcp_runtime_integrity')
        data = strict_json(raw)
        node = 'node.exe' if os.name == 'nt' else 'node'
        if (data.get('schema') != 'runteams.managed-mcp/1' or
                data.get('platform') != sys.platform or data.get('machine') != __import__('platform').machine() or
                set(data.get('files', {})) != {node, 'worker.cjs', 'app-host.js'}):
            raise MCPError('mcp_runtime_incompatible')
        for name, expected in data['files'].items():
            path = root / name
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 256 * 1024 * 1024 or
                    sha256(path.read_bytes()) != expected):
                raise MCPError('mcp_runtime_integrity')
        return root / node, root / 'worker.cjs'


def platform_runtime():
    """Signed application resources; explicit development provisioning only."""
    if getattr(sys,'frozen',False):root=Path(sys._MEIPASS)/'mcp-runtime'
    else:root=Path(os.environ.get('RUNTEAMS_MCP_RUNTIME_DIR',str(resource_root()/'runtime-dependencies/mcp-runtime'))).absolute()
    return _platform_resource(root)


def presentation_runtime(execution_runtime):
    """The trusted UI host may update without replacing frozen execution tools.

    Packaged applications keep their signed resource closure. Source hosts may
    explicitly provision a verified presentation bundle; author assets and
    browser requests cannot select it. Its Node/worker is never executed here.
    """
    root = os.environ.get('RUNTEAMS_MCP_PRESENTATION_RUNTIME_DIR')
    if getattr(sys, 'frozen', False) or not root:
        return execution_runtime
    return _platform_resource(Path(root).absolute())


def _platform_resource(root):
    try:
        pin=root/'runtime.sha256'
        if pin.is_symlink():raise ValueError()
        runtime=ManagedMCPRuntime(root,pin.read_text().strip());runtime.verify();return runtime
    except (OSError,ValueError):raise MCPError('mcp_platform_runtime_unavailable') from None


def _environment(node, work):
    # A small OS environment, not the app's shell/provider/platform secrets.
    env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'COMSPEC') if k in os.environ}
    env.update(PATH=str(node.parent) + os.pathsep + os.defpath,
               HOME=str(work), USERPROFILE=str(work), TMPDIR=str(work), TEMP=str(work), TMP=str(work),
               LANG='en_US.UTF-8', NODE_NO_WARNINGS='1')
    return env


def _signal_work_group(group, action):
    try:
        os.killpg(group, action)
    except ProcessLookupError:
        return
    except PermissionError:
        # Darwin can return EPERM for a group containing only zombies after
        # the managed leader has exited. A failed signal is NOT proof of exit.
        # Confirm the actual kernel process states; live/unknown members still
        # propagate the original error, so pause cannot claim a false stop.
        try:
            result = subprocess.run(['/bin/ps','-axo','pgid=,stat='],
                capture_output=True, timeout=3, env={'PATH':os.defpath,'LC_ALL':'C'})
            if result.returncode or len(result.stdout)>1024*1024:
                raise ValueError('unavailable_process_inventory')
            for line in result.stdout.decode('ascii').splitlines():
                fields=line.split()
                if len(fields)!=2 or not fields[0].isdigit() or not fields[1][0].isalpha():
                    raise ValueError('invalid_process_inventory')
                if int(fields[0])==group and not fields[1].startswith('Z'):
                    raise ValueError('live_process_group')
        except (OSError,ValueError,subprocess.TimeoutExpired):
            raise PermissionError('mcp_process_group_stop_unconfirmed') from None


class EmployeeMCP:
    """One worker per work; close from the existing owner on disable/logout.

    authorize(binding, bundle_digest, action, detail) MUST use trusted current
    asset/enablement and, for direct UI calls, its actual confirmation route.
    False/exception denies before author code/call. No string from author UI is
    interpreted as user consent, and tool annotations never authorize actions.
    """
    def __init__(self, *, runtime, bundle, package_root, work_root, binding, authorize, environment_scope=None, credential_scope=None, invocation_scope=None):
        if not isinstance(bundle, MCPBundle) or not isinstance(binding, (WorkBinding, PipelineWorkBinding)) or not callable(authorize):
            raise TypeError('trusted_mcp_configuration_required')
        self.runtime, self.bundle, self.binding = runtime, bundle, binding
        self.package_root, self.work_root = Path(package_root).absolute(), Path(work_root).absolute()
        self.authorize = authorize
        self.environment_scope = environment_scope
        if credential_scope is not None and not callable(credential_scope):raise TypeError('trusted_mcp_credentials_required')
        self.credential_scope=credential_scope
        if invocation_scope is not None and not callable(invocation_scope):raise TypeError('trusted_mcp_invocation_required')
        self.invocation_scope=invocation_scope
        self.credential_lease=None
        self.environment_stack = ExitStack()
        self.lock, self.close_lock = threading.RLock(), threading.Lock()
        self.process = None
        self.closed = False
        self.cleanup_complete = False
        self.next_id = 0
        self.lines = queue.Queue(maxsize=8)
        self.tools = None

    def _check(self, action, detail=None):
        if self.closed:
            raise MCPError('mcp_work_closed')
        try:
            allowed = self.authorize(self.binding, self.bundle.digest, action, detail or {})
        except BaseException:
            self.close()
            raise
        if allowed is not True:
            self.close()
            raise PermissionError('mcp_not_authorized')

    def start(self):
        with self.lock:
            self._check('start')  # MUST precede all author process execution.
            if self.process is not None:
                return
            node, worker = self.runtime.verify()
            self.bundle.verify(self.package_root)
            platforms = self.bundle.manifest.get('compatibility', {}).get('platforms', ['darwin', 'linux', 'win32'])
            if sys.platform not in platforms:
                raise MCPPackageError('mcp_platform_unavailable')
            machine=__import__('platform').machine()
            machine={'aarch64':'arm64','AMD64':'x86_64'}.get(machine,machine)
            if machine not in self.bundle.manifest.get('compatibility',{}).get('architectures',['arm64','x86_64']):
                raise MCPPackageError('mcp_platform_unavailable')
            if any(p.is_symlink() for p in (self.work_root, *self.work_root.parents)):
                raise MCPError('invalid_mcp_work_directory')
            if self.package_root == self.work_root or self.package_root in self.work_root.parents:
                raise MCPError('invalid_mcp_work_directory')
            self.work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            env = _environment(node, self.work_root)
            if self.environment_scope is not None:
                try:
                    extra = self.environment_stack.enter_context(self.environment_scope())
                    data={'RUNTEAMS_PIPELINE_HOST','RUNTEAMS_PIPELINE_CAPABILITY'}
                    connections={'RUNTEAMS_CONNECTION_HOST','RUNTEAMS_CONNECTION_CAPABILITY'}
                    if set(extra) not in (set(),data,connections,data|connections):
                        raise MCPError('invalid_mcp_host_environment')
                    env.update(extra)
                except BaseException:
                    self.environment_stack.close()
                    raise
            required=self.bundle.credential_names()
            if required:
                try:
                    if self.credential_scope is None:raise PermissionError('mcp_credentials_not_bound')
                    lease=self.environment_stack.enter_context(self.credential_scope(self.binding,self.bundle.digest,required))
                    if not isinstance(lease,MCPBoundCredentials):raise TypeError('trusted_mcp_credentials_required')
                    if (set(lease.values)!=set(required) or any(not isinstance(value,str) or not 1<=len(value.encode('utf-8'))<=8192 or '\0' in value for value in lease.values.values())
                            or sum(len(value.encode('utf-8')) for value in lease.values.values())>64*1024):raise ValueError('mcp_credential_binding_invalid')
                    lease.verify();self.credential_lease=lease;env.update(lease.values)
                except BaseException:
                    self.credential_lease=None;self.environment_stack.close();raise
            entry = self.package_root / self.bundle.manifest['server']['entry_point']
            command, args = (str(node), [str(entry)]) if self.bundle.manifest['server']['type'] == 'node' else (str(entry), [])
            if self.bundle.manifest['server']['type']=='node' and 'RUNTEAMS_CONNECTION_HOST' in env:
                args=['--require',str(Path(__file__).with_name('native_connection_host.cjs')),*args]
            try:
                self.process = subprocess.Popen([str(node), str(worker)], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=self.work_root,
                    env=env, start_new_session=os.name != 'nt')
            except BaseException:
                self.credential_lease=None;self.environment_stack.close()
                raise
            self.reader = threading.Thread(target=self._read, daemon=True, name='employee-mcp-output')
            self.reader.start()
            try:
                self._rpc('open', {'command': command, 'args': args, 'cwd': str(self.work_root), 'env': env}, timeout=12)
                self._check('active')
            except BaseException:
                self.close()
                raise

    def authority(self):
        # Native authority polling cannot wait on tool IO or a user decision.
        self._check('active')
        try:
            if self.credential_lease is not None:self.credential_lease.verify()
        except PermissionError:
            self.close();raise
        return {'authorized': True, 'context_revision': 0}

    def _read(self):
        try:
            while not self.closed:
                line = self.process.stdout.readline(MAX_FRAME + 1)
                if not line or len(line) > MAX_FRAME or not line.endswith(b'\n'):
                    break
                self.lines.put(line, timeout=1)
        except (OSError, queue.Full):
            pass
        finally:
            try:
                self.lines.put_nowait(None)
            except queue.Full:
                pass

    def _rpc(self, method, params, *, timeout=10):
        self.next_id += 1
        request_id = self.next_id
        payload = json.dumps({'id': request_id, 'method': method, 'params': params}, allow_nan=False).encode() + b'\n'
        if len(payload) > MAX_FRAME:
            raise MCPError('mcp_message_budget')
        sent = False
        try:
            if self.closed or self.process is None:
                raise MCPError('mcp_work_closed')
            if self.credential_lease is not None:self.credential_lease.verify()
            # A broken pipe/short write can still follow partial dispatch.
            sent = True
            self.process.stdin.write(payload)
            self.process.stdin.flush()
            line = self.lines.get(timeout=timeout)
            if line is None:
                raise MCPError('mcp_process_exited')
            reply = strict_json(line)
            if not isinstance(reply, dict) or reply.get('id') != request_id or 'result' not in reply:
                raise MCPError('mcp_invalid_response')
            lease=self.credential_lease
            if lease is not None:lease.verify()
            return redact_value(reply['result'],dict(lease.values) if lease is not None else {})
        except (Exception, KeyboardInterrupt) as error:
            try:
                self.close()
            except (Exception, KeyboardInterrupt) as cleanup_error:
                # Cleanup uncertainty cannot turn a dispatched effect into a
                # permission rejection and permit a new journal key to replay it.
                if sent and method == 'tools/call':
                    raise MCPOutcomeUnknown('mcp_call_outcome_unknown') from cleanup_error
                raise
            if sent and method == 'tools/call':
                raise MCPOutcomeUnknown('mcp_call_outcome_unknown') from error
            if isinstance(error, MCPError):
                raise
            raise MCPError('mcp_request_failed') from error

    def list_tools(self):
        with self.lock:
            self._check('active')
            self.start() if self.process is None else None
            items, cursor, seen = [], None, set()
            for _ in range(20):
                page = self._rpc('tools/list', {'cursor': cursor} if cursor else {})
                items.extend(page.get('tools', []))
                cursor = page.get('nextCursor')
                if len(items) > 1000 or cursor in seen:
                    raise MCPError('mcp_tools_budget')
                if not cursor:
                    break
                seen.add(cursor)
            else:
                raise MCPError('mcp_tools_budget')
            if len({t['name'] for t in items}) != len(items):
                raise MCPError('mcp_duplicate_tool')
            self._check('active')
            self.tools = {t['name']: t for t in items}
            return items

    def call_tool(self, name, arguments, *, source, timeout=65):
        if source not in ('agent', 'app') or not isinstance(arguments, dict):
            raise ValueError('invalid_mcp_call')
        with self.lock:
            self._check('active')
            if self.tools is None:
                self.list_tools()
            tool = self.tools.get(name)
            if tool is None:
                raise PermissionError('mcp_tool_unavailable')
            visibility = tool.get('_meta', {}).get('ui', {}).get('visibility', ['model', 'app'])
            if ('model' if source == 'agent' else 'app') not in visibility:
                raise PermissionError('mcp_tool_unavailable')
            # Every direct app call goes through the host. Page initialization
            # or a false readOnlyHint never silently grants permission.
            self._check('tool', {'source': source, 'name': name, 'arguments': arguments})
            with self.invocation_scope() if self.invocation_scope is not None else nullcontext():
                result = self._rpc('tools/call', {'name': name, 'arguments': arguments}, timeout=timeout)
            try:
                self._check('active')
            except Exception as error:
                # An account/enablement change prevents delivering the result;
                # it cannot undo an effect the author program already made.
                raise MCPOutcomeUnknown('mcp_call_outcome_unknown') from error
            return result

    def read_app(self, tool_name):
        with self.lock:
            self._check('active')
            if self.tools is None:
                self.list_tools()
            tool = self.tools.get(tool_name, {})
            uri = tool.get('_meta', {}).get('ui', {}).get('resourceUri')
            if not isinstance(uri, str) or not uri.startswith('ui://'):
                raise MCPError('mcp_app_unavailable')
            value = self._rpc('resources/read', {'uri': uri})
            contents = value.get('contents') if isinstance(value, dict) else None
            if (not isinstance(contents, list) or len(contents) != 1 or
                    not isinstance(contents[0], dict) or contents[0].get('uri') != uri or
                    contents[0].get('mimeType') != 'text/html;profile=mcp-app' or
                    not isinstance(contents[0].get('text'), str)):
                raise MCPAppResourceInvalid('mcp_app_resource_invalid')
            self._check('active')
            return contents[0]

    def close(self):
        # Does not wait for the request lock: logout/cancel must interrupt a
        # blocked tool. Killing this group includes managed author descendants.
        with self.close_lock:
            if self.cleanup_complete:
                return
            self.closed = True
            try:
                process = self.process
                if process is None:
                    self.cleanup_complete = True
                    return
                try:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    else:
                        _signal_work_group(process.pid, signal.SIGTERM)
                    process.wait(timeout=1)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
                finally:
                    # Still kill descendants if the helper exited before its children.
                    try:
                        if os.name != 'nt':
                            _signal_work_group(process.pid, signal.SIGKILL)
                        process.wait(timeout=3)
                    finally:
                        for stream in (process.stdin, process.stdout):
                            try:
                                stream.close()
                            except OSError:
                                pass
                self.cleanup_complete = True
            finally:
                self.credential_lease=None
                self.environment_stack.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.close()
