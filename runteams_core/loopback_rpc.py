"""Host-scoped loopback JSON-RPC; the caller supplies its authorized dispatcher."""
from contextlib import contextmanager
import contextvars
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
import secrets
import sys
import threading
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


@contextmanager
def serve_rpc(dispatcher, cloud=None):
    context = contextvars.copy_context()
    actor = cloud.identity() if cloud is not None else None
    capability = secrets.token_urlsafe(32)
    lock = threading.RLock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != '/protocol' or not hmac.compare_digest(
                    self.headers.get('Authorization', ''), 'Bearer ' + capability):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8 * 1024 * 1024:
                    raise ValueError('任务工具请求大小无效')
                message = json.loads(self.rfile.read(length))
                if not isinstance(message, dict):
                    raise ValueError('任务工具请求无效')
                def invoke():
                    if cloud is not None and cloud.identity() != actor:
                        raise PermissionError('账户已变化，请重新打开。')
                    return dispatcher(message)
                if message.get('method') == 'tools/call' and (message.get('params') or {}).get('name') == 'runteams_request_choice':
                    # A human question has no business mutation; do not hold the
                    # protocol lock while waiting for the user to answer.
                    result = context.copy().run(invoke)
                else:
                    with lock:
                        result = context.copy().run(invoke)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception('Employee protocol request failed')
                result = {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(locals().get('message'), dict) else None,
                          'error': {'code': -32603, 'message': str(exc)}}
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:{}/protocol'.format(server.server_port), capability
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def proxy(url):
    target = urlsplit(url)
    if target.scheme != 'http' or target.hostname != '127.0.0.1' or target.path != '/protocol':
        raise ValueError('任务工具连接无效')
    capability = os.environ.pop('RUNTEAMS_PROTOCOL_CAPABILITY', '')
    if not capability:
        raise ValueError('任务工具授权缺失')
    for line in sys.stdin:
        message = json.loads(line)
        request = Request(url, data=json.dumps(message).encode(), headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + capability}, method='POST')
        human_input = message.get('method') == 'tools/call' and (message.get('params') or {}).get('name') == 'runteams_request_choice'
        with urlopen(request, timeout=None if human_input else 300) as response:
            result = json.load(response)
        if result is not None:
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\n')
            sys.stdout.flush()
