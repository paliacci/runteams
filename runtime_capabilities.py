# -*- coding: utf-8 -*-
"""Agent Channel、插件、Skill 与 MCP 的可见资产清单。

只读取官方 CLI 的机器可读状态；不读取凭据内容。插件安装只通过对应渠道的官方 CLI。
"""
import base64
import json
import hashlib
import ipaddress
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import model_channels
import plugin_brands


SCHEMA_VERSION = 1
_CACHE = {}
_PLUGIN_DEPENDENCIES = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 45
_PLUGIN_ICONS = {}
_PLUGIN_ICONS_LOCK = threading.Lock()
_PLUGIN_RESOURCES = {}
_PLUGIN_RESOURCES_LOCK = threading.Lock()
_PLUGIN_ICON_FETCH_LOCK = threading.Lock()
_PLUGIN_ICON_CACHE_DIR = os.path.join(tempfile.gettempdir(), "runteams-plugin-icons")
_PLUGIN_INSTALL_LOCK = threading.Lock()
_PLUGIN_ICON_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".ico": "image/x-icon",
}
_PLUGIN_RESOURCE_MAX_FILES = 5000
_PLUGIN_RESOURCE_MAX_TEXT_BYTES = 2 * 1024 * 1024
_PLUGIN_RESOURCE_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_PLUGIN_RESOURCE_BLOCKED_PARTS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
}
_PLUGIN_RESOURCE_BLOCKED_NAMES = {
    ".env", ".npmrc", ".pypirc", "credentials.json", "auth.json",
    "id_rsa", "id_ed25519",
}


def _cache_key(channel, executable, workspace_root=""):
    try:
        stamp = os.path.getmtime(executable)
    except OSError:
        stamp = 0
    return (channel.get("provider"), executable, stamp,
            os.path.abspath(os.path.expanduser(channel.get("config_dir") or "")),
            os.path.realpath(workspace_root) if workspace_root else "")


def _run_json(argv, env, timeout=12, cwd=None):
    try:
        result = model_channels._run(argv, env, timeout=timeout, cwd=cwd)
        text = (result.stdout or "").strip()
        return json.loads(text) if text else None, result
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None, None


def _plugin_id(item):
    plugin_id = item.get("pluginId") or item.get("id") or item.get("fullName") or ""
    if plugin_id:
        return str(plugin_id)
    name = str(item.get("name") or "")
    marketplace = str(item.get("marketplaceName") or item.get("marketplace") or "")
    return name + ("@" + marketplace if name and marketplace else "")


def _plugins(data):
    installed, available = [], []
    if isinstance(data, list):
        raw_installed, raw_available = data, []
    elif isinstance(data, dict):
        raw_installed = data.get("installed") or data.get("plugins") or []
        raw_available = data.get("available") or []
    else:
        raw_installed, raw_available = [], []
    for item in list(raw_installed) + list(raw_available):
        if not isinstance(item, dict):
            continue
        metadata = _plugin_metadata(item)
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        homepage = str(metadata.get("homepage_url") or item.get("homepage") or "")[:500]
        icon_homepage = str(item.get("iconHomepage") or item.get("icon_homepage") or homepage)[:500]
        record = {
            "id": _plugin_id(item),
            "name": str(item.get("name") or ""),
            "display_name": str(metadata.get("display_name") or item.get("displayName") or item.get("name") or ""),
            "description": str(metadata.get("description") or item.get("description") or "")[:500],
            "category": str(metadata.get("category") or item.get("category") or "")[:120],
            "icon_url": str(metadata.get("icon_url") or _register_homepage_icon(icon_homepage)),
            "marketplace": str(item.get("marketplaceName") or item.get("marketplace") or ""),
            "version": str(item.get("version") or ""),
            "developer_name": str(metadata.get("developer_name") or
                                  item.get("developerName") or author.get("name") or "")[:120],
            "developer_url": str(metadata.get("developer_url") or
                                 item.get("developerUrl") or author.get("url") or "")[:500],
            "long_description": str(metadata.get("long_description") or
                                    item.get("longDescription") or item.get("description") or "")[:2000],
            "homepage_url": homepage,
            "privacy_policy_url": str(metadata.get("privacy_policy_url") or
                                      item.get("privacyPolicyUrl") or "")[:500],
            "terms_url": str(metadata.get("terms_url") or item.get("termsUrl") or "")[:500],
            "license": str(metadata.get("license") or item.get("license") or "")[:120],
            "capabilities": list(metadata.get("capabilities") or item.get("capabilities") or [])[:12],
            "default_prompts": list(metadata.get("default_prompts") or
                                    item.get("defaultPrompts") or [])[:6],
            "components": list(metadata.get("components") or item.get("components") or [])[:24],
            "auth_policy": str(item.get("authPolicy") or "")[:80],
            "installed": bool(item.get("installed", item in raw_installed)),
            "enabled": bool(item.get("enabled", item.get("installed", item in raw_installed))),
            "status": str(item.get("status") or item.get("loadStatus") or ""),
            "has_resources": bool(_plugin_source_path(item)),
        }
        target = installed if record["installed"] else available
        if record["id"] and not any(x["id"] == record["id"] for x in target):
            target.append(record)
    return installed, available


