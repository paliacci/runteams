"""Run profile-bound external triggers and meeting delivery inside the application."""

from contextlib import closing
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import re
import sqlite3
import threading
from uuid import NAMESPACE_URL, uuid5

from runteams_core.foundation.regular_files import sqlite_file_uri

from runteams_core.automation import composio_realtime, fireflies_recaps
from runteams_core.configuration.credentials import app_secrets
from runteams_core.employees.mcp.composio_connections import ComposioError, accounts, request, slug
from runteams_core.employees.mcp.employee_applications import bindings
from runteams_core.foundation.contracts import ContractError
from runteams_core.storage import device_data, local_database, product_store


DIRECTORY = 'connected-automations'
CONFIG = 'settings.json'
DATABASE = 'receipts.sqlite3'
SCHEMA = """
CREATE TABLE IF NOT EXISTS gmail_events (
    operation TEXT PRIMARY KEY, received TEXT NOT NULL, state TEXT NOT NULL, dispatched TEXT
);
CREATE TABLE IF NOT EXISTS recaps (
    id TEXT PRIMARY KEY, state TEXT NOT NULL, mail_id TEXT, changed_at TEXT NOT NULL
);
"""
RETRY_ERRORS = (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error,
                http.client.HTTPException, ComposioError, ContractError)


def _now():
    return datetime.now(timezone.utc).isoformat()


def directory():
    return device_data.root() / DIRECTORY


def _private(path):
    stat = path.stat()
    if path.is_symlink() or stat.st_mode & 0o077:
        raise PermissionError('本机连接自动化的配置权限无效。')
    return path


def load_config():
    folder = directory()
    path = folder / CONFIG
    if not path.exists():
        return None
    settings = json.loads(_private(path).read_text())
    if (settings.get('schema') != 'runteams.connected-automations/1'
            or settings.get('scope') != device_data.identity()
            or not isinstance(settings.get('employee'), dict)):
        raise PermissionError('本机连接自动化的账户配置已变化。')
    return settings


