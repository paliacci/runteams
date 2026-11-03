# -*- coding: utf-8 -*-
"""订阅模型渠道：全局目录直接来自各厂商 CLI，业务页不维护模型清单。"""
import json
import copy
import os
import shlex
import subprocess
import queue
import threading
import time
import math
import signal
import tempfile
import re
from datetime import datetime

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


def is_connected(channel, status):
    """One connection contract for display, discovery and execution checks.

    Quota and model-list transport status are separate observations. A native
    login/compatibility failure cannot be promoted by successful quota polling.
    """
    return bool(channel.get("enabled", 1) and status.get("status") == "ready"
                and status.get("installed") and status.get("authenticated")
                and status.get("compatible", True)
                and (status.get("connection_verified") is True
                     if channel.get("provider") == "claude-code"
                     else status.get("connection_verified") is not False))


def _expanded(path):
    return os.path.abspath(os.path.expanduser(path)) if (path or "").strip() else ""


def config_directory(channel, env=None):
    """Resolve the exact native profile used by every channel data reader."""
    info = provider_info(channel.get("provider"))
    env = os.environ if env is None else env
    return _expanded(channel.get("config_dir") or env.get(info["config_env"]) or info["default_config_dir"])


def resolve_channel_executable(channel):
    explicit = _expanded(channel.get("executable") or "")
    if explicit:
        from cli_discovery import resolve
        return resolve(channel.get("provider"), explicit=explicit)
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
    adapter = runtime["adapter"](executable=executable, config_dir=config_dir)
    # A queued run may start after a desktop/CLI update moved the executable.
    selection = dict(channel)
    adapter.resolve_executable = lambda: resolve_channel_executable(selection)
    return adapter


def _probe_env(channel):
    from cli_discovery import execution_env
    env = execution_env(channel.get("provider"), channel.get("executable"), os.environ)
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


_CLAUDE_USAGE_CACHE = {}
_CLAUDE_USAGE_LOCK = threading.Lock()


class UsageQueryError(RuntimeError):
    """A public usage failure; never contains CLI output or credentials."""
    def __init__(self, code, detail, http_status=None):
        super().__init__(detail)
        self.code = code
        self.http_status = http_status


def _claude_cli_usage(executable, env, timeout=5):
    # The control response omits authentication errors. Read only known error
    # signatures from a private, short-lived official CLI diagnostic file.
    with tempfile.TemporaryDirectory(prefix="runteams-usage-") as directory:
        diagnostic_path = os.path.join(directory, "cli.log")
        payload, failure = None, None
        try:
            payload = _claude_cli_usage_query(executable, env, timeout, diagnostic_path)
        except UsageQueryError as error:
            failure = error
        if not payload or not _claude_usage_windows(payload):
            auth_error = _claude_usage_auth_error(diagnostic_path)
            if auth_error:
                raise auth_error
        if failure:
            raise failure
        return payload


def _claude_usage_auth_error(path):
    """Allowlist error signatures; never return raw logs, URLs or credentials."""
    try:
        with open(path, "rb") as source:
            source.seek(0, os.SEEK_END)
            source.seek(max(0, source.tell() - 131072))
            lines = source.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    relevant = [line for line in lines if "[ERROR]" in line]
    if any("Failed to fetch oauth profile from OAuth token:" in line and
           re.search(r"status code 401\b", line) for line in relevant):
        return UsageQueryError("authentication_failed",
                               "Claude Code 账户验证未通过（HTTP 401），请在终端重新登录 Claude Code 后重试", 401)
    for line in relevant:
        if "OAuth refresh failed" in line:
            status = re.search(r"status code (400|401)\b", line)
            if status:
                code = int(status.group(1))
                return UsageQueryError("authentication_failed",
                                       "Claude Code 登录授权刷新失败（HTTP {}），请在终端重新登录 Claude Code 后重试".format(code), code)
    return None