def _channel_config_dir(channel):
    configured = str((channel or {}).get("config_dir") or "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    info = model_channels.provider_info((channel or {}).get("provider"))
    return os.path.abspath(os.path.expanduser(info.get("default_config_dir") or ""))


def _official_catalog_plugins(channel):
    """Read the provider-owned public catalog cache when CLI listing is uninitialized.

    Claude Code downloads its official catalog before a marketplace is registered,
    but `plugin list --available` only exposes configured marketplaces.  Reading the
    CLI-owned cache lets discovery work without mutating channel settings; installing
    an item still goes through the official CLI.
    """
    info = model_channels.provider_info((channel or {}).get("provider"))
    marketplace = info.get("official_marketplace")
    if not isinstance(marketplace, dict):
        return []
    relative = str(marketplace.get("catalog_cache") or "").strip()
    marketplace_id = str(marketplace.get("id") or "").strip()
    if not relative or not marketplace_id or os.path.isabs(relative):
        return []
    root = _channel_config_dir(channel)
    path = os.path.realpath(os.path.join(root, relative))
    if not path.startswith(os.path.realpath(root) + os.sep):
        return []
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > 20 * 1024 * 1024:
            return []
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    catalog = payload.get("catalog") if isinstance(payload, dict) else {}
    raw = catalog.get("plugins") if isinstance(catalog, dict) else {}
    if not isinstance(raw, dict):
        return []
    result = []
    for plugin_id, value in raw.items():
        if not isinstance(value, dict):
            continue
        plugin_id = str(plugin_id or value.get("source") or "").strip()
        if not plugin_id.endswith("@" + marketplace_id):
            continue
        entry = value.get("marketplace_entry")
        entry = entry if isinstance(entry, dict) else {}
        components = value.get("components")
        components = components if isinstance(components, dict) else {}
        component_names = []
        for source in ("skills", "commands", "agents", "mcpServers", "lspServers", "hooks"):
            if components.get(source):
                component_names.append(source)
        author = entry.get("author") if isinstance(entry.get("author"), dict) else {}
        name = str(value.get("plugin") or entry.get("name") or plugin_id.split("@", 1)[0]).strip()
        brand_homepage = plugin_brands.homepage(name)
        result.append({
            "pluginId": plugin_id,
            "name": name,
            "displayName": str(entry.get("displayName") or entry.get("name") or name),
            "description": str(entry.get("description") or "")[:500],
            "category": str(entry.get("category") or "")[:120],
            "marketplaceName": marketplace_id,
            "version": str(value.get("version") or ""),
            "author": {"name": str(author.get("name") or "")[:120],
                       "url": str(author.get("url") or "")[:500]},
            "homepage": str(entry.get("homepage") or "")[:500],
            "iconHomepage": brand_homepage,
            "components": component_names,
            "installed": False,
            "enabled": False,
            "uniqueInstalls": int(value.get("unique_installs") or 0),
        })
    result.sort(key=lambda item: (-item["uniqueInstalls"], item["name"].lower()))
    return result[:1000]


def _plugins_with_official_catalog(channel, plugin_data):
    installed, available = _plugins(plugin_data)
    _unused, official = _plugins({"available": _official_catalog_plugins(channel)})
    known = {str(item.get("id") or "").lower() for item in installed + available}
    for item in official:
        key = str(item.get("id") or "").lower()
        if key and key not in known:
            known.add(key)
            available.append(item)
    return installed, available


def _plugin_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("installed") or data.get("plugins") or [])
    return []


def _plugin_source_path(item):
    source = item.get("source")
    if isinstance(source, dict):
        source = source.get("path") or source.get("source")
    for value in (source, item.get("installPath"), item.get("install_path"),
                  item.get("cachePath"), item.get("path")):
        value = str(value or "").strip()
        if value and os.path.isdir(os.path.expanduser(value)):
            return os.path.abspath(os.path.expanduser(value))
    return ""


def _register_plugin_icon(source_path, interface):
    """登记插件目录内的公开图片，前端只拿到不可反解的短引用。"""
    try:
        root = Path(source_path).resolve()
    except (OSError, RuntimeError):
        return ""
    for value in (interface.get("logo"), interface.get("composerIcon")):
        value = str(value or "").strip()
        if not value:
            continue
        try:
            path = (Path(value) if os.path.isabs(value) else root / value).resolve()
            path.relative_to(root)
            stat = path.stat()
        except (OSError, RuntimeError, ValueError):
            continue
        mime = _PLUGIN_ICON_TYPES.get(path.suffix.lower())
        if not mime or not path.is_file() or stat.st_size > 3 * 1024 * 1024:
            continue
        token = hashlib.sha256("{}:{}:{}".format(
            path, stat.st_mtime_ns, stat.st_size).encode("utf-8")).hexdigest()[:24]
        with _PLUGIN_ICONS_LOCK:
            _PLUGIN_ICONS[token] = (str(path), mime)
        return "/api/environment/plugin-icon/{}".format(token)
    return ""


def configure_plugin_icon_cache(data_dir):
    """把远程站点图标缓存放进应用可写数据目录。"""
    global _PLUGIN_ICON_CACHE_DIR
    root = os.path.abspath(os.path.expanduser(str(data_dir or "").strip()))
    if root:
        _PLUGIN_ICON_CACHE_DIR = os.path.join(root, "cache", "plugin-icons")


def _public_hostname(homepage):
    """只接受公开站点域名；不让目录元数据触达本机或局域网地址。"""
    try:
        parsed = urllib.parse.urlparse(str(homepage or "").strip())
        host = (parsed.hostname or "").strip().rstrip(".").lower().encode("idna").decode("ascii")
    except (TypeError, ValueError, UnicodeError):
        return ""
    if parsed.scheme not in ("http", "https") or not host or "." not in host:
        return ""
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return ""
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    if address and not address.is_global:
        return ""
    return host[:253]


