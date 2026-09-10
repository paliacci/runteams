# -*- coding: utf-8 -*-
"""RunTeams production shell persistence.

Business assets live in the independent core database.  This module owns only
local application-shell state: credentials metadata, Agent Channels, chats,
automations, and encrypted mobile relay bookkeeping.
"""
import base64
import json
import os
import re
import secrets
import sqlite3

import automation_store
import local_database
import provider_catalog


data_dir = local_database.data_dir
conn = local_database.conn
now = local_database.now
_lock = local_database.lock


PRODUCT_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state(
  key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS credential_entries(
  name TEXT PRIMARY KEY,
  pos INTEGER NOT NULL DEFAULT 0,
  source_name TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_channels(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT 'claude-code', executable TEXT NOT NULL DEFAULT '',
  config_dir TEXT NOT NULL DEFAULT '', default_model TEXT NOT NULL DEFAULT '',
  default_effort TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1, is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chats(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT '新对话',
  title_source TEXT NOT NULL DEFAULT 'pending',
  kind TEXT NOT NULL DEFAULT 'general', context_json TEXT NOT NULL DEFAULT '{}',
  draft_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active',
  channel_id INTEGER, model TEXT NOT NULL DEFAULT '', reasoning_effort TEXT NOT NULL DEFAULT '',
  scope_pipeline_id INTEGER, extensions_enabled INTEGER NOT NULL DEFAULT 0,
  subject_type TEXT NOT NULL DEFAULT 'workspace', employee_id INTEGER,
  employee_release_id INTEGER, employee_release_digest TEXT NOT NULL DEFAULT '',
  scope_type TEXT NOT NULL DEFAULT 'global', scope_run_id INTEGER,
  runtime_provider TEXT NOT NULL DEFAULT '', runtime_thread_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
  role TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', applied TEXT,
  attachments TEXT NOT NULL DEFAULT '[]', capabilities TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}', ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mobile_host_sync(
  singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
  account_id TEXT NOT NULL DEFAULT '',
  host_id TEXT NOT NULL UNIQUE, snapshot_key TEXT NOT NULL, writer_token TEXT NOT NULL,
  created_at TEXT NOT NULL, relay_registered_at TEXT NOT NULL DEFAULT '',
  relay_last_synced_at TEXT NOT NULL DEFAULT '', relay_last_snapshot_version INTEGER NOT NULL DEFAULT 0,
  relay_last_snapshot_hash TEXT NOT NULL DEFAULT '', relay_last_error TEXT NOT NULL DEFAULT '',
  relay_push_state_json TEXT NOT NULL DEFAULT '', relay_device_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS mobile_host_retirements(
  host_id TEXT PRIMARY KEY, writer_token TEXT NOT NULL,
  created_at TEXT NOT NULL, last_attempt_at TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS mobile_command_receipts(
  command_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, sequence INTEGER NOT NULL,
  issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, action TEXT NOT NULL,
  target_id TEXT NOT NULL, action_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing', result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '',
  UNIQUE(device_id,sequence));
CREATE TABLE IF NOT EXISTS mobile_command_result_outbox(
  command_id TEXT PRIMARY KEY, result_json TEXT NOT NULL,
  created_at TEXT NOT NULL, uploaded_at TEXT NOT NULL DEFAULT '');
"""


def _load(connection, sql, args=()):
    return [dict(row) for row in connection.execute(sql, args).fetchall()]


def core_data_root():
    configured = (os.environ.get("RUNTEAMS_CORE_DATA") or "").strip()
    return os.path.realpath(configured or os.path.join(
        os.path.dirname(os.path.abspath(local_database.DB_PATH)), "core"))


def assistant_workspace():
    """Managed workspace shared by General Chat, Employee design, and attachments."""
    configured = (os.environ.get("RUNTEAMS_WORKSPACES") or "").strip()
    root = os.path.realpath(os.path.expanduser(configured)) if configured else os.path.join(
        data_dir(), "workspaces")
    path = os.path.realpath(os.path.join(root, "assistant"))
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _table_exists(connection, name):
    return bool(connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _ensure_channels(connection):
    timestamp = now()
    existing = {row[0] for row in connection.execute("SELECT provider FROM model_channels")}
    has_default = bool(connection.execute(
        "SELECT 1 FROM model_channels WHERE is_default=1 LIMIT 1").fetchone())
    for item in provider_catalog.PROVIDERS:
        provider = item["id"]
        if provider in existing:
            continue
        is_default = 1 if item.get("default") and not has_default else 0
        connection.execute(
            "INSERT INTO model_channels(name,provider,default_model,default_effort,enabled,is_default,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (item["channel_name"], provider, "", "", 1, is_default, timestamp, timestamp),
        )
        existing.add(provider)
        has_default = has_default or bool(is_default)


def _dedupe_channels(connection):
    """Keep one local Agent Channel per provider and repair shell references."""
    for provider in provider_catalog.provider_ids():
        rows = connection.execute(
            "SELECT id FROM model_channels WHERE provider=? ORDER BY is_default DESC,id",
            (provider,),
        ).fetchall()
        if len(rows) < 2:
            continue
        keep = rows[0][0]
        for row in rows[1:]:
            duplicate = row[0]
            connection.execute(
                "UPDATE chats SET channel_id=? WHERE channel_id=?", (keep, duplicate)
            )
            connection.execute("DELETE FROM model_channels WHERE id=?", (duplicate,))


def _migrate_product_schema(connection):
    """Migrate only the local product shell; never touch retired business tables."""
    credential_cols = {
        row[1] for row in connection.execute("PRAGMA table_info(credential_entries)")
    }
    if "group_id" in credential_cols:
        if _table_exists(connection, "credential_groups"):
            rows = connection.execute(
                "SELECT e.name,e.created_at,e.updated_at FROM credential_entries e "
                "LEFT JOIN credential_groups g ON g.id=e.group_id "
                "ORDER BY CASE WHEN e.group_id IS NULL THEN 0 ELSE 1 END,"
                "COALESCE(g.pos,0),e.pos,e.name"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT name,created_at,updated_at FROM credential_entries ORDER BY pos,name"
            ).fetchall()
        connection.execute("ALTER TABLE credential_entries RENAME TO credential_entries_grouped")
        connection.execute(
            "CREATE TABLE credential_entries("
            "name TEXT PRIMARY KEY,pos INTEGER NOT NULL DEFAULT 0,"
            "source_name TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        for pos, row in enumerate(rows, 1):
            connection.execute(
                "INSERT INTO credential_entries(name,pos,created_at,updated_at) VALUES(?,?,?,?)",
                (row["name"], pos, row["created_at"], row["updated_at"]),
            )
        connection.execute("DROP TABLE credential_entries_grouped")
    connection.execute("DROP TABLE IF EXISTS credential_groups")
    credential_cols = {
        row[1] for row in connection.execute("PRAGMA table_info(credential_entries)")
    }
    if "source_name" not in credential_cols:
        connection.execute(
            "ALTER TABLE credential_entries ADD COLUMN source_name TEXT NOT NULL DEFAULT ''"
        )

    channel_cols = {
        row[1] for row in connection.execute("PRAGMA table_info(model_channels)")
    }
    if "default_effort" not in channel_cols:
        connection.execute(
            "ALTER TABLE model_channels ADD COLUMN default_effort TEXT NOT NULL DEFAULT ''"
        )

    chat_columns = {
        "channel_id": "INTEGER",
        "model": "TEXT NOT NULL DEFAULT ''",
        "reasoning_effort": "TEXT NOT NULL DEFAULT ''",
        "scope_pipeline_id": "INTEGER",
        "extensions_enabled": "INTEGER NOT NULL DEFAULT 0",
        "runtime_provider": "TEXT NOT NULL DEFAULT ''",
        "runtime_thread_id": "TEXT NOT NULL DEFAULT ''",
        "title_source": "TEXT NOT NULL DEFAULT ''",
        "kind": "TEXT NOT NULL DEFAULT 'general'",
        "context_json": "TEXT NOT NULL DEFAULT '{}'",
        "draft_json": "TEXT NOT NULL DEFAULT '{}'",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "subject_type": "TEXT NOT NULL DEFAULT 'workspace'",
        "employee_id": "INTEGER",
        "employee_release_id": "INTEGER",
        "employee_release_digest": "TEXT NOT NULL DEFAULT ''",
        "scope_type": "TEXT NOT NULL DEFAULT 'global'",
        "scope_run_id": "INTEGER",
    }
    existing = {row[1] for row in connection.execute("PRAGMA table_info(chats)")}
    for name, definition in chat_columns.items():
        if name not in existing:
            connection.execute("ALTER TABLE chats ADD COLUMN {} {}".format(name, definition))
    # Backfill the canonical Bot binding from the legacy opaque context.  Keep
    # the original JSON for older clients, but make the identity queryable by
    # the new runtime and API.
    connection.execute(
        "UPDATE chats SET subject_type='employee',employee_id=CAST(COALESCE("
        "json_extract(context_json,'$.target_employee_id'),"
        "json_extract(context_json,'$.target_worker_id'),"
        "json_extract(context_json,'$.worker_id')) AS INTEGER) "
        "WHERE kind='general' AND subject_type='workspace' AND json_valid(context_json) AND COALESCE("
        "json_extract(context_json,'$.target_employee_id'),"
        "json_extract(context_json,'$.target_worker_id'),"
        "json_extract(context_json,'$.worker_id')) IS NOT NULL"
    )
    connection.execute(
        "UPDATE chats SET title='新对话',title_source='pending' "
        "WHERE title_source='' AND title=("
        "SELECT substr(trim(replace(replace(m.text,char(13),' '),char(10),' ')),1,24) "
        "FROM chat_messages m WHERE m.chat_id=chats.id AND m.role='user' ORDER BY m.id LIMIT 1)"
    )
    connection.execute(
        "UPDATE chats SET title_source=CASE WHEN title='新对话' THEN 'pending' ELSE 'manual' END "
        "WHERE title_source=''"
    )
    connection.execute(
        "UPDATE chats SET scope_type='pipeline' WHERE scope_pipeline_id IS NOT NULL "
        "AND scope_type='global'"
    )

    message_columns = {
        "attachments": "TEXT NOT NULL DEFAULT '[]'",
        "capabilities": "TEXT NOT NULL DEFAULT '[]'",
        "metadata": "TEXT NOT NULL DEFAULT '{}'",
    }
    existing = {row[1] for row in connection.execute("PRAGMA table_info(chat_messages)")}
    for name, definition in message_columns.items():
        if name not in existing:
            connection.execute(
                "ALTER TABLE chat_messages ADD COLUMN {} {}".format(name, definition)
            )

    host_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(mobile_host_sync)")
    }
    if "account_id" not in host_columns:
        connection.execute(
            "ALTER TABLE mobile_host_sync ADD COLUMN account_id TEXT NOT NULL DEFAULT ''"
        )
    connection.execute("DROP TABLE IF EXISTS mobile_pairings")
    _ensure_channels(connection)
    _dedupe_channels(connection)
    for item in provider_catalog.PROVIDERS:
        connection.execute(
            "UPDATE model_channels SET name=?,executable='',config_dir='' WHERE provider=?",
            (item["channel_name"], item["id"]),
        )
    connection.execute("UPDATE model_channels SET default_model='',default_effort=''")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_model_channels_provider ON model_channels(provider)"
    )
    default_row = connection.execute(
        "SELECT id FROM model_channels WHERE is_default=1 ORDER BY id LIMIT 1"
    ).fetchone()
    if default_row:
        connection.execute(
            "UPDATE chats SET channel_id=? WHERE channel_id IS NULL", (default_row[0],)
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id,id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_mobile_commands_device_sequence "
        "ON mobile_command_receipts(device_id,sequence DESC)"
    )


def init_product_db():
    with _lock, conn() as connection:
        connection.executescript("BEGIN IMMEDIATE;\n" + PRODUCT_SCHEMA)
        automation_store.init_schema(connection)
        _migrate_product_schema(connection)


# Agent Channels
def list_channels():
    with conn() as connection:
        return _load(connection, "SELECT * FROM model_channels ORDER BY is_default DESC,id")


def get_channel(channel_id):
    with conn() as connection:
        row = connection.execute(
            "SELECT * FROM model_channels WHERE id=?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None


def get_default_channel(provider=None):
    with conn() as connection:
        if provider:
            row = connection.execute(
                "SELECT * FROM model_channels WHERE provider=? AND enabled=1 "
                "ORDER BY is_default DESC,id LIMIT 1", (provider,)
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM model_channels WHERE enabled=1 "
                "ORDER BY is_default DESC,id LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


def upsert_channel(channel_id, fields):
    columns = ("name", "provider", "executable", "config_dir", "enabled", "is_default")
    values = {key: fields[key] for key in columns if key in fields}
    values["updated_at"] = now()
    with _lock, conn() as connection:
        provider = values.get("provider")
        if not channel_id and provider:
            row = connection.execute(
                "SELECT id FROM model_channels WHERE provider=?", (provider,)
            ).fetchone()
            channel_id = row[0] if row else None
        if values.get("is_default"):
            connection.execute("UPDATE model_channels SET is_default=0")
        if channel_id:
            sets = ",".join("{}=?".format(key) for key in values)
            connection.execute(
                "UPDATE model_channels SET {} WHERE id=?".format(sets),
                list(values.values()) + [channel_id],
            )
            connection.execute(
                "UPDATE model_channels SET default_model='',default_effort='' WHERE id=?",
                (channel_id,),
            )
            return channel_id
        values["created_at"] = now()
        return connection.execute(
            "INSERT INTO model_channels({}) VALUES({})".format(
                ",".join(values), ",".join("?" * len(values))
            ), list(values.values()),
        ).lastrowid


def delete_channel(_channel_id):
    return False, "内置厂商渠道不能删除，可以在设置中停用"


def set_channel_enabled(channel_id, enabled):
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE model_channels SET enabled=?,updated_at=? WHERE id=?",
            (1 if enabled else 0, now(), channel_id),
        )
        return connection.total_changes > 0


# Credential metadata (secret values remain in app_secrets).
def list_credential_entries():
    with conn() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT name,pos,source_name,created_at,updated_at "
            "FROM credential_entries ORDER BY pos,name"
        )]


def save_credential_entry(name, source_name=None):
    name = str(name or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,119}", name):
        raise ValueError("Key 只能包含字母、数字和下划线，且不能以数字开头")
    clean_source = os.path.basename(str(source_name or ""))[:255]
    with _lock, conn() as connection:
        timestamp = now()
        row = connection.execute(
            "SELECT name FROM credential_entries WHERE name=?", (name,)
        ).fetchone()
        if row:
            if source_name is None:
                connection.execute(
                    "UPDATE credential_entries SET updated_at=? WHERE name=?",
                    (timestamp, name),
                )
            else:
                connection.execute(
                    "UPDATE credential_entries SET source_name=?,updated_at=? WHERE name=?",
                    (clean_source, timestamp, name),
                )
        else:
            position = connection.execute(
                "SELECT COALESCE(MAX(pos),0)+1 FROM credential_entries"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO credential_entries(name,pos,source_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?)",
                (name, position, clean_source, timestamp, timestamp),
            )
    return {"name": name, "source_name": clean_source}


def set_credential_source_names(values):
    values = values if isinstance(values, dict) else {}
    timestamp = now()
    with _lock, conn() as connection:
        known = {row["name"] for row in connection.execute(
            "SELECT name FROM credential_entries")}
        for name, source_name in values.items():
            if name in known:
                connection.execute(
                    "UPDATE credential_entries SET source_name=?,updated_at=? WHERE name=?",
                    (os.path.basename(str(source_name or ""))[:255], timestamp, name),
                )


def reorder_credential_entries(order):
    names = [str(name or "").strip() for name in (order or [])]
    if not names or len(names) != len(set(names)):
        raise ValueError("凭据顺序无效")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,119}", name) for name in names):
        raise ValueError("凭据顺序包含无效 Key")
    timestamp = now()
    with _lock, conn() as connection:
        existing = {row["name"] for row in connection.execute(
            "SELECT name FROM credential_entries")}
        if not existing.issubset(set(names)):
            raise ValueError("凭据顺序不完整")
        for position, name in enumerate(names, 1):
            if name in existing:
                connection.execute(
                    "UPDATE credential_entries SET pos=?,updated_at=? WHERE name=?",
                    (position, timestamp, name),
                )
            else:
                connection.execute(
                    "INSERT INTO credential_entries(name,pos,created_at,updated_at) VALUES(?,?,?,?)",
                    (name, position, timestamp, timestamp),
                )
    return list_credential_entries()


def delete_credential_entry(name):
    with _lock, conn() as connection:
        removed = connection.execute(
            "DELETE FROM credential_entries WHERE name=?", (str(name or "").strip(),)
        ).rowcount
    return bool(removed)


# Mobile relay durability.
def claim_mobile_command(command_id, device_id, sequence, issued_at, expires_at,
                         action, target_id, action_id):
    with _lock, conn() as connection:
        existing = connection.execute(
            "SELECT status,result_json FROM mobile_command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if existing:
            try:
                result = json.loads(existing["result_json"] or "{}")
            except (TypeError, ValueError):
                result = {}
            return {"existing": True, "status": existing["status"], "result": result}
        latest = connection.execute(
            "SELECT MAX(sequence) FROM mobile_command_receipts WHERE device_id=?", (device_id,)
        ).fetchone()[0]
        if latest is not None and int(sequence) <= int(latest):
            return {"claimed": False, "message": "检测到重复或乱序指令"}
        try:
            connection.execute(
                "INSERT INTO mobile_command_receipts(command_id,device_id,sequence,issued_at,"
                "expires_at,action,target_id,action_id,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,'processing',?)",
                (command_id, device_id, int(sequence), issued_at, expires_at,
                 action, target_id, action_id, now()),
            )
        except sqlite3.IntegrityError:
            return {"claimed": False, "message": "检测到重复指令"}
        return {"claimed": True}


def complete_mobile_command(command_id, status, result):
    if status not in ("succeeded", "rejected"):
        raise ValueError("invalid mobile command status")
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE mobile_command_receipts SET status=?,result_json=?,completed_at=? "
            "WHERE command_id=?",
            (status, json.dumps(result or {}, ensure_ascii=False, separators=(",", ":")),
             now(), command_id),
        )


def queue_mobile_command_result(command_id, result):
    with _lock, conn() as connection:
        connection.execute(
            """INSERT INTO mobile_command_result_outbox(command_id,result_json,created_at)
                 VALUES(?,?,?) ON CONFLICT(command_id) DO UPDATE SET
                 result_json=excluded.result_json,uploaded_at=''""",
            (command_id, json.dumps(result, ensure_ascii=False, separators=(",", ":")), now()),
        )


def pending_mobile_command_results(limit=100):
    with conn() as connection:
        rows = connection.execute(
            "SELECT command_id,result_json FROM mobile_command_result_outbox "
            "WHERE uploaded_at='' ORDER BY created_at,command_id LIMIT ?",
            (max(1, min(500, int(limit or 100))),),
        ).fetchall()
    result = []
    for row in rows:
        try:
            envelope = json.loads(row["result_json"] or "{}")
        except (TypeError, ValueError):
            continue
        result.append({"command_id": row["command_id"], "result": envelope})
    return result


def mark_mobile_command_result_uploaded(command_id):
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE mobile_command_result_outbox SET uploaded_at=? WHERE command_id=?",
            (now(), command_id),
        )


def _retire_mobile_host(connection, row):
    if not row:
        return None
    connection.execute(
        "INSERT INTO mobile_host_retirements(host_id,writer_token,created_at) VALUES(?,?,?) "
        "ON CONFLICT(host_id) DO UPDATE SET writer_token=excluded.writer_token,last_error=''",
        (row["host_id"], row["writer_token"], now()),
    )
    connection.execute("DELETE FROM mobile_host_sync WHERE singleton_id=1")
    connection.execute("DELETE FROM mobile_command_result_outbox")
    connection.execute("DELETE FROM mobile_command_receipts")
    return dict(row)


def get_mobile_host_sync():
    with conn() as connection:
        row = connection.execute(
            "SELECT * FROM mobile_host_sync WHERE singleton_id=1"
        ).fetchone()
        return dict(row) if row else None


def get_or_create_mobile_host_sync(account_id=""):
    account_id = str(account_id or "")
    with _lock, conn() as connection:
        row = connection.execute(
            "SELECT * FROM mobile_host_sync WHERE singleton_id=1"
        ).fetchone()
        if row and account_id and row["account_id"] != account_id:
            _retire_mobile_host(connection, row)
            row = None
        if not row:
            encoded_key = base64.urlsafe_b64encode(
                secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
            connection.execute(
                "INSERT INTO mobile_host_sync(singleton_id,account_id,host_id,snapshot_key,writer_token,created_at) "
                "VALUES(1,?,?,?,?,?)",
                (account_id, secrets.token_hex(16), encoded_key, secrets.token_urlsafe(32), now()),
            )
            row = connection.execute(
                "SELECT * FROM mobile_host_sync WHERE singleton_id=1"
            ).fetchone()
        return dict(row)


def retire_mobile_host_sync():
    with _lock, conn() as connection:
        row = connection.execute(
            "SELECT * FROM mobile_host_sync WHERE singleton_id=1"
        ).fetchone()
        return _retire_mobile_host(connection, row)


def pending_mobile_host_retirements():
    with conn() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT host_id,writer_token,created_at,last_attempt_at,last_error "
            "FROM mobile_host_retirements ORDER BY created_at"
        ).fetchall()]


def mark_mobile_host_retired(host_id):
    with _lock, conn() as connection:
        connection.execute("DELETE FROM mobile_host_retirements WHERE host_id=?", (host_id,))


def mark_mobile_host_retirement_error(host_id, error):
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE mobile_host_retirements SET last_attempt_at=?,last_error=? WHERE host_id=?",
            (now(), (error or "撤销失败")[:500], host_id),
        )


def mark_mobile_host_registered(device_count=0):
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE mobile_host_sync SET relay_registered_at=?,relay_device_count=?,relay_last_error='' "
            "WHERE singleton_id=1", (now(), max(0, int(device_count or 0))),
        )


def mark_mobile_host_synced(snapshot_version, snapshot_hash, device_count=0):
    timestamp = now()
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE mobile_host_sync SET relay_registered_at=COALESCE(NULLIF(relay_registered_at,''),?),"
            "relay_last_synced_at=?,relay_last_snapshot_version=?,relay_last_snapshot_hash=?,"
            "relay_last_error='',relay_device_count=? WHERE singleton_id=1",
            (timestamp, timestamp, int(snapshot_version), snapshot_hash,
             max(0, int(device_count or 0))),
        )


def mark_mobile_host_push_state(state_json):
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE mobile_host_sync SET relay_push_state_json=? WHERE singleton_id=1",
            ((state_json or "")[:20000],),
        )


def mark_mobile_host_relay_error(error):
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE mobile_host_sync SET relay_last_error=? WHERE singleton_id=1",
            ((error or "中转同步失败")[:500],),
        )


# Chats and Employee design sessions.
def list_chats():
    with conn() as connection:
        return _load(
            connection,
        "SELECT id,title,title_source,kind,status,channel_id,model,reasoning_effort,"
            "scope_pipeline_id,extensions_enabled,subject_type,employee_id,"
            "employee_release_id,employee_release_digest,scope_type,scope_run_id,"
            "runtime_provider,runtime_thread_id,"
            "updated_at,context_json,"
            "(SELECT text FROM chat_messages m WHERE m.chat_id=chats.id ORDER BY m.id DESC LIMIT 1) AS last_message_text,"
            "(SELECT ts FROM chat_messages m WHERE m.chat_id=chats.id ORDER BY m.id DESC LIMIT 1) AS last_message_at,"
            "(SELECT text FROM chat_messages m WHERE m.chat_id=chats.id AND m.role='bot' ORDER BY m.id DESC LIMIT 1) AS last_bot_message_text,"
            "(SELECT ts FROM chat_messages m WHERE m.chat_id=chats.id AND m.role='bot' ORDER BY m.id DESC LIMIT 1) AS last_bot_message_at "
            "FROM chats WHERE kind!='automation' "
            "AND EXISTS(SELECT 1 FROM chat_messages m WHERE m.chat_id=chats.id) "
            "ORDER BY updated_at DESC,id DESC",
        )


def create_chat(channel_id=None, model="", reasoning_effort="", scope_pipeline_id=None,
                extensions_enabled=False, kind="general", context=None,
                subject_type="workspace", employee_id=None, employee_release_id=None,
                employee_release_digest="", scope_type="global", scope_run_id=None):
    kind = "automation" if kind == "automation" else "general"
    context = context if isinstance(context, dict) else {}
    subject_type = str(subject_type or "workspace").strip().lower()
    if subject_type not in {"workspace", "employee"}:
        raise ValueError("会话对象类型无效")
    scope_type = str(scope_type or "global").strip().lower()
    if scope_type not in {"global", "pipeline", "run"}:
        raise ValueError("会话作用域无效")
    if subject_type == "employee" and employee_id in (None, ""):
        raise ValueError("员工 Bot 会话缺少员工绑定")
    if subject_type == "employee":
        if scope_type == "pipeline" and scope_pipeline_id in (None, ""):
            raise ValueError("流水线作用域必须绑定流水线")
        if scope_type == "run" and scope_run_id in (None, ""):
            raise ValueError("运行作用域必须绑定 WorkflowRun")
        if scope_type == "global":
            scope_pipeline_id, scope_run_id = None, None
    with _lock, conn() as connection:
        if not channel_id:
            row = connection.execute(
                "SELECT id FROM model_channels WHERE enabled=1 "
                "ORDER BY is_default DESC,id LIMIT 1"
            ).fetchone()
            if row:
                channel_id = row["id"]
        return connection.execute(
            "INSERT INTO chats(title,title_source,kind,context_json,channel_id,model,"
            "reasoning_effort,scope_pipeline_id,extensions_enabled,subject_type,employee_id,"
            "employee_release_id,employee_release_digest,scope_type,scope_run_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("新对话", "pending", kind, json.dumps(context, ensure_ascii=False), channel_id,
             model or "", reasoning_effort or "", scope_pipeline_id,
             1 if extensions_enabled else 0, subject_type,
             int(employee_id) if employee_id not in (None, "") else None,
             int(employee_release_id) if employee_release_id not in (None, "") else None,
             str(employee_release_digest or ""), scope_type,
             int(scope_run_id) if scope_run_id not in (None, "") else None,
             now(), now()),
        ).lastrowid


def create_agent_session(kind, title, channel_id, model, reasoning_effort,
                         scope_pipeline_id, context):
    if str(kind or "").strip() != "employee_design":
        raise ValueError("不支持的 Agent 会话类型")
    with _lock, conn() as connection:
        return connection.execute(
            "INSERT INTO chats(title,title_source,kind,context_json,draft_json,status,channel_id,"
            "model,reasoning_effort,scope_pipeline_id,extensions_enabled,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'active',?,?,?,?,0,?,?)",
            ((title or "Agent 会话").strip(), "system", "employee_design",
             json.dumps(context or {}, ensure_ascii=False), "{}", channel_id,
             model or "", reasoning_effort or "", scope_pipeline_id, now(), now()),
        ).lastrowid


def _message(row):
    item = dict(row)
    for key, fallback in (("applied", []), ("attachments", []),
                          ("capabilities", []), ("metadata", {})):
        try:
            item[key] = json.loads(item.get(key) or json.dumps(fallback))
        except (TypeError, ValueError):
            item[key] = fallback
    return item


def get_chat(chat_id):
    with conn() as connection:
        row = connection.execute(
            "SELECT id,title,title_source,kind,context_json,draft_json,status,channel_id,model,"
            "reasoning_effort,scope_pipeline_id,extensions_enabled,subject_type,employee_id,"
            "employee_release_id,employee_release_digest,scope_type,scope_run_id,runtime_provider,"
            "runtime_thread_id,created_at,updated_at FROM chats WHERE id=?",
            (chat_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        for source, target in (("context_json", "context"), ("draft_json", "draft")):
            try:
                item[target] = json.loads(item.pop(source) or "{}")
            except (TypeError, ValueError):
                item.pop(source, None)
                item[target] = {}
        item["messages"] = [
            _message(message) for message in connection.execute(
                "SELECT id,role,text,applied,attachments,capabilities,metadata,ts "
                "FROM chat_messages WHERE chat_id=? ORDER BY id", (chat_id,)
            ).fetchall()
        ]
        return item


def update_agent_session_draft(chat_id, draft, status="active"):
    state = status if status in ("active", "ready", "applied") else "active"
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE chats SET draft_json=?,status=?,updated_at=? "
            "WHERE id=? AND kind='employee_design'",
            (json.dumps(draft or {}, ensure_ascii=False), state, now(), chat_id),
        )


def update_agent_session_context(chat_id, context, status=None):
    with _lock, conn() as connection:
        if status in ("active", "ready", "applied"):
            connection.execute(
                "UPDATE chats SET context_json=?,status=?,updated_at=? "
                "WHERE id=? AND kind='employee_design'",
                (json.dumps(context or {}, ensure_ascii=False), status, now(), chat_id),
            )
        else:
            connection.execute(
                "UPDATE chats SET context_json=?,updated_at=? "
                "WHERE id=? AND kind='employee_design'",
                (json.dumps(context or {}, ensure_ascii=False), now(), chat_id),
            )


def update_chat_config(chat_id, channel_id, model, reasoning_effort,
                       scope_pipeline_id=None, extensions_enabled=False, context=None):
    with _lock, conn() as connection:
        current = connection.execute(
            "SELECT subject_type FROM chats WHERE id=?", (chat_id,)).fetchone()
        if current and current["subject_type"] == "employee":
            # Employee Bot identity and scope are fixed for the session lifetime.
            # The generic config endpoint is called before every turn by the
            # web client, so accepting its transient pipeline value here could
            # silently detach a run/pipeline-scoped Bot from its audit context.
            connection.execute(
                "UPDATE chats SET channel_id=?,model=?,reasoning_effort=?,"
                "extensions_enabled=?,updated_at=? WHERE id=?",
                (channel_id, model or "", reasoning_effort or "",
                 1 if extensions_enabled else 0, now(), chat_id),
            )
        else:
            connection.execute(
                "UPDATE chats SET channel_id=?,model=?,reasoning_effort=?,scope_pipeline_id=?,"
                "extensions_enabled=?,updated_at=? WHERE id=?",
                (channel_id, model or "", reasoning_effort or "", scope_pipeline_id,
                 1 if extensions_enabled else 0, now(), chat_id),
            )
        if isinstance(context, dict):
            connection.execute(
                "UPDATE chats SET context_json=? WHERE id=? AND kind='general'",
                (json.dumps(context, ensure_ascii=False), chat_id),
            )


def set_chat_employee_release(chat_id, release_id=None, release_digest=""):
    """Record the latest release observed by a Bot turn, without rebinding it."""
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE chats SET employee_release_id=?,employee_release_digest=? "
            "WHERE id=? AND kind='general' AND subject_type='employee'",
            (int(release_id) if release_id not in (None, "") else None,
             str(release_digest or ""), chat_id),
        )


def bind_employee_chat(chat_id, employee_id, employee_release_id=None,
                       employee_release_digest="", scope_type="global",
                       scope_pipeline_id=None, scope_run_id=None):
    """Bind a general chat to one Employee Bot without changing its messages/runtime."""
    try:
        employee_id = int(employee_id)
    except (TypeError, ValueError):
        raise ValueError("员工 Bot 会话缺少有效员工")
    scope_type = str(scope_type or "global").strip().lower()
    if scope_type not in {"global", "pipeline", "run"}:
        raise ValueError("会话作用域无效")
    if scope_type == "pipeline" and scope_pipeline_id in (None, ""):
        raise ValueError("流水线作用域必须绑定流水线")
    if scope_type == "run" and scope_run_id in (None, ""):
        raise ValueError("运行作用域必须绑定 WorkflowRun")
    if scope_type == "global":
        scope_pipeline_id, scope_run_id = None, None
    with _lock, conn() as connection:
        changed = connection.execute(
            "UPDATE chats SET subject_type='employee',employee_id=?,employee_release_id=?,"
            "employee_release_digest=?,scope_type=?,scope_pipeline_id=?,scope_run_id=?,"
            "updated_at=? WHERE id=? AND kind='general'",
            (employee_id,
             int(employee_release_id) if employee_release_id not in (None, "") else None,
             str(employee_release_digest or ""), scope_type,
             int(scope_pipeline_id) if scope_pipeline_id not in (None, "") else None,
             int(scope_run_id) if scope_run_id not in (None, "") else None,
             now(), chat_id),
        ).rowcount
    if changed != 1:
        raise ValueError("对话不存在或不是普通 Bot 会话")
    return get_chat(chat_id)


def add_chat_message(chat_id, role, text, applied=None, attachments=None,
                     capabilities=None, metadata=None):
    with _lock, conn() as connection:
        message_id = connection.execute(
            "INSERT INTO chat_messages(chat_id,role,text,applied,attachments,capabilities,metadata,ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (chat_id, role, text or "", json.dumps(applied or [], ensure_ascii=False),
             json.dumps(attachments or [], ensure_ascii=False),
             json.dumps(capabilities or [], ensure_ascii=False),
             json.dumps(metadata or {}, ensure_ascii=False), now()),
        ).lastrowid
        connection.execute("UPDATE chats SET updated_at=? WHERE id=?", (now(), chat_id))
        return message_id


def get_chat_message(chat_id, message_id):
    with conn() as connection:
        row = connection.execute(
            "SELECT id,role,text,applied,attachments,capabilities,metadata,ts "
            "FROM chat_messages WHERE chat_id=? AND id=?", (chat_id, message_id),
        ).fetchone()
        return _message(row) if row else None


def resolve_chat_plan(chat_id, message_id, applied=None, resolution="applied"):
    """Persist the terminal state of a structured plan on its original bot message."""
    state = "cancelled" if resolution == "cancelled" else "applied"
    with _lock, conn() as connection:
        row = connection.execute(
            "SELECT role,text,metadata FROM chat_messages WHERE chat_id=? AND id=?",
            (chat_id, message_id),
        ).fetchone()
        if not row or row["role"] != "bot":
            raise ValueError("待确认方案已经不存在")
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        if not metadata.get("pending") or not isinstance(metadata.get("plan"), dict):
            raise ValueError("这项方案已经处理")
        metadata.pop("pending", None)
        metadata.pop("plan", None)
        metadata["plan_resolution"] = state
        text = row["text"] or ""
        if state == "cancelled" and "（已保留现状）" not in text:
            text = (text.rstrip() + "\n\n（已保留现状）").strip()
        connection.execute(
            "UPDATE chat_messages SET text=?,applied=?,metadata=? WHERE chat_id=? AND id=?",
            (text, json.dumps(applied or [], ensure_ascii=False),
             json.dumps(metadata, ensure_ascii=False), chat_id, message_id),
        )
        connection.execute("UPDATE chats SET updated_at=? WHERE id=?", (now(), chat_id))


def rewind_chat(chat_id, message_id):
    with _lock, conn() as connection:
        row = connection.execute(
            "SELECT id,role,text,applied,attachments,capabilities,metadata,ts "
            "FROM chat_messages WHERE chat_id=? AND id=?", (chat_id, message_id),
        ).fetchone()
        if not row:
            raise ValueError("要编辑的消息已经不存在")
        if row["role"] != "user":
            raise ValueError("只能从用户消息重新开始")
        connection.execute(
            "DELETE FROM chat_messages WHERE chat_id=? AND id>=?", (chat_id, message_id)
        )
        connection.execute(
            "UPDATE chats SET runtime_provider='',runtime_thread_id='',updated_at=? WHERE id=?",
            (now(), chat_id),
        )
        return _message(row)


def set_chat_runtime(chat_id, provider, thread_id, title=""):
    with _lock, conn() as connection:
        values = [(provider or "").strip(), (thread_id or "").strip()]
        sets = "runtime_provider=?,runtime_thread_id=?"
        clean_title = (title or "").strip()
        if clean_title:
            sets += ",title=?,title_source='official'"
            values.append(clean_title)
        values.extend([now(), chat_id])
        connection.execute(
            "UPDATE chats SET {},updated_at=? WHERE id=?".format(sets), values
        )


def set_chat_official_title(chat_id, title):
    clean_title = (title or "").strip()
    if clean_title:
        with _lock, conn() as connection:
            connection.execute(
                "UPDATE chats SET title=?,title_source='official',updated_at=? WHERE id=?",
                (clean_title, now(), chat_id),
            )


def set_chat_channel_title(chat_id, title):
    clean_title = (title or "").strip()
    if clean_title:
        with _lock, conn() as connection:
            connection.execute(
                "UPDATE chats SET title=?,title_source='channel',updated_at=? WHERE id=?",
                (clean_title, now(), chat_id),
            )


def find_chat_attachment(chat_id, attachment_id):
    with conn() as connection:
        rows = connection.execute(
            "SELECT attachments FROM chat_messages WHERE chat_id=?", (chat_id,)
        ).fetchall()
    for row in rows:
        try:
            items = json.loads(row["attachments"] or "[]")
        except (TypeError, ValueError):
            items = []
        for item in items:
            if item.get("id") == attachment_id:
                return item
    return None


def rename_chat(chat_id, title):
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE chats SET title=?,title_source='manual' WHERE id=?",
            ((title or "").strip() or "新对话", chat_id),
        )


def delete_chat(chat_id):
    with _lock, conn() as connection:
        connection.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
        connection.execute("DELETE FROM chats WHERE id=?", (chat_id,))


def delete_employee_chats(employee_id):
    employee_id = int(employee_id)
    with _lock, conn() as connection:
        ids = []
        for row in connection.execute(
                "SELECT id,employee_id,context_json FROM chats WHERE kind='employee_design' "
                "OR (kind='general' AND subject_type='employee')").fetchall():
            try:
                context = json.loads(row["context_json"] or "{}")
            except (TypeError, ValueError):
                context = {}
            if (int(row["employee_id"] or 0) == employee_id or
                    int(context.get("target_employee_id") or
                        context.get("target_worker_id") or
                        context.get("worker_id") or 0) == employee_id):
                ids.append(row["id"])
        if ids:
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                "DELETE FROM chat_messages WHERE chat_id IN ({})".format(placeholders), ids)
            connection.execute(
                "DELETE FROM chats WHERE id IN ({})".format(placeholders), ids)
    return ids


def reset_core_chat_context():
    with _lock, conn() as connection:
        ids = [row[0] for row in connection.execute(
            "SELECT id FROM chats WHERE kind='employee_design'").fetchall()]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                "DELETE FROM chat_messages WHERE chat_id IN ({})".format(placeholders), ids
            )
            connection.execute(
                "DELETE FROM chats WHERE id IN ({})".format(placeholders), ids
            )
        connection.execute(
            "UPDATE chats SET scope_pipeline_id=NULL,scope_run_id=NULL,scope_type='global',"
            "subject_type='workspace',employee_id=NULL,employee_release_id=NULL,"
            "employee_release_digest='',context_json='{}' WHERE kind='general'"
        )
    return ids
