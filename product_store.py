# -*- coding: utf-8 -*-
"""Cloud business records and explicit device-owned personal conversations.

Personal transcripts live in durable device storage. Business-bound, creator,
organization and automation conversations continue through their cloud owner.
"""
import base64
import uuid
from contextlib import nullcontext
import json
import os
import re
import secrets
import sqlite3
import subprocess
from datetime import datetime

import automation_store
import local_database
import provider_catalog


data_dir = local_database.data_dir
conn = local_database.conn
now = local_database.now
_lock = local_database.lock


PRODUCT_SCHEMA = "CREATE TABLE IF NOT EXISTS credential_entries(\n  name TEXT PRIMARY KEY,\n  pos INTEGER NOT NULL DEFAULT 0,\n  source_name TEXT NOT NULL DEFAULT '',\n  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);\nCREATE TABLE IF NOT EXISTS model_channels(\n  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,\n  provider TEXT NOT NULL DEFAULT 'claude-code', executable TEXT NOT NULL DEFAULT '',\n  config_dir TEXT NOT NULL DEFAULT '', default_model TEXT NOT NULL DEFAULT '',\n  default_effort TEXT NOT NULL DEFAULT '',\n  enabled INTEGER NOT NULL DEFAULT 1, is_default INTEGER NOT NULL DEFAULT 0,\n  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);\nCREATE TABLE IF NOT EXISTS mobile_host_sync(\n  singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),\n  account_id TEXT NOT NULL DEFAULT '',\n  host_id TEXT NOT NULL UNIQUE, snapshot_key TEXT NOT NULL, writer_token TEXT NOT NULL,\n  created_at TEXT NOT NULL, relay_registered_at TEXT NOT NULL DEFAULT '',\n  relay_last_synced_at TEXT NOT NULL DEFAULT '', relay_last_snapshot_version INTEGER NOT NULL DEFAULT 0,\n  relay_last_snapshot_hash TEXT NOT NULL DEFAULT '', relay_last_error TEXT NOT NULL DEFAULT '',\n  relay_push_state_json TEXT NOT NULL DEFAULT '', relay_device_count INTEGER NOT NULL DEFAULT 0);\nCREATE TABLE IF NOT EXISTS mobile_host_retirements(\n  host_id TEXT PRIMARY KEY, writer_token TEXT NOT NULL,\n  created_at TEXT NOT NULL, last_attempt_at TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '');\nCREATE TABLE IF NOT EXISTS mobile_command_receipts(\n  command_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, sequence INTEGER NOT NULL,\n  issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, action TEXT NOT NULL,\n  target_id TEXT NOT NULL, action_id TEXT NOT NULL,\n  status TEXT NOT NULL DEFAULT 'processing', result_json TEXT NOT NULL DEFAULT '{}',\n  created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '',\n  UNIQUE(device_id,sequence));\nCREATE TABLE IF NOT EXISTS mobile_command_result_outbox(\n  command_id TEXT PRIMARY KEY, result_json TEXT NOT NULL,\n  created_at TEXT NOT NULL, uploaded_at TEXT NOT NULL DEFAULT '');\nCREATE TABLE IF NOT EXISTS local_asset_grants(\n  id INTEGER PRIMARY KEY AUTOINCREMENT,\n  name TEXT NOT NULL, path TEXT NOT NULL,\n  dev INTEGER NOT NULL DEFAULT 0, ino INTEGER NOT NULL DEFAULT 0,\n  is_git INTEGER NOT NULL DEFAULT 0, git_root_commit TEXT NOT NULL DEFAULT '',\n  excluded_json TEXT NOT NULL DEFAULT '[]',\n  revoked_at TEXT NOT NULL DEFAULT '',\n  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_used_at TEXT NOT NULL DEFAULT '');\n"

# 本地资产授权：只存在本机，和凭据保险箱同一类数据（见 design/LOCAL_ASSET_GRANTS.md）。
# 默认排除项：机密文件、依赖/虚拟环境目录和超限二进制；授权时展示，用户可逐项放开。
LOCAL_ASSET_DEFAULT_EXCLUDES = (
    ".env", ".env.*", "*.pem", "*.key", "id_rsa*", ".ssh/", ".aws/",
    "node_modules/", ".venv/", "venv/", "__pycache__/",
)
LOCAL_ASSET_MAX_FILE_BYTES = 100 * 1024 * 1024
LOCAL_ASSET_GIT_MAX_BYTES = 2 * 1024 * 1024 * 1024
LOCAL_ASSET_GIT_MAX_FILES = 100_000
LOCAL_ASSET_SNAPSHOT_MAX_BYTES = 1024 * 1024 * 1024
LOCAL_ASSET_SNAPSHOT_MAX_FILES = 20_000