def _claude_cli_usage_query(executable, env, timeout, diagnostic_path):
    """Read the official CLI's get_usage control response without a model turn."""
    process = subprocess.Popen(
        [executable, "--input-format", "stream-json", "--output-format", "stream-json",
         "--verbose", "--no-session-persistence", "--debug-file", diagnostic_path, "-p"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, env=env, cwd=tempfile.gettempdir(), bufsize=1,
        start_new_session=(os.name != "nt"))
    lines = queue.Queue()

    def read_stdout():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def request(request_id, payload):
        process.stdin.write(json.dumps({"type": "control_request", "request_id": request_id,
                                        "request": payload}) + "\n")
        process.stdin.flush()
        while time.monotonic() < deadline:
            try:
                raw = lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if raw is None:
                raise UsageQueryError("cli_exit", "Claude Code 在额度查询完成前退出，请重试")
            try:
                message = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(message, dict):
                continue
            response = message.get("response") or {}
            if not isinstance(response, dict):
                continue
            if message.get("type") != "control_response" or response.get("request_id") != request_id:
                continue
            if response.get("subtype") != "success":
                code = "unsupported_cli" if request_id == "usage" else "cli_initialize_failed"
                raise UsageQueryError(code, "当前 Claude Code 不支持额度查询，请更新 CLI 后重试"
                                      if code == "unsupported_cli" else "Claude Code 初始化失败，请检查 CLI 登录状态")
            payload = response.get("response")
            if not isinstance(payload, dict):
                raise UsageQueryError("invalid_response", "Claude Code 返回的额度数据格式不正确")
            return payload
        raise UsageQueryError("timeout", "Claude Code 额度查询超时，请稍后重试")

    try:
        request("initialize", {"subtype": "initialize", "hooks": None})
        # A control request is local CLI management, not a user/assistant message.
        return request("usage", {"subtype": "get_usage"})
    except (BrokenPipeError, OSError):
        raise UsageQueryError("cli_exit", "Claude Code 额度查询未完成，请检查 CLI 后重试") from None
    finally:
        try:
            if process.poll() is None:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        reader.join(timeout=0.2)
        for stream in (process.stdin, process.stdout):
            if stream:
                stream.close()


def _usage_reset_time(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            numeric = parsed.timestamp()
        except (ValueError, TypeError, OverflowError):
            return None
    return numeric if math.isfinite(numeric) and numeric > 0 else None


def _claude_usage_windows(payload):
    """get_usage utilization is a percent, as displayed by the CLI /usage view."""
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return []
    windows = []

    def append_window(key, label, value):
        if not isinstance(value, dict):
            return
        used = value.get("used_percentage", value.get("utilization"))
        if isinstance(used, bool) or used is None:
            return
        try:
            used = float(used)
        except (ValueError, TypeError):
            return
        if not math.isfinite(used):
            return
        reset = _usage_reset_time(value.get("resets_at"))
        if reset is not None and reset <= time.time():
            return  # An old window must not survive its reset.
        used = max(0, min(100, used))
        windows.append({"key": key, "label": label, "used_percent": round(used, 1),
                        "remaining_percent": round(100 - used, 1), "resets_at": reset})

    for key, label in (("five_hour", "5小时"), ("seven_day", "每周"),
                       ("seven_day_sonnet", "Sonnet 每周"), ("seven_day_opus", "Opus 每周"),
                       ("seven_day_oauth_apps", "应用每周")):
        append_window(key, label, limits.get(key))
    for index, value in enumerate(limits.get("model_scoped") or []):
        if isinstance(value, dict):
            append_window("model_scoped_" + str(index), str(value.get("display_name") or "模型")[:80] + " 每周", value)
    return windows


def _claude_channel_usage(channel, executable, env, auth, timeout):
    key = (executable, _expanded(env.get("CLAUDE_CONFIG_DIR") or "~/.claude"), auth.get("account", ""))
    # Serialize read-only quota polling and reuse a short account-scoped cache.
    with _CLAUDE_USAGE_LOCK:
        cached = _CLAUDE_USAGE_CACHE.get(key)
        if cached and time.monotonic() < cached[0]:
            result = copy.deepcopy(cached[1])
            windows = [w for w in result.get("windows", []) if w["resets_at"] is None or w["resets_at"] > time.time()]
            if len(windows) == len(result.get("windows", [])):
                return result
        try:
            payload = _claude_cli_usage(executable, env, timeout)
            windows = _claude_usage_windows(payload)
            selected = next((w for w in windows if w["key"] == "seven_day"), None) or next((w for w in windows if w["key"] == "five_hour"), None)
            if selected:
                window = "weekly" if selected["key"] == "seven_day" else "five_hour"
                result = dict({k: selected[k] for k in ("used_percent", "remaining_percent", "resets_at")}, status="ready", window=window, windows=windows, detail="", code="", source="claude_cli")
            else:
                unsupported = payload.get("rate_limits_available") is False
                result = {"status": "unavailable", "code": "plan_unavailable" if unsupported else "usage_not_returned",
                          "detail": "当前 Claude 账户未提供订阅额度" if unsupported else
                          "Claude Code 未返回每周额度；请在官方 CLI 中运行 /usage 检查额度及登录状态",
                          "windows": windows, "source": "claude_cli"}
        except UsageQueryError as error:
            result = {"status": "error", "code": error.code, "detail": str(error), "windows": [], "source": "claude_cli"}
            if error.http_status is not None:
                result["http_status"] = error.http_status
        # A timeout/unsupported quota response cannot undo a confirmed OAuth
        # rejection. Only a successful official response verifies recovery.
        if (cached and cached[1].get("code") == "authentication_failed"
                and result.get("status") != "ready" and result.get("code") != "authentication_failed"):
            result = dict(cached[1])
        result["checked_at"] = time.time()
        _CLAUDE_USAGE_CACHE[key] = (time.monotonic() + (30 if result["status"] == "ready" else 10), copy.deepcopy(result))
        # Expire quota snapshots, but retain explicit rejection until positive
        # official evidence; the process-local account cache is bounded below.
        for old in list(_CLAUDE_USAGE_CACHE):
            if (_CLAUDE_USAGE_CACHE[old][0] <= time.monotonic()
                    and _CLAUDE_USAGE_CACHE[old][1].get("code") != "authentication_failed"):
                _CLAUDE_USAGE_CACHE.pop(old, None)
        while len(_CLAUDE_USAGE_CACHE) > 64:
            old = next(value for value in _CLAUDE_USAGE_CACHE if value != key)
            _CLAUDE_USAGE_CACHE.pop(old)
        return result


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
                if auth.get("code") == "authentication_failed":
                    result.update(status="error", code="authentication_failed", source="claude_cli",
                                  http_status=auth.get("http_status"), detail=auth.get("detail") or "请重新登录 Claude Code。")
                else:
                    result.update(status="not_connected", detail="CLI 尚未登录")
                return result
            result.update(_claude_channel_usage(channel, executable, env, auth, timeout))
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
            "--no-session-persistence"]
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
    from cli_discovery import executable_stamp
    from model_catalog_display import _identity
    stamp = executable_stamp(executable)
    return (channel.get("provider"), executable, stamp,
            _expanded(channel.get("config_dir") or ""), _identity([channel], None)[2:])


def channel_catalog(channel, refresh=False, *, observation=None):
    """返回单个渠道的全局模型目录；失败时不伪造可选模型。"""
    if not channel.get("enabled", 1):
        return {"channel_id": channel.get("id"), "provider": channel.get("provider"),
                "source": "unavailable", "status": "disabled", "models": [], "error": "渠道未连接"}
    try:
        executable = resolve_channel_executable(channel)
        key = _catalog_key(channel, executable)
        # Catalog validation needs fresh native login/compatibility checks, not
        # an extra App Server just to format an email/subscription label.
        status = observation if observation is not None else probe(channel, account_summary=False)
        if not is_connected(channel, status):
            with _MODEL_CACHE_LOCK:
                _MODEL_CACHE.pop(key, None)
            return {"channel_id": channel.get("id"), "provider": channel.get("provider"),
                    "source": "unavailable", "status": status.get("status") or "error",
                    "code": status.get("code") or "", "models": [],
                    "error": status.get("detail") or "模型渠道尚未连接，请重新连接。"}

    except Exception as e:
        return {"channel_id": channel.get("id"), "provider": channel.get("provider"),
                "source": "unavailable", "status": "error", "models": [], "error": "模型目录暂时无法读取，请重试。"}

    now = time.monotonic()
    if not refresh:
        with _MODEL_CACHE_LOCK:
            cached = _MODEL_CACHE.get(key)
        if cached and cached[0] > now:
            result = copy.deepcopy(cached[1])
            result["channel_id"] = channel.get("id")
            return result
    try:
        loader_name = (_ADAPTERS.get(channel.get("provider")) or {}).get("model_loader")
        if not loader_name:
            raise RuntimeError("暂不支持此模型渠道：{}".format(channel.get("provider") or "unknown"))
        models = globals()[loader_name](channel)
        if not isinstance(models, list) or any(not isinstance(item, dict) or not isinstance(item.get("value"), str) or not item["value"].strip() for item in models) or len({item["value"] for item in models}) != len(models):
            raise ValueError("Invalid official model catalog")
        result = {"channel_id": channel.get("id"), "provider": channel.get("provider"),
                  "source": "cli", "status": "ready", "models": models, "automatic_model": latest_flagship_model(models), "error": ""}
        if channel.get("provider") == "claude-code":
            result["connection_verified"] = status.get("connection_verified") is True
        ttl = _MODEL_CACHE_TTL
    except Exception as e:
        result = {"channel_id": channel.get("id"), "provider": channel.get("provider"),
                  "source": "unavailable", "status": "error", "models": [], "error": "模型目录暂时无法读取，请重试。"}
        ttl = _MODEL_ERROR_CACHE_TTL
    with _MODEL_CACHE_LOCK:
        cached_result = copy.deepcopy(result)
        cached_result.pop("channel_id", None)
        _MODEL_CACHE[key] = (now + ttl, cached_result)
    return result


def global_catalog(channels, refresh=False):
    """整个产品共享的 CLI 模型目录。"""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='model-catalog') as pool:
        return {"channels": list(pool.map(lambda channel: channel_catalog(channel, refresh=refresh), channels))}