def _register_homepage_icon(homepage):
    """登记官网 favicon；令牌只映射域名，不暴露原始目录数据。"""
    host = _public_hostname(homepage)
    if not host:
        return ""
    github_owner = ""
    if host in ("github.com", "www.github.com"):
        try:
            github_owner = urllib.parse.urlparse(str(homepage)).path.strip("/").split("/", 1)[0]
        except (TypeError, ValueError):
            github_owner = ""
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", github_owner):
            github_owner = ""
    identity = "github-avatar:" + github_owner.lower() if github_owner else "homepage-favicon:" + host
    token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    with _PLUGIN_ICONS_LOCK:
        _PLUGIN_ICONS.setdefault(token, {"kind": "favicon", "host": host,
                                         "github_owner": github_owner})
    return "/api/environment/plugin-icon/{}".format(token)


def _image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if data.startswith((b"\xff\xd8\xff",)):
        return ".jpg", "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if data.startswith(b"\x00\x00\x01\x00"):
        return ".ico", "image/x-icon"
    return None


def _cached_homepage_icon(token, host, github_owner=""):
    """通过固定 favicon 服务取图并落盘；失败时让前端保留既有占位图。"""
    cache_root = os.path.abspath(_PLUGIN_ICON_CACHE_DIR)
    try:
        os.makedirs(cache_root, exist_ok=True)
    except OSError:
        return None
    for suffix, mime in _PLUGIN_ICON_TYPES.items():
        path = os.path.join(cache_root, token + suffix)
        try:
            if os.path.isfile(path) and 0 < os.path.getsize(path) <= 512 * 1024:
                return path, mime
        except OSError:
            continue
    with _PLUGIN_ICON_FETCH_LOCK:
        for suffix, mime in _PLUGIN_ICON_TYPES.items():
            path = os.path.join(cache_root, token + suffix)
            try:
                if os.path.isfile(path) and 0 < os.path.getsize(path) <= 512 * 1024:
                    return path, mime
            except OSError:
                continue
        if github_owner:
            url = "https://github.com/{}.png?size=128".format(
                urllib.parse.quote(github_owner, safe=""))
        else:
            url = "https://www.google.com/s2/favicons?" + urllib.parse.urlencode({
                "domain": host, "sz": "128",
            })
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "RunTeams/0.1 favicon"})
            with urllib.request.urlopen(request, timeout=6) as response:
                data = response.read(512 * 1024 + 1)
        except (OSError, ValueError):
            return None
        image_type = _image_type(data)
        if not image_type or not data or len(data) > 512 * 1024:
            return None
        suffix, mime = image_type
        path = os.path.join(cache_root, token + suffix)
        temporary = path + ".tmp-{}".format(os.getpid())
        try:
            with open(temporary, "wb") as handle:
                handle.write(data)
            os.replace(temporary, path)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            return None
        return path, mime


def plugin_icon(token):
    """解析已登记图标；不接受调用方传入文件路径。"""
    if not re.fullmatch(r"[a-f0-9]{24}", str(token or "")):
        return None
    with _PLUGIN_ICONS_LOCK:
        item = _PLUGIN_ICONS.get(token)
    if not item:
        return None
    if isinstance(item, dict) and item.get("kind") == "favicon":
        return _cached_homepage_icon(str(token), item.get("host") or "",
                                     item.get("github_owner") or "")
    path, mime = item
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > 3 * 1024 * 1024:
            return None
    except OSError:
        return None
    return path, mime


def _plugin_resource_is_sensitive(relative_path):
    parts = [part.lower() for part in Path(relative_path).parts]
    if any(part in _PLUGIN_RESOURCE_BLOCKED_PARTS for part in parts):
        return True
    name = parts[-1] if parts else ""
    if name in _PLUGIN_RESOURCE_BLOCKED_NAMES:
        return True
    if name.startswith(".env.") and name not in (".env.example", ".env.sample"):
        return True
    return name.endswith((".pem", ".key", ".p12", ".pfx"))


def _plugin_resource_root(channel, plugin_id):
    """Resolve an installed provider plugin without exposing its local path."""
    requested = str(plugin_id or "").strip()
    if not channel or not channel.get("enabled"):
        raise ValueError("模型渠道尚未启用")
    if not requested or len(requested) > 240:
        raise ValueError("扩展标识无效")
    try:
        executable = model_channels.resolve_channel_executable(channel)
    except Exception as exc:
        raise RuntimeError("模型渠道不可用") from exc
    provider = model_channels.provider_info(channel.get("provider"))
    list_args = list(provider.get("plugin_list_args") or [])
    if not list_args:
        raise ValueError("当前模型渠道不支持读取扩展资源")
    data, result = _run_json(
        [executable] + list_args, model_channels._probe_env(channel), 20)
    if data is None:
        detail = ""
        if result is not None:
            detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        raise RuntimeError(detail.splitlines()[-1][:300] if detail else "扩展目录读取失败")
    item = next((value for value in _plugin_items(data)
                 if isinstance(value, dict) and _matches(requested, {
                     "id": _plugin_id(value), "name": value.get("name") or "",
                 })), None)
    if not item or item.get("installed") is False:
        raise ValueError("这个扩展尚未安装")
    source_path = _plugin_source_path(item)
    if not source_path:
        raise ValueError("这个扩展没有可浏览的本地资源")
    root = os.path.realpath(source_path)
    if not os.path.isdir(root):
        raise ValueError("扩展资源不存在")
    return root


