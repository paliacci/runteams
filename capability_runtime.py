# -*- coding: utf-8 -*-
"""Runtime contract and preflight for immutable worker capabilities.

Capabilities declare what runs and what it needs.  The scheduler validates the
contract before a card consumes an attempt, so an unavailable interpreter or
package is a platform/capability problem rather than a vague request for the
user to intervene.
"""
import importlib.util
import os
import re
import shutil
import sys
import platform
from urllib.parse import urlparse


RUNNERS = ("python", "node", "local-process", "portable")
EFFECTS = ("operation", "diagnostic", "verifier")
SHARED_DATA_KINDS = ("file", "directory")
SHARED_DATA_ACCESS = ("read", "read_write")
_DEPENDENCY_ECOSYSTEMS = ("python", "node")
_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@/+-]{0,159}$")
_IMPORT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,159}$")
_VERSION = re.compile(r"^[A-Za-z0-9<>=!~.*,+-]{0,80}$")
_PYTHON_EXACT = re.compile(r"^==[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")
_NODE_EXACT = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9._-]+)?$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_PLATFORM = re.compile(r"^[A-Za-z0-9_.-]{3,80}$")


class CapabilityRuntimeError(ValueError):
    pass


def infer_effect(slug="", description=""):
    """Compatibility semantics for capabilities published before effect existed.

    New capabilities must declare this explicitly.  The conservative matcher is
    only for immutable historical releases whose manifest cannot be rewritten.
    """
    text = "{} {}".format(slug or "", description or "").lower()
    verifier_words = ("verify", "validate", "validation", "check", "test", "lint",
                      "audit", "preflight", "simulator", "验收", "检查", "测试")
    diagnostic_words = ("read", "query", "research", "scorecard", "scout", "inspect",
                        "诊断", "查询", "调研")
    if any(word in text for word in verifier_words):
        return "verifier"
    if any(word in text for word in diagnostic_words):
        return "diagnostic"
    return "operation"


def _legacy_runner(entry_path):
    suffix = os.path.splitext(str(entry_path or ""))[1].lower()
    if suffix == ".py":
        return "python"
    if suffix in (".js", ".mjs", ".cjs"):
        return "node"
    return "local-process"


def _dependency(raw, default_ecosystem):
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        raise CapabilityRuntimeError("能力依赖必须是名称或对象")
    ecosystem = str(raw.get("ecosystem") or default_ecosystem or "").strip().lower()
    if ecosystem not in _DEPENDENCY_ECOSYSTEMS:
        raise CapabilityRuntimeError("能力依赖类型只能是 python 或 node")
    name = str(raw.get("name") or "").strip()
    if not _PACKAGE.match(name):
        raise CapabilityRuntimeError("能力依赖名称无效：{}".format(name or "未填写"))
    version = str(raw.get("version") or "").strip()[:80]
    if not _VERSION.match(version):
        raise CapabilityRuntimeError("能力依赖版本范围无效：{}".format(version))
    item = {"ecosystem": ecosystem, "name": name, "version": version}
    if ecosystem == "python":
        import_name = str(raw.get("import") or raw.get("import_name") or name).strip()
        # Distribution names commonly use dashes while Python imports use underscores.
        import_name = import_name.replace("-", "_")
        if not _IMPORT.match(import_name):
            raise CapabilityRuntimeError("Python 导入名无效：{}".format(import_name or "未填写"))
        item["import"] = import_name
    return item


def platform_key():
    return "{}-{}".format(platform.system(), platform.machine())


def _safe_relative_path(value, label):
    value = str(value or "").replace("\\", "/").strip()
    normalized = os.path.normpath(value).replace("\\", "/")
    if (not value or "\0" in value or value.startswith("/") or
            re.match(r"^[A-Za-z]:/", value) or normalized in (".", "..") or
            normalized.startswith("../")):
        raise CapabilityRuntimeError("{}必须是运行包内的安全相对路径".format(label))
    return normalized


