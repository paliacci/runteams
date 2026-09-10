# -*- coding: utf-8 -*-
"""订阅模型渠道：全局目录直接来自各厂商 CLI，业务页不维护模型清单。"""
import json
import os
import shlex
import subprocess
import queue
import threading
import time

import cli_compatibility
from adapter_claude import ClaudeCodeAdapter, resolve_claude
from adapter_codex import CodexAdapter, resolve_codex
import provider_catalog


PROVIDERS = provider_catalog.PROVIDER_MAP
DEFAULT_PROVIDER_ID = provider_catalog.DEFAULT_PROVIDER_ID
_ADAPTERS = {
    "claude-code": {"resolve": resolve_claude, "adapter": ClaudeCodeAdapter,
                    "model_loader": "_claude_models", "auth_probe": "_probe_claude_auth"},
    "codex": {"resolve": resolve_codex, "adapter": CodexAdapter,
              "model_loader": "_codex_models", "auth_probe": "_probe_codex_auth"},
}
if set(_ADAPTERS) != set(PROVIDERS):
    raise RuntimeError("模型渠道目录与适配器注册表不一致")

_MODEL_CACHE = {}
_MODEL_CACHE_LOCK = threading.Lock()
_MODEL_CACHE_TTL = 300
_MODEL_ERROR_CACHE_TTL = 15


def provider_info(provider):
    return provider_catalog.provider_info(provider)


def public_providers():
    return provider_catalog.public_catalog()


def _expanded(path):
    return os.path.abspath(os.path.expanduser(path)) if (path or "").strip() else ""


def resolve_channel_executable(channel):
    explicit = _expanded(channel.get("executable") or "")
    if explicit:
        if os.path.isfile(explicit) and os.access(explicit, os.X_OK):
            return explicit
        raise RuntimeError("CLI 不可执行：{}".format(explicit))
    runtime = _ADAPTERS.get(channel.get("provider"))
    if not runtime:
        raise RuntimeError("暂不支持此模型渠道：{}".format(channel.get("provider") or "unknown"))
    return runtime["resolve"]()


def adapter_for(channel):
    executable = resolve_channel_executable(channel)
    config_dir = _expanded(channel.get("config_dir") or "")
    runtime = _ADAPTERS.get(channel.get("provider"))
    if not runtime:
        raise RuntimeError("暂不支持此模型渠道：{}".format(channel.get("provider") or "unknown"))
    return runtime["adapter"](executable=executable, config_dir=config_dir)


def _probe_env(channel):
    env = os.environ.copy()
    config_dir = _expanded(channel.get("config_dir") or "")
    if config_dir:
        env[provider_info(channel.get("provider"))["config_env"]] = config_dir
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                "OPENAI_API_KEY", "CODEX_ACCESS_TOKEN"):
        env.pop(key, None)
    return env


def _run(argv, env, timeout=8, cwd=None):
    return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, env=env, timeout=timeout, cwd=cwd)


def _plan_label(plan):
    value = (plan or "").strip().lower()
    labels = {"free": "Free", "plus": "Plus", "pro": "Pro", "team": "Team",
              "business": "Business", "enterprise": "Enterprise", "edu": "Edu"}
    return labels.get(value, value.replace("_", " ").title())