def _local_asset_forbidden_roots():
    home = os.path.realpath(os.path.expanduser("~"))
    return [
        os.path.join(home, "Library"),
        os.path.join(home, ".ssh"),
        os.path.join(home, ".aws"),
        os.path.realpath(core_data_root()),
        os.path.realpath(data_dir()),
    ]


def _is_same_or_descendant(candidate, ancestor):
    candidate = os.path.normpath(candidate)
    ancestor = os.path.normpath(ancestor)
    return candidate == ancestor or candidate.startswith(ancestor + os.sep)


def validate_local_asset_path(raw_path):
    """校验用户所选文件或目录；拒绝系统与本产品自身数据目录。"""
    expanded = os.path.expanduser(str(raw_path or "").strip())
    if not expanded:
        raise ValueError("请选择一个文件或文件夹")
    resolved = os.path.realpath(expanded)
    if not (os.path.isdir(resolved) or os.path.isfile(resolved)):
        raise ValueError("所选文件或文件夹不存在")
    if os.path.islink(expanded.rstrip(os.sep)):
        raise ValueError("暂不支持符号链接")
    home = os.path.realpath(os.path.expanduser("~"))
    if resolved == os.path.abspath(os.sep):
        raise ValueError("不能授权整个磁盘根目录")
    if _is_same_or_descendant(home, resolved):
        raise ValueError("不能授权「{}」：它是用户主目录或其上级目录，请选择具体的项目文件夹".format(resolved))
    for forbidden in _local_asset_forbidden_roots():
        if _is_same_or_descendant(resolved, forbidden):
            if resolved == os.path.realpath(data_dir()) and _git_repo_without_tracked_data(resolved):
                # A source checkout that also hosts this product's data (a
                # development workspace): grants of git repositories are
                # mounted with `git clone --local`, which carries only committed
                # files, so untracked product data can never reach the copy.
                continue
            raise ValueError("不能授权「{}」：它是系统目录或 RunTeams 自己的数据目录（{}），请选择项目所在的文件夹".format(
                resolved, forbidden))
    return resolved


_PRODUCT_DATA_ENTRIES = ("runteams.db", "runteams.db-wal", "runteams.db-shm", "foreman.db",
                         "board.db", "secrets.json", "core", "workspaces", "artifacts",
                         "cache", "backups", "transcripts", "task-seeds")