def _plugin_tree_fingerprint(root):
    """Hash the executable extension asset, not its machine-specific location."""
    digest = hashlib.sha256()
    count = 0
    total = 0
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs
            if not os.path.islink(os.path.join(current, name))
            and name.lower() not in _PLUGIN_RESOURCE_BLOCKED_PARTS)
        for name in sorted(names):
            path = os.path.join(current, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            if _plugin_resource_is_sensitive(relative):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                raise ValueError("扩展资源读取失败")
            count += 1
            total += size
            if count > _PLUGIN_RESOURCE_MAX_FILES or total > 64 * 1024 * 1024:
                raise ValueError("扩展资源过大，暂时不能作为员工的固定依赖")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            try:
                with open(path, "rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
            except OSError as exc:
                raise ValueError("扩展资源读取失败") from exc
            digest.update(b"\0")
    if not count:
        raise ValueError("这个扩展没有可运行的本地资源")
    return digest.hexdigest()


def _codex_marketplace_root(item, source_path):
    source = item.get("marketplaceSource") or item.get("marketplace_source") or {}
    if isinstance(source, dict):
        value = str(source.get("source") or source.get("path") or "").strip()
        if value and os.path.isdir(os.path.expanduser(value)):
            return os.path.abspath(os.path.expanduser(value))
    current = Path(source_path).resolve()
    for parent in (current,) + tuple(current.parents):
        if (parent / ".agents" / "plugins" / "marketplace.json").is_file():
            return str(parent)
    return ""


def plugin_dependency(channel, plugin_id, refresh=False):
    """Resolve one installed extension for an isolated employee runtime.

    The top-level fields are safe to freeze in an employee release.  Local paths
    stay under ``runtime`` and must never be returned by an HTTP endpoint.
    """
    requested = str(plugin_id or "").strip()
    provider_id = str((channel or {}).get("provider") or "").strip()
    if not channel or not channel.get("enabled"):
        raise ValueError("模型渠道尚未启用")
    try:
        executable = model_channels.resolve_channel_executable(channel)
    except Exception as exc:
        raise RuntimeError("模型渠道不可用") from exc
    cache_key = (_cache_key(channel, executable), requested.lower())
    with _CACHE_LOCK:
        cached = _PLUGIN_DEPENDENCIES.get(cache_key)
        if cached and not refresh and time.monotonic() - cached[0] < _CACHE_TTL:
            return json.loads(json.dumps(cached[1]))
    provider = model_channels.provider_info(provider_id)
    list_args = list(provider.get("plugin_list_args") or [])
    if not list_args:
        raise ValueError("当前模型渠道不支持扩展")
    data, result = _run_json(
        [executable] + list_args, model_channels._probe_env(channel), 20)
    if data is None:
        detail = ""
        if result is not None:
            detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        raise RuntimeError(detail.splitlines()[-1][:300] if detail else "扩展目录读取失败")
    item = next((value for value in _plugin_items(data)
                 if isinstance(value, dict) and _matches(requested, {
                     "id": _plugin_id(value), "name": value.get("name") or "",
                 })), None)
    if not item or item.get("installed") is False:
        raise ValueError("这个扩展尚未安装")
    if item.get("enabled") is False:
        raise ValueError("这个扩展尚未启用")
    source_path = _plugin_source_path(item)
    if not source_path:
        raise ValueError("这个扩展不能被员工独立加载")
    marketplace = str(item.get("marketplaceName") or item.get("marketplace") or "")
    marketplace_root = (_codex_marketplace_root(item, source_path)
                        if provider_id == "codex" else "")
    if provider_id == "codex" and (not marketplace or not marketplace_root):
        raise ValueError("这个 Codex 扩展缺少可隔离运行的来源信息")
    dependency = {
        "provider": provider_id,
        "plugin_id": _plugin_id(item),
        "name": str(item.get("displayName") or item.get("name") or _plugin_id(item))[:160],
        "version": str(item.get("version") or "")[:120],
        "fingerprint": _plugin_tree_fingerprint(source_path),
        "runtime": {
            "plugin_dir": source_path,
            "marketplace": marketplace,
            "marketplace_root": marketplace_root,
        },
    }
    with _CACHE_LOCK:
        _PLUGIN_DEPENDENCIES[cache_key] = (
            time.monotonic(), json.loads(json.dumps(dependency)))
    return dependency


def plugin_resources(channel, plugin_id):
    """List safe, regular files for an installed extension and return an opaque handle."""
    root = _plugin_resource_root(channel, plugin_id)
    files = []
    truncated = False
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs
            if not os.path.islink(os.path.join(current, name))
            and name.lower() not in _PLUGIN_RESOURCE_BLOCKED_PARTS)
        for name in sorted(names):
            path = os.path.join(current, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            if _plugin_resource_is_sensitive(relative):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            files.append({"path": relative, "size": size})
            if len(files) >= _PLUGIN_RESOURCE_MAX_FILES:
                truncated = True
                break
        if truncated:
            break
    if not files:
        raise ValueError("这个扩展没有可浏览的资源")
    try:
        stamp = os.stat(root).st_mtime_ns
    except OSError:
        stamp = 0
    token = hashlib.sha256("{}:{}:{}".format(
        root, stamp, plugin_id).encode("utf-8")).hexdigest()[:24]
    with _PLUGIN_RESOURCES_LOCK:
        _PLUGIN_RESOURCES[token] = root
    preferred = next((name for name in ("SKILL.md", "README.md", "plugin.json")
                      if any(item["path"] == name for item in files)), files[0]["path"])
    return {"token": token, "files": files, "active_file": preferred,
            "truncated": truncated}


def plugin_resource_file(token, relative_path):
    """Read one registered extension file with containment and content limits."""
    if not re.fullmatch(r"[a-f0-9]{24}", str(token or "")):
        raise ValueError("资源引用无效")
    with _PLUGIN_RESOURCES_LOCK:
        root = _PLUGIN_RESOURCES.get(str(token))
    if not root:
        raise ValueError("资源引用已失效，请重新打开扩展")
    requested = str(relative_path or "").replace("\\", "/").strip("/")
    if (not requested or "\x00" in requested or os.path.isabs(str(relative_path or ""))
            or any(part in ("", ".", "..") for part in requested.split("/"))
            or _plugin_resource_is_sensitive(requested)):
        raise ValueError("资源路径无效")
    candidate = os.path.join(root, *requested.split("/"))
    path = os.path.realpath(candidate)
    try:
        if (os.path.commonpath((root, path)) != root or os.path.islink(candidate)
                or not os.path.isfile(path)):
            raise ValueError("资源不存在")
        size = os.path.getsize(path)
    except OSError as exc:
        raise ValueError("资源不存在") from exc
    suffix = Path(path).suffix.lower()
    possible_image = suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif")
    if size > _PLUGIN_RESOURCE_MAX_TEXT_BYTES and (
            not possible_image or size > _PLUGIN_RESOURCE_MAX_IMAGE_BYTES):
        return {"path": requested, "size": size, "kind": "large"}
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError("资源读取失败") from exc
    image_type = _image_type(data)
    if image_type and image_type[1] in (
            "image/png", "image/jpeg", "image/webp", "image/gif"):
        return {"path": requested, "size": size, "kind": "image",
                "media_type": image_type[1],
                "content": base64.b64encode(data).decode("ascii")}
    if b"\x00" in data:
        return {"path": requested, "size": size, "kind": "binary"}
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": requested, "size": size, "kind": "binary"}
    return {"path": requested, "size": size, "kind": "text", "content": content}


def warm_plugin_icons(channels):
    """启动阶段只读取插件目录，让快照里的图标首屏即可命中。"""
    def inspect(channel):
        try:
            executable = model_channels.resolve_channel_executable(channel)
            env = model_channels._probe_env(channel)
            argv = [executable] + list(model_channels.provider_info(
                channel.get("provider"))["plugin_list_args"])
            data, _ = _run_json(argv, env, 6)
            _plugins(data)
        except Exception:
            return

    channels = list(channels or [])
    if not channels:
        return 0
    with ThreadPoolExecutor(max_workers=min(4, len(channels))) as pool:
        list(pool.map(inspect, channels))
    with _PLUGIN_ICONS_LOCK:
        return len(_PLUGIN_ICONS)


def _plugin_metadata(item):
    source_path = _plugin_source_path(item)
    if not source_path:
        return {}
    candidates = (Path(source_path) / ".codex-plugin" / "plugin.json",
                  Path(source_path) / ".claude-plugin" / "plugin.json",
                  Path(source_path) / "plugin.json")
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        interface = data.get("interface") if isinstance(data.get("interface"), dict) else {}
        author = data.get("author") if isinstance(data.get("author"), dict) else {}
        capabilities = [str(value)[:80] for value in (interface.get("capabilities") or [])
                        if isinstance(value, (str, int, float))]
        prompts = [str(value)[:300] for value in (interface.get("defaultPrompt") or [])
                   if isinstance(value, (str, int, float))]
        components = [source for source in (
            "skills", "commands", "agents", "mcpServers", "mcp_servers",
            "lspServers", "hooks", "apps",
        ) if data.get(source)]
        return {
            "display_name": interface.get("displayName") or data.get("displayName") or data.get("name"),
            "description": interface.get("shortDescription") or data.get("description"),
            "long_description": interface.get("longDescription") or data.get("description"),
            "category": interface.get("category") or data.get("category"),
            "icon_url": _register_plugin_icon(source_path, interface),
            "developer_name": interface.get("developerName") or author.get("name"),
            "developer_url": author.get("url"),
            "homepage_url": interface.get("websiteURL") or data.get("homepage"),
            "privacy_policy_url": interface.get("privacyPolicyURL"),
            "terms_url": interface.get("termsOfServiceURL"),
            "license": data.get("license"),
            "capabilities": capabilities,
            "default_prompts": prompts,
            "components": components,
        }
    return {}


def _skill_metadata(path):
    """读取 Skill 的公开元数据；不把正文或本地绝对路径返回给前端。"""
    name, description = path.parent.name, ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:32768]
    except OSError:
        return name, description
    if not text.startswith("---"):
        return name, description
    frontmatter = text.split("---", 2)[1]
    for raw in frontmatter.splitlines():
        match = re.match(r"^\s*(name|description)\s*:\s*(.*?)\s*$", raw, re.I)
        if not match:
            continue
        value = match.group(2).strip().strip("\"'")
        if match.group(1).lower() == "name" and value:
            name = value
        elif match.group(1).lower() == "description" and value not in ("|", ">"):
            description = value
    return name[:160], description[:500]


def _skill_icon(path):
    """优先登记 Skill 自带图标；只允许 Skill 目录内的公开图片。"""
    values = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:32768]
    except OSError:
        text = ""
    if text.startswith("---"):
        frontmatter = text.split("---", 2)[1]
        for raw in frontmatter.splitlines():
            match = re.match(r"^\s*(icon|icon_url|logo)\s*:\s*(.*?)\s*$", raw, re.I)
            if match:
                value = match.group(2).strip().strip("\"'")
                if value:
                    values.append(value)
    values.extend(("icon.svg", "icon.png", "icon.webp", "logo.svg", "logo.png",
                   "assets/icon.svg", "assets/icon.png", "assets/logo.svg", "assets/logo.png"))
    for value in values:
        icon_url = _register_plugin_icon(str(path.parent), {"logo": value})
        if icon_url:
            return icon_url
    return ""