def _codex_app_server_request(executable, env, method, params=None, timeout=5):
    """调用 Codex 官方 app-server 的单个 JSONL 请求。"""
    p = subprocess.Popen([executable, "app-server", "--listen", "stdio://"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, env=env, bufsize=1,
                         start_new_session=(os.name != "nt"))
    lines = queue.Queue()

    def read_stdout():
        try:
            for line in p.stdout:
                lines.put(line)
        except Exception:
            pass

    threading.Thread(target=read_stdout, daemon=True).start()
    messages = [
        {"method": "initialize", "id": 0, "params": {"clientInfo": {
            "name": "runteams", "title": "RunTeams.ai", "version": "0.1"}}},
        {"method": "initialized", "params": {}},
        {"method": method, "id": 1, "params": params or {}},
    ]
    try:
        for message in messages:
            p.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        p.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            try:
                data = json.loads(line)
            except Exception:
                continue
            if data.get("id") != 1:
                continue
            if data.get("error"):
                error = data.get("error") or {}
                raise RuntimeError(error.get("message") or "Codex app-server 请求失败")
            return data.get("result") or {}
        return {}
    finally:
        try:
            p.terminate()
            p.wait(timeout=1)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        for stream in (p.stdin, p.stdout):
            try:
                stream.close()
            except Exception:
                pass


def _codex_account(executable, env, timeout=5):
    """通过官方 app-server 的 account/read 获取脱敏账户摘要，不读取 auth.json/token。"""
    result = _codex_app_server_request(
        executable, env, "account/read", {"refreshToken": False}, timeout)
    account = (result.get("account") or {})
    if account.get("type") != "chatgpt":
        return {}
    return {"email": (account.get("email") or "").strip(),
            "plan": _plan_label(account.get("planType"))}


def _codex_rate_limits(executable, env, timeout=5):
    """读取 Codex 官方 app-server 的限额窗口（只读，不发送模型请求）。"""
    result = _codex_app_server_request(
        executable, env, "account/rateLimits/read", {}, timeout)
    limits = result.get("rateLimits") or {}
    candidates = []

    def add_limit(name, value):
        if not isinstance(value, dict):
            return
        used = value.get("usedPercent")
        duration = value.get("windowDurationMins")
        try:
            used = float(used)
            duration = float(duration)
        except (TypeError, ValueError):
            return
        if duration <= 0 or used != used:  # NaN guard
            return
        candidates.append({"name": str(name or ""), "used_percent": max(0, min(100, used)),
                           "window_minutes": duration, "resets_at": value.get("resetsAt")})

    for name in ("primary", "secondary"):
        add_limit(name, limits.get(name))
    # Newer Codex builds may expose per-product windows in this map.
    for product, value in (limits.get("rateLimitsByLimitId") or {}).items():
        if isinstance(value, dict) and any(key in value for key in ("usedPercent", "windowDurationMins")):
            add_limit(product, value)
        elif isinstance(value, dict):
            for name, nested in value.items():
                add_limit("{}:{}".format(product, name), nested)
    # Some versions put the map alongside rateLimits rather than inside it.
    for product, value in (result.get("rateLimitsByLimitId") or {}).items():
        add_limit(product, value)
    if not candidates:
        return {}
    weekly = [item for item in candidates if item["window_minutes"] >= 7 * 24 * 60]
    # 账户菜单的承诺是「每周剩余」，没有周窗口时宁可显示不可用，
    # 也不把短周期额度误标成周额度。
    if not weekly:
        return {}
    selected = max(weekly, key=lambda item: item["window_minutes"])
    selected["remaining_percent"] = max(0, min(100, 100 - selected["used_percent"]))
    selected["window"] = "weekly"
    return selected


def channel_usage(channel, timeout=5):
    """读取已连接 CLI 的可用额度摘要；失败时返回可展示的状态，不伪造额度。"""
    provider = channel.get("provider") or ""
    info = provider_info(provider)
    result = {"channel_id": channel.get("id"), "provider": provider,
              "label": info.get("short_label") or info.get("label") or provider,
              "status": "unavailable", "remaining_percent": None,
              "used_percent": None, "window": "weekly", "resets_at": None,
              "checked_at": time.time(), "detail": ""}
    if not channel.get("enabled", 1):
        result.update(status="disabled", detail="渠道未连接")
        return result
    try:
        executable = resolve_channel_executable(channel)
        env = _probe_env(channel)
        if provider == "codex":
            # 以官方只读 rate-limits 响应作为连接状态的事实来源。
            # login status 的文本在不同 CLI 版本/语言下会变化，不能仅凭
            # “logged in” 字样把一个实际可用的账号误判为未连接。
            try:
                limit = _codex_rate_limits(executable, env, timeout=timeout)
            except Exception:
                limit = {}
            if not limit:
                auth = _probe_codex_auth(executable, env)
                result.update(status="unavailable" if auth.get("authenticated") else "not_connected",
                              detail="Codex CLI 未返回每周限额" if auth.get("authenticated") else "CLI 尚未登录")
                return result
            result.update(status="ready", remaining_percent=round(limit["remaining_percent"], 1),
                          used_percent=round(limit["used_percent"], 1),
                          window=limit["window"], resets_at=limit.get("resets_at"))
            return result
        if provider == "claude-code":
            auth = _probe_claude_auth(executable, env)
            if not auth.get("authenticated"):
                result.update(status="not_connected", detail="CLI 尚未登录")
                return result
            # Claude Code exposes this value in its configured statusline and in
            # the interactive /usage command, but currently has no documented
            # one-shot machine-readable CLI endpoint for a read-only poll.
            result.update(status="unavailable", detail="Claude Code CLI 暂不提供可直接读取的每周额度")
            return result
        result.update(detail="暂不支持此模型渠道")
    except subprocess.TimeoutExpired:
        result.update(status="error", detail="CLI 额度查询超时")
    except Exception as exc:
        result.update(status="error", detail=str(exc)[:240])
    return result


def channels_usage(channels):
    """批量读取已连接渠道的额度，保持与渠道目录相同的公开字段边界。"""
    usages = [channel_usage(channel) for channel in channels if channel.get("enabled", 1)]
    # 默认渠道记录可能存在但尚未完成登录；账户菜单只展示真正已连接的 CLI。
    return {"channels": [item for item in usages if item.get("status") not in ("not_connected", "disabled")],
            "checked_at": time.time()}


def _codex_models(channel, timeout=6):
    """从当前 Codex CLI/登录账号读取选择器可见模型及能力。"""
    executable = resolve_channel_executable(channel)
    result = _codex_app_server_request(
        executable, _probe_env(channel), "model/list",
        {"limit": 100, "includeHidden": False}, timeout)
    models, seen = [], set()
    for entry in result.get("data") or []:
        model = str(entry.get("model") or entry.get("id") or "").strip()
        if not model or entry.get("hidden") is True or model in seen:
            continue
        seen.add(model)
        efforts = []
        effort_descriptions = {}
        for effort in entry.get("supportedReasoningEfforts") or []:
            value = str(effort.get("reasoningEffort") or "").strip()
            if not value or value in efforts:
                continue
            efforts.append(value)
            if effort.get("description"):
                effort_descriptions[value] = str(effort["description"])
        cli_default_effort = str(entry.get("defaultReasoningEffort") or "").strip()
        item = {
            "value": model,
            "resolved_model": model,
            "display_name": str(entry.get("displayName") or model).strip(),
            "description": str(entry.get("description") or "").strip(),
            "efforts": efforts,
            "effort_descriptions": effort_descriptions,
            # RunTeams 的 Codex 岗位默认用于严肃交付。只在模型明确支持时
            # 覆盖 CLI 的较低默认值；用户显式选择的 effort 仍由
            # normalize_selection 原样保留。
            "default_effort": "high" if "high" in efforts else cli_default_effort,
            "is_default": bool(entry.get("isDefault")),
        }
        models.append(item)
    if not models:
        raise RuntimeError("Codex CLI 没有返回可见模型")
    return models


def _claude_models(channel, timeout=8):
    """读取 Claude Code 初始化协议返回的 /model 选择器目录，不发送提示。"""
    executable = resolve_channel_executable(channel)
    argv = [executable, "--print", "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
            "--no-session-persistence", "--safe-mode"]
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=_probe_env(channel),
                         bufsize=1, start_new_session=(os.name != "nt"))
    lines = queue.Queue()

    def read_stdout():
        try:
            for line in p.stdout:
                lines.put(line)
        except Exception:
            pass

    threading.Thread(target=read_stdout, daemon=True).start()
    request = {"type": "control_request", "request_id": "models",
               "request": {"subtype": "initialize", "hooks": None}}
    try:
        p.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        p.stdin.flush()
        deadline = time.monotonic() + timeout
        raw_models = None
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            try:
                data = json.loads(line)
            except Exception:
                continue
            if data.get("type") != "control_response":
                continue
            response = data.get("response") or {}
            if response.get("request_id") != "models":
                continue
            if response.get("subtype") != "success":
                raise RuntimeError(response.get("error") or "Claude Code 初始化失败")
            payload = response.get("response") or response
            raw_models = payload.get("models")
            break
        if not raw_models:
            raise RuntimeError("Claude Code 没有返回可见模型")
        models, seen = [], set()
        for entry in raw_models:
            cli_value = str(entry.get("value") or "").strip()
            # Claude 还会返回一个语义化的 default 项；产品只展示明确模型。
            if not cli_value or cli_value == "default" or cli_value in seen:
                continue
            seen.add(cli_value)
            efforts = [str(x).strip() for x in entry.get("supportedEffortLevels") or [] if str(x).strip()]
            models.append({
                "value": cli_value,
                "resolved_model": str(entry.get("resolvedModel") or "").strip(),
                "display_name": str(entry.get("displayName") or cli_value).strip(),
                "description": str(entry.get("description") or "").strip(),
                "efforts": list(dict.fromkeys(efforts)),
                "effort_descriptions": {},
                "default_effort": "high" if "high" in efforts else efforts[0] if efforts else "",
                "is_default": False,
            })
        if not models:
            raise RuntimeError("Claude Code 没有返回可见模型")
        return models
    finally:
        try:
            p.terminate()
            p.wait(timeout=1)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        for stream in (p.stdin, p.stdout):
            try:
                stream.close()
            except Exception:
                pass


