#!/usr/bin/env python3
"""Prepare project dependencies or Microsoft's upstream browser CLI per task."""
import argparse
from contextlib import contextmanager
import hashlib
import platform
import tempfile
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import re
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).parent))
from _result import emit

BROWSER_PACKAGE = "@playwright/cli@0.1.20"


def owned(path):
    root = Path.cwd().resolve()
    result = Path(path).resolve()
    if result == root or root not in result.parents:
        raise ValueError("路径必须位于本次任务工作区内")
    return result


def runtime_environment():
    scratch = owned(".scratch")
    if not (scratch / "env.sh").is_file():
        raise ValueError("先执行 isolated-env")
    env = dict(os.environ)
    cache = Path(env["RUNTEAMS_DEPENDENCY_CACHE"]) if env.get("RUNTEAMS_DEPENDENCY_CACHE") else scratch / "dependency-cache"
    cache.mkdir(parents=True, exist_ok=True)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    env.update(HOME=str(scratch / "home"), TMPDIR=str(scratch / "tmp"),
               XDG_CACHE_HOME=str(scratch / "xdg/cache"),
               XDG_CONFIG_HOME=str(scratch / "xdg/config"),
               XDG_DATA_HOME=str(scratch / "xdg/data"),
               PIP_CACHE_DIR=str(Path(env["RUNTEAMS_DEPENDENCY_CACHE"]) / "pip"
                                 if env.get("RUNTEAMS_DEPENDENCY_CACHE") else scratch / "pip-cache"),
               PIP_CONFIG_FILE=os.devnull, PYTHONNOUSERSITE="1",
               PIP_DISABLE_PIP_VERSION_CHECK="1",
               PLAYWRIGHT_BROWSERS_PATH=str(cache / "browsers"),
               PLAYWRIGHT_SKIP_BROWSER_GC="1",
               PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="30000",
               # Unix sockets have a short byte limit. Upstream accepts a path
               # relative to the task cwd; keep sockets owned by .scratch even
               # when the absolute employee workspace path is very deep.
               PWTEST_SOCKETS_DIR=".scratch/s",
               npm_config_cache=str(cache / "npm"),
               npm_config_fetch_retries="1",
               npm_config_fetch_timeout="30000",
               npm_config_userconfig=str(scratch / "npm-user.conf"),
               npm_config_globalconfig=str(scratch / "npm-global.conf"),
               LOCALAPPDATA=str(scratch / "home/AppData/Local"),
               CI="1", NO_UPDATE_NOTIFIER="1")
    return env