def _portable_package(raw):
    if not isinstance(raw, dict):
        raise CapabilityRuntimeError("可移植能力必须声明 runtime.package")
    package_id = str(raw.get("id") or raw.get("name") or "").strip()
    if not _PACKAGE.match(package_id):
        raise CapabilityRuntimeError("运行包 id 无效")
    version = str(raw.get("version") or "").strip()
    if not _NODE_EXACT.match(version):
        raise CapabilityRuntimeError("运行包必须锁定精确版本（例如 1.2.3）")
    publisher = str(raw.get("publisher") or "").strip()[:160]
    platforms = {}
    for key, source in (raw.get("platforms") or {}).items():
        key = str(key or "").strip()
        if not _PLATFORM.match(key) or not isinstance(source, dict):
            raise CapabilityRuntimeError("运行包平台声明无效")
        url = str(source.get("url") or "").strip()[:2000]
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise CapabilityRuntimeError("运行包必须使用 HTTPS 下载地址")
        sha256 = str(source.get("sha256") or "").strip().lower()
        if not _SHA256.match(sha256):
            raise CapabilityRuntimeError("运行包必须声明 64 位 SHA-256")
        archive = str(source.get("archive") or "zip").strip().lower()
        if archive not in ("zip", "tar.gz", "tar.xz"):
            raise CapabilityRuntimeError("运行包压缩格式只能是 zip、tar.gz 或 tar.xz")
        executable = _safe_relative_path(source.get("executable"), "运行入口")
        size_bytes = int(source.get("size_bytes") or 0)
        if size_bytes < 0 or size_bytes > 1024 * 1024 * 1024:
            raise CapabilityRuntimeError("运行包大小声明无效")
        platforms[key] = {"url": url, "sha256": sha256, "archive": archive,
                          "executable": executable, "size_bytes": size_bytes}
    if not platforms:
        raise CapabilityRuntimeError("运行包至少要声明一个系统构建")
    return {"id": package_id, "version": version, "publisher": publisher,
            "platforms": platforms}


def _limits(raw):
    raw = raw if isinstance(raw, dict) else {}
    values = {
        "memory_mb": (64, 32768, 1024),
        "cpu_seconds": (1, 86400, 600),
        "processes": (1, 128, 8),
        "file_size_mb": (1, 16384, 512),
        "open_files": (16, 4096, 256),
    }
    result = {}
    for key, (minimum, maximum, fallback) in values.items():
        try:
            value = int(raw.get(key, fallback))
        except (TypeError, ValueError):
            value = fallback
        result[key] = max(minimum, min(maximum, value))
    return result


def _shared_data(raw_items):
    result = []
    seen = set()
    for raw in raw_items or []:
        if isinstance(raw, str):
            raw = {"path": raw}
        if not isinstance(raw, dict):
            raise CapabilityRuntimeError("共享数据依赖必须是路径或对象")
        path = _safe_relative_path(raw.get("path"), "共享数据路径")
        kind = str(raw.get("kind") or "file").strip().lower()
        if kind not in SHARED_DATA_KINDS:
            raise CapabilityRuntimeError("共享数据类型只能是 file 或 directory")
        access = str(raw.get("access") or "read").strip().lower()
        if access not in SHARED_DATA_ACCESS:
            raise CapabilityRuntimeError("共享数据权限只能是 read 或 read_write")
        label = str(raw.get("label") or path).strip()[:160] or path
        marker = (path, kind, access)
        if marker not in seen:
            result.append({"path": path, "kind": kind, "access": access,
                           "label": label})
            seen.add(marker)
    if len(result) > 32:
        raise CapabilityRuntimeError("单项能力声明的共享数据依赖不能超过 32 个")
    return result


