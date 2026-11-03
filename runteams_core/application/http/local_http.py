"""Loopback-only transport for the local application; no account or cloud routes."""
import hmac
from pathlib import Path
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie, CookieError
import json
import secrets
import re
import socketserver
import sqlite3
from urllib.parse import parse_qs, urlsplit

from runteams_core.assets.library_assets import AssetConflict, MAX_SOURCE_BYTES
from runteams_core.application.http.local_web import ASSETS, CSP, read_asset
from runteams_core.foundation.local_json import strict_json
from runteams_core.application.local_runtime import LocalInputError, RuntimeBusy
from runteams_core.foundation.contracts import ContractError

MAX_REQUEST_BYTES = max(MAX_SOURCE_BYTES + 65536, 4 * ((25 * 1024 * 1024 + 2) // 3) + 131072)
CAPABILITIES = ('library.read', 'assets.list', 'assets.create', 'assets.read', 'assets.save',
                'assets.import', 'assets.rename', 'assets.export', 'business.ui', 'settings.read', 'settings.save', 'models.read', 'chat.local', 'chat.attachments',
                'chat.tools.environment', 'chat.tools.questions', 'chat.tools.project-memory', 'chat.work-folders', 'chat.skills', 'chat.rewind', 'documents.read', 'documents.write', 'documents.assets', 'documents.tools', 'library.backup', 'library.restore', 'library.backup.automatic', 'sdk.source', 'sdk.authoring', 'sdk.build','employee.work','employee.reports','employee.mcp','employee.schedules','pipeline.work','pipeline.mcp','pipeline.schedules')




class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True  # Restart after closed HTTP connections; never SO_REUSEPORT.

    def __init__(self, application, port):
        self.application = application
        self.session_token = secrets.token_urlsafe(32)
        self.browser_token = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), LocalHandler)

    def server_close(self):
        self.application.close()
        super().server_close()

    def serve_forever(self, poll_interval=0.5):
        if (self.application.binding.root/'work/runteams.db').is_file() or any((self.application.binding.root/(kind+'-schedules')/'schedules.sqlite3').is_file() for kind in ('employee','pipeline')):
            self.application.runtime.activate_employee_host()
        self.application.automatic_backups.start()
        try:return super().serve_forever(poll_interval)
        finally:self.application.automatic_backups.close()

    def server_bind(self):
        # HTTPServer's getfqdn performs DNS; this service has no DNS dependency.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address

    @property
    def origin(self):
        return 'http://127.0.0.1:' + str(self.server_port)

    def descriptor(self, *, native=False):
        # Private stdout handshake for a local launcher, never a browser URL.
        value={'schema': 'runteams.local-service/1', 'edition': 'community',
                'origin': self.origin, 'session_token': self.session_token,
                'capabilities': list(CAPABILITIES), 'ui_url': self.origin + '/'}
        if native:value['native_work']={'schema':'runteams.creator-desktop/2','platform_origin':self.origin,'owner':self.application.runtime.work_router().native_control}
        return value

    @property
    def cookie_name(self):
        return 'runteams_local_' + str(self.server_port)