def _fallback_models():
    return []


def _catalog_key(channel, executable):
    try:
        stat = os.stat(executable)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = (0, 0)
    return (channel.get("provider"), executable, stamp,
            _expanded(channel.get("config_dir") or ""))


def channel_catalog(channel, refresh=False):
    """返回单个渠道的全局模型目录；失败时不伪造可选模型。"""
    try:
        executable = resolve_channel_executable(channel)
        key = _catalog_key(channel, executable)
    except Exception as e:
        return {"channel_id": channel.get("id"), "provider": channel.get("provider"),
                "source": "fallback", "models": _fallback_models(), "error": str(e)[:300]}

    now = time.monotonic()
    if not refresh:
        with _MODEL_CACHE_LOCK:
            cached = _MODEL_CACHE.get(key)
        if cached and cached[0] > now:
            result = dict(cached[1])
            result["channel_id"] = channel.get("id")
            return result
    try:
        loader_name = (_ADAPTERS.get(channel.get("provider")) or {}).get("model_loader")
        if not loader_name:
            raise RuntimeError("暂不支持此模型渠道：{}".format(channel.get("provider") or "unknown"))
        models = globals()[loader_name](channel)
        result = {"channel_id": channel.get("id"), "provider": channel.get("provider"),
                  "source": "cli", "models": models, "error": ""}
        ttl = _MODEL_CACHE_TTL
    except Exception as e:
        result = {"channel_id": channel.get("id"), "provider": channel.get("provider"),
                  "source": "fallback", "models": _fallback_models(), "error": str(e)[:300]}
        ttl = _MODEL_ERROR_CACHE_TTL
    with _MODEL_CACHE_LOCK:
        cached_result = dict(result)
        cached_result.pop("channel_id", None)
        _MODEL_CACHE[key] = (now + ttl, cached_result)
    return result