def _scan_skill_directory(root, source, plugin_id="", enabled=True):
    root = Path(os.path.expanduser(str(root or "")))
    if not root.is_dir():
        return []
    result = []
    try:
        manifests = sorted(root.glob("*/SKILL.md"))
    except OSError:
        manifests = []
    for manifest in manifests[:200]:
        name, description = _skill_metadata(manifest)
        result.append({
            "id": (plugin_id + ":" if plugin_id else "") + manifest.parent.name,
            "name": name or manifest.parent.name,
            "description": description,
            "icon_url": _skill_icon(manifest),
            "source": source,
            "plugin_id": plugin_id,
            "enabled": bool(enabled),
            "scope": "plugin" if plugin_id else "personal",
            "manage_mode": "plugin" if plugin_id else "read_only",
        })
    return result


def _skills(channel, plugin_data, workspace_root=""):
    """汇总渠道可见 Skill；生命周期仍由父插件或渠道配置目录负责。"""
    result, seen_paths = [], set()
    for item in _plugin_items(plugin_data):
        if not isinstance(item, dict) or not item.get("installed", True):
            continue
        plugin_id = _plugin_id(item)
        source_path = _plugin_source_path(item)
        if not source_path:
            continue
        skills_root = Path(source_path) / "skills"
        for skill in _scan_skill_directory(skills_root, "plugin", plugin_id,
                                           item.get("enabled", True)):
            key = (plugin_id, skill["id"].split(":", 1)[-1])
            if key not in seen_paths:
                seen_paths.add(key)
                result.append(skill)

    info = model_channels.provider_info(channel.get("provider"))
    config_dir = str(channel.get("config_dir") or "").strip()
    if not config_dir:
        config_dir = info["default_config_dir"]
    personal_roots = [Path(os.path.expanduser(config_dir)) / "skills"]
    if not str(channel.get("config_dir") or "").strip():
        personal_roots.extend(Path(os.path.expanduser(path)) for path in info.get("personal_skills_extra") or [])
    for personal_root in personal_roots:
        for skill in _scan_skill_directory(personal_root, "personal"):
            key = ("personal", skill["id"])
            if key not in seen_paths:
                seen_paths.add(key)
                result.append(skill)

    workspace_root = (os.path.realpath(os.path.expanduser(workspace_root))
                      if str(workspace_root or "").strip() else "")
    if workspace_root and os.path.isdir(workspace_root):
        relative = info["project_skills_dir"]
        project_root = Path(workspace_root) / relative
        for skill in _scan_skill_directory(project_root, "project"):
            key = ("project", skill["id"])
            if key not in seen_paths:
                seen_paths.add(key)
                skill["scope"] = "project"
                result.append(skill)
    return result