class LocalHandler(BaseHTTPRequestHandler):
    server_version = 'RunTeamsLocal/1'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        pass  # Requests can contain personal asset names or local references.

    def _json(self, status, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(raw)
        except OSError:
            pass  # A dropped response is recovered by the same operation ID.

    def _transport_allowed(self):
        host = self.server.origin.removeprefix('http://')
        if self.headers.get_all('Host', []) != [host]:
            return False
        origins = self.headers.get_all('Origin', [])
        if origins and origins != [self.server.origin]:
            return False
        return self.headers.get('Sec-Fetch-Site', '') in ('', 'none', 'same-origin')

    def _authentication(self):
        auth = self.headers.get_all('Authorization', [])
        if auth:
            return 'bearer' if len(auth) == 1 and hmac.compare_digest(auth[0].encode(),
                ('Bearer ' + self.server.session_token).encode()) else None
        headers = self.headers.get_all('Cookie', [])
        if len(headers) != 1:
            return None
        try:
            cookie = SimpleCookie(headers[0]).get(self.server.cookie_name)
            if cookie and hmac.compare_digest(cookie.value.encode(), self.server.browser_token.encode()):
                return 'browser'
        except (CookieError, ValueError):
            return None

    def _static(self, path):
        try:
            nonce = secrets.token_urlsafe(24)
            raw, content_type = read_asset(path, nonce, self.server.application.binding.library_id)
        except OSError:
            return self._json(503, {'error': 'local_ui_unavailable'})
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', CSP.format(nonce=nonce).replace("frame-ancestors 'none'","frame-ancestors 'self'") if path == '/rich-document/dist/index.html' else CSP.format(nonce=nonce))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Connection', 'close')
            if ASSETS[path][0] == 'web/index.html':
                self.send_header('Set-Cookie', self.server.cookie_name + '=' + self.server.browser_token
                    + '; HttpOnly; SameSite=Strict; Path=/api/')
            self.end_headers()
            self.wfile.write(raw)
        except OSError:
            pass

    def _request(self):
        if not self._transport_allowed():
            return self._json(403, {'error': 'local_origin_required'})
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            return self._json(400, {'error': 'invalid_request_target'})
        if parsed.scheme or parsed.netloc or parsed.fragment:
            return self._json(400, {'error': 'invalid_request_target'})
        if self.command == 'GET' and (parsed.path in ('/documents','/trash') or re.fullmatch(r'/(?:chats|documents)/local-[a-f0-9]{32}', parsed.path)):
            return self._static('/')
        if self.command == 'GET' and parsed.path in ASSETS and (not parsed.query or
                ASSETS[parsed.path][0] == 'web/index.html' or set(parse_qs(parsed.query)) <= {'v'}):
            return self._static(parsed.path)
        if self.command == 'GET' and parsed.path == '/api/health' and not parsed.query:
            return self._json(200, {'app': 'RunTeams', 'edition': 'community',
                                   'capabilities': list(CAPABILITIES)})
        mode = self._authentication()
        if not mode:
            return self._json(401, {'error': 'local_session_required'})
        image_read = self.command == 'GET' and re.fullmatch(r'/api/chat/[1-9][0-9]*/attachment/[a-f0-9]{24}', parsed.path)
        archive_read = self.command == 'GET' and re.fullmatch(r'/api/backups/[a-f0-9-]{36}/download', parsed.path)
        library=self.server.application.binding.library_id;generation=self.server.application.backups.generation
        expected=self.headers.get_all('X-RunTeams-Library',[])
        generations=self.headers.get_all('X-RunTeams-Library-Generation',[])
        exempt=parsed.path=='/api/library' or image_read or archive_read
        if ((expected and expected!=[library]) or (generations and generations!=[generation])
                or mode=='browser' and not exempt and (not expected or not generations)):
            return self._json(403,{'error':'library_scope_changed'})
        request_scope=None if parsed.path=='/api/library' else (library,generation)
        source_conflicts=source_contracts=()
        source_request=parsed.path.startswith('/api/creator-source/')
        try:
            if source_request:
                from runteams_core.authoring.source.creator_source_revisions import SourceConflict
                from runteams_core.authoring.creator_contracts import CreatorContractError
                source_conflicts=(SourceConflict,)
                source_contracts=(CreatorContractError,)

            if self.command == 'POST' and parsed.path == '/api/backups/import':
                from runteams_core.storage.backups.backup_files import MAX_ARCHIVE
                from runteams_core.storage.backups.local_backups import operation_id
                lengths=self.headers.get_all('Content-Length',[]);operations=self.headers.get_all('X-RunTeams-Operation',[])
                if parsed.query or self.headers.get_all('Transfer-Encoding') or len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(operations)!=1:raise ValueError('备份上传请求无效。')
                if self.headers.get_all('Content-Type',[])!=['application/zip']:return self._json(415,{'error':'请选择ZIP备份文件。'})
                length=int(lengths[0])
                if not 1<=length<=MAX_ARCHIVE:return self._json(413,{'error':'请选择不超过512MB的备份。'})
                operation_id(operations[0]);self.connection.settimeout(30)
                with self.server.application.request(request_scope):
                    try:result=self.server.application.backups.upload(self.rfile,length,operations[0])
                    except AssetConflict:raise
                    except ValueError as error:raise LocalInputError(str(error)) from error
                    return self._json(200,result)
            if self.command == 'GET':
                query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True,
                                 max_num_fields=8)
                if any(len(values) != 1 for values in query.values()):
                    raise ValueError('重复的查询字段。')
                data = {key: value[0] for key, value in query.items()}
                if 'limit' in data:
                    data['limit'] = int(data['limit'])
            else:
                if parsed.query or self.headers.get_all('Transfer-Encoding'):
                    raise ValueError('请求格式无效。')
                sizes = self.headers.get_all('Content-Length', [])
                if len(sizes) != 1 or not sizes[0].isascii() or not sizes[0].isdecimal():
                    raise ValueError('请求长度无效。')
                length = int(sizes[0])
                if not 1 <= length <= MAX_REQUEST_BYTES:
                    return self._json(413, {'error': 'request_too_large'})
                types = self.headers.get_all('Content-Type', [])
                if len(types) != 1 or types[0].lower() not in (
                        'application/json', 'application/json; charset=utf-8'):
                    return self._json(415, {'error': 'json_required'})
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('请求不完整。')
                data = strict_json(raw)
            stream = re.fullmatch(r'/api/chat/([1-9][0-9]*)/stream', parsed.path)
            if self.command == 'POST' and stream:
                return self._conversation_stream(int(stream[1]), data, request_scope)
            if parsed.path=='/api/work-host' and self.command=='POST':
                if self.headers.get('Origin')!=self.server.origin or self.headers.get('X-RunTeams-Work-Host')!='1':raise PermissionError('工作界面来源无效。')
                with self.server.application.request(request_scope),self.server.application.runtime.scope():
                    return self._json(200,self.server.application.runtime.browser_work(data,self.server.origin))
            result = self.server.application.dispatch(self.command, parsed.path, data, scope=request_scope)
            if source_request:
                from runteams_core.authoring.source.creator_source_operations import SourceDownload
                if isinstance(result, SourceDownload):
                    with self.server.application.request(request_scope):
                        self.server.application.check()
                        self.send_response(200)
                        self.send_header('Content-Type','application/zip')
                        self.send_header('Content-Length',str(len(result.raw)))
                        self.send_header('Content-Disposition','attachment; filename="runteams-source-'+result.identity[:12]+'.zip"')
                        self.send_header('X-RunTeams-Source-Revision',result.revision)
                        self.send_header('Cache-Control','no-store')
                        self.send_header('X-Content-Type-Options','nosniff')
                        self.send_header('Content-Security-Policy',"sandbox; default-src 'none'")
                        self.end_headers();self.wfile.write(result.raw)
                    return
            from runteams_core.application.http.local_backup_http import BackupDownload
            if isinstance(result,BackupDownload):return self._backup_download(result,request_scope)
            from runteams_core.application.http.local_document_http import DocumentResponse
            if isinstance(result, DocumentResponse):
                if result.filename:
                    return self._document_download(result)
                return self._json(result.status, result.payload)
            from runteams_core.conversations.local_conversation_inputs import ConversationFile
            if isinstance(result, ConversationFile):
                return self._conversation_file(result)
            return self._json(200, result)
        except source_conflicts as error:
            return self._json(409, {'error':str(error),'code':'source_revision_conflict'})
        except source_contracts as error:
            return self._json(503 if error.code in ('platform_builder_unavailable','import_check_budget','import_checker_unavailable') else 422, {'error':str(error),'code':error.code})
        except FileNotFoundError:
            return self._json(404 if source_request else 503, {'error':'未找到这份本机源码。' if source_request else 'local_storage_unavailable'})
        except BlockingIOError as error:
            return self._json(409 if source_request else 503, {'error':str(error),'code':'builder_busy'} if source_request else {'error':'local_storage_unavailable'})
        except ContractError as error:
            return self._json(400, {'error':str(error)})
        except LocalInputError as error:
            return self._json(400, {'error': str(error)})
        except RuntimeBusy as error:
            return self._json(409, {'error': str(error)})
        except AssetConflict:
            return self._json(409, {'error': 'asset_conflict'})
        except RuntimeError as error:
            return self._json(503, {'error': str(error)})
        except PermissionError:
            return self._json(403, {'error': 'library_scope_changed'})
        except KeyError:
            return self._json(404, {'error': 'not_found'})
        except (ValueError, TypeError, UnicodeError, RecursionError) as error:
            if parsed.path.endswith(('employee-configuration','/configuration')) or parsed.path.endswith('/stream'):
                from runteams_core.configuration.employee_configuration import ConfigurationInvalid, ConfigurationConflict
                if isinstance(error,ConfigurationInvalid):return self._json(422,{'error':str(error),'code':'employee_configuration_invalid','fields':error.errors})
                if isinstance(error,ConfigurationConflict):return self._json(409,{'error':str(error),'code':'employee_configuration_conflict'})
            return self._json(400, {'error': 'invalid_request'})
        except (OSError, sqlite3.Error):
            return self._json(503, {'error': 'local_storage_unavailable'})

    def _backup_download(self, result, scope):
        self.connection.settimeout(120)
        with self.server.application.request(scope):
            self.close_connection=True
            with result.path.open('rb') as file:
                self.send_response(200)
                self.send_header('Content-Type','application/zip')
                self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(result.name,safe=''))
                self.send_header('Content-Length',str(result.path.stat().st_size))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"sandbox; default-src 'none'")
                self.send_header('Connection','close');self.end_headers()
                try:
                    while chunk:=file.read(1024*1024):self.wfile.write(chunk)
                except OSError:pass

    def _document_download(self, result):
        self.server.application.check()
        self.close_connection = True
        self.send_response(result.status)
        self.send_header('Content-Type', result.mime)
        self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(result.filename,safe=''))
        self.send_header('Content-Length',str(len(result.payload)))
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"sandbox; default-src 'none'")
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Connection','close')
        self.end_headers()
        try:self.wfile.write(result.payload)
        except OSError:pass

    def _conversation_file(self, file):
        self.server.application.check()
        raw = file.path.read_bytes()
        self.server.application.check()
        self.close_connection = True
        try:
            self.send_response(200)
            image = file.mime in ('image/png', 'image/jpeg', 'image/webp')
            self.send_header('Content-Type', file.mime if image else 'application/octet-stream')
            self.send_header('Content-Disposition', ('inline' if image else 'attachment')
                             + "; filename*=UTF-8''" + quote(file.name, safe=''))
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "sandbox; default-src 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(raw)
        except OSError:
            pass

    def _conversation_stream(self, chat_id, data, scope=None):
        runtime = self.server.application.runtime
        try:
            with self.server.application.request(scope):
                message_id, operation = runtime.start(chat_id, data)
        except ValueError as error:
            if getattr(error,'errors',None) is not None:raise
            raise LocalInputError(str(error)) from None
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            def emit(value):
                self.wfile.write(json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b'\n')
                self.wfile.flush()
            emit(runtime.accepted(chat_id, message_id))
            for event in runtime.observe(chat_id, operation):
                emit(event)
        except OSError:
            pass  # The accepted worker persists its final result independently.

    do_GET = _request
    do_POST = _request

    def do_OPTIONS(self):
        self._json(403, {'error': 'cross_origin_access_denied'})
