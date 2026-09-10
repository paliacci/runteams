"""Agent Skills importer and deterministic capability verifier."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import capability_runtime
import execution_backend
import failure_protocol

from .contracts import ContractError, normalize_package_manifest


_IGNORED = {".DS_Store", "__pycache__", ".git"}
_MAX_FILES = 500
_MAX_BYTES = 32 * 1024 * 1024


class PackageExecutionInterrupted(RuntimeError):
    pass


class PackageExecutionCancelled(RuntimeError):
    pass


class PackageVerificationError(ContractError):
    def __init__(self, message, checks=None):
        super().__init__(message)
        self.checks = list(checks or [])


def _redact_text(value, credentials):
    text = str(value or "")
    for secret in sorted({str(item) for item in (credentials or {}).values() if str(item)},
                         key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def _redact_value(value, credentials):
    if isinstance(value, dict):
        return {(_redact_text(key, credentials) if isinstance(key, str) else key):
                _redact_value(item, credentials) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, credentials) for item in value]
    if isinstance(value, str):
        return _redact_text(value, credentials)
    return value


def _safe_relative(value):
    value = str(value or "").replace("\\", "/").strip()
    normalized = os.path.normpath(value).replace("\\", "/")
    if (not value or value.startswith("/") or normalized in (".", "..") or
            normalized.startswith("../") or "\0" in value):
        raise ContractError("能力包路径不安全：{}".format(value or "(empty)"))
    return normalized


def _scalar(value):
    value = str(value or "").strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            return str(json.loads(value))
        except ValueError:
            pass
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _frontmatter(text):
    if not text.startswith("---\n"):
        raise ContractError("SKILL.md 必须包含 YAML frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise ContractError("SKILL.md frontmatter 未闭合")
    lines, values, index = text[4:end].splitlines(), {}, 0
    known = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    while index < len(lines):
        raw = lines[index]
        index += 1
        if not raw.strip() or raw.lstrip().startswith("#") or raw[:1].isspace() or ":" not in raw:
            continue
        key, raw_value = raw.split(":", 1)
        key, raw_value = key.strip(), raw_value.strip()
        if key not in known:
            continue
        if key == "metadata":
            metadata = {}
            while index < len(lines) and (not lines[index].strip() or lines[index][:1].isspace()):
                nested = lines[index]
                index += 1
                if not nested.strip() or nested.lstrip().startswith("#") or ":" not in nested:
                    continue
                nested_key, nested_value = nested.strip().split(":", 1)
                metadata[str(nested_key).strip()] = _scalar(nested_value)
            values[key] = metadata
            continue
        if raw_value in (">", ">-", ">+", "|", "|-", "|+"):
            block = []
            while index < len(lines) and (not lines[index].strip() or lines[index][:1].isspace()):
                block.append(lines[index].strip())
                index += 1
            values[key] = ("\n" if raw_value.startswith("|") else " ").join(block).strip()
        else:
            values[key] = _scalar(raw_value)
    if not values.get("name") or not values.get("description"):
        raise ContractError("SKILL.md 必须声明 name 和 description")
    name, description = values["name"], values["description"]
    if (len(name) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)):
        raise ContractError("SKILL.md name 不符合 Agent Skills 规范")
    if len(description) > 1024:
        raise ContractError("SKILL.md description 超过 1024 字符")
    if values.get("compatibility") and len(values["compatibility"]) > 500:
        raise ContractError("SKILL.md compatibility 超过 500 字符")
    return values


def _capability_id(value):
    value = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    if not value:
        raise ContractError("无法从 Skill 名称生成能力 id")
    return value[:80]


class PackageStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def inspect_agent_skill(self, source):
        prepared = self._prepare_agent_skill(source)
        return {"digest": prepared["digest"], "manifest": prepared["manifest"]}

    def import_agent_skill(self, source, confirmed_digest=None):
        prepared = self._prepare_agent_skill(source)
        if confirmed_digest is not None and str(confirmed_digest) != prepared["digest"]:
            raise ContractError("能力包内容已变化，请重新检查后确认")
        files, manifest, package_digest = (
            prepared["files"], prepared["manifest"], prepared["digest"])
        target = self.objects / package_digest
        if not target.exists():
            staging = Path(tempfile.mkdtemp(prefix=".import-", dir=self.objects))
            try:
                for relative, body in files.items():
                    destination = staging / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(body)
                checks = self.verify_manifest(staging, manifest)
                try:
                    staging.rename(target)
                    self._seal(target)
                except FileExistsError:
                    pass
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        else:
            checks = self.verify_manifest(target, manifest)
            self._seal(target)
        return {"digest": package_digest, "manifest": manifest,
                "blob_ref": str(target), "checks": checks}

    def _prepare_agent_skill(self, source):
        source = Path(source).resolve()
        if not source.is_dir():
            raise ContractError("能力包目录不存在")
        skill_path = source / "SKILL.md"
        if not skill_path.is_file():
            raise ContractError("Agent Skill 能力包必须包含 SKILL.md")
        files, total = {}, 0
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source).as_posix()
            if any(part in _IGNORED for part in path.relative_to(source).parts):
                continue
            if path.is_symlink():
                raise ContractError("能力包不能包含符号链接：{}".format(relative))
            if not path.is_file():
                continue
            if len(files) >= _MAX_FILES:
                raise ContractError("能力包文件数量超过限制")
            body = path.read_bytes()
            total += len(body)
            if total > _MAX_BYTES:
                raise ContractError("能力包大小超过 32 MB")
            files[_safe_relative(relative)] = body
        try:
            skill_text = files["SKILL.md"].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError("SKILL.md 必须使用 UTF-8") from exc
        meta = _frontmatter(skill_text)
        if source.name != meta["name"]:
            raise ContractError("SKILL.md name 必须与能力包目录名一致")
        metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
        capabilities = [{"id": _capability_id(meta["name"]), "kind": "skill",
                         "name": metadata.get("display_name") or meta["name"],
                         "description": meta["description"], "entry": "SKILL.md"}]
        extension = {}
        if "runteams.json" in files:
            try:
                extension = json.loads(files["runteams.json"].decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ContractError("runteams.json 不是有效的 UTF-8 JSON") from exc
            if extension.get("schema") != "runteams.package-extension/v1":
                raise ContractError("runteams.json 版本无效")
            for raw in extension.get("capabilities") or []:
                entry = _safe_relative(raw.get("entry"))
                if entry not in files:
                    raise ContractError("工具入口不存在：{}".format(entry))
                runtime = capability_runtime.normalize(raw.get("runtime"), entry, files)
                if runtime.get("dependencies"):
                    raise ContractError("首版能力包只接受零外部依赖工具")
                healthcheck = runtime.get("healthcheck") or {}
                if not healthcheck.get("enabled") or not healthcheck.get("declared"):
                    raise ContractError("可执行工具必须声明真实 healthcheck")
                overlap = set((healthcheck.get("fixture_files") or {})).intersection(files)
                if overlap:
                    raise ContractError("行为用例文件不能覆盖能力包文件：{}".format(
                        sorted(overlap)[0]))
                cases = healthcheck.get("cases") or []
                if not cases:
                    raise ContractError("可执行工具必须声明行为用例")
                if runtime.get("effect") == "verifier" and {
                        item.get("expected") for item in cases} != {"passed", "failed"}:
                    raise ContractError("校验工具必须同时覆盖通过和失败用例")
                capabilities.append({"id": raw.get("id"), "kind": "tool",
                                     "name": raw.get("name") or raw.get("id"),
                                     "description": raw.get("description") or "",
                                     "entry": entry, "runtime": runtime,
                                     "credentials": raw.get("credentials") or []})
        manifest = normalize_package_manifest({
            "schema": "runteams.package/v1", "format": "agent-skill",
            "name": meta["name"],
            "display_name": extension.get("display_name") or
                            metadata.get("package_display_name") or
                            metadata.get("display_name") or meta["name"],
            "description": meta["description"],
            "capabilities": capabilities,
            "files": [{"path": path, "sha256": hashlib.sha256(body).hexdigest(),
                       "size": len(body)} for path, body in sorted(files.items())],
            "extensions": {"agent_skills": meta,
                           "runteams": {"present": bool(extension)}},
        })
        return {"digest": self._tree_digest(files), "manifest": manifest,
                "files": files}

    @staticmethod
    def _tree_digest(files):
        value = hashlib.sha256()
        for path, body in sorted(files.items()):
            encoded = path.encode("utf-8")
            value.update(len(encoded).to_bytes(4, "big"))
            value.update(encoded)
            value.update(len(body).to_bytes(8, "big"))
            value.update(body)
        return value.hexdigest()

    def verify_manifest(self, blob_ref, manifest):
        source = Path(blob_ref).resolve()
        self._assert_manifest_files(source, manifest)
        temporary = Path(tempfile.mkdtemp(prefix=".verify-", dir=self.root))
        blob_ref = temporary / "package"
        shutil.copytree(source, blob_ref, copy_function=shutil.copyfile)
        self._make_writable(blob_ref)
        try:
            return self._verify_directory(blob_ref, manifest)
        finally:
            self._make_writable(temporary)
            shutil.rmtree(temporary)

    @staticmethod
    def verification_runner():
        """Describe the exact managed runtime used by package healthchecks."""
        version = ".".join(str(value) for value in sys.version_info[:3])
        return "RunTeams bundled Python {}".format(version)

    def object_path(self, digest):
        digest = str(digest or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ContractError("能力包对象摘要无效")
        source = (self.objects / digest).resolve()
        if source.parent != self.objects or not source.is_dir():
            raise ContractError("能力包对象不存在：{}".format(digest))
        files, total = {}, 0
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source).as_posix()
            if path.is_symlink():
                raise ContractError("能力包对象包含符号链接：{}".format(relative))
            if not path.is_file():
                continue
            if len(files) >= _MAX_FILES:
                raise ContractError("能力包文件数量超过限制")
            body = path.read_bytes()
            total += len(body)
            if total > _MAX_BYTES:
                raise ContractError("能力包大小超过 32 MB")
            files[_safe_relative(relative)] = body
        if self._tree_digest(files) != digest:
            raise ContractError("能力包对象与不可变摘要不一致")
        return source

    def verify_frozen(self, digest, capabilities):
        source = self.object_path(digest)
        temporary = Path(tempfile.mkdtemp(prefix=".verify-", dir=self.root))
        copied = temporary / "package"
        shutil.copytree(source, copied, copy_function=shutil.copyfile)
        self._make_writable(copied)
        try:
            return self._verify_directory(copied, {"capabilities": list(capabilities or [])})
        finally:
            self._make_writable(temporary)
            shutil.rmtree(temporary)

    def materialize_frozen(self, digest, destination):
        return self.materialize(self.object_path(digest), destination)

    def _verify_directory(self, blob_ref, manifest):
        checks = [{"capability_id": item["id"], "status": "verified",
                   "kind": item["kind"], "detail": "SKILL.md 结构有效"}
                  for item in manifest["capabilities"] if item["kind"] == "skill"]
        for capability in manifest["capabilities"]:
            if capability["kind"] != "tool":
                continue
            runtime = capability["runtime"]
            if runtime["runner"] != "python":
                raise ContractError("首版能力验证器只运行 Python 工具")
            healthcheck = runtime.get("healthcheck") or {}
            for relative, content in (healthcheck.get("fixture_files") or {}).items():
                destination = blob_ref / _safe_relative(relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            cases = healthcheck.get("cases") or []
            # Immutable releases imported before behavior cases existed remain runnable.
            if not cases:
                cases = [{"arguments": healthcheck.get("arguments") or [],
                          "expected": "passed"}]
            case_results = []
            for index, case in enumerate(cases, 1):
                command = self._python_command(blob_ref / capability["entry"])
                command.extend(case.get("arguments") or [])
                try:
                    result = self._run(command, blob_ref, timeout=30, python_path=blob_ref)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    detail = "第 {} 个行为用例无法执行：{}".format(index, exc)
                    failed = {"capability_id": capability["id"], "status": "failed",
                              "kind": "tool", "detail": detail}
                    raise PackageVerificationError(
                        "能力 {} {}".format(capability["id"], detail), checks + [failed]) from exc
                output_lines = [line for line in result["output"].splitlines() if line.strip()]
                try:
                    payload = json.loads(output_lines[-1]) if output_lines else {}
                except ValueError:
                    payload = {}
                actual = (payload.get("evaluation") or {}).get("status")
                expected = case.get("expected") or "passed"
                expected_exit = 0 if expected == "passed" else 1
                execution = payload.get("execution") or {}
                valid = (payload.get("schema") == "runteams.tool-result/v1" and
                         execution.get("status") == "completed" and
                         execution.get("exit_code") == result["exit_code"] and
                         actual == expected and
                         ((result["exit_code"] == 0) if expected_exit == 0
                          else (result["exit_code"] != 0)))
                if not valid:
                    summary = (payload.get("evaluation") or {}).get("summary")
                    detail = ("第 {} 个行为用例预期 {}，实际 {}（退出码 {}）{}".format(
                        index, expected, actual or "无有效结果", result["exit_code"],
                        "：{}".format(summary) if summary else ""))[-2000:]
                    failed = {"capability_id": capability["id"], "status": "failed",
                              "kind": "tool", "detail": detail}
                    raise PackageVerificationError(
                        "能力 {} 行为验证失败：{}".format(capability["id"], detail),
                        checks + [failed])
                case_results.append(payload)
            checks.append({"capability_id": capability["id"], "status": "verified",
                           "kind": "tool",
                           "detail": "{} 个行为用例通过".format(len(case_results))})
        return checks

    @staticmethod
    def _assert_manifest_files(root, manifest):
        expected = {item["path"]: (item["sha256"], int(item["size"]))
                    for item in manifest.get("files") or []}
        actual = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ContractError("能力包对象包含符号链接")
            if path.is_file():
                body = path.read_bytes()
                actual[path.relative_to(root).as_posix()] = (
                    hashlib.sha256(body).hexdigest(), len(body))
        if actual != expected:
            raise ContractError("能力包对象与不可变 manifest 不一致")

    @staticmethod
    def _seal(root):
        for path in sorted(Path(root).rglob("*"), reverse=True):
            try:
                path.chmod(0o555 if path.is_dir() else 0o444)
            except OSError:
                pass
        try:
            Path(root).chmod(0o555)
        except OSError:
            pass

    @staticmethod
    def _make_writable(root):
        root = Path(root)
        for path in root.rglob("*"):
            try:
                path.chmod(0o755 if path.is_dir() else 0o644)
            except OSError:
                pass
        try:
            root.chmod(0o755)
        except OSError:
            pass

    @classmethod
    def materialize(cls, source, destination):
        source, destination = Path(source).resolve(), Path(destination).resolve()
        if destination.exists():
            cls._make_writable(destination)
            shutil.rmtree(destination)
        shutil.copytree(source, destination, copy_function=shutil.copyfile)
        cls._make_writable(destination)
        return destination

    def run_tool(self, blob_ref, capability, arguments, workspace, cancel_event=None,
                 cancel_check=None, on_process=None, tool_id=None, credentials=None,
                 invocation_id=None):
        if capability.get("kind") != "tool":
            raise ContractError("该能力不是可执行工具")
        runtime = capability.get("runtime") or {}
        if runtime.get("runner") != "python":
            raise ContractError("首版能力运行器只支持 Python")
        arguments = [str(value) for value in (arguments or [])]
        if len(arguments) > 50 or any("\0" in value or len(value) > 1000 for value in arguments):
            raise ContractError("能力参数无效")
        command = self._python_command(Path(blob_ref).resolve() / capability["entry"]) + arguments
        executed = self._run(command, Path(workspace).resolve(), timeout=300,
                             python_path=Path(blob_ref).resolve(), cancel_event=cancel_event,
                             cancel_check=cancel_check, on_process=on_process,
                             credentials=credentials,
                             invocation_id=invocation_id,
                             execution_entry={"entry_path": capability["entry"],
                                              "runtime": runtime})
        parsed = None
        try:
            parsed = _redact_value(json.loads(executed["output"]), credentials)
        except (TypeError, ValueError):
            pass
        if isinstance(parsed, dict) and parsed.get("schema") == "runteams.tool-result/v1":
            parsed["tool_id"] = str(tool_id or parsed.get("tool_id") or capability["id"])
            return parsed
        failure = None
        if executed["exit_code"] != 0:
            failure = {"owner": "task", "code": "nonzero_exit",
                       "message": "能力执行未通过",
                       "output": _redact_text(executed["output"], credentials)}
        return failure_protocol.result(tool_id=tool_id or capability["id"],
                                       exit_code=executed["exit_code"],
                                       output=_redact_text(executed["output"], credentials),
                                       failure=failure)

    @staticmethod
    def _python_command(entry):
        entry = str(Path(entry).resolve())
        if getattr(sys, "frozen", False):
            return [sys.executable, "--runteams-task-tool", entry]
        return [sys.executable, entry]

    @staticmethod
    def _run(command, cwd, timeout, python_path=None, cancel_event=None,
             cancel_check=None, on_process=None, execution_entry=None, credentials=None,
             invocation_id=None):
        # Tools receive only operational process settings plus the exact credential Keys
        # declared by their immutable capability contract. Ambient user secrets are not a
        # hidden dependency and never become visible to an undeclared package.
        operational = ("PATH", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP",
                       "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
                       "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SYSTEMROOT")
        env = {key: os.environ[key] for key in operational if os.environ.get(key)}
        env.update({"PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": os.devnull,
                    "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        env.update({str(key): str(value) for key, value in (credentials or {}).items()})
        if python_path:
            env["PYTHONPATH"] = str(python_path)
            env["RUNTEAMS_TASK_TOOL_ROOT"] = str(python_path)
            env["RUNTEAMS_TASK_TOOL_PATHS"] = str(python_path)
        if invocation_id:
            env["RUNTEAMS_INVOCATION_ID"] = str(invocation_id)
        with tempfile.TemporaryDirectory(prefix=".runteams-tool-") as temporary:
            private_tmp = Path(temporary)
            if execution_entry:
                command = execution_backend.prepare_command(
                    execution_entry, command, str(cwd), str(private_tmp),
                    label="package-capability")
            started, next_cancel_check, next_resource_check = time.monotonic(), 0, 0
            resource_error = ""
            with tempfile.TemporaryFile(dir=private_tmp) as output_file:
                process = subprocess.Popen(command, cwd=cwd, env=env,
                                           stdin=subprocess.DEVNULL, stdout=output_file,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                if on_process:
                    on_process(process.pid, str((execution_entry or {}).get("entry_path") or
                                                (command[-1] if command else "")))
                while process.poll() is None:
                    if cancel_event is not None and cancel_event.wait(0.1):
                        execution_backend.stop_process_tree(process)
                        raise PackageExecutionInterrupted("应用退出，能力工具将在重启后继续")
                    current = time.monotonic()
                    if cancel_check is not None and current >= next_cancel_check:
                        next_cancel_check = current + 0.5
                        if cancel_check():
                            execution_backend.stop_process_tree(process)
                            raise PackageExecutionCancelled("任务已终止，能力工具同步停止")
                    if execution_entry and current >= next_resource_check:
                        next_resource_check = current + 0.5
                        resource_error = execution_backend.process_limit_violation(
                            process.pid, execution_entry)
                        if resource_error:
                            execution_backend.stop_process_tree(process)
                            break
                    if current - started >= timeout:
                        execution_backend.stop_process_tree(process)
                        raise subprocess.TimeoutExpired(command, timeout)
                    if cancel_event is None:
                        time.sleep(0.1)
                size = output_file.tell()
                output_file.seek(max(0, size - 30000))
                output = output_file.read().decode("utf-8", errors="replace")
            if resource_error:
                output += ("\n" if output else "") + "RUNTEAMS_RESOURCE_LIMIT: " + resource_error
            return {"exit_code": int(process.returncode or 0), "output": output[-30000:]}
