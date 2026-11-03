from runteams_core.resources import root as resource_root
"""Browser transport for the existing work owner. No second business executor.

Private owner/control descriptors stay in this process. Each mounted page gets a
separate asset origin; only its trusted parent relays SDK calls to this service.
"""
import contextvars
import http.client
import re
from pathlib import Path
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

from .creator_contracts import canonical, strict_json
from .native_view_transport import _Server
from .creator_ui import ui_json
from .native_work_owner import ACTIVE_WORK_LIMIT

ROOT = resource_root()


def transport(config, path, payload=None, *, asset=False):
    target = urlsplit(config['origin' if asset else 'control'])
    if target.scheme != 'http' or target.hostname != '127.0.0.1' or not target.port or target.path:
        raise PermissionError('work_transport_invalid')
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=115 if path == '/message' else 15)
    try:
        headers = {} if asset else {'Authorization': 'Bearer ' + config['nonce']}
        body = None if payload is None else canonical(payload)
        if body is not None:
            ui_json(payload); headers['Content-Type'] = 'application/json'
        connection.request('GET' if body is None else 'POST', path, body, headers)
        response = connection.getresponse()
        raw = response.read((8 * 1024 * 1024 if asset else 131072) + 1)
        if response.status != 200 or len(raw) > (8 * 1024 * 1024 if asset else 131072):
            raise PermissionError('work_access_denied') if response.status == 403 else RuntimeError('work_reply_unknown')
        return (raw, dict(response.getheaders())) if asset else strict_json(raw)
    finally:
        connection.close()


class BrowserWorkHost:
    def __init__(self, router, scope):
        self.router = router; self.scope = scope; self.lock = threading.RLock()
        self.clients = {}; self.closed = threading.Event()
        self.thread = threading.Thread(target=self._reap, daemon=True, name='browser-work-leases')
        self.thread.start()

    def _reap(self):
        while not self.closed.wait(5):
            with self.lock:
                stale = [token for token, client in self.clients.items() if time.monotonic() - client['seen'] > 180]
            for token in stale:
                self.retire(token)

    def retire(self, token):
        with self.lock:
            client = self.clients.pop(token, None)
        if client:
            with client['lock']:
                works=list(client['works'].values())
            for work in works:
                try: work.close()
                except Exception: pass  # Owner retirement may already have closed this work.
            try: self.router.client(client['id'], close=True)
            except Exception: pass  # Cleanup cannot confer authority or replay a mutation.

    def call(self, value, origin):
        ui_json(value)
        if not isinstance(value, dict): raise ValueError('work_request_invalid')
        action = value.get('action'); current = self.scope()
        if not current[1]: raise PermissionError('work_login_required')
        if action == 'register':
            if set(value) != {'action'}: raise ValueError('work_request_invalid')
            with self.lock:
                if self.closed.is_set() or len(self.clients) >= 32: raise PermissionError('work_host_unavailable')
                token = secrets.token_urlsafe(32); client_id = str(uuid.uuid4())
                self.router.client(client_id)
                self.clients[token] = {'id':client_id, 'scope':current, 'origin':origin, 'works':{},
                    'lock':threading.RLock(), 'seen':time.monotonic()}
            return {'client':token}
        token = value.get('client')
        with self.lock:
            client = self.clients.get(token) if isinstance(token,str) else None
            if self.closed.is_set() or not client or client['scope'] != current or client['origin'] != origin:
                raise PermissionError('work_scope_changed')
            client['seen'] = time.monotonic()
        with client['lock']:
            with self.lock:
                if self.clients.get(token) is not client: raise PermissionError('work_scope_changed')
            if action == 'detach': self.retire(token); return {'active':False}
            if action == 'heartbeat': return {'active':True}
            if action == 'discover':
                if set(value) != {'action','client','chat_id','workspace_id'} or value['workspace_id'] != current[2]:
                    raise PermissionError('work_scope_changed')
                return self.router.discover(value['chat_id'], current[2])
            if action == 'open':
                if set(value) != {'action','client','workspace_id','chat_id','installation_id','view','input','operation_key'} or value['workspace_id'] != current[2]:
                    raise PermissionError('work_scope_changed')
                payload = {key:value[key] for key in ('workspace_id','chat_id','installation_id','view','input','operation_key')}
                # Keep failed/unknown requests in the original owner's ledger.
                opened = self.router.open(payload, client=client['id'])
                if opened.get('state') != 'ready': raise RuntimeError('work_open_unknown')
                work = client['works'].get(opened['id'])
                if work is None:
                    if len(client['works']) >= ACTIVE_WORK_LIMIT:
                        self.router.release(opened['id'])
                        raise PermissionError('work_host_capacity')
                    try: work = BrowserWork(self.router, opened, origin, value['chat_id'])
                    except BaseException:
                        self.router.release(opened['id']); raise
                    client['works'][work.id] = work
                return {'id':work.id, 'chat_id':work.chat, 'url':work.url, 'epoch':work.epoch, 'methods':work.methods}
            work = client['works'].get(value.get('id'))
            if not work or value.get('chat_id') != work.chat: raise PermissionError('work_binding_invalid')
            if action == 'unmount':
                work.close(); client['works'].pop(work.id, None); return {'mounted':False,'id':work.id}
        return work.call(value)

    def close(self):
        self.closed.set()
        with self.lock: tokens = list(self.clients)
        for token in tokens: self.retire(token)
        self.thread.join(timeout=2)


