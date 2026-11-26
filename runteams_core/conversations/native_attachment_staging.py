"""One-use picker snapshots in the current library's private staging tree."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
import re
import shutil
import stat
import threading
import time

from runteams_core.foundation.durable_files import publish_json
from runteams_core.foundation.regular_files import is_link, open_beneath, storage_path


TTL = 30 * 60
_TOKEN = re.compile(r"[a-f0-9]{32}")
_MANIFEST = "selection.json"
_lock = threading.Lock()
_reserved = set()


def directory(path):
    path = storage_path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if is_link(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("附件暂存目录无效。")
    return path


def scope_key(scope):
    return sha256(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def publish(stage, record):
    publish_json(stage / _MANIFEST, record, replace=True)


def _read(stage):
    try:
        with os.fdopen(open_beneath(stage, (_MANIFEST,)), "rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return None
        record = json.loads(raw)
        return record if isinstance(record, dict) and record.get("version") == 1 else None
    except (OSError, ValueError):
        return None


def _expired(record):
    created = record.get("created_at")
    return not isinstance(created, (int, float)) or not time.time() - TTL <= created <= time.time()


def clean(root):
    cutoff = time.time() - TTL
    with _lock:
        for stage in root.iterdir():
            if not _TOKEN.fullmatch(stage.name) or stage in _reserved:
                continue
            try:
                info = stage.lstat()
            except FileNotFoundError:
                continue
            if is_link(info) or not stat.S_ISDIR(info.st_mode):
                continue
            record = _read(stage)
            if (_expired(record) if record else info.st_mtime < cutoff):
                shutil.rmtree(stage, ignore_errors=True)


def _record(stage, scope):
    record = _read(stage)
    if not record or record.get("token") != stage.name or _expired(record):
        raise ValueError("附件选择已过期，请重新选择")
    if record.get("scope") != scope:
        raise PermissionError("资料库已变化，请重新选择附件。")
    if type(record.get("size")) is not int or record["size"] <= 0:
        raise ValueError("附件暂存内容无效，请重新选择")
    return record


def contains_source(root, scope, tokens):
    for token in tokens:
        if not _TOKEN.fullmatch(token):
            continue
        try:
            if _record(root / token, scope).get("sdk_source"):
                return True
        except (ValueError, PermissionError):
            pass
    return False


def _source(stage, record, allowed_extensions):
    kind = record.get("kind")
    if kind == "folder":
        source = stage / "folder"
    elif kind in {"image", "file"} and isinstance(record.get("name"), str):
        extension = os.path.splitext(record["name"])[1]
        if extension not in allowed_extensions:
            raise ValueError("附件暂存内容无效，请重新选择")
        source = stage / ("original" + extension)
    else:
        raise ValueError("附件暂存内容无效，请重新选择")
    info = source.lstat()
    expected_type = stat.S_ISDIR if kind == "folder" else stat.S_ISREG
    if is_link(info) or not expected_type(info.st_mode):
        raise ValueError("附件暂存内容无效，请重新选择")
    if kind != "folder" and info.st_size != record["size"]:
        raise ValueError("附件暂存内容无效，请重新选择")
    return source


@contextmanager
def reserve(root, scope, tokens, allowed_extensions, claim_used):
    if not all(_TOKEN.fullmatch(token) for token in tokens):
        raise ValueError("附件选择已过期，请重新选择")
    stages = [root / token for token in tokens]
    with _lock:
        if any(stage in _reserved for stage in stages):
            raise ValueError("附件正在保存，请稍后再试")
        _reserved.update(stages)
    try:
        selections = []
        for stage in stages:
            record = _record(stage, scope)
            if "claim" in record:
                claim = record["claim"]
                if claim_used is None or not claim:
                    raise ValueError("附件选择已过期，请重新选择")
                if claim_used(claim):
                    shutil.rmtree(stage, ignore_errors=True)
                    raise ValueError("附件选择已过期，请重新选择")
            try:
                source = _source(stage, record, allowed_extensions)
            except FileNotFoundError as error:
                raise ValueError("附件选择已过期，请重新选择") from error
            selections.append((stage, record, source))
        yield selections
    finally:
        with _lock:
            _reserved.difference_update(stages)