def _mcp_records(data):
    raw = data if isinstance(data, list) else ((data or {}).get("servers") if isinstance(data, dict) else [])
    result = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        transport = item.get("transport") or ""
        if isinstance(transport, dict):
            transport = transport.get("type") or ""
        icon = item.get("icon_url") or item.get("iconUrl") or item.get("logo") or item.get("icon") or ""
        if isinstance(icon, dict):
            icon = icon.get("url") or icon.get("src") or ""
        icon = str(icon or "").strip()
        if not re.match(r"^https?://", icon, re.I):
            icon = ""
        result.append({
            "name": str(item.get("name") or item.get("id") or ""),
            "enabled": bool(item.get("enabled", True)),
            "transport": str(transport),
            "icon_url": icon[:500],
            "auth_status": str(item.get("auth_status") or item.get("authStatus") or "unknown"),
            "status": str(item.get("status") or "configured"),
        })
    return [item for item in result if item["name"]]


def _parse_claude_mcp(text):
    result = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.lower().startswith(("checking ", "no mcp")):
            continue
        match = re.match(r"^([^:]+):.*?(?:-|–)\s*(.+)$", line)
        if not match:
            continue
        name, state = match.group(1).strip(), match.group(2).strip()
        low = state.lower()
        result.append({"name": name, "enabled": "disabled" not in low,
                       "transport": "", "auth_status": "not_logged_in" if "auth" in low else "unknown",
                       "status": "connected" if any(x in low for x in ("connected", "✓", "ready")) else state[:80]})
    return result


def _diagnostics(data):
    if not isinstance(data, dict):
        return []
    checks = data.get("checks") or {}
    allowed = ("installation", "auth.credentials", "config.load", "mcp.config",
               "network.provider_reachability", "network.websocket_reachability", "sandbox.helpers")
    result = []
    for key in allowed:
        item = checks.get(key)
        if not isinstance(item, dict):
            continue
        result.append({"id": key, "status": item.get("status") or "unknown",
                       "summary": str(item.get("summary") or "")[:300],
                       "remediation": str(item.get("remediation") or "")[:500]})
    return result