def normalize(spec=None, entry_path="", files=None):
    """Normalize a versioned runner contract; old .py entries remain valid."""
    spec = spec if isinstance(spec, dict) else {}
    contract_version = int(spec.get("version") or (2 if spec else 1))
    if contract_version not in (1, 2, 3):
        raise CapabilityRuntimeError("不支持的能力运行契约版本")
    runner = str(spec.get("runner") or spec.get("kind") or _legacy_runner(entry_path)).strip().lower()
    if runner not in RUNNERS:
        raise CapabilityRuntimeError("能力运行器只能是 python、node、local-process 或 portable")
    effect = str(spec.get("effect") or "operation").strip().lower()
    if effect not in EFFECTS:
        raise CapabilityRuntimeError("能力作用类型只能是 operation、diagnostic 或 verifier")
    if runner == "portable" and contract_version < 3:
        raise CapabilityRuntimeError("可移植运行包必须使用 version=3")
    suffix = os.path.splitext(str(entry_path or ""))[1].lower()
    if runner == "python" and suffix != ".py":
        raise CapabilityRuntimeError("Python 能力入口必须是 .py 文件")
    if runner == "node" and suffix not in (".js", ".mjs", ".cjs"):
        raise CapabilityRuntimeError("Node 能力入口必须是 .js、.mjs 或 .cjs 文件")
    executable = str(spec.get("executable") or "").strip()[:160]
    if runner == "local-process" and not executable:
        raise CapabilityRuntimeError("本地进程能力必须声明 executable")
    package = _portable_package(spec.get("package")) if runner == "portable" else None
    launcher_args = []
    for raw in spec.get("launcher_args") or []:
        value = str(raw or "")
        if not value or "\0" in value or len(value) > 300:
            raise CapabilityRuntimeError("运行包启动参数无效")
        launcher_args.append(value)
    if len(launcher_args) > 50:
        raise CapabilityRuntimeError("运行包启动参数过多")
    dependencies = []
    seen = set()
    for raw in spec.get("dependencies") or []:
        item = _dependency(raw, runner if runner in _DEPENDENCY_ECOSYSTEMS else "")
        if contract_version >= 2:
            exact = (_PYTHON_EXACT.match(item["version"]) if item["ecosystem"] == "python"
                     else _NODE_EXACT.match(item["version"]))
            if not exact:
                example = "==2.13.0" if item["ecosystem"] == "python" else "2.13.0"
                raise CapabilityRuntimeError(
                    "新版能力依赖必须锁定精确版本：{}（例如 {}）".format(item["name"], example))
        marker = (item["ecosystem"], item["name"], item.get("import", ""))
        if marker not in seen:
            dependencies.append(item)
            seen.add(marker)
    if runner == "portable" and dependencies:
        raise CapabilityRuntimeError("可移植运行包必须自包含，不能再声明外部依赖")
    healthcheck = spec.get("healthcheck") if isinstance(spec.get("healthcheck"), dict) else {}
    healthcheck_args = []
    for raw in healthcheck.get("arguments") or []:
        value = str(raw or "")
        if not value or "\0" in value or len(value) > 1000:
            raise CapabilityRuntimeError("能力自检参数无效")
        healthcheck_args.append(value)
    if len(healthcheck_args) > 50:
        raise CapabilityRuntimeError("能力自检参数过多")
    fixture_files = {}
    for path, content in (healthcheck.get("fixture_files") or {}).items():
        safe_path = _safe_relative_path(path, "能力自检文件")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 1024 * 1024:
            raise CapabilityRuntimeError("能力自检文件必须是小于 1 MB 的文本")
        fixture_files[safe_path] = content
    cases = []
    for index, raw in enumerate(healthcheck.get("cases") or []):
        if not isinstance(raw, dict):
            raise CapabilityRuntimeError("能力行为用例必须是对象")
        arguments = []
        for value in raw.get("arguments") or []:
            value = str(value or "")
            if not value or "\0" in value or len(value) > 1000:
                raise CapabilityRuntimeError("能力行为用例参数无效")
            arguments.append(value)
        if len(arguments) > 50:
            raise CapabilityRuntimeError("能力行为用例参数过多")
        expected = str(raw.get("expected") or "passed").strip().lower()
        if expected not in ("passed", "failed"):
            raise CapabilityRuntimeError("能力行为用例预期只能是 passed 或 failed")
        cases.append({"arguments": arguments, "expected": expected})
    if len(cases) > 20:
        raise CapabilityRuntimeError("单项能力的行为用例不能超过 20 个")
    result = {"version": contract_version, "runner": runner, "effect": effect,
            "executable": executable,
            "dependencies": dependencies,
            "shared_data": _shared_data(spec.get("shared_data")),
            "healthcheck": {"enabled": healthcheck.get("enabled", True) is not False,
                            "declared": bool(healthcheck_args or fixture_files or cases),
                            "arguments": healthcheck_args,
                            "fixture_files": fixture_files,
                            "cases": cases}}
    if runner == "portable":
        result["package"] = package
        result["launcher_args"] = launcher_args
    if contract_version >= 3:
        result["limits"] = _limits(spec.get("limits"))
    return result


def _local_python_modules(bundle_files):
    modules = set()
    for path in (bundle_files or {}):
        path = str(path).replace("\\", "/")
        first = path.split("/", 1)[0]
        if first.endswith(".py"):
            first = first[:-3]
        if first and first != "__init__":
            modules.add(first)
    return modules