def run_logged(command, env, directory, stage, timeout, cwd=None):
    """Keep child output even on timeout; the full log survives scratch cleanup."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / (stage + ".log")
    started = time.monotonic()
    timed_out = False
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
    text = log.read_text(encoding="utf-8", errors="replace")
    record = {"stage": stage, "command": command, "exit_code": process.returncode,
              "timed_out": timed_out, "seconds": round(time.monotonic() - started, 2),
              "log": str(log.relative_to(Path.cwd()))}
    (directory / (stage + ".json")).write_text(json.dumps(record, ensure_ascii=False, indent=2))
    if timed_out:
        text += "\n准备阶段 {} 超过 {} 秒；完整日志：{}".format(stage, timeout, record["log"])
    return subprocess.CompletedProcess(command, 124 if timed_out else process.returncode, text, "")


def prepare_project(python, project, requirements, env):
    invocation = os.environ.get("RUNTEAMS_INVOCATION_ID") or uuid.uuid4().hex
    directory = owned("evidence/runtime-preparation/" + invocation)
    venv = owned(".scratch/project-venv")
    executable = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    pip = [str(executable), "-I", "-m", "pip"]
    network = ["--disable-pip-version-check", "--progress-bar", "off", "--timeout", "15", "--retries", "1"]
    # Registry-only declarations can be resolved by pip against cached wheels
    # without contacting PyPI. Direct URLs, local projects and nested files keep
    # pip's normal behavior; do not reinterpret their dependency semantics.
    lines = [line.split("#", 1)[0].strip() for line in requirements.read_text().splitlines()]
    registry_only = all(not line or (re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(\[.*?\])?([<>=!~; ].*)?$", line)
                                    and not any(mark in line for mark in ("://", " @ ", "/", "\\"))) for line in lines)
    wheels = (Path(env["RUNTEAMS_DEPENDENCY_CACHE"]) / "wheels"
              if env.get("RUNTEAMS_DEPENDENCY_CACHE") else owned(".scratch/project-wheels"))
    wheels.mkdir(parents=True, exist_ok=True)
    commands = [
        ("venv", [python, "-I", "-m", "venv", str(venv)], 25),
        ("install", pip + ["install"] + network + ["-r", str(requirements)], 240),
        ("check", [str(executable), "-I", "-m", "pip", "check"], 10),
        ("freeze", [str(executable), "-I", "-m", "pip", "freeze", "--all"], 10),
    ]
    logs = []
    deadline = time.monotonic() + 280
    for stage, command, timeout in commands:
        if stage == "install" and registry_only:
            offline = pip + ["install", "--no-index", "--find-links", str(wheels), "-r", str(requirements)]
            result = run_logged(offline, env, directory, "cached-install", 20, cwd=str(project))
            logs.append("cached-install:\n" + result.stdout[-1200:])
            if result.returncode == 0:
                continue
            download = pip + ["download"] + network + ["--dest", str(wheels), "-r", str(requirements)]
            for attempt in range(2):
                result = run_logged(download, env, directory, "download-" + str(attempt + 1),
                                    max(1, min(230, deadline - time.monotonic() - 25)), cwd=str(project))
                logs.append("download:\n" + result.stdout[-1200:])
                transient = any(word in result.stdout for word in ("SSLError", "SSLEOFError", "ReadTimeout", "ConnectionError", "Temporary failure", "Connection reset"))
                if result.returncode == 0 or not transient:
                    break
            if result.returncode == 0:
                command = offline
                timeout = 20
            else:
                return emit("prepare-runtime", False, "包下载失败，环境尚未就绪；完整日志已保存",
                            "\n".join(logs), "dependency_download_failed",
                            [str(p.relative_to(Path.cwd())) for p in directory.iterdir()])
        timeout = max(1, min(timeout, deadline - time.monotonic()))
        result = run_logged(command, env, directory, stage, timeout, cwd=str(project))
        logs.append(stage + ":\n" + result.stdout[-1800:])
        if result.returncode:
            return emit("prepare-runtime", False,
                        "运行环境尚未就绪：{}失败；先解决准备问题再开始巡检".format(stage),
                        "\n".join(logs), "dependency_setup_failed",
                        [str(p.relative_to(Path.cwd())) for p in directory.iterdir()])
    registry = owned(".runteams/project-runner.json")
    record = json.loads(registry.read_text())
    record.setdefault("runtimes", {})["project"] = str(executable)
    registry.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    ready = {"status": "ready", "python": str(executable),
             "requirements": str(requirements), "logs": str(directory.relative_to(Path.cwd())),
             "cache": env["PIP_CACHE_DIR"], "wheel_cache": str(wheels), "dependency_check": "passed"}
    (directory / "ready.json").write_text(json.dumps(ready, ensure_ascii=False, indent=2))
    return emit("prepare-runtime", True,
                "隔离依赖安装与一致性检查通过；随后启动实例并探测就绪，再开始巡检",
                json.dumps(ready, ensure_ascii=False) + "\n" + "\n".join(logs),
                artifacts=[str(p.relative_to(Path.cwd())) for p in directory.iterdir()])


def browser_versions(runtime):
    return {package: json.loads((runtime / "node_modules" / package / "package.json").read_text())["version"]
            for package in ("@playwright/cli", "playwright", "playwright-core")}


@contextmanager
def browser_installation(env, directory, upgrade=False):
    """A managed installation is promoted only after this task's launch check."""
    base = Path(env["RUNTEAMS_DEPENDENCY_CACHE"]) / "playwright-cli" / (sys.platform + "-" + platform.machine())
    base.mkdir(parents=True, exist_ok=True)
    # OS-held lock releases on process exit, including interrupted installation.
    with (base / "install.lock").open("a+b") as lock:
        if os.name == "posix":
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        else:
            import msvcrt
            lock.seek(0); lock.write(b"0"); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        current = base / "current.json"
        if current.is_file() and not upgrade:
            record = json.loads(current.read_text())
            source = (base / record["directory"]).resolve()
            if base.resolve() not in source.parents:
                raise ValueError("已安装浏览器工具路径无效")
            lockfile = source / "package-lock.json"
            if (not lockfile.is_file() or browser_versions(source) != record["versions"] or
                    hashlib.sha256(lockfile.read_bytes()).hexdigest() != record["lock_sha256"]):
                raise ValueError("已安装浏览器工具不完整，请显式重新准备或升级")
            yield source, lambda: None, True
            return
        npm = shutil.which("npm")
        if not npm:
            raise ValueError("首次准备或升级浏览器工具需要 npm")
        requested = BROWSER_PACKAGE
        if upgrade:
            latest = run_logged([npm, "view", "@playwright/cli", "dist-tags.latest", "--prefer-online"],
                                env, directory, "latest", 60)
            version = latest.stdout.strip()
            if latest.returncode or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
                raise ValueError("无法确认升级版本；原有安装保持不变")
            requested = "@playwright/cli@" + version
        with tempfile.TemporaryDirectory(prefix="candidate-", dir=base) as temporary:
            candidate = Path(temporary) / "installation"
            candidate.mkdir(); (candidate / "package.json").write_text('{"private":true}')
            cli = candidate / "node_modules/.bin" / ("playwright-cli.cmd" if os.name == "nt" else "playwright-cli")
            commands = [
                ("npm", [npm, "install", "--prefix", str(candidate), "--save-exact", "--no-audit", "--no-fund", "--ignore-scripts", "--prefer-offline", requested]),
                ("skill", [str(cli), "install", "--skills=agents"]),
                ("version", [str(cli), "--version"]),
            ]
            for stage, command in commands:
                result = run_logged(command, env, directory, stage, 180, cwd=str(candidate))
                if result.returncode:
                    raise ValueError("浏览器工具{}失败；原有安装保持不变，完整日志已保存".format(stage))
            versions = browser_versions(candidate)
            def promote():
                destination = base / (versions["@playwright/cli"] + "-" + uuid.uuid4().hex[:12])
                candidate.rename(destination)
                record = {"directory": destination.name, "versions": versions,
                          "lock_sha256": hashlib.sha256((destination / "package-lock.json").read_bytes()).hexdigest()}
                pending = base / ("current-" + uuid.uuid4().hex + ".json")
                pending.write_text(json.dumps(record, ensure_ascii=False))
                os.replace(pending, current)
            yield candidate, promote, False