def require_catalog(channel, *, refresh=False, catalog=None, observation=None):
    """The sole model-availability gate; never freeze unknown/empty selections."""
    if not channel.get("enabled", 1):
        raise ValueError("模型渠道尚未连接，请重新连接后再继续。")
    if catalog is None:
        options = {"refresh": True} if refresh else {}
        if observation is not None:
            options["observation"] = observation
        catalog = channel_catalog(channel, **options)
    if catalog.get("status") in ("disabled", "login_required", "missing", "incompatible", "not_connected") or catalog.get("connection_verified") is False:
        raise ValueError("模型渠道尚未连接，请重新连接后再继续。")
    if catalog.get("status") != "ready" or catalog.get("source") != "cli":
        raise ValueError("模型目录暂时无法读取，请重试。")
    models = catalog.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("模型目录没有可用模型，请重新读取。")
    if any(not isinstance(item, dict) or not isinstance(item.get("value"), str) or not item["value"].strip() for item in models):
        raise ValueError("模型目录数据无效，请重新读取。")
    if len({item["value"] for item in models}) != len(models):
        raise ValueError("模型目录数据无效，请重新读取。")
    return catalog


def normalize_selection(channel, model, effort, *, catalog=None):
    """Resolve only against the official catalog; explicit models never drift."""
    model = str(model or "").strip()
    effort = str(effort or "").strip().lower()
    catalog = require_catalog(channel, catalog=catalog)
    if not model:
        model = latest_flagship_model(catalog["models"])
    selected = next((item for item in catalog["models"] if item["value"] == model), None)
    if not selected:
        raise ValueError("指定的模型不在当前官方模型目录中，请重新选择。")
    supported = selected.get("efforts") or []
    if not supported:
        return model, ""
    if effort not in supported:
        effort = "high" if "high" in supported else selected.get("default_effort") or supported[0]
    return model, effort