def preflight_entry(entry, bundle_files=None, prepareable=False, shared_root=None):
    """Return structured checks for one frozen capability entry."""
    entry = entry if isinstance(entry, dict) else {}
    runtime = normalize(entry.get("runtime"), entry.get("entry_path"), bundle_files)
    slug = str(entry.get("slug") or "能力")
    checks = []
    runner = runtime["runner"]
    if runner == "python":
        ready = bool(sys.executable)
        detail = "RunTeams Python 运行器已就绪" if ready else "RunTeams Python 运行器不可用"
    elif runner == "node":
        ready = bool(shutil.which("node"))
        detail = "Node 运行器已就绪" if ready else "此电脑尚未安装可用的 Node 运行器"
    elif runner == "local-process":
        ready = bool(shutil.which(runtime["executable"]))
        detail = ("本地运行器已就绪" if ready else
                      "找不到本地运行器 {}".format(runtime["executable"]))
    else:
        source = (runtime.get("package") or {}).get("platforms", {}).get(platform_key())
        ready = bool(source)
        detail = ("运行包支持当前电脑" if ready else
                  "运行包没有适用于 {} 的构建".format(platform_key()))
    checks.append({"kind": "capability_runtime", "name": slug, "status": "ready" if ready else "blocked",
                   "owner": "system", "detail": detail,
                   "remediation": "由 RunTeams 准备运行环境后重试。" if not ready else ""})

    local_modules = _local_python_modules(bundle_files)
    for dep in runtime["dependencies"]:
        ecosystem = dep["ecosystem"]
        if ecosystem == "python":
            import_name = dep["import"].split(".", 1)[0]
            available = import_name in local_modules or importlib.util.find_spec(import_name) is not None
            detail = ("Python 依赖 {} 已就绪" if available else "缺少 Python 依赖 {}").format(dep["name"])
        else:
            package_path = "node_modules/{}/package.json".format(dep["name"])
            available = package_path in (bundle_files or {})
            detail = ("Node 依赖 {} 已随能力冻结" if available else
                      "Node 依赖 {} 尚未随能力冻结").format(dep["name"])
        status = "ready" if available else ("warning" if prepareable else "blocked")
        checks.append({"kind": "capability_dependency", "name": dep["name"],
                       "capability": slug, "ecosystem": ecosystem,
                       "status": status, "owner": "system" if prepareable else "capability",
                       "detail": detail,
                       "remediation": (("RunTeams 将在首次开工前准备此依赖。" if prepareable else
                                        "让岗位 Agent 补齐并重新发布此能力。") if not available else "")})
    if shared_root:
        root = os.path.realpath(os.path.expanduser(str(shared_root)))
        for item in runtime["shared_data"]:
            path = os.path.realpath(os.path.join(root, item["path"]))
            contained = path.startswith(root + os.sep)
            if item["kind"] == "directory":
                exists = contained and os.path.isdir(path)
            else:
                exists = contained and os.path.isfile(path)
            readable = exists and os.access(path, os.R_OK)
            writable = readable and (item["access"] != "read_write" or os.access(path, os.W_OK))
            ready = bool(readable and writable)
            if not exists:
                detail = "共享数据不存在：{}".format(item["path"])
            elif not readable:
                detail = "共享数据不可读：{}".format(item["path"])
            elif item["access"] == "read_write" and not writable:
                detail = "共享数据不可写：{}".format(item["path"])
            else:
                detail = "共享数据已就绪：{}".format(item["path"])
            checks.append({"kind": "capability_environment", "name": item["label"],
                           "capability": slug, "path": item["path"],
                           "status": "ready" if ready else "blocked", "owner": "system",
                           "detail": detail,
                           "remediation": ("恢复 RunTeams 共享数据资产或其访问权限后重试。"
                                           if not ready else "")})
    return {"ready": all(item["status"] != "blocked" for item in checks),
            "runtime": runtime, "checks": checks}


def preflight_resources(resources, prepareable=False, shared_root=None):
    resources = resources if isinstance(resources, dict) else {}
    bundles = resources.get("bundles") or {}
    checks = []
    for entry in list(resources.get("tools") or []) + list(resources.get("checks") or []):
        bundle = bundles.get(entry.get("bundle")) or {}
        checks.extend(preflight_entry(entry, bundle.get("files") or {}, prepareable=prepareable,
                                      shared_root=shared_root).get("checks") or [])
    for missing in resources.get("missing") or []:
        checks.append({"kind": "capability_reference", "name": missing.get("slug") or "未命名能力",
                       "status": "blocked", "owner": "capability",
                       "detail": "岗位引用的{}已不存在".format(
                           "工具" if missing.get("kind") == "tool" else "检查"),
                       "remediation": "让岗位 Agent 重新选择或创建能力，然后重新发布岗位。"})
    return {"ready": all(item.get("status") != "blocked" for item in checks), "checks": checks}