def global_catalog(channels, refresh=False):
    """整个产品共享的 CLI 模型目录。"""
    return {"channels": [channel_catalog(channel, refresh=refresh) for channel in channels]}


def normalize_selection(channel, model, effort):
    """按 CLI 目录规范化模型与思考深度；空值选第一个真实模型。"""
    model = str(model or "").strip()
    effort = str(effort or "").strip().lower()
    catalog = channel_catalog(channel)
    if not model and catalog["models"]:
        model = catalog["models"][0]["value"]
    selected = next((item for item in catalog["models"] if item["value"] == model), None)
    if not selected:
        if not effort:
            effort = provider_info(channel.get("provider")).get("default_effort") or ""
        return model, effort
    supported = selected.get("efforts") or []
    if not supported:
        return model, ""
    if effort not in supported:
        effort = "high" if "high" in supported else selected.get("default_effort") or supported[0]
    return model, effort


def _probe_codex_auth(exe, env):
    p = _run([exe, "login", "status"], env)
    blob = ((p.stdout or "") + (p.stderr or "")).strip()
    ok = p.returncode == 0 and "logged in" in blob.lower()
    account_info = {}
    if ok:
        try:
            account_info = _codex_account(exe, env)
        except Exception:
            pass
    account = " · ".join(x for x in (account_info.get("email"), account_info.get("plan")) if x)
    return {"authenticated": ok, "status": "ready" if ok else "login_required",
            "account": account or ("ChatGPT 订阅" if ok else ""),
            "account_email": account_info.get("email", ""),
            "subscription": account_info.get("plan", ""), "detail": blob[:300]}


