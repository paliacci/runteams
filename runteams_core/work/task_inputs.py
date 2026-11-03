"""Managed, immutable snapshots of files attached to a task."""

from pathlib import Path
import hashlib
import re
import shutil


PUBLIC_KEYS = ("id", "name", "mime_type", "size", "kind", "file_count", "ref")
LOCAL_INPUT_REF = re.compile(r'device-input://([1-9][0-9]*)/([a-f0-9]{24})/([a-f0-9]{64})')


def _device_storage(core_root):
    from runteams_core.work.device_work import recognizes, DeviceWorkStorage
    from runteams_core.storage.business_storage import storage_for, bound_storage
    path = Path(core_root) / 'runteams.db'
    storage=bound_storage(path)
    if storage is None:
        if not recognizes(path):return None
        storage=storage_for(path)
    return storage if isinstance(storage, DeviceWorkStorage) else None


def _cloud(core_root):
    from runteams_core.storage.business_storage import storage_for
    storage = storage_for(Path(core_root)/'runteams.db')
    if hasattr(storage, 'check_scope'):
        storage.check_scope()
    return storage.file_cloud


def task_root(core_root, task_id):
    storage = _device_storage(core_root)
    if storage is not None:
        from runteams_core.work.device_work import ID_MIN, ID_MAX
        storage.check_scope()
        if not ID_MIN <= int(task_id) <= ID_MAX:
            raise ValueError('本机任务资料编号无效')
        from runteams_core.employees.employee_workspaces import _directory
        directory = _directory(Path(core_root) / 'task-inputs')
        return _directory(directory / ('task-' + str(int(task_id))))
    root = Path(core_root).resolve() / "task-inputs" / "task-{}".format(int(task_id))
    root.mkdir(parents=True, exist_ok=True)
    return root


def public(items):
    return [{key: item.get(key) for key in PUBLIC_KEYS if item.get(key) is not None}
            for item in (items or []) if isinstance(item, dict)]


def consume(core_root, task_id, tokens):
    storage = _device_storage(core_root)
    if storage is not None:
        with storage.connect() as connection:
            if connection.execute('SELECT 1 FROM tasks WHERE id=? AND trashed_at IS NULL', (int(task_id),)).fetchone() is None:
                raise ValueError('本机任务不存在')
            return _consume(core_root, task_id, tokens)
    with _cloud(core_root).account_scope():
        return _consume(core_root, task_id, tokens)


def _consume(core_root, task_id, tokens):
    # The native picker and its one-time tokens belong to the desktop adapter;
    # the core only keeps the resulting stable snapshot references.
    from runteams_core.conversations import chat_attachments

    from runteams_core.assets.cloud_files import put_tree
    storage = _device_storage(core_root)
    cloud = None if storage is not None else _cloud(core_root)
    def finalize(items):
        for item in items:
            path = task_root(core_root, task_id)/item['id']
            if storage is not None:
                from runteams_core.assets.cloud_files import tree_bytes
                sha = hashlib.sha256(tree_bytes(path)).hexdigest()
                item['ref'] = 'device-input://{}/{}/{}'.format(int(task_id), item['id'], sha)
                storage.check_scope()
            else:
                item['ref'] = put_tree(cloud, path)
        return items
    saved = chat_attachments.consume_native_to(task_root(core_root, task_id), tokens, finalize=finalize)
    result = []
    for item in saved:
        entry = {key: item.get(key) for key in
                 ("id", "name", "mime_type", "size", "kind", "file_count")
                 if item.get(key) is not None}
        entry["ref"] = item['ref']
        result.append(entry)
    return result


def discard_task(core_root, task_id):
    root = Path(core_root).resolve()
    target = (root / "task-inputs" / "task-{}".format(int(task_id))).resolve()
    inputs_root = (root / "task-inputs").resolve()
    if target.parent != inputs_root:
        raise ValueError("任务资料目录无效")
    shutil.rmtree(target, ignore_errors=True)


def remove(core_root, task_id, input_id):
    input_id = str(input_id or "")
    if not re.fullmatch(r"[a-f0-9]{24}", input_id):
        raise ValueError("任务资料不存在")
    target = (task_root(core_root, task_id) / input_id).resolve()
    if target.parent != task_root(core_root, task_id).resolve() or not target.exists():
        raise ValueError("任务资料不存在")
    shutil.rmtree(target)