def copy_browser_installation(source, target):
    # Never share writable files, node_modules or session state with employees.
    if target.exists():
        shutil.rmtree(target)
    if sys.platform == "darwin":
        copied = subprocess.run(["/bin/cp", "-cR", str(source), str(target)], capture_output=True, timeout=60)
        if copied.returncode == 0:
            return
        if target.exists():
            shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)


def prepare_browser(env, upgrade=False):
    registry_path = owned(".runteams/project-runner.json")
    registry = json.loads(registry_path.read_text())
    existing = (registry.get("runtimes") or {}).get("browser")
    if existing:
        if upgrade:
            raise ValueError("本任务版本已冻结；在新的准备任务中显式升级")
        if isinstance(existing, dict) and owned(existing["entry"]).is_file() and owned(existing["config"]).is_file():
            return emit("prepare-runtime", True, "本次任务沿用已准备的官方浏览器版本", json.dumps(existing, ensure_ascii=False))
        raise ValueError("本任务浏览器环境已清理；先建立全新隔离环境")
    if not shutil.which("node"):
        raise ValueError("官方浏览器工具需要 Node.js 18+")
    # The capability host supplies the product-owned cache. Direct standalone
    # invocation falls back to task-local storage without borrowing global npm.
    env.setdefault("RUNTEAMS_DEPENDENCY_CACHE", str(owned(".scratch/dependency-cache")))
    runtime = owned(".scratch/browser-runtime")
    invocation = os.environ.get("RUNTEAMS_INVOCATION_ID") or uuid.uuid4().hex
    directory = owned("evidence/runtime-preparation/" + invocation)
    suffix = ".cmd" if os.name == "nt" else ""
    cli = runtime / "node_modules/.bin" / ("playwright-cli" + suffix)
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    channel = "chrome" if sys.platform == "darwin" and chrome.is_file() else None
    with browser_installation(env, directory, upgrade) as (source, promote, reused):
        copy_browser_installation(source, runtime)
        if channel is None:
            playwright = runtime / "node_modules/.bin" / ("playwright" + suffix)
            installed = run_logged([str(playwright), "install", "chromium", "--only-shell"], env, directory, "chromium", 420)
            if installed.returncode:
                raise ValueError("浏览器二进制准备失败；原有工具安装保持不变")
        version = run_logged([str(cli), "--version"], env, directory, "task-version", 15)
        if version.returncode:
            raise ValueError("已安装浏览器工具验证失败；不下载或替换已冻结版本")
        skill = runtime / ".agents/skills/playwright-cli/SKILL.md"
        if not skill.is_file():
            raise ValueError("官方技能未安装；查看准备日志")
        versions = browser_versions(runtime)
        origins = ["http://{}:{}".format(host, int(port))
                   for port in registry.get("ports", []) for host in ("127.0.0.1", "localhost", "[::1]")]
        if not origins:
            raise ValueError("没有本次任务登记的实例端口")
        config = owned(".scratch/browser.config.json")
        config.write_text(json.dumps({
            "browser": {"browserName": "chromium", "isolated": True,
                        "launchOptions": dict(headless=True, **({"channel": channel} if channel else {})),
                        "contextOptions": {"serviceWorkers": "block", "viewport": {"width": 1280, "height": 900}}},
            "network": {"allowedOrigins": origins}, "outputDir": str(owned("evidence/browser")), "saveSession": True,
            "timeouts": {"action": 5000, "navigation": 15000, "idle": 120000},
        }, ensure_ascii=False))
        launch = run_logged([str(cli), "-s=runteams-preflight", "open", "--config=" + str(config)], env, directory, "launch", 45, cwd=str(Path.cwd()))
        close = run_logged([str(cli), "-s=runteams-preflight", "close"], env, directory, "close", 30, cwd=str(Path.cwd()))
        if launch.returncode or close.returncode or "### Error" in launch.stdout or "### Error" in close.stdout:
            return emit("prepare-runtime", False, "浏览器启动与关闭验证失败；原有安装保持不变", launch.stdout + close.stdout,
                        "environment_unavailable", [str(p.relative_to(Path.cwd())) for p in directory.iterdir()])
        promote()
    env_file = owned(".scratch/browser-env.sh")
    names = ("HOME", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "LOCALAPPDATA",
             "PLAYWRIGHT_BROWSERS_PATH", "PLAYWRIGHT_SKIP_BROWSER_GC", "PWTEST_SOCKETS_DIR", "npm_config_cache",
             "npm_config_userconfig", "npm_config_globalconfig", "CI", "NO_UPDATE_NOTIFIER")
    lines = ["# Load from the task workspace before every official browser command.", ". .scratch/env.sh"]
    lines.extend("export {}={}".format(name, shlex.quote(env[name])) for name in names)
    lines.append("export PATH={}:\"$PATH\"".format(shlex.quote(str(cli.parent))))
    env_file.write_text("\n".join(lines) + "\n")
    record = {"provider": "Microsoft Playwright", "requested": "@playwright/cli@" + versions["@playwright/cli"], "versions": versions,
              "entry": str(cli), "skill": str(skill), "environment": str(env_file), "config": str(config),
              "lockfile": str(runtime / "package-lock.json"), "browser_cache": env["PLAYWRIGHT_BROWSERS_PATH"],
              "channel": channel or "chromium-headless-shell", "installation_reused": reused,
              "logs": str(directory.relative_to(Path.cwd()))}
    registry.setdefault("runtimes", {})["browser"] = record
    registry_path.write_text(json.dumps(registry, ensure_ascii=False))
    evidence = owned("evidence/browser"); evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "runtime.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    shutil.copyfile(runtime / "package-lock.json", evidence / "package-lock.json")
    return emit("prepare-runtime", True, "官方浏览器工具已准备，读取返回的 skill 并使用 browser-cli 调用", json.dumps(record, ensure_ascii=False))