def command(entry, entry_path, arguments, env, frozen_launcher=None):
    """Build the command for a normalized contract without shell interpolation."""
    runtime = normalize((entry or {}).get("runtime"), (entry or {}).get("entry_path"))
    runner = runtime["runner"]
    if runner == "python":
        if frozen_launcher:
            return list(frozen_launcher) + [entry_path] + list(arguments or [])
        # Prefer the interpreter already running RunTeams. On macOS /usr/bin/python3
        # can be an xcrun shim that unexpectedly starts xcodebuild and makes an otherwise
        # valid Python capability fail before its entry point is reached.
        python = sys.executable or shutil.which("python3")
        if not python:
            raise CapabilityRuntimeError("RunTeams Python 运行器不可用")
        return [python, entry_path] + list(arguments or [])
    if runner == "node":
        node = shutil.which("node")
        if not node:
            raise CapabilityRuntimeError("Node 运行器尚未就绪")
        return [node, entry_path] + list(arguments or [])
    if runner == "portable":
        executable = str((env or {}).get("RUNTEAMS_PORTABLE_EXECUTABLE") or "")
        if not executable or not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise CapabilityRuntimeError("能力运行包尚未安装")
        return [executable] + list(runtime.get("launcher_args") or []) + [entry_path] + list(arguments or [])
    executable = shutil.which(runtime["executable"])
    if not executable:
        raise CapabilityRuntimeError("本地运行器 {} 尚未就绪".format(runtime["executable"]))
    return [executable, entry_path] + list(arguments or [])


def classify_failure(output, exit_code):
    text = str(output or "")
    lower = text.lower()
    if not exit_code:
        return None
    simulator_service_signals = (
        "kAXErrorAPIDisabled",
        "Unable to determine access",
        "Lost connection to testmanagerd",
        "Lost connection to the test runner",
    )
    if any(value in text for value in simulator_service_signals):
        return {"code": "simulator_service_unavailable", "owner": "system",
                "message": "iOS 模拟器的测试服务暂时不可用",
                "remediation": ""}
    if "ModuleNotFoundError" in text or "ImportError" in text:
        return {"code": "dependency_missing", "owner": "unknown",
                "message": "执行时缺少依赖，但尚不能判断属于任务还是岗位能力",
                "remediation": "由当前岗位 Agent 检查导入来源与工作区；只有独立复现后才能修改岗位能力。"}
    resource_signals = ("File too large", "[Errno 27]", "MemoryError",
                        "Cannot allocate memory", "Too many open files", "[Errno 24]")
    if ("RUNTEAMS_RESOURCE_LIMIT:" in text or any(value in text for value in resource_signals)
            or int(exit_code or 0) in (-9, -24, -25)):
        return {"code": "resource_limit", "owner": "unknown",
                "message": "执行超过资源上限，但尚不能判断是任务规模还是岗位能力问题",
                "remediation": "由当前岗位 Agent 缩小复现范围并诊断资源消耗。"}
    if "Operation not permitted" in text:
        return {"code": "permission_denied", "owner": "unknown",
                "message": "操作被本机系统或目标资源拒绝，尚不能判断具体原因",
                "remediation": "由当前岗位 Agent 检查访问目标与系统授权；只有确实需要用户授予 macOS 权限时才请求处理。"}
    if "command not found" in text or "RUNTEAMS_RUNTIME_UNAVAILABLE:" in text:
        return {"code": "runtime_unavailable", "owner": "system",
                "message": "能力所需运行器不可用",
                "remediation": "由 RunTeams 准备运行环境后重试；无需修改任务内容。"}
    task_failure_signals = (
        "** test failed **", "test case '-[", "xctassert", "assertionerror",
        "assertion failed", "assertion failure", "tests failed", "test failed", "build failed",
        "validation failed", "验收未通过", "检查未通过",
    )
    framework_failure = (("pytest" in lower or "jest" in lower or "gradle" in lower or
                          "xctest" in lower)
                         and (" failed" in lower or "failure" in lower))
    if framework_failure or any(value in lower for value in task_failure_signals):
        return {"code": "task_verification_failed", "owner": "task",
                "message": "任务实现尚未通过验证",
                "remediation": "保留原始证据，由当前岗位 Agent 继续诊断、修改并重新验证。"}
    # An arbitrary non-zero exit code does not prove that the immutable
    # capability is broken.  Most often it is the verifier correctly rejecting
    # the task under test.  Keep ownership unknown so the working Agent can use
    # the raw evidence instead of prematurely handing the job to maintenance.
    return {"code": "execution_failed", "owner": "unknown",
            "message": "执行未通过",
            "remediation": "由当前岗位 Agent 根据完整输出继续诊断；只有证实能力实现损坏后才转交维护。"}