def _git_repo_without_tracked_data(path):
    """True when ``path`` is a git work tree root that commits none of the product data."""
    try:
        top = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
        if top.returncode != 0 or os.path.realpath(top.stdout.strip()) != path:
            return False
        # Without a commit the mount falls back to a snapshot copy, which
        # would include the product data, so a HEAD is required.
        head = subprocess.run(["git", "-C", path, "rev-parse", "--verify", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        if head.returncode != 0:
            return False
        tracked = subprocess.run(["git", "-C", path, "ls-files", "--", *_PRODUCT_DATA_ENTRIES],
                                 capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return tracked.returncode == 0 and not tracked.stdout.strip()


def _git_root_commits(path):
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-list", "--max-parents=0", "HEAD"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in (result.stdout or "").splitlines() if line.strip()})


def _git_branch(path):
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def _git_uncommitted_count(path):
    try:
        result = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return 0
    if result.returncode != 0:
        return 0
    return len([line for line in (result.stdout or "").splitlines() if line.strip()])


def inspect_local_asset_source(resolved_path):
    """Identify a validated grant path for the confirmation card and identity checks."""
    root_commits = _git_root_commits(resolved_path) if os.path.isdir(resolved_path) else []
    is_git = bool(root_commits) and os.path.isdir(os.path.join(resolved_path, ".git"))
    st = os.stat(resolved_path)
    return {
        "name": os.path.basename(resolved_path.rstrip(os.sep)) or resolved_path,
        "path": resolved_path,
        "dev": st.st_dev, "ino": st.st_ino,
        "is_git": is_git,
        "git_root_commit": ",".join(root_commits) if is_git else "",
        "branch": _git_branch(resolved_path) if is_git else "",
        "uncommitted_count": _git_uncommitted_count(resolved_path) if is_git else 0,
        "default_excludes": list(LOCAL_ASSET_DEFAULT_EXCLUDES),
        "local_kind": "file" if os.path.isfile(resolved_path) else "folder",
    }


def _local_asset_row(row, usage=None):
    if not row:
        return None
    item = dict(row)
    item["excluded"] = json.loads(item.pop("excluded_json", "[]") or "[]")
    item["revoked"] = bool(item.get("revoked_at"))
    if usage is not None:
        item["usage"] = usage
    return item


def _local_asset_grant_row_by_id(grant_id):
    with conn() as connection:
        return connection.execute(
            "SELECT * FROM local_asset_grants WHERE id=?", (int(grant_id),)).fetchone()


def create_local_asset_grant(raw_path, name=None, restored_excludes=None):
    resolved = validate_local_asset_path(raw_path)
    info = inspect_local_asset_source(resolved)
    restored = {str(item or "").strip() for item in (restored_excludes or [])}
    excluded = [item for item in LOCAL_ASSET_DEFAULT_EXCLUDES if item not in restored]
    display_name = str(name or info["name"]).strip()[:160] or info["name"]
    ts = now()
    with _lock, conn() as connection:
        existing = connection.execute(
            "SELECT id FROM local_asset_grants WHERE dev=? AND ino=? AND revoked_at=''",
            (info["dev"], info["ino"])).fetchone()
        if existing:
            return _local_asset_row(connection.execute(
                "SELECT * FROM local_asset_grants WHERE id=?", (existing["id"],)).fetchone())
        grant_id = connection.execute(
            "INSERT INTO local_asset_grants(name,path,dev,ino,is_git,git_root_commit,"
            "excluded_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (display_name, resolved, info["dev"], info["ino"], int(info["is_git"]),
             info["git_root_commit"], json.dumps(excluded, ensure_ascii=False), ts, ts),
        ).lastrowid
    return _local_asset_row(_local_asset_grant_row_by_id(grant_id))


def get_local_asset_grant(grant_id):
    return _local_asset_row(_local_asset_grant_row_by_id(grant_id))


def list_local_asset_grants(include_revoked=True):
    with conn() as connection:
        rows = connection.execute(
            "SELECT * FROM local_asset_grants ORDER BY revoked_at!='',name").fetchall()
    items = [_local_asset_row(row) for row in rows]
    if not include_revoked:
        items = [item for item in items if not item["revoked"]]
    return items


def rename_local_asset_grant(grant_id, name):
    name = str(name or "").strip()[:160]
    if not name:
        raise ValueError("名称不能为空")
    with _lock, conn() as connection:
        changed = connection.execute(
            "UPDATE local_asset_grants SET name=?,updated_at=? WHERE id=?",
            (name, now(), int(grant_id))).rowcount
    if not changed:
        raise ValueError("授权不存在")
    return get_local_asset_grant(grant_id)


def revoke_local_asset_grant(grant_id):
    with _lock, conn() as connection:
        changed = connection.execute(
            "UPDATE local_asset_grants SET revoked_at=?,updated_at=? WHERE id=? AND revoked_at=''",
            (now(), now(), int(grant_id))).rowcount
    return bool(changed)


def touch_local_asset_grant_used(grant_id):
    with _lock, conn() as connection:
        connection.execute(
            "UPDATE local_asset_grants SET last_used_at=? WHERE id=?",
            (now(), int(grant_id)))


def _load(connection, sql, args=()):
    return [dict(row) for row in connection.execute(sql, args).fetchall()]


def core_data_root():
    configured = (os.environ.get("RUNTEAMS_CORE_DATA") or "").strip()
    base = os.path.realpath(configured or os.path.join(
        os.path.dirname(os.path.abspath(local_database.DB_PATH)), "core"))
    from runteams_core.business_storage import bound_storage
    if bound_storage(os.path.join(base,'runteams.db')) is not None:
        return base
    from runteams_core.storage_context import current_provider
    return str(current_provider().core_data_root(base))


def assistant_workspace():
    """Managed workspace shared by General Chat, Employee design, and attachments."""
    configured = (os.environ.get("RUNTEAMS_WORKSPACES") or "").strip()
    root = os.path.realpath(os.path.expanduser(configured)) if configured else os.path.join(
        data_dir(), "workspaces")
    from runteams_core.business_storage import bound_storage
    if bound_storage(local_database.DB_PATH) is None:
        from runteams_core.storage_context import resolve
        from pathlib import Path
        binding = resolve(Path(local_database.DB_PATH).resolve().parent / 'device-data')
        root = os.path.join(str(binding.root), 'workspaces')
    path = os.path.realpath(os.path.join(root, "assistant"))
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


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


def init_product_db():
    from runteams_core.business_storage import storage_for
    storage = storage_for(local_database.DB_PATH)
    if hasattr(storage, 'initialize_product'):
        return storage.initialize_product()
    storage.initialize()
    init_host_db()


def init_host_db():
    """Initialize host configuration without creating a cloud/account client."""
    with _lock, local_database.host_conn() as connection:
        connection.executescript(PRODUCT_SCHEMA)
        _ensure_channels(connection)
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_model_channels_provider ON model_channels(provider)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_mobile_commands_device_sequence ON mobile_command_receipts(device_id,sequence DESC)")
        connection.execute("PRAGMA user_version=300")


# Agent Channels
def _channel_record(row):
    if row is None:
        return None
    item = dict(row)
    item['id'] = provider_catalog.channel_id(item['provider'])
    return item


def list_channels():
    with local_database.host_conn() as connection:
        return [_channel_record(row) for row in connection.execute(
            "SELECT * FROM model_channels ORDER BY is_default DESC,provider")]


def get_channel(channel_id):
    provider = provider_catalog.channel_provider(channel_id)
    if provider is None:
        return None
    with local_database.host_conn() as connection:
        row = connection.execute(
            "SELECT * FROM model_channels WHERE provider=?", (provider,)
        ).fetchone()
        return _channel_record(row)


def get_default_channel(provider=None):
    with local_database.host_conn() as connection:
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
        return _channel_record(row)


def upsert_channel(channel_id, fields):
    columns = ("name", "provider", "executable", "config_dir", "enabled", "is_default")
    values = {key: fields[key] for key in columns if key in fields}
    values["updated_at"] = now()
    with _lock, local_database.host_conn() as connection:
        provider = provider_catalog.channel_provider(channel_id) if channel_id else values.get('provider')
        if provider not in provider_catalog.CHANNEL_IDS or (values.get('provider') and values['provider'] != provider):
            raise ValueError('渠道厂商身份无效或已变化')
        row = connection.execute('SELECT id FROM model_channels WHERE provider=?', (provider,)).fetchone()
        storage_id = row[0] if row else None
        values['provider'] = provider
        if values.get("is_default"):
            connection.execute("UPDATE model_channels SET is_default=0")
        if storage_id:
            sets = ",".join("{}=?".format(key) for key in values)
            connection.execute(
                "UPDATE model_channels SET {} WHERE id=?".format(sets),
                list(values.values()) + [storage_id],
            )
            connection.execute(
                "UPDATE model_channels SET default_model='',default_effort='' WHERE id=?",
                (storage_id,),
            )
            return provider_catalog.channel_id(provider)
        values["created_at"] = now()
        connection.execute(
            "INSERT INTO model_channels({}) VALUES({})".format(
                ",".join(values), ",".join("?" * len(values))
            ), list(values.values()),
        )
        return provider_catalog.channel_id(provider)


def delete_channel(_channel_id):
    return False, "内置厂商渠道不能删除，可以在设置中停用"


def set_channel_enabled(channel_id, enabled):
    provider = provider_catalog.channel_provider(channel_id)
    if provider is None:
        return False
    with _lock, local_database.host_conn() as connection:
        connection.execute(
            "UPDATE model_channels SET enabled=?,updated_at=? WHERE provider=?",
            (1 if enabled else 0, now(), provider),
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
def device_chat(chat_id):
    from runteams_core import device_data
    return device_data.contains(chat_id)


def chat_conn(chat_id, *, readonly=False):
    from runteams_core import device_data
    if device_data.enabled() and int(chat_id)>=device_data.LOCAL_CHAT_ID_MIN:
        if not device_data.personal():
            raise PermissionError('请在个人工作区打开本机对话。')
        return device_data.connect(readonly=readonly)
    return device_data.connect(readonly=readonly) if device_chat(chat_id) else conn()


def chat_lock(chat_id):
    # SQLite serializes device writers. A cloud request must never hold their lock.
    from runteams_core import device_data
    return nullcontext() if (device_data.enabled() and int(chat_id)>=device_data.LOCAL_CHAT_ID_MIN
        or device_chat(chat_id)) else _lock


def list_chats(*, device_only=False):
    def read(connection):
        rows = _load(
            connection,
        "SELECT id,title,title_source,kind,status,channel_id,model,reasoning_effort,"
            "scope_pipeline_id,extensions_enabled,subject_type,employee_id,"
            "employee_release_id,employee_release_digest,scope_type,scope_run_id,"
            "runtime_provider,"
            "updated_at,context_json,"
            "(SELECT substr(text,1,320) FROM chat_messages m WHERE m.chat_id=chats.id AND m.role='user' ORDER BY m.id ASC LIMIT 1) AS first_user_message_text,"
            "(SELECT substr(text,1,320) FROM chat_messages m WHERE m.chat_id=chats.id ORDER BY m.id DESC LIMIT 1) AS last_message_text,"
            "(SELECT ts FROM chat_messages m WHERE m.chat_id=chats.id ORDER BY m.id DESC LIMIT 1) AS last_message_at,"
            "(SELECT id FROM chat_messages m WHERE m.chat_id=chats.id ORDER BY m.id DESC LIMIT 1) AS last_message_id,"
            "(SELECT substr(text,1,320) FROM chat_messages m WHERE m.chat_id=chats.id AND m.role='bot' ORDER BY m.id DESC LIMIT 1) AS last_bot_message_text,"
            "(SELECT ts FROM chat_messages m WHERE m.chat_id=chats.id AND m.role='bot' ORDER BY m.id DESC LIMIT 1) AS last_bot_message_at,"
            "(SELECT id FROM chat_messages m WHERE m.chat_id=chats.id AND m.role='bot' ORDER BY m.id DESC LIMIT 1) AS last_bot_message_id,"
            "(SELECT metadata FROM chat_messages m WHERE m.chat_id=chats.id AND m.role='bot' ORDER BY m.id DESC LIMIT 1) AS last_bot_message_metadata "
            "FROM chats WHERE kind!='automation' "
            "AND EXISTS(SELECT 1 FROM chat_messages m WHERE m.chat_id=chats.id) "
            "ORDER BY updated_at DESC,id DESC",
        )


        for row in rows:
            try:
                metadata = json.loads(row.pop('last_bot_message_metadata', None) or '{}')
                if not isinstance(metadata, dict):
                    raise ValueError('Invalid reply metadata')
                trace = metadata.get('trace') if isinstance(metadata.get('trace'), dict) else {}
                notice = metadata.get('system_notice') if isinstance(metadata.get('system_notice'), dict) else {}
                row['last_bot_message_completed'] = bool(row.get('last_bot_message_id')) and not any((
                    metadata.get('failed'), metadata.get('incomplete'), metadata.get('stopped'),
                    trace.get('failed'), trace.get('cancelled'), trace.get('complete') is False, notice.get('kind') in ('error', 'stopped')))
            except (TypeError, ValueError):
                row['last_bot_message_completed'] = False
        return rows


    from runteams_core import device_data
    if not device_data.personal():
        with conn() as connection:
            return read(connection)
    with device_data.connect(readonly=True) as connection:
        local = [dict(row, storage_scope='device') for row in read(connection)]
    if device_only:
        return local
    with conn() as connection:
        remote = read(connection)
    with device_data.connect(readonly=True) as connection:
        known = {row[0] for row in connection.execute('SELECT chat_id FROM device_chat_index')}
    return sorted(local + [row for row in remote if row['id'] not in known],
                  key=lambda row:(row['updated_at'],row['id']), reverse=True)


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
        from runteams_core.employee_context import current as employee_context
        package = context.get('local_employee_package')
        if not package or scope_type != 'global' or scope_pipeline_id or scope_run_id:
            raise ValueError("员工会话缺少员工绑定")
        employee_context().validate_source_package(package)
    if subject_type == "employee":
        if scope_type == "pipeline" and scope_pipeline_id in (None, ""):
            raise ValueError("流水线作用域必须绑定流水线")
        if scope_type == "run" and scope_run_id in (None, ""):
            raise ValueError("运行作用域必须绑定 WorkflowRun")
        if scope_type == "global":
            scope_pipeline_id, scope_run_id = None, None
    from runteams_core import device_data
    if 'source_pipeline_workspace' in context:
        from runteams_core.pipeline_references import checked_reference
        if subject_type != 'workspace' or scope_type != 'global' or scope_pipeline_id or scope_run_id:
            raise ValueError('流水线会话归属不能改变。')
        checked_reference(context['source_pipeline_workspace'])
    local = device_data.personal() and device_data.eligible({
        'kind':kind,'context':context,'subject_type':subject_type,'scope_type':scope_type,
        'scope_pipeline_id':scope_pipeline_id,'scope_run_id':scope_run_id})
    if not channel_id:
        channel = get_default_channel()
        channel_id = channel['id'] if channel else None
    with (nullcontext() if local else _lock), (device_data.connect() if local else conn()) as connection:
        if local:
            chat_id = device_data.LOCAL_CHAT_ID_MIN + secrets.randbelow(device_data.LOCAL_CHAT_ID_MIN)
            # Explicit ID keeps the cloud and device namespaces disjoint.
            connection.execute('INSERT INTO chats(id,title,title_source,kind,context_json,channel_id,model,reasoning_effort,extensions_enabled,subject_type,employee_id,employee_release_id,employee_release_digest,scope_type,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (chat_id,'新对话','pending',kind,json.dumps(context,ensure_ascii=False),channel_id,
                 model or '',reasoning_effort or '',1 if extensions_enabled else 0,subject_type,
                 int(employee_id) if employee_id not in (None, '') else None,
                 int(employee_release_id) if employee_release_id not in (None, '') else None,
                 str(employee_release_digest or ''),scope_type,now(),now()))
            connection.execute('INSERT INTO device_chat_index(chat_id,identity,imported_at) VALUES(?,?,?)',
                (chat_id,str(uuid.uuid4()),now()))
            return chat_id
        if not channel_id:
            row = connection.execute(
                "SELECT provider FROM model_channels WHERE enabled=1 "
                "ORDER BY is_default DESC,id LIMIT 1"
            ).fetchone()
            if row:
                channel_id = provider_catalog.channel_id(row['provider'])
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
    from runteams_core import device_data
    from runteams_core.creator_local_authoring import valid_context
    from runteams_core.creator_local_source import current_store
    if kind!='employee_design' or not valid_context(context) or scope_pipeline_id or not device_data.personal():
        raise ValueError('员工创作须绑定当前个人 SDK 源码。')
    current_store(context['creator_local_scope']).describe(context['creator_local_source_id'])
    with device_data.connect() as connection:
        chat_id = device_data.LOCAL_CHAT_ID_MIN + secrets.randbelow(device_data.LOCAL_CHAT_ID_MIN)
        connection.execute("INSERT INTO chats(id,title,title_source,kind,context_json,status,channel_id,model,reasoning_effort,extensions_enabled,created_at,updated_at) VALUES(?,?,'system',?,?,'active',?,?,?,1,?,?)",
            (chat_id,(title or '创作员工').strip(),kind,json.dumps(context,ensure_ascii=False),channel_id,model or '',reasoning_effort or '',now(),now()))
        connection.execute('INSERT INTO device_chat_index(chat_id,identity,imported_at) VALUES(?,?,?)',(chat_id,str(uuid.uuid4()),now()))
        return chat_id


def _message(row):
    item = dict(row)
    if item.get('ts'):
        item['ts'] = local_database.timestamp(item['ts']).isoformat(timespec="seconds")
    for key, fallback in (("applied", []), ("attachments", []),
                          ("capabilities", []), ("metadata", {})):
        try:
            item[key] = json.loads(item.get(key) or json.dumps(fallback))
        except (TypeError, ValueError) as exc:
            raise ValueError('云端消息资源记录无效，请重新读取或修复。') from exc
    if item['metadata'].get('response_feedback_case'):
        from runteams_core.storage_context import current_provider
        item['metadata']['response_feedback_case']=current_provider().project_reply_feedback_case(item['metadata']['response_feedback_case'])
    return item


def get_chat(chat_id, include_messages=True, *, message_limit=None, message_cursor=None):
    with chat_conn(chat_id, readonly=True) as connection:
        row = connection.execute(
            "SELECT id,title,title_source,kind,context_json,status,channel_id,model,"
            "reasoning_effort,scope_pipeline_id,extensions_enabled,subject_type,employee_id,"
            "employee_release_id,employee_release_digest,scope_type,scope_run_id,runtime_provider,"
            "runtime_generation,created_at,updated_at FROM chats WHERE id=?",
            (chat_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["storage_scope"] = "device" if device_chat(chat_id) else "cloud"
        if item['storage_scope']=='device':
            from runteams_core import device_data
            item['public_id']=device_data.public_id(chat_id)
        runtime = None
        if item['storage_scope']=='device':
            runtime = connection.execute('SELECT provider,thread_id FROM device_chat_runtime_links WHERE chat_id=? AND generation=?',
                (int(chat_id),int(item['runtime_generation']))).fetchone()
        if item['storage_scope']!='device':
            with conn() as runtime_connection:
                runtime = runtime_connection.execute('SELECT provider,thread_id FROM chat_runtime_links WHERE account_id=? AND chat_id=? AND generation=?',
                (_runtime_account(),int(chat_id),int(item['runtime_generation']))).fetchone()
        item['runtime_thread_id'] = runtime['thread_id'] if runtime else ''
        if runtime:
            item['runtime_provider'] = runtime['provider']
        for source, target in (("context_json", "context"),):
            try:
                item[target] = json.loads(item.pop(source) or "{}")
            except (TypeError, ValueError) as exc:
                raise ValueError('云端会话记录无效，请重新读取或修复。') from exc
        if message_limit is not None:
            from runteams_core.read_pages import page_size,scope_key,cursor_after,cursor_for,CursorError
            from runteams_core.business_storage import storage_for
            size=page_size(message_limit)
            from runteams_core import device_data
            scope=scope_key('chat-messages',device_data.identity()['library_id'] if device_chat(chat_id) else _runtime_account(),device_data.epoch(chat_id) if device_chat(chat_id) else storage_for(local_database.DB_PATH).data_epoch(),int(chat_id))
            after=cursor_after(message_cursor,scope)
            if after is not None and (len(after)!=1 or type(after[0]) is not int):raise CursorError('消息分页已失效，请重新打开对话。')
            rows=connection.execute('SELECT id,role,text,applied,attachments,capabilities,metadata,ts FROM chat_messages WHERE chat_id=?'
                +(' AND id<?' if after else '')+' ORDER BY id DESC LIMIT ?',
                ([int(chat_id),after[0],size+1] if after else [int(chat_id),size+1])).fetchall() if include_messages else []
            more=len(rows)>size;rows=rows[:size]
            item['messages']=[_message(message) for message in reversed(rows)]
            item['messages_page']={'has_more':more,'next_cursor':cursor_for(scope,[int(rows[-1]['id'])]) if more else None}
            return item
        if message_cursor:raise ValueError('消息分页缺少数量。')
        item["messages"] = [
            _message(message) for message in connection.execute(
                "SELECT id,role,text,applied,attachments,capabilities,metadata,ts "
                "FROM chat_messages WHERE chat_id=? ORDER BY id", (chat_id,)
            ).fetchall()
        ] if include_messages else []
        return item


def update_agent_session_context(chat_id, context):
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
        connection.execute(
            "UPDATE chats SET context_json=?,updated_at=? "
            "WHERE id=? AND kind='employee_design'",
            (json.dumps(context or {}, ensure_ascii=False), now(), chat_id),
        )


def update_chat_config(chat_id, channel_id, model, reasoning_effort,
                       scope_pipeline_id=None, extensions_enabled=False, context=None):
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
        current = connection.execute(
            "SELECT subject_type,context_json FROM chats WHERE id=?", (chat_id,)).fetchone()
        pipeline_context = json.loads(current['context_json'] or '{}') if current else {}
        pipeline_binding = pipeline_context.get('source_pipeline_workspace')
        if pipeline_binding is not None:
            from runteams_core.pipeline_references import checked_reference
            checked_reference(pipeline_binding)
            if context is not None and (not isinstance(context, dict) or context.get('source_pipeline_workspace') != pipeline_binding):
                raise ValueError('流水线会话归属不能改变。')
            if scope_pipeline_id:
                raise ValueError('流水线会话不能绑定其他流水线。')
            context = pipeline_context
        elif isinstance(context, dict) and 'source_pipeline_workspace' in context:
            raise ValueError('不能把已有对话改为流水线会话。')
        if current and (current["subject_type"] == "employee" or pipeline_binding is not None):
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
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
        connection.execute(
            "UPDATE chats SET employee_release_id=?,employee_release_digest=? "
            "WHERE id=? AND kind='general' AND subject_type='employee'",
            (int(release_id) if release_id not in (None, "") else None,
             str(release_digest or ""), chat_id),
        )


def add_chat_message(chat_id, role, text, applied=None, attachments=None,
                     capabilities=None, metadata=None):
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
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
    with chat_conn(chat_id, readonly=True) as connection:
        row = connection.execute(
            "SELECT id,role,text,applied,attachments,capabilities,metadata,ts "
            "FROM chat_messages WHERE chat_id=? AND id=?", (chat_id, message_id),
        ).fetchone()
        return _message(row) if row else None


def set_chat_message_feedback(chat_id, message_id, rating, *, environment=None):
    """Record the owner's reply rating without altering transcript or activity order."""
    if rating not in (None, 'up', 'down'):
        raise ValueError('回复评价无效。')
    from runteams_core import device_data
    if not device_data.personal() or not device_chat(chat_id):
        raise PermissionError('请在原个人工作区评价这条回复。')
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
        row = connection.execute(
            "SELECT role,metadata FROM chat_messages WHERE chat_id=? AND id=?",
            (chat_id, message_id),
        ).fetchone()
        if not row or row['role'] != 'bot':
            raise ValueError('这条回复已不存在或不能评价。')
        metadata = json.loads(row['metadata'] or '{}')
        if not isinstance(metadata, dict) or metadata.get('failed') or metadata.get('system_notice'):
            raise ValueError('这条消息不能评价。')
        from runteams_core.storage_context import current_provider
        case = current_provider().record_reply_feedback_case(chat_id, message_id, rating, environment or {})
        if case:metadata['response_feedback_case'] = case
        if rating is None:
            metadata.pop('response_feedback', None)
        else:
            metadata['response_feedback'] = rating
        connection.execute("UPDATE chat_messages SET metadata=? WHERE chat_id=? AND id=?",
            (json.dumps(metadata, ensure_ascii=False), chat_id, message_id))
    return {'message_id': message_id, 'rating': rating}


def add_chat_question_answer(chat_id, text, metadata, prefix=None):
    """Commit the pre-answer assistant segment and answer in one local transaction."""
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
        for row in connection.execute("SELECT * FROM chat_messages WHERE chat_id=? AND role='user'", (chat_id,)):
            saved = _message(row)
            if saved.get('metadata', {}).get('question_request_id') == metadata['question_request_id']:
                return saved
        def insert(role, body, details, timestamp=None):
            return connection.execute(
                "INSERT INTO chat_messages(chat_id,role,text,applied,attachments,capabilities,metadata,ts) VALUES(?,?,?,?,?,?,?,?)",
                (chat_id, role, body or '', '[]', '[]', '[]', json.dumps(details, ensure_ascii=False), timestamp or now())).lastrowid
        metadata = dict(metadata)
        if prefix:
            metadata['question_prefix_id'] = insert('bot', prefix.get('text', ''), prefix['metadata'], prefix.get('ts'))
        message_id = insert('user', text, metadata)
        connection.execute("UPDATE chats SET updated_at=? WHERE id=?", (now(), chat_id))
        return _message(connection.execute("SELECT * FROM chat_messages WHERE chat_id=? AND id=?", (chat_id, message_id)).fetchone())


def resolve_chat_plan(chat_id, message_id, applied=None, resolution="applied", run_cards=None):
    """Persist the terminal state of a structured plan on its original bot message."""
    state = "cancelled" if resolution == "cancelled" else "applied"
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
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
        if run_cards:
            metadata["run_cards"] = run_cards
        if state == "cancelled":
            metadata['system_notice'] = {'kind': 'plan_cancelled', 'text': '已取消这项方案。'}
        connection.execute(
            "UPDATE chat_messages SET applied=?,metadata=? WHERE chat_id=? AND id=?",
            (json.dumps(applied or [], ensure_ascii=False),
             json.dumps(metadata, ensure_ascii=False), chat_id, message_id),
        )
        connection.execute("UPDATE chats SET updated_at=? WHERE id=?", (now(), chat_id))


def rewind_chat(chat_id, message_id):
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
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
        if device_chat(chat_id):
            from runteams_core.device_runtime_links import reset
            reset(connection, int(chat_id))
            connection.execute('UPDATE chats SET updated_at=? WHERE id=?', (now(), chat_id))
        else:
            connection.execute(
                "UPDATE chats SET runtime_provider='',runtime_generation=runtime_generation+1,updated_at=? WHERE id=?",
                (now(), chat_id),
            )
        return _message(row)


def _runtime_account():
    from runteams_core.business_storage import storage_for
    storage = storage_for(local_database.DB_PATH)
    if hasattr(storage,'cloud'):
        import hashlib
        return hashlib.sha256((storage.cloud.url+'\n'+storage.cloud.identity()+('\n'+storage.cloud.workspace() if storage.cloud.workspace() else '')).encode()).hexdigest()
    return 'engineering-fixture'


def set_chat_runtime(chat_id, provider, thread_id, title=""):
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
        row=connection.execute('SELECT runtime_generation FROM chats WHERE id=?',(int(chat_id),)).fetchone()
        if not row:
            raise ValueError('对话不存在')
        if device_chat(chat_id):
            connection.execute('INSERT INTO device_chat_runtime_links(chat_id,generation,provider,thread_id) VALUES(?,?,?,?) '
                'ON CONFLICT(chat_id) DO UPDATE SET generation=excluded.generation,provider=excluded.provider,thread_id=excluded.thread_id',
                (int(chat_id),int(row['runtime_generation']),(provider or '').strip(),(thread_id or '').strip()))
        else:
            with conn() as runtime_connection:
                runtime_connection.execute('INSERT INTO chat_runtime_links(account_id,chat_id,generation,provider,thread_id) VALUES(?,?,?,?,?) '
                'ON CONFLICT(account_id,chat_id) DO UPDATE SET generation=excluded.generation,provider=excluded.provider,thread_id=excluded.thread_id',
                (_runtime_account(),int(chat_id),int(row['runtime_generation']),(provider or '').strip(),(thread_id or '').strip()))
        values = [(provider or "").strip()]
        sets = "runtime_provider=?"
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
        with chat_lock(chat_id), chat_conn(chat_id) as connection:
            connection.execute(
                "UPDATE chats SET title=?,title_source='official',updated_at=? WHERE id=?",
                (clean_title, now(), chat_id),
            )


def set_chat_channel_title(chat_id, title):
    clean_title = (title or "").strip()
    if clean_title:
        with chat_lock(chat_id), chat_conn(chat_id) as connection:
            connection.execute(
                "UPDATE chats SET title=?,title_source='channel',updated_at=? WHERE id=?",
                (clean_title, now(), chat_id),
            )


def find_chat_attachment(chat_id, attachment_id):
    with chat_conn(chat_id, readonly=True) as connection:
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
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
        connection.execute(
            "UPDATE chats SET title=?,title_source='manual' WHERE id=?",
            ((title or "").strip() or "新对话", chat_id),
        )


def delete_chat(chat_id):
    with chat_lock(chat_id), chat_conn(chat_id) as connection:
        connection.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
        connection.execute("DELETE FROM chats WHERE id=?", (chat_id,))

    if device_chat(chat_id):
        from runteams_core import device_data
        with device_data.connect() as connection:
            connection.execute('UPDATE device_chat_index SET deleted=1 WHERE chat_id=?', (chat_id,))