def choose_python(explicit=None):
    candidates = [explicit] if explicit else [sys.executable] + [
        shutil.which("python3.{}".format(v)) for v in range(14, 9, -1)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            result = subprocess.run([candidate, "-I", "-c",
                                     "import sys; print(sys.version_info >= (3,10))"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip() == "True":
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise ValueError("需要 Python 3.10 或更新版本；未找到可用解释器")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("project", "browser"))
    parser.add_argument("--project")
    parser.add_argument("--python")
    parser.add_argument("--upgrade", action="store_true", help="显式验证升级；失败保留已有可用安装")
    parser.add_argument("--check", action="store_true", help="仅检查计划，不安装；不表示浏览器已就绪")
    args = parser.parse_args()
    try:
        requirements = None
        if args.kind == "project":
            if not args.project:
                raise ValueError("项目依赖准备需要 --project")
            project = owned(args.project)
            requirements = owned(project / "requirements.txt")
            if not requirements.is_file():
                raise ValueError("未找到 requirements.txt；按项目声明选择相应依赖管理器")
        if args.check:
            return emit("prepare-runtime", True, "依赖准备计划有效，尚未安装或验证运行环境")
        env = runtime_environment()
        if args.kind == "browser":
            return prepare_browser(env, upgrade=args.upgrade)
        python = choose_python(args.python)
        return prepare_project(python, project, requirements, env)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return emit("prepare-runtime", False, str(exc), code="environment_unavailable")


if __name__ == "__main__":
    raise SystemExit(main())
