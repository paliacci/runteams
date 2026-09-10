# -*- coding: utf-8 -*-
"""本机凭据保险箱。

凭据值只保存在权限为 0600 的本机文件中，不进入数据库、移动同步、Prompt 或运行记录。
当前产品只提供一个扁平凭据集合；能力包用同名 Key 显式声明依赖，运行时只解析并注入
当前工具声明的那几项值。
"""
import json
import os
import threading

import product_store as store


_lock = threading.Lock()
MAX_SECRET_BYTES = 512 * 1024


def _path():
    configured = str(os.environ.get("RUNTEAMS_SECRET_VAULT") or "").strip()
    return os.path.abspath(configured) if configured else os.path.join(store.data_dir(), "secrets.json")


def vault_path():
    """Return the local vault location, never its contents."""
    return _path()


def _load():
    try:
        with open(_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # 开发期旧文件使用 {global, cards}；正式模型只保留全局集合，忽略无消费者的 Card 覆盖值。
    if isinstance(data.get("global"), dict):
        data = data["global"]
    return {str(name): str(value) for name, value in data.items()
            if str(name).strip() and isinstance(value, (str, int, float, bool))}


def _save(values):
    path = _path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(values, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _clean_name(name):
    return str(name or "").strip()[:120]


def _mask(value):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return value[:2] + "•" * max(2, min(8, len(value) - 6)) + value[-4:]


def set_secret(name, value):
    name = _clean_name(name)
    if not name:
        raise ValueError("密钥名不能为空")
    value = str(value if value is not None else "")
    if len(value.encode("utf-8")) > MAX_SECRET_BYTES:
        raise ValueError("凭据文件不能超过 512 KB")
    with _lock:
        values = _load()
        if value == "":
            values.pop(name, None)
        else:
            values[name] = value
        _save(values)
    return {"name": name, "set": value != ""}


def set_secrets(values):
    """一次性保存多项凭据，验证全部输入后再落盘。"""
    if not isinstance(values, dict) or not values:
        raise ValueError("没有需要保存的凭据")
    cleaned = {}
    for raw_name, raw_value in values.items():
        name = _clean_name(raw_name)
        if not name:
            raise ValueError("密钥名不能为空")
        value = str(raw_value if raw_value is not None else "")
        if not value.strip():
            raise ValueError("凭据值不能为空")
        if len(value.encode("utf-8")) > MAX_SECRET_BYTES:
            raise ValueError("凭据文件不能超过 512 KB")
        cleaned[name] = value
    with _lock:
        current = _load()
        current.update(cleaned)
        _save(current)
    return [{"name": name, "set": True} for name in cleaned]


def list_masked():
    """返回 Key、掩码和是否已填写，绝不返回明文。"""
    return {name: {"set": True, "masked": _mask(value)}
            for name, value in _load().items()}


def names():
    """返回当前已填写的 Key；用于发布和启动前的可运行性检查。"""
    return set(_load())


def resolve(requested):
    """只解析调用方明确请求的 Key，绝不提供整库读取接口。"""
    requested = [str(name or "").strip() for name in (requested or [])]
    if not requested:
        return {}
    values = _load()
    return {name: values[name] for name in requested if name in values and values[name] != ""}