def inventory(channel, refresh=False, workspace_root=""):
    """返回脱敏、可序列化的 Channel 能力清单。"""
    base = {"schema_version": SCHEMA_VERSION, "provider": channel.get("provider"),
            "checked_at": int(time.time()), "status": "missing", "runtime": {},
            "plugins": [], "available_plugins": [], "skills": [], "mcp_servers": [], "diagnostics": []}
    try:
        executable = model_channels.resolve_channel_executable(channel)
    except Exception as exc:
        base["runtime"] = {"installed": False, "authenticated": False, "detail": str(exc)[:300]}
        return base
    workspace_root = (os.path.realpath(os.path.expanduser(workspace_root))
                      if str(workspace_root or "").strip() else "")
    workspace_root = workspace_root if os.path.isdir(workspace_root) else ""
    key = _cache_key(channel, executable, workspace_root)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < _CACHE_TTL:
            return json.loads(json.dumps(cached[1]))

    probe = model_channels.probe(channel)
    base["status"] = probe.get("status") or "error"
    base["runtime"] = {
        "installed": bool(probe.get("installed")), "authenticated": bool(probe.get("authenticated")),
        "compatible": bool(probe.get("compatible", True)),
        "version": probe.get("version") or "", "executable": probe.get("executable") or executable,
        "account": probe.get("account") or "",
        # 登录成功时 CLI 的 detail 可能包含组织 ID 等原始认证元数据；能力清单不需要回传。
        "detail": "" if probe.get("installed") and probe.get("authenticated") else (probe.get("detail") or ""),
    }
    env = model_channels._probe_env(channel)
    def channel_json(argv, timeout):
        if workspace_root:
            return _run_json(argv, env, timeout, workspace_root)
        return _run_json(argv, env, timeout)
    if channel.get("provider") == "codex":
        plugin_data, _ = channel_json([executable, "plugin", "list", "--available", "--json"], 15)
        base["plugins"], base["available_plugins"] = _plugins(plugin_data)
        base["skills"] = _skills(channel, plugin_data, workspace_root)
        mcp_data, _ = channel_json([executable, "mcp", "list", "--json"], 12)
        base["mcp_servers"] = _mcp_records(mcp_data)
        doctor_data, _ = _run_json([executable, "doctor", "--json"], env, 15)
        base["diagnostics"] = _diagnostics(doctor_data)
    else:
        plugin_data, _ = channel_json([executable, "plugin", "list", "--json", "--available"], 15)
        base["plugins"], base["available_plugins"] = _plugins_with_official_catalog(
            channel, plugin_data)
        base["skills"] = _skills(channel, plugin_data, workspace_root)
        mcp_data, mcp_result = _run_json([executable, "mcp", "list", "--json"], env, 12)
        if mcp_data is not None:
            base["mcp_servers"] = _mcp_records(mcp_data)
        else:
            try:
                plain = model_channels._run([executable, "mcp", "list"], env, timeout=12,
                                            cwd=workspace_root or None)
                base["mcp_servers"] = _parse_claude_mcp((plain.stdout or "") + (plain.stderr or ""))
            except Exception:
                base["mcp_servers"] = []
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), json.loads(json.dumps(base)))
    return base


def _matches(required, actual):
    need = required.strip().lower()
    full = str(actual.get("id") or actual.get("name") or "").strip().lower()
    name = str(actual.get("name") or full.split("@", 1)[0]).strip().lower()
    return need == full or ("@" not in need and need == name)


def _marketplace_names(value):
    if not isinstance(value, list):
        return set()
    names = set()
    for item in value:
        if isinstance(item, dict):
            item = item.get("name") or item.get("id") or item.get("marketplace")
        name = str(item or "").strip().lower()
        if name:
            names.add(name)
    return names


def _ensure_official_marketplace(channel, available, executable, env, timeout):
    info = model_channels.provider_info(channel.get("provider"))
    marketplace = info.get("official_marketplace")
    if not isinstance(marketplace, dict):
        return
    marketplace_id = str(marketplace.get("id") or "").strip()
    source = str(marketplace.get("source") or "").strip()
    item_marketplace = str(available.get("marketplace") or "").strip()
    if not marketplace_id or not source or item_marketplace != marketplace_id:
        return
    configured, _ = _run_json(
        [executable, "plugin", "marketplace", "list", "--json"], env,
        timeout=max(10, min(30, int(timeout or 30))))
    if configured is None or marketplace_id.lower() in _marketplace_names(configured):
        return
    try:
        result = model_channels._run(
            [executable, "plugin", "marketplace", "add", source], env,
            timeout=max(30, min(120, int(timeout or 120))))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("初始化 Claude 官方扩展目录超时，请稍后重试") from exc
    except OSError as exc:
        raise RuntimeError("无法启动 Claude CLI") from exc
    if result.returncode:
        detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        detail = detail.splitlines()[-1][:300] if detail else "Claude 官方扩展目录初始化失败"
        raise RuntimeError(detail)