class ConnectedEmployeeRuntime:
    def __init__(self, config, schedules, wake, run_turn):
        self.config = config
        self.schedules = schedules
        self.wake = wake
        self.run_turn = run_turn
        self.root = directory()
        self.stop = threading.Event()
        self.changed = threading.Event()
        self.working = threading.Event()
        self.socket = None
        self.threads = []
        self.status = {'gmail_push': 'connecting', 'fireflies': 'starting'}

    def _check(self):
        device_data.check(self.config['scope'])
        if self.stop.is_set():
            raise PermissionError('本机连接自动化正在停止。')

    def _database(self):
        path = self.root / DATABASE
        if path.exists():
            _private(path)
        else:
            try:
                path.touch(mode=0o600, exist_ok=False)
            except FileExistsError:
                _private(path)
        return sqlite3.connect(path, timeout=8)

    def _secret(self, name):
        self._check()
        path = _private(self.root / 'credentials.json')
        with app_secrets.vault_scope(path):
            value = app_secrets.resolve([name]).get(name)
        if not value:
            raise PermissionError('缺少本机自动化凭据。')
        return value

    def _switch_socket(self, connection):
        self.socket = connection
        if connection is not None and self.stop.is_set():
            connection.shutdown()

    def start(self):
        _private(self.root)
        with closing(self._database()) as db:
            db.executescript(SCHEMA)
        for name, worker in (('gmail-realtime', self._receive_gmail), ('gmail-dispatch', self._dispatch_gmail),
                             ('fireflies', self._poll_fireflies)):
            thread = threading.Thread(name='runteams-' + name, target=worker, daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self):
        self.stop.set()
        self.changed.set()
        socket = self.socket
        if socket is not None:
            socket.shutdown()
        for thread in self.threads:
            thread.join(4)

    def _receive_gmail(self):
        import websocket

        delay = 1

        def on_ready():
            nonlocal delay
            delay = 1
            self.status['gmail_push'] = 'listening'

        while not self.stop.is_set():
            try:
                key = self._secret('composio_trigger')
                composio_realtime.subscribe(key, self.stop, self._remember_gmail, on_ready, self._switch_socket)
            except (*RETRY_ERRORS, websocket.WebSocketException):
                self.status['gmail_push'] = 'reconnecting'
            self.status['gmail_push'] = 'reconnecting'
            self.stop.wait(delay)
            delay = min(30, delay * 2)

    def _remember_gmail(self, event):
        self._check()
        options = self.config['gmail']
        operation = composio_realtime.gmail_operation(event, account=options['account'],
                                                      user=options['user'], trigger=options['trigger'])
        if operation is None:
            return
        with closing(self._database()) as db, db:
            db.execute("INSERT OR IGNORE INTO gmail_events VALUES (?,?,'pending',NULL)", (operation, _now()))
        self.changed.set()

    def _dispatch_gmail(self):
        while not self.stop.is_set():
            self.changed.clear()
            try:
                self._check()
                with closing(self._database()) as db:
                    pending = db.execute("SELECT operation FROM gmail_events WHERE state='pending' ORDER BY received LIMIT 1").fetchone()
                    if pending:
                        outcome = self._start_gmail(pending[0])
                        if outcome:
                            with db:
                                db.execute('UPDATE gmail_events SET state=?,dispatched=? WHERE operation=?',
                                           (outcome, _now(), pending[0]))
            except RETRY_ERRORS:
                pass  # A busy plan or a storage rotation leaves the event queued.
            self.changed.wait(3)

    def _start_gmail(self, operation):
        options = self.config['gmail']
        ref = self.config['employee']
        backend = self.schedules()
        if not backend.dispatch_allowed(options['schedule_id']):
            return None
        receipt = backend.receipt(operation)
        if receipt['state'] == 'committed':
            return 'accepted' if receipt['result']['id'] == options['schedule_id'] else 'skipped'
        if receipt['state'] != 'unknown':
            return 'skipped'
        row = next((row for row in backend.list_reference(ref)['items'] if row['id'] == options['schedule_id']), None)
        if row is None or not row['enabled']:
            return None
        self._bound_gmail()
        self._check()
        backend.command({'operation_id': operation, 'action': 'run', 'id': row['id'],
                         'expected_revision': row['revision'], 'reference': ref, 'value': None})
        self.wake()
        return 'accepted'

    def _bound_gmail(self):
        self._check()
        expected = self.config['gmail']
        apps = bindings({'action': 'employee-apps-read', 'employee': self.config['employee']})['applications']
        matches = [entry['account']['id'] for entry in apps if entry['provider'] == 'composio'
                   and entry['id'] == 'gmail' and entry.get('account')]
        if matches != [expected['account']]:
            raise PermissionError('Eva 的 Gmail 连接已变化。')
        return expected

    def _gmail_for_recipient(self):
        expected = self._bound_gmail()
        root = Path(local_database.DB_PATH).resolve().parent / 'host-credentials/mcp-connections'
        scope = self.config['scope']['cache_scope']
        db = root / (scope + '.sqlite3')
        with closing(sqlite3.connect(sqlite_file_uri(db) + '?mode=ro', uri=True)) as conn:
            user = conn.execute("SELECT value FROM composio_settings WHERE name='user_id'").fetchone()
        if not user or user[0] != expected['user']:
            raise PermissionError('Composio 项目账户已变化。')
        with app_secrets.vault_scope(root / (scope + '.secrets.json')):
            key = app_secrets.resolve(['composio']).get('composio')
        if not key or not any(row['id'] == expected['account'] and row['status'] == 'ACTIVE'
                              and not row['disabled'] for row in accounts(key, user[0], 'gmail')):
            raise PermissionError('Eva 的 Gmail 连接已失效。')
        session = slug(request(key, 'POST', '/tool_router/session', body={
            'user_id': user[0], 'toolkits': {'enable': ['gmail']}, 'instant': False,
            'multi_account': {'enable': True, 'require_explicit_selection': True},
            'workbench': {'enable': False}, 'manage_connections': {'enable': False, 'enable_connection_removal': False},
        })['session_id'])
        recipient = self.config['fireflies']['recipient']

        def gmail(tool, args):
            self._check()
            if tool == 'GMAIL_SEND_EMAIL' and (args.get('recipient_email') != recipient or
                                               not set(args) <= {'user_id', 'recipient_email', 'subject', 'body',
                                                                 'include_signature', 'is_html'}):
                raise PermissionError('会后纪要只发给本人。')
            result = request(key, 'POST', f'/tool_router/session/{session}/execute',
                             body={'tool_slug': tool, 'account': expected['account'], 'arguments': args}, execution=True)
            if result.get('result_type') != 'completed':
                raise RuntimeError(f'Gmail did not confirm {tool}')
            data = result['data']
            return data.get('response_data', data)

        profile = gmail('GMAIL_GET_PROFILE', {'user_id': 'me'})
        if (profile.get('emailAddress') or profile.get('email_address') or '').lower() != recipient:
            raise PermissionError('会后纪要的 Gmail 收件人已变化。')
        return gmail

    def _poll_fireflies(self):
        config = self.config['fireflies']
        if not re.fullmatch(r'[a-z0-9._+-]+@[a-z0-9.-]+', config['recipient']):
            self.status['fireflies'] = 'configuration_error'
            return
        while not self.stop.is_set():
            try:
                self._check()
                backend = self.schedules()
                if not backend.dispatch_allowed(self.config['gmail']['schedule_id']):
                    self.status['fireflies'] = 'paused'
                    self.stop.wait(30)
                    continue
                key = self._secret('fireflies')
                ids = list(fireflies_recaps.matching_transcripts(key, config))
                self.status['fireflies'] = 'watching'
                with closing(self._database()) as db:
                    pending = [row[0] for row in db.execute("SELECT id FROM recaps WHERE state IN ('submitting','sending','sent')")]
                    for identifier in dict.fromkeys(pending + ids):
                        if self.stop.is_set():
                            break
                        self.working.set()
                        try:
                            fireflies_recaps.process(db, identifier, key, config,
                                history=lambda: product_store.get_chat(config['eva_chat']),
                                turn=lambda marker, prompt: self.run_turn(
                                    self.config['scope'], str(uuid5(NAMESPACE_URL, marker)),
                                    config['eva_chat'], prompt, self.stop),
                                gmail_for_recipient=self._gmail_for_recipient, stopped=self.stop.is_set)
                        except RETRY_ERRORS:
                            self.status['fireflies'] = 'pending_retry'
                        finally:
                            self.working.clear()
            except RETRY_ERRORS:
                self.status['fireflies'] = 'reconnecting'
            self.stop.wait(30)