class BrowserWork:
    def __init__(self, router, opened, parent, chat):
        self.router=router; self.id=opened['id']; self.chat=chat; self.config=opened['configuration']
        self.parent=parent; self.epoch=str(uuid.uuid4()); self.methods=list(self.config['methods'])
        self.lock=threading.RLock(); self.close_lock=threading.Lock(); self.cleanup_complete=False; self.closed=False; self.loaded=False; self.sequence=0; self.uncertain=False; self.pending=None; self.reload_permitted=False
        self.context=contextvars.copy_context()
        transport(self.config, '/document', {'document':self.epoch})
        self.server=_Server(self._handler())
        self.url=f'http://127.0.0.1:{self.server.server_port}/'+self.config['entry'].lstrip('/')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True,name='browser-work-assets'); self.thread.start()

    def call(self, value):
        if self.closed or value.get('epoch') != self.epoch: raise PermissionError('work_document_stale')
        action=value['action']
        if action == 'authority': return transport(self.config, '/authority')
        with self.lock:
            if self.closed: raise PermissionError('work_document_stale')
            if action == 'message':
                if set(value) != {'action','client','id','chat_id','epoch','sequence','method','params'} or type(value['sequence']) is not int or value['sequence'] != self.sequence+1:
                    raise PermissionError('work_sequence_invalid')
                if self.uncertain or self.pending or value['method'] not in self.methods: raise PermissionError('work_call_unavailable')
                # A lost response freezes this document. Never automatically retry.
                self.sequence += 1; self.uncertain=True
                reply=transport(self.config,'/message',{'document':self.epoch,'method':value['method'],'params':value['params']})
                if reply.get('schema') != 'runteams.ui-context/2' or type(reply.get('ok')) is not bool: raise RuntimeError('work_reply_invalid')
                self.uncertain=False
                self.reload_permitted=reply.get('ok') is True and value['method']=='mcp.preview.select'
                return {**reply,'id':value['sequence']}
            if action in ('submit','receipt'):
                key=value.get('operation_key')
                if not isinstance(key,str) or not 1<=len(key)<=128: raise ValueError('work_input_invalid')
                if action == 'submit':
                    if set(value) != {'action','client','id','chat_id','epoch','sequence','operation_key','input_ref'} or self.pending or self.uncertain or value['sequence'] != self.sequence:
                        raise PermissionError('work_fence_invalid')
                    self.pending=key
                    payload={'document':self.epoch,'operation_key':key,'input_ref':value['input_ref']}
                else:
                    if set(value) != {'action','client','id','chat_id','epoch','operation_key'} or self.pending != key: raise PermissionError('work_receipt_invalid')
                    payload={'document':self.epoch,'operation_key':key}
                try: receipt=transport(self.config,'/chat-submit' if action=='submit' else '/chat-receipt',payload)
                except Exception: return {'state':'unknown','message_persisted':False,'agent_started':False}
                if receipt.get('state') == 'confirmed':
                    if (receipt.get('chat_id') != self.chat or type(receipt.get('message_id')) is not int or receipt['message_id']<=0 or
                        receipt.get('message_persisted') is not True or receipt.get('agent_started') is not False): raise RuntimeError('work_receipt_invalid')
                    uuid.UUID(receipt['business_epoch']); self.pending=None
                    return {'state':'confirmed','message_persisted':True,'agent_started':False,
                        'creator_message':{key:receipt[key] for key in ('message_id','business_epoch')}|{'operation_key':key}}
                if receipt.get('state') == 'rejected': self.pending=None
                return {'state':receipt.get('state','unknown'),'message_persisted':False,'agent_started':False}
            raise ValueError('work_action_invalid')

    def _handler(self):
        work=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def setup(self):
                super().setup();self.connection.settimeout(3)
            def do_GET(self):
                try:
                    if work.closed or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}': raise PermissionError()
                    target=urlsplit(self.path)
                    if target.query or target.fragment: raise PermissionError()
                    if target.path == '/__runteams_browser_host/'+work.epoch+'.js':
                        config=canonical({'id':work.id,'epoch':work.epoch,'parent':work.parent,'methods':work.methods}).decode()
                        body=(ROOT/'web/ui/work-page-host.js').read_bytes().replace(b'null/*__HOST_CONFIG__*/',config.encode(),1)
                        headers={'Content-Type':'text/javascript'}
                    else:
                        body,headers=transport(work.config,self.path,asset=True)
                        headers={k.lower():v for k,v in headers.items() if k.lower() in ('content-type','content-security-policy','x-content-type-options','referrer-policy')}
                        if target.path == '/'+work.config['entry'].lstrip('/'):
                            with work.lock:
                                # Only a confirmed SDK preview selection requests a new
                                # document. Arbitrary reload cannot clear an unknown effect.
                                if work.loaded:
                                    if not work.reload_permitted or work.uncertain or work.pending: raise PermissionError()
                                    epoch=str(uuid.uuid4())
                                    transport(work.config,'/document',{'document':epoch})
                                    work.epoch=epoch;work.sequence=0;work.reload_permitted=False
                                work.loaded=True
                            if 'text/html' not in headers.get('content-type',''): raise PermissionError()
                            script=('<script src="/__runteams_browser_host/'+work.epoch+'.js"></script>').encode()
                            head=re.search(br'<head(?:\s[^>]*)?>',body,re.I)
                            doc=re.match(br'\s*<!doctype[^>]*>',body,re.I)
                            offset=head.end() if head else doc.end() if doc else 0
                            body=body[:offset]+script+body[offset:]
                        policy=headers.pop('content-security-policy',"default-src 'none'")
                        policy='; '.join(part for part in policy.split(';') if not part.strip().lower().startswith('frame-ancestors'))
                        headers['Content-Security-Policy']=policy+f"; frame-ancestors 'self' {work.parent}"
                    self.send_response(200)
                    for key,val in headers.items(): self.send_header(key,val)
                    self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','no-referrer')
                    self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Length',str(len(body)))
                    self.end_headers(); self.wfile.write(body)
                except Exception: self.send_error(403)
        return Handler

    def close(self):
        with self.close_lock:
            if self.cleanup_complete:return
            with self.lock:
                was_closed=self.closed;self.closed=True
            if not was_closed:
                self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
            # An unsuccessful owner cleanup stays revoked, but retryable. Do
            # not acknowledge unmount or free the slot before it is confirmed.
            result=self.context.copy().run(self.router.release,self.id)
            if result.get('native_closed') is not True:raise RuntimeError('work_close_unconfirmed')
            self.cleanup_complete=True