def latest_flagship_model(models):
    """Apply the same catalog-only default policy as the conversation picker."""
    from functools import cmp_to_key
    models=[item for item in models if item.get('value')]
    def name(item):return re.sub(r'\[[^\]]*\]','',str(item.get('resolved_model') or item['value']))
    def flagship(item):return item.get('is_flagship') is True or str(item.get('tier','')).lower() in ('flagship','frontier')
    def lightweight(item):return not flagship(item) and re.search(r'(?:^|[-_\s])(?:mini|nano|lite|luna|haiku|sonnet|flash|instant|small|terra)(?:$|[-_\s\d])',name(item)+' '+item['value'],re.I)
    candidates=[item for item in models if flagship(item)] or [item for item in models if not lightweight(item)] or models
    def version(item):
        found=re.search(r'\d+(?:[.-]\d+)*',name(item))
        return [int(part) for part in re.split('[.-]',found[0]) if int(part)<10000000] if found else []
    def capability(item):return bool(re.search('flagship|frontier|most capable|most intelligent|旗舰|最强',str(item.get('description','')),re.I))
    def compare(a,b):
        av,bv=version(a),version(b)
        for index in range(max(len(av),len(bv))):
            delta=(bv[index] if index<len(bv) else 0)-(av[index] if index<len(av) else 0)
            if delta:return delta
        return int(capability(b))-int(capability(a)) or int(bool(b.get('is_default')))-int(bool(a.get('is_default')))
    return sorted(candidates,key=cmp_to_key(compare))[0]['value'] if candidates else ''


