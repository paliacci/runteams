"""Managed, immutable snapshots of files attached to a task."""

from pathlib import Path
import re
import shutil


INPUT_REF = re.compile(r"^task-input://(\d+)/([a-f0-9]{24})$")
PUBLIC_KEYS = ("id", "name", "mime_type", "size", "kind", "file_count", "ref")


def task_root(core_root, task_id):
    root = Path(core_root).resolve() / "task-inputs" / "task-{}".format(int(task_id))
    root.mkdir(parents=True, exist_ok=True)
    return root


def public(items):
    return [{key: item.get(key) for key in PUBLIC_KEYS if item.get(key) is not None}
            for item in (items or []) if isinstance(item, dict)]


def consume(core_root, task_id, tokens):
    # The native picker and its one-time tokens belong to the desktop adapter;
    # the core only keeps the resulting stable snapshot references.
    import chat_attachments

    saved = chat_attachments.consume_native_to(task_root(core_root, task_id), tokens)
    result = []
    for item in saved:
        entry = {key: item.get(key) for key in
                 ("id", "name", "mime_type", "size", "kind", "file_count")
                 if item.get(key) is not None}
        entry["ref"] = "task-input://{}/{}".format(int(task_id), item["id"])
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
    match = INPUT_REF.fullmatch(str(item.get("ref") or ""))
    if not match or int(match.group(1)) != int(task_id):
        return None
    item_root = (task_root(core_root, task_id) / match.group(2)).resolve()
    if item_root.parent != task_root(core_root, task_id).resolve() or not item_root.is_dir():
        raise ValueError("任务资料「{}」已不存在".format(item.get("name") or "未命名资料"))
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


def materialize(core_root, task_id, items, workspace):
    """Copy task snapshots into the current employee workspace and return public inputs."""
    destination = Path(workspace).resolve() / ".runteams" / "inputs"
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
        if source is None:
            materialized.append(item)
            continue
        base = _safe_destination_name(item.get("name"), "input")
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
