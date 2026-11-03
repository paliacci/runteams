"""Original private native view transport, shared without creator cloud authority."""
import hmac,json,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .creator_contracts import canonical
from .creator_ui import ui_json

class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, handler):
        self.slots = threading.BoundedSemaphore(4)
        self.stopping = threading.Event()
        super().__init__(('127.0.0.1', 0), handler)

    def process_request(self, request, address):
        # A complete HTTP response can reach the native client before its
        # worker has closed the socket and returned its permit. Keep one
        # accepted request on this server thread until that handoff completes;
        # do not reset a valid successor or add unbounded worker/queue state.
        deadline = time.monotonic() + 3
        while not self.stopping.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if self.slots.acquire(timeout=min(.05, remaining)):
                if self.stopping.is_set():
                    self.slots.release()
                    break
                try: super().process_request(request, address)
                except BaseException:
                    self.slots.release()
                    raise
                return
        self.shutdown_request(request)

    def shutdown(self):
        self.stopping.set()
        super().shutdown()

    def server_close(self):
        self.stopping.set()
        super().server_close()

    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()


class NativeViewTransport:
    @property
    def native_configuration(self):
        """Trusted native process only; never embed this in author HTML/JS."""
        return {'origin':f'http://127.0.0.1:{self.servers[0].server_port}',
            'control':f'http://127.0.0.1:{self.servers[1].server_port}',
            'nonce':self.nonce,'entry':self.opened['entry'],'methods':sorted(self.methods)}


    def _handler(self, control):
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_args): pass
            def setup(self):
                super().setup(); self.connection.settimeout(3)
            def send(self,status,body,headers=None):
                self.send_response(status)
                for key,value in (headers or {'Content-Type':'application/json','Cache-Control':'no-store'}).items():
                    self.send_header(key,value)
                self.send_header('Content-Length',str(len(body))); self.send_header('Connection','close')
                self.end_headers(); self.wfile.write(body)
            def admitted(self):
                if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}': return False
                if control:
                    if self.headers.get('Origin') or any(k.lower().startswith('sec-fetch-') for k in self.headers): return False
                    return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+bridge.nonce)
                return True
            def fail(self,error):
                denied=isinstance(error,PermissionError) or getattr(error,'code',None) in (
                    'ui_session_expired','context_scope_changed','ui_stale_epoch') or getattr(error,'status_code',None)==404
                self.send(403 if denied else 503,canonical({'error':'ui_access_denied' if denied else 'ui_request_unknown'}))
            def do_GET(self):
                try:
                    if not self.admitted(): raise PermissionError()
                    if control:
                        if self.path!='/authority': raise PermissionError()
                        self.send(200,canonical(bridge.authority()))
                    else:
                        body,headers=bridge.asset(self.path); self.send(200,body,headers)
                except Exception as error: self.fail(error)
            def do_POST(self):
                try:
                    if not control or not self.admitted(): raise PermissionError()
                    if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type')!='application/json':
                        raise PermissionError()
                    length=int(self.headers.get('Content-Length','-1'))
                    if not 0<=length<=20000: raise PermissionError()
                    raw=self.rfile.read(length)
                    if len(raw)!=length: raise PermissionError()
                    payload=json.loads(raw); ui_json(payload)
                    if self.path=='/document' and isinstance(payload,dict) and set(payload)=={'document'}:
                        value=bridge.rotate(payload['document'])
                    elif self.path=='/message' and isinstance(payload,dict) and set(payload)=={'document','method','params'}:
                        value=bridge.message(payload['document'],payload['method'],payload['params'])
                    elif self.path=='/chat-submit' and isinstance(payload,dict) and set(payload)=={'document','operation_key','text'}:
                        value=bridge.submit_chat(payload['document'],payload['operation_key'],payload['text'])
                    elif self.path=='/chat-submit' and isinstance(payload,dict) and set(payload)=={'document','operation_key','input_ref'}:
                        value=bridge.submit_chat(payload['document'],payload['operation_key'],input_ref=payload['input_ref'])
                    elif self.path=='/chat-receipt' and isinstance(payload,dict) and set(payload)=={'document','operation_key'}:
                        value=bridge.chat_receipt(payload['document'],payload['operation_key'])
                    else: raise PermissionError()
                    self.send(200,canonical(value))
                except Exception as error: self.fail(error)
        return Handler