def resolve_published_selection(channel, model, effort, *, catalog=None):
    """Resolve a frozen product selection only against the official CLI catalog."""
    catalog = require_catalog(channel, catalog=catalog)
    models = catalog['models']
    selected_model = str(model or channel.get('default_model') or '').strip()
    if not selected_model:
        selected_model = latest_flagship_model(models)
    selected = next((item for item in models if item['value'] == selected_model), None)
    if selected is None: raise ValueError('选用模型不在此官方渠道目录中')
    selected_effort = str(effort or channel.get('default_effort') or '').strip()
    supported = selected.get('efforts') or []
    if selected_effort and selected_effort not in supported:
        raise ValueError('此模型不支持选用的思考深度')
    if not selected_effort and supported:
        selected_effort = selected.get('default_effort') or supported[0]
    return selected_model, selected_effort


def _probe_codex_auth(exe, env, *, account_summary=True):
    p = _run([exe, "login", "status"], env)
    blob = ((p.stdout or "") + (p.stderr or "")).strip()
    ok = p.returncode == 0 and "logged in" in blob.lower()
    account_info = {}
    if ok and account_summary:
        try:
            account_info = _codex_account(exe, env)
        except Exception:
            pass
    account = " ".join(x for x in (account_info.get("email"), account_info.get("plan")) if x)
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
        account += " " + subtype
    result = {"authenticated": ok, "status": "ready" if ok else "login_required",
              "connection_verified": False,
              "account": account, "detail": blob[:300]}
    if ok:
        # auth status reports the presence of local credentials, including
        # revoked OAuth tokens. Verify through the official read-only control
        # protocol; share the quota cache rather than sending a model turn.
        usage = _claude_channel_usage({}, exe, env, result, 5)
        if usage.get("code") == "authentication_failed":
            result.update(authenticated=False, status="login_required", code="authentication_failed",
                          http_status=usage.get("http_status"), detail=usage.get("detail") or "Claude Code 登录验证失败，请重新登录。")
        elif usage.get("status") == "ready":
            result["connection_verified"] = True
        else:
            # Local credentials and the static model list do not establish an
            # effective connection. Keep authentication evidence separate: an
            # unavailable verification is not an invented OAuth rejection.
            result.update(status="not_connected", code="connection_unverified",
                          detail="Claude Code 连接验证未通过，请在官方 CLI 中检查登录状态后重试。")
    return result


def probe(channel, *, account_summary=True):
    """通过官方 CLI 探测安装及登录状态，不发模型请求、不消耗订阅额度。"""
    from cli_discovery import DiscoveryError
    out = {"installed": False, "authenticated": False, "compatible": False,
           "status": "missing",
           "account": "", "detail": "", "version": "", "executable": ""}
    if not channel.get("enabled", 1):
        return {**out, "status": "disabled"}
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
        if channel.get('provider') == 'codex':
            out.update(globals()[auth_probe](exe, env, account_summary=account_summary))
        else:
            out.update(globals()[auth_probe](exe, env))
        if not compatibility["compatible"]:
            out.update(status="incompatible", detail=compatibility["detail"])
    except DiscoveryError as exc:
        out.update(installed=exc.installed, executable=exc.executable, discovery_error=True,
                   status=exc.status, detail=str(exc))
    except subprocess.TimeoutExpired:
        out.update(status="error", detail="CLI 状态检测超时")
    except Exception as e:
        out.update(status="missing" if not out["installed"] else "error", detail=str(e)[:300])
    if out.get('status') != 'ready':
        import model_catalog_display
        model_catalog_display.invalidate(channel)
        import runtime_capabilities
        runtime_capabilities.invalidate_channel(channel)
    return out


def login_command(channel):
    """返回可复制到终端的订阅登录命令；凭据由官方 CLI 自己管理。"""
    try:
        from cli_discovery import cached_display_executable
        exe = cached_display_executable(channel.get('provider'), channel.get('executable') or '') or resolve_channel_executable(channel)
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