def handle(handler):
    """Same-origin platform-only endpoint. Author asset origins cannot use it."""
    port=handler.server.server_port; host=handler.headers.get('Host'); origin=handler.headers.get('Origin')
    if (host not in {f'127.0.0.1:{port}',f'localhost:{port}'} or origin != 'http://'+host or
        handler.headers.get('Sec-Fetch-Site') == 'cross-site' or handler.headers.get('X-RunTeams-Work-Host') != '1' or
        handler.headers.get('Transfer-Encoding') or handler.headers.get('Content-Type') != 'application/json'):
        return handler._json({'error':'工作界面的访问来源无效。'},403)
    try:
        length=int(handler.headers.get('Content-Length','-1'))
        if not 0<=length<=20000:raise ValueError()
        raw=handler.rfile.read(length)
        if len(raw)!=length:raise ValueError()
        value=strict_json(raw)
        with handler.server.creator_owner_lock:
            if handler.server.creator_owner_stopped:raise PermissionError()
            if handler.server.browser_work_host is None:
                from runteams_core import agent_interaction
                handler.server.browser_work_host=BrowserWorkHost(handler.server.creator_router(),agent_interaction.scope)
            host_service=handler.server.browser_work_host
        return handler._json(host_service.call(value,origin))
    except PermissionError:return handler._json({'error':'工作界面已失效，请重新打开。'},403)
    except (ValueError,TypeError,KeyError):return handler._json({'error':'工作界面请求无效。'},400)
    except Exception:return handler._json({'error':'工作界面回执尚未确认，请重新核对。'},503)
