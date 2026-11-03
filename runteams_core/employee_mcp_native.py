"""MCP Apps adapter on the existing private native WebView transport."""
import json
import secrets
import threading
import uuid
from urllib.parse import urlsplit

from .native_view_transport import NativeViewTransport, _Server
from .employee_mcp import MCPError


from .employee_mcp_resource import _resource_html, host_html, app_host_script


class EmployeeMCPBridge(NativeViewTransport):
    """Trusted host creates after asset and explicit extension enablement.

    Reuses the existing nonce, separate control origin, native document epochs
    and WKWebView authority checks. No browser-accessible control endpoint.
    """
    def __init__(self, session, tool, input_value, *, invoke=None, on_close=None, host_tools=(), authority=None, close_session=True):
        self.session = session
        self.invoke, self.on_close = invoke, on_close
        self.host_authority = authority
        self.close_session = close_session
        self.lock, self.close_lock = threading.RLock(), threading.Lock()
        self.closed = False; self.close_result = None; self.document = None; self.sequence = 0
        self.nonce = secrets.token_urlsafe(32)
        self.methods = frozenset({'mcp.tools.call'})
        self.opened = {'entry': 'views/mcp-host.html'}
        self.servers, self.threads = [], []
        try:
            session.start()
            tools = session.list_tools()
            if {t['name'] for t in tools} & {t['name'] for t in host_tools}:
                raise MCPError('mcp_reserved_host_tool')
            tools = [*tools, *host_tools]
            resource = session.read_app(tool)
            self.app_html, self.app_policy = _resource_html(resource)
            session.runtime.verify()
            self.script = app_host_script(session.runtime)
            self.html = host_html(session.bundle.manifest.get('display_name',session.bundle.manifest['name']),tools,input_value)
            for control in (False, True):
                server = _Server(self._handler(control)); self.servers.append(server)
                thread = threading.Thread(target=server.serve_forever, daemon=True, name='employee-mcp-app')
                thread.start(); self.threads.append(thread)
        except BaseException:
            self.close()
            raise

    def _check(self):
        if self.closed:
            raise PermissionError('MCP work closed')

    def authority(self):
        self._check()
        return self.host_authority() if self.host_authority is not None else self.session.authority()

    def rotate(self, document):
        if not isinstance(document, str) or str(uuid.UUID(document)) != document.lower():
            raise PermissionError('Invalid document')
        with self.lock:
            value = self.authority()
            self.document = document
            return value

    def message(self, document, method, params):
        with self.lock:
            self._check()
            if document != self.document or self.document is None:
                raise PermissionError('MCP document changed')
            if (method != 'mcp.tools.call' or not isinstance(params, dict) or set(params) != {'name', 'arguments'} or
                    not isinstance(params['name'], str) or not isinstance(params['arguments'], dict)):
                raise PermissionError('MCP method unavailable')
            self.sequence += 1
            result = (self.invoke(params['name'],params['arguments']) if self.invoke is not None else
                      self.session.call_tool(params['name'], params['arguments'], source='app', timeout=8))
            return {'schema': 'runteams.ui-context/2', 'id': self.sequence, 'ok': True, 'result': result}

    def asset(self, path):
        self.authority()
        if path == '/views/mcp-host.html':
            body, mime = self.html, 'text/html; charset=utf-8'
        elif path == '/views/app-host.js':
            body, mime = self.script, 'text/javascript'
        elif path == '/views/mcp-app.html':
            body, mime = self.app_html, 'text/html; charset=utf-8'
        else:
            raise PermissionError('MCP resource unavailable')
        return body, {'Content-Type': mime, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'Cross-Origin-Resource-Policy': 'same-origin',
            'Content-Security-Policy': self.app_policy if path == '/views/mcp-app.html' else
                "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; frame-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'"}

    def submit_chat(self, *args, **kwargs):
        raise PermissionError('Use the platform conversation')

    chat_receipt = submit_chat

    def close(self):
        with self.close_lock:
            if self.close_result is not None:
                return dict(self.close_result)
            self.closed = True
            if self.close_session:
                self.session.close()
            if self.on_close is not None:self.on_close()
            for server in self.servers:
                server.shutdown(); server.server_close()
            for thread in self.threads:
                thread.join(timeout=2)
            self.nonce = ''
            self.close_result = {'native_closed': True, 'cloud_session_closed': False, 'mcp_closed': self.close_session}
            return dict(self.close_result)