def _safe_destination_name(value, fallback):
    name = Path(str(value or "")).name.strip() or fallback
    name = re.sub(r"[\x00-\x1f/:]", "_", name).strip(". ")
    return name or fallback


def _source_for_item(core_root, task_id, item):
    from runteams_core.assets.cloud_files import TREE_PREFIX, restore_tree
    storage = _device_storage(core_root)
    local = LOCAL_INPUT_REF.fullmatch(str(item.get('ref') or ''))
    if local is not None:
        if storage is None or int(local[1]) != int(task_id) or local[2] != item.get('id'):
            raise ValueError('本机任务资料引用无效')
        item_root = task_root(core_root, task_id) / local[2]
        from runteams_core.assets.cloud_files import tree_bytes
        if hashlib.sha256(tree_bytes(item_root)).hexdigest() != local[3]:
            raise ValueError('本机任务资料内容校验失败')
    else:
        if str(item.get('ref') or '').startswith('device-input://'):
            raise ValueError('本机任务资料引用无效')
        if not str(item.get('ref') or '').startswith(TREE_PREFIX):
            return None
        if storage is not None:
            raise ValueError('本机工作不能读取尚未取得的云端任务资料')
        identifier = str(item.get('id') or '')
        if not re.fullmatch(r'[a-f0-9]{24}', identifier):
            raise ValueError('任务资料标识无效')
        item_root = task_root(core_root, task_id) / identifier
        restore_tree(_cloud(core_root), item['ref'], item_root)
    candidates = sorted(item_root.iterdir())
    if not candidates:
        raise ValueError("任务资料「{}」内容为空".format(item.get("name") or "未命名资料"))
    preferred = next((path for path in candidates if path.name == "folder"), None)
    return preferred or next((path for path in candidates if path.name.startswith("original")),
                             candidates[0])


def source_for_item(core_root, task_id, item):
    """Resolve a managed task input to its immutable on-disk snapshot.

    The service layer uses this read-only resolver for preview/download
    requests.  Keep the validation in one place so the browser can never
    address a path outside the task's managed input directory.
    """
    return _source_for_item(core_root, task_id, item)


def materialize(core_root, task_id, items, workspace, database=None,
                input_directory=".runteams/inputs"):
    """Copy task snapshots into the current employee workspace and return public inputs."""
    workspace_root = Path(workspace).resolve()
    destination = (workspace_root / input_directory).resolve()
    if workspace_root not in destination.parents:
        raise ValueError("交接文件目录必须在本次工作区内")
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    materialized = []
    used = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            materialized.append(raw)
            continue
        item = dict(raw)
        source = _source_for_item(core_root, task_id, item)
        artifact_match = re.fullmatch(r"artifact://([1-9][0-9]*)", str(item.get("ref") or ""))
        if source is None and artifact_match:
            from runteams_core.storage.repository import Repository
            if not database:
                raise ValueError("交接缺少产物数据库")
            with Repository(database).connect() as connection:
                row = connection.execute("SELECT ref FROM artifacts WHERE id=? AND trashed_at IS NULL",
                                         (int(artifact_match.group(1)),)).fetchone()
            source = Path(row["ref"]).resolve() if row else None
            if source is None or Path(core_root).resolve()/"artifacts" not in source.parents or not source.is_file():
                raise ValueError("交接产物已不可用")
            item["artifact_id"] = int(artifact_match.group(1))
        if source is None:
            materialized.append(item)
            continue
        base = _safe_destination_name(item.get("name"), "input")
        if artifact_match and source.suffix and Path(base).suffix != source.suffix:
            base += source.suffix
        candidate, index = base, 2
        while candidate.casefold() in used:
            stem, suffix = Path(base).stem, Path(base).suffix
            candidate = "{} {}{}".format(stem, index, suffix)
            index += 1
        used.add(candidate.casefold())
        target = destination / candidate
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        materialized.append(dict(item, path=str(target.relative_to(Path(workspace).resolve()))))
    return materialized