def _probe_claude_auth(exe, env):
    p = _run([exe, "auth", "status"], env)
    blob = ((p.stdout or "") + (p.stderr or "")).strip()
    try:
        data = json.loads(p.stdout or "{}")
    except Exception:
        data = {}
    ok = p.returncode == 0 and bool(data.get("loggedIn"))
    account = data.get("email") or data.get("orgName") or ""
    subtype = data.get("subscriptionType") or ""
    if account and subtype:
        account += " · " + subtype
    return {"authenticated": ok, "status": "ready" if ok else "login_required",
            "account": account, "detail": blob[:300]}


def probe(channel):
    """只做本地 CLI/登录探测，不发模型请求、不消耗订阅额度。"""
    out = {"installed": False, "authenticated": False, "compatible": False,
           "status": "missing",
           "account": "", "detail": "", "version": "", "executable": ""}
    try:
        exe = resolve_channel_executable(channel)
        out["installed"] = True
        out["executable"] = exe
        env = _probe_env(channel)
        ver = _run([exe, "--version"], env, timeout=5)
        out["version"] = ((ver.stdout or ver.stderr or "").strip().splitlines() or [""])[0]
        runtime = _ADAPTERS.get(channel.get("provider")) or {}
        compatibility = cli_compatibility.check(
            channel.get("provider"), exe, env, run=_run)
        out["compatible"] = bool(compatibility["compatible"])
        out["protocol"] = compatibility["protocol"]
        auth_probe = runtime.get("auth_probe")
        if not auth_probe:
            raise RuntimeError("暂不支持此模型渠道：{}".format(channel.get("provider") or "unknown"))
        out.update(globals()[auth_probe](exe, env))
        if not compatibility["compatible"]:
            out.update(status="incompatible", detail=compatibility["detail"])
    except subprocess.TimeoutExpired:
        out.update(status="error", detail="CLI 状态检测超时")
    except Exception as e:
        out.update(status="missing" if not out["installed"] else "error", detail=str(e)[:300])
    return out


def login_command(channel):
    """返回可复制到终端的订阅登录命令；凭据由官方 CLI 自己管理。"""
    try:
        exe = resolve_channel_executable(channel)
    except Exception:
        exe = provider_info(channel.get("provider"))["executable"]
    config_dir = _expanded(channel.get("config_dir") or "")
    prefix = ""
    if config_dir:
        key = provider_info(channel.get("provider"))["config_env"]
        if os.name == "nt":
            prefix = '$env:{}="{}"; '.format(key, config_dir.replace('"', '`"'))
        else:
            prefix = "{}={} ".format(key, shlex.quote(config_dir))
    args = [exe] + list(provider_info(channel.get("provider"))["login_args"])
    if os.name == "nt":
        return prefix + subprocess.list2cmdline(args)
    return prefix + " ".join(shlex.quote(x) for x in args)


def public_channel(channel, with_status=False):
    item = dict(channel)
    info = provider_info(item.get("provider"))
    item["provider_label"] = info["label"]
    item["login_command"] = login_command(item)
    if with_status:
        item["probe"] = probe(item)
    return item
