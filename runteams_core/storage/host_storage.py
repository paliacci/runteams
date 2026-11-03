from runteams_core.foundation.resources import root as resource_root
"""Device host settings/secrets only. Business SQL is never sent to a server."""
from contextlib import contextmanager
import re
import sqlite3
from pathlib import Path
from runteams_core.foundation.contracts import ContractError
from runteams_core.storage.storage_context import current_provider


def _unsupported(module):
    current_provider().reject_host_business(module)

HOST_TABLES = frozenset({'model_channels','credential_entries','local_asset_grants',
    'mobile_host_sync','mobile_host_retirements','mobile_command_receipts',
    'mobile_command_result_outbox','chat_runtime_links'})

# Old OAuth rows may remain on disk; no current route may read or write them.
RETIRED_HOST_TABLES = frozenset({'mail_oauth_pending'})


def referenced_tables(sql):
    # Ignore string literals, including JSON bodies; quoted identifiers remain.
    tokens = re.sub(r"'(?:''|[^'])*'", "''", str(sql))
    tokens = re.sub(r'\bDO\s+UPDATE\s+SET\b', 'DO SET', tokens, flags=re.I)
    return set(re.findall(r'\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+["`\[]?([a-z_][a-z_0-9]*)', tokens, re.I))


class HostStorage:
    file_cloud = None
    def __init__(self, path):
        self.path = str(path)
        self._identity = self._current_identity()

    @staticmethod
    def _current_identity():
        return current_provider().host_identity()

    def check_scope(self):
        if self._identity != self._current_identity():
            raise PermissionError('账户或工作区已变化，请重新打开。')

    def initialize(self):
        schema = resource_root() / 'contracts/host-execution.sql'
        with sqlite3.connect(self.path, timeout=30) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables - HOST_TABLES - RETIRED_HOST_TABLES - {'product_model','document_native_links'}:
                raise ContractError('这个数据文件包含旧业务数据，原数据保持不变。')
            if 'document_native_links' in tables:
                connection.execute('DROP TABLE document_native_links')
            connection.executescript(schema.read_text())

    @contextmanager
    def connect(self):
        self.check_scope()
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield HostConnection(connection)
                self.check_scope()
        finally:
            connection.close()

    def data_epoch(self):
        _unsupported('业务数据')

    def rotate_data_epoch(self):
        _unsupported('业务数据')

    def recovery_ids(self, domain):
        _unsupported('业务恢复')

    def definition_lock(self):
        _unsupported('资产编辑')

    def canonical_data(self, value):
        _unsupported('资产保存')


class HostConnection:
    def __init__(self, connection):
        self.connection = connection

    @property
    def in_transaction(self):
        return self.connection.in_transaction

    @property
    def total_changes(self):
        return self.connection.total_changes

    def execute(self, sql, parameters=()):
        tables = referenced_tables(sql)
        if tables and tables <= HOST_TABLES:
            return self.connection.execute(sql, parameters)
        if str(sql).strip().upper() in ('BEGIN', 'BEGIN IMMEDIATE', 'BEGIN TRANSACTION'):
            return self.connection.execute(sql)
        _unsupported('这项业务')

    def begin_write(self):
        _unsupported('这项业务')

    def executescript(self, script):
        raise ContractError('不能通过业务入口修改本机数据结构。')