def install_plugin(channel, plugin_id, timeout=180):
    """通过当前 Channel 的官方 CLI 安装一个已发现的插件。

    插件必须先出现在 CLI 返回的可用目录里；命令使用声明式 argv 执行，
    不经过 shell，也不接受调用方提供任意命令。
    """
    requested = str(plugin_id or "").strip()
    if not channel or not channel.get("enabled"):
        raise ValueError("模型渠道尚未启用")
    if not requested or len(requested) > 240:
        raise ValueError("扩展标识无效")
    with _PLUGIN_INSTALL_LOCK:
        before = inventory(channel, refresh=True)
        installed = next((item for item in before.get("plugins") or []
                          if _matches(requested, item)), None)
        if installed and installed.get("enabled") is not False:
            return {"plugin": installed, "already_installed": True}
        available = next((item for item in before.get("available_plugins") or []
                          if _matches(requested, item)), None)
        if not available:
            raise ValueError("当前模型渠道找不到这个扩展")
        provider = model_channels.provider_info(channel.get("provider"))
        template = provider.get("plugin_add_args") or []
        if not template:
            raise ValueError("当前模型渠道暂不支持安装扩展")
        executable = model_channels.resolve_channel_executable(channel)
        env = model_channels._probe_env(channel)
        _ensure_official_marketplace(channel, available, executable, env, timeout)
        argv = [executable] + [str(part).format(id=available.get("id") or requested)
                               for part in template]
        try:
            result = model_channels._run(
                argv, env, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("安装超时，请稍后重试") from exc
        except OSError as exc:
            raise RuntimeError("无法启动模型渠道 CLI") from exc
        if result.returncode:
            detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
            detail = detail.splitlines()[-1][:300] if detail else "官方 CLI 安装失败"
            raise RuntimeError(detail)
        with _CACHE_LOCK:
            _CACHE.clear()
            _PLUGIN_DEPENDENCIES.clear()
        after = inventory(channel, refresh=True)
        found = next((item for item in after.get("plugins") or []
                      if _matches(requested, item)), None)
        plugin = dict(found or available)
        plugin.update({"installed": True, "enabled": True})
        return {"plugin": plugin, "already_installed": False}


def _status_rank(value):
    return {"blocked": 3, "warning": 2, "ready": 1}.get(value, 0)


def environment_summary(channels, refresh=False, workspace_root=""):
    """Aggregate channel-owned assets without reading employee-domain records."""
    channels = list(channels or [])
    found = {}
    if channels:
        with ThreadPoolExecutor(max_workers=min(4, len(channels))) as pool:
            jobs = {pool.submit(inventory, channel, refresh, workspace_root): channel for channel in channels}
            for job in as_completed(jobs):
                channel = jobs[job]
                try:
                    found[channel.get("id")] = job.result()
                except Exception as exc:
                    found[channel.get("id")] = {
                        "status": "error", "runtime": {"installed": False, "authenticated": False,
                                                        "detail": str(exc)[:300]},
                        "plugins": [], "available_plugins": [], "mcp_servers": [], "diagnostics": [],
                    }

    channel_rows, plugins, available_plugins, skills, mcps, issues = [], [], [], [], [], []
    ready_channels = 0
    for channel in channels:
        inv = found.get(channel.get("id")) or {}
        runtime = inv.get("runtime") or {}
        ready = bool(channel.get("enabled") and runtime.get("installed") and
                     runtime.get("authenticated") and runtime.get("compatible", True))
        if ready:
            ready_channels += 1
        channel_row = {
            "id": channel.get("id"), "name": channel.get("name") or channel.get("provider") or "Agent Channel",
            "provider": channel.get("provider") or "", "enabled": bool(channel.get("enabled")),
            "ready": ready, "status": inv.get("status") or "unknown", "runtime": runtime,
            "plugin_count": len(inv.get("plugins") or []), "skill_count": len(inv.get("skills") or []),
            "mcp_count": len(inv.get("mcp_servers") or []),
            "diagnostics": inv.get("diagnostics") or [],
        }
        channel_rows.append(channel_row)
        if not ready:
            if not channel.get("enabled"):
                detail, remediation = "Agent Channel 未启用", "在模型与订阅渠道中启用并连接。"
            elif not runtime.get("installed"):
                detail, remediation = "找不到 Agent CLI", runtime.get("detail") or "安装 CLI 或设置可执行文件路径。"
            elif runtime.get("compatible") is False:
                detail = "Agent CLI 版本与 RunTeams 不兼容"
                remediation = runtime.get("detail") or "更新到当前官方 Agent CLI。"
            else:
                detail, remediation = "Agent CLI 尚未登录", "使用官方 CLI 完成订阅登录。"
            issues.append({"kind": "runtime", "name": channel_row["name"], "status": "blocked",
                           "detail": detail, "remediation": remediation, "channel_id": channel.get("id")})
        skills_by_plugin = {}
        for skill in inv.get("skills") or []:
            plugin_id = str(skill.get("plugin_id") or "")
            if plugin_id:
                skills_by_plugin.setdefault(plugin_id, []).append({
                    "id": str(skill.get("id") or "")[:240],
                    "name": str(skill.get("name") or skill.get("id") or "")[:160],
                    "description": str(skill.get("description") or "")[:500],
                })
        for item in inv.get("plugins") or []:
            row = dict(item)
            row.update({"channel_id": channel.get("id"), "channel_name": channel_row["name"],
                        "used_by": [],
                        "included_skills": skills_by_plugin.get(str(item.get("id") or ""), [])})
            plugins.append(row)
            if not item.get("enabled"):
                issues.append({"kind": "plugin", "name": item.get("id") or item.get("name"),
                               "status": "warning", "detail": "插件已安装但未启用",
                               "remediation": "在官方 CLI 中启用该插件。", "channel_id": channel.get("id")})
        for item in inv.get("available_plugins") or []:
            row = dict(item)
            row.update({"channel_id": channel.get("id"), "channel_name": channel_row["name"],
                        "provider": channel.get("provider") or ""})
            available_plugins.append(row)
        for item in inv.get("skills") or []:
            row = dict(item)
            row.update({"channel_id": channel.get("id"), "channel_name": channel_row["name"],
                        "provider": channel.get("provider") or ""})
            skills.append(row)
        for item in inv.get("mcp_servers") or []:
            row = dict(item)
            row.update({"channel_id": channel.get("id"), "channel_name": channel_row["name"],
                        "used_by": []})
            mcps.append(row)
            auth = item.get("auth_status")
            if not item.get("enabled") or auth in ("not_logged_in", "unauthorized", "login_required", "required"):
                issues.append({"kind": "mcp", "name": item.get("name"), "status": "warning",
                               "detail": "MCP Server 已停用" if not item.get("enabled") else "MCP Server 尚未认证",
                               "remediation": "在官方 CLI 中启用并完成认证。", "channel_id": channel.get("id")})
        for item in inv.get("diagnostics") or []:
            if item.get("status") not in ("ok", "ready", "passed", "pass"):
                issues.append({"kind": "diagnostic", "name": item.get("id"), "status": "warning",
                               "detail": item.get("summary") or "运行环境检查未通过",
                               "remediation": item.get("remediation") or "按 Agent CLI 提示修复。",
                               "channel_id": channel.get("id")})
    issues.sort(key=lambda item: (-_status_rank(item.get("status")), str(item.get("name") or "")))
    return {
        "schema_version": SCHEMA_VERSION, "checked_at": int(time.time()),
        "ready": not any(item.get("status") == "blocked" for item in issues),
        "counts": {"channels": len(channel_rows), "ready_channels": ready_channels,
                   "plugins": len(plugins), "available_plugins": len(available_plugins),
                   "skills": len(skills),
                   "mcp_servers": len(mcps), "issues": len(issues)},
        "channels": channel_rows, "plugins": plugins, "available_plugins": available_plugins,
        "skills": skills,
        "mcp_servers": mcps, "issues": issues,
    }
