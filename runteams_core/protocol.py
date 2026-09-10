"""Minimal MCP collaboration protocol backed by the new core tables."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

import failure_protocol

from .contracts import ContractError, digest, normalize_work_result
from .packages import PackageStore
from .repository import Repository, utc_now


TERMINAL_STATES = ("completed", "blocked", "needs_human", "failed", "canceled", "interrupted")
_INVOCATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_INVOCATION_EVENTS = ("capability.invocation_started", "capability.invocation_completed")


def trial_unavailable_capability(snapshot, position_key, employee):
    """Return an unavailable capability injected only by an employee trial."""
    if not snapshot.get("trial") or position_key != "subject":
        return ""
    work_order = (snapshot.get("task") or {}).get("payload") or {}
    context = work_order.get("context") if isinstance(work_order, dict) else {}
    signal = context.get("test_signal") if isinstance(context, dict) else None
    if not isinstance(signal, dict) or signal.get("state") != "unavailable":
        return ""
    reference = str(signal.get("capability_ref") or "").strip()
    frozen_refs = set()
    for item in employee.get("capabilities") or []:
        capabilities = item.get("capabilities") or [item.get("capability") or {}]
        for capability in capabilities:
            if item.get("package_key") and capability.get("id"):
                frozen_refs.add("{}/{}".format(item["package_key"], capability["id"]))
    return reference if reference in frozen_refs else ""


def _text(value, error=False):
    structured = value if isinstance(value, dict) else {"message": str(value)}
    return {"content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
            "structuredContent": structured, "isError": bool(error)}


class EmployeeProtocol:
    def __init__(self, database, employee_run_id, workspace, credential_resolver=None):
        self.repository = Repository(database)
        self.employee_run_id = int(employee_run_id)
        self.workspace = Path(workspace).resolve()
        self.package_store = PackageStore(Path(database).resolve().parent / "packages")
        self.credential_resolver = credential_resolver

    @property
    def stream(self):
        return "employee_run:{}".format(self.employee_run_id)

    def context(self):
        with self.repository.connect() as connection:
            run = connection.execute("SELECT * FROM employee_runs WHERE id=?",
                                     (self.employee_run_id,)).fetchone()
            if run is None:
                raise ContractError("员工运行不存在")
            workflow = connection.execute(
                "SELECT snapshot_json FROM workflow_runs WHERE id=?",
                (run["workflow_run_id"],)).fetchone()
        snapshot = json.loads(workflow["snapshot_json"])
        position = next((item for item in
                         ((snapshot.get("definition") or {}).get("positions") or [])
                         if item.get("key") == run["position_key"]), None)
        if position is None or not isinstance(position.get("employee"), dict):
            raise ContractError("工作流缺少冻结的员工快照")
        return dict(run), position["employee"]

    def events(self):
        return self.repository.events(self.stream)

    def _runtime_capabilities(self, employee):
        """Return selected capabilities plus tools shipped by their frozen packages.

        A skill may legitimately reference a companion script declared as a tool in
        the same immutable package.  The package digest is already frozen by the
        selected skill, so exposing that tool does not broaden the installed version
        or allow code from a different revision to run.
        """
        packages = [item for item in employee.get("capabilities") or []
                    if item.get("package_key")]
        resolved = []
        for item in packages:
            for capability in item.get("capabilities") or [item.get("capability") or {}]:
                if capability.get("id"):
                    resolved.append({
                        "package_key": item.get("package_key"),
                        "revision_id": item.get("revision_id"),
                        "digest": item.get("digest"),
                        "capability": capability,
                    })
        known = {
            (item.get("package_key"), (item.get("capability") or {}).get("id"))
            for item in resolved
        }
        manifests = {}
        with self.repository.connect() as connection:
            for item in packages:
                package_key = item.get("package_key")
                digest_value = item.get("digest")
                marker = (package_key, digest_value)
                if marker in manifests:
                    continue
                row = connection.execute(
                    "SELECT pr.manifest_json FROM package_revisions pr "
                    "JOIN packages p ON p.id=pr.package_id "
                    "WHERE p.key=? AND pr.digest=?",
                    marker,
                ).fetchone()
                manifests[marker] = json.loads(row["manifest_json"]) if row else {}
        # v1 releases selected individual entry points. Keep exposing companion
        # package tools for those immutable historical releases. New v2 releases
        # already carry every internal resource explicitly and need no expansion.
        for item in packages:
            if item.get("capabilities"):
                continue
            marker = (item.get("package_key"), item.get("digest"))
            for capability in (manifests.get(marker) or {}).get("capabilities") or []:
                key = (item.get("package_key"), capability.get("id"))
                if capability.get("kind") != "tool" or key in known:
                    continue
                resolved.append({
                    "package_key": item.get("package_key"),
                    "revision_id": item.get("revision_id"),
                    "digest": item.get("digest"),
                    "capability": capability,
                })
                known.add(key)
        return resolved

    def task(self):
        run, employee = self.context()
        with self.repository.connect() as connection:
            workflow = connection.execute(
                "SELECT snapshot_json FROM workflow_runs WHERE id=?",
                (run["workflow_run_id"],)).fetchone()
        snapshot = json.loads(workflow["snapshot_json"])
        unavailable = trial_unavailable_capability(
            snapshot, run["position_key"], employee)
        unavailable_package = unavailable.split("/", 1)[0] if unavailable else ""
        completed = [item["data_json"].get("step_id") for item in self.events()
                     if item["type"] == "step.completed"]
        capabilities, materialized = [], set()
        for item in self._runtime_capabilities(employee):
            capability = item["capability"]
            package_marker = (item["package_key"], item["digest"])
            if (item["package_key"] != unavailable_package and
                    package_marker not in materialized):
                local_ref = self.workspace / ".runteams" / "capabilities" / item["package_key"]
                local_ref.parent.mkdir(parents=True, exist_ok=True)
                self.package_store.materialize_frozen(item["digest"], local_ref)
                materialized.add(package_marker)
            reference = "{}/{}".format(item["package_key"], capability["id"])
            capabilities.append({"ref": reference,
                                 "kind": capability["kind"], "name": capability["name"],
                                 "available": item["package_key"] != unavailable_package,
                                 "effect": (capability.get("runtime") or {}).get("effect") or "",
                                 "credentials": list(capability.get("credentials") or []),
                                 "path": ".runteams/capabilities/{}".format(item["package_key"])})
        required_verifiers = ["{}/{}".format(item["package_key"], item["capability"]["id"])
                              for item in self._runtime_capabilities(employee)
                              if item.get("package_key") and
                              item["capability"].get("kind") == "tool" and
                              (item["capability"].get("runtime") or {}).get("effect") == "verifier"]
        return {"protocol": "runteams.employee/v1", "work_order": json.loads(run["input_json"]),
                "employee": {"name": employee["name"], "role": employee["role"],
                             "program": employee["program"],
                             "interface": employee.get("interface") or {}},
                "capabilities": capabilities,
                "extensions": [{"provider": item.get("provider"),
                                "plugin_id": item.get("plugin_id"),
                                "name": item.get("name") or item.get("plugin_id")}
                               for item in employee.get("capabilities") or []
                               if item.get("plugin_id")],
                "required_verifiers": required_verifiers,
                "checkpoint": {"completed_steps": completed,
                               "operation_invocations": [
                                   {key: item[key] for key in (
                                       "invocation_id", "capability_ref", "arguments", "state")}
                                   for item in self._operation_invocations(run)]}}

    def _operation_records(self, connection, run):
        rows = connection.execute(
            "SELECT e.type,e.data_json FROM events e JOIN employee_runs er "
            "ON e.stream=('employee_run:' || er.id) "
            "WHERE er.workflow_run_id=? AND er.position_key=? "
            "AND e.type IN (?,?) ORDER BY e.id",
            (run["workflow_run_id"], run["position_key"], *_INVOCATION_EVENTS),
        ).fetchall()
        records = {}
        for row in rows:
            data = json.loads(row["data_json"])
            invocation_id = str(data.get("invocation_id") or "")
            if not invocation_id:
                continue
            if row["type"] == "capability.invocation_started":
                records[invocation_id] = {
                    "invocation_id": invocation_id,
                    "capability_ref": data.get("capability_ref"),
                    "arguments": data.get("arguments") or [],
                    "request_digest": data.get("request_digest"),
                    "state": "in_doubt",
                }
                continue
            record = records.setdefault(invocation_id, {
                "invocation_id": invocation_id,
                "capability_ref": data.get("capability_ref"),
                "arguments": data.get("arguments") or [],
                "request_digest": data.get("request_digest"),
            })
            record.update({"state": "completed", "result": data.get("result"),
                           "workspace_digest": data.get("workspace_digest")})
        return list(records.values())

    def _operation_invocations(self, run):
        with self.repository.connect() as connection:
            return self._operation_records(connection, run)

    def _claim_operation(self, run, reference, arguments, invocation_id):
        invocation_id = str(invocation_id or "").strip()
        if not _INVOCATION_ID.fullmatch(invocation_id):
            raise ContractError(
                "operation 工具必须提供稳定 invocation_id（字母或数字开头，最长 120 字符）")
        request_digest = digest({"capability_ref": reference, "arguments": arguments})
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            records = self._operation_records(connection, run)
            existing = next((item for item in records
                             if item["invocation_id"] == invocation_id), None)
            if existing is not None:
                if existing.get("request_digest") != request_digest:
                    raise ContractError("同一 invocation_id 不能用于不同的工具或参数")
                if existing.get("state") == "completed":
                    return existing
                raise ContractError(
                    "operation {} 的执行结果未知，禁止自动重放；请先核对外部系统".format(
                        invocation_id))
            in_doubt = next((item for item in records if item.get("state") == "in_doubt"), None)
            if in_doubt is not None:
                raise ContractError(
                    "operation {} 的执行结果未知，禁止自动重放或开始新的 operation；"
                    "请先核对外部系统".format(in_doubt["invocation_id"]))
            data = {"invocation_id": invocation_id, "capability_ref": reference,
                    "arguments": arguments, "request_digest": request_digest,
                    "employee_run_id": self.employee_run_id}
            self.repository.event(
                self.stream, "capability.invocation_started", data, connection=connection)
        return dict(data, state="execute")

    def _complete_operation(self, claim, result, workspace_digest):
        data = {key: claim[key] for key in (
            "invocation_id", "capability_ref", "arguments", "request_digest")}
        data.update({"result": result, "workspace_digest": workspace_digest,
                     "employee_run_id": self.employee_run_id})
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository.event(
                self.stream, "capability.invocation_completed", data, connection=connection)
            self.repository.event(
                self.stream, "capability.executed",
                {"capability_ref": claim["capability_ref"], "result": result,
                 "workspace_digest": workspace_digest,
                 "invocation_id": claim["invocation_id"]}, connection=connection)

    def call(self, name, arguments):
        arguments = arguments or {}
        run, employee = self.context()
        if name == "get_task":
            self.repository.event(self.stream, "task.read", {})
            return _text(self.task())
        if run["state"] in TERMINAL_STATES:
            return _text("员工运行已经结束", True)
        if not any(item["type"] == "task.read" for item in self.events()):
            return _text("必须先调用 get_task", True)
        try:
            if name == "report_progress":
                summary = str(arguments.get("summary") or "").strip()
                if not summary:
                    raise ContractError("进展不能为空")
                self.repository.event(self.stream, "progress.reported", {
                    "summary": summary[:2000], "percent": arguments.get("percent")})
                return _text({"ok": True})
            if name == "advance_step":
                return _text(self._advance(employee, arguments))
            if name == "run_capability":
                return _text(self._run_capability(run, employee, arguments))
            if name == "publish_artifact":
                return _text({"ok": True, "artifact": self._publish_artifact(arguments)})
            if name == "complete":
                result = self._complete(employee, arguments)
                return _text({"ok": True, "result": result,
                              "instruction": "提交成功，立即结束本次运行"})
            if name == "request_human":
                question = str(arguments.get("question") or "").strip()
                if not question:
                    raise ContractError("问题不能为空")
                result = normalize_work_result({"status": "needs_human", "summary": "",
                                                "output": {"question": question,
                                                           "context": arguments.get("context") or ""},
                                                "issues": [], "artifacts": self._artifacts()})
                self._terminal(result)
                return _text({"ok": True, "instruction": "已暂停，立即结束本次运行"})
            if name == "report_blocked":
                reason = str(arguments.get("reason") or "").strip()
                if not reason:
                    raise ContractError("阻塞原因不能为空")
                result = normalize_work_result({"status": "blocked", "summary": "",
                                                "output": {"reason": reason,
                                                           "recovery": arguments.get("recovery") or ""},
                                                "issues": [reason], "artifacts": self._artifacts()})
                self._terminal(result)
                return _text({"ok": True, "instruction": "已记录阻塞，立即结束本次运行"})
            if name == "report_failed":
                reason = str(arguments.get("reason") or "").strip()
                if not reason:
                    raise ContractError("失败原因不能为空")
                result = normalize_work_result({"status": "failed", "summary": "",
                                                "output": {"reason": reason,
                                                           "recovery": arguments.get("recovery") or ""},
                                                "issues": [reason], "artifacts": self._artifacts()})
                self._terminal(result)
                return _text({"ok": True, "instruction": "已记录运行失败，立即结束本次运行"})
            return _text("未知工具：{}".format(name), True)
        except Exception as exc:
            return _text(str(exc), True)

    def _advance(self, employee, arguments):
        steps = employee["program"]["steps"]
        completed = [item["data_json"].get("step_id") for item in self.events()
                     if item["type"] == "step.completed"]
        expected = next((item for item in steps if item["id"] not in completed), None)
        step_id = str(arguments.get("step_id") or "")
        if expected is None:
            raise ContractError("全部步骤已经完成")
        if step_id != expected["id"]:
            raise ContractError("下一步必须是 {}".format(expected["id"]))
        summary = str(arguments.get("summary") or "").strip()
        if not summary:
            raise ContractError("步骤摘要不能为空")
        self.repository.event(self.stream, "step.completed",
                              {"step_id": step_id, "summary": summary[:2000]})
        return {"ok": True, "completed": len(completed) + 1, "total": len(steps)}

    def _run_capability(self, run, employee, arguments):
        reference = str(arguments.get("capability_ref") or "")
        frozen = next((item for item in self._runtime_capabilities(employee)
                       if reference == "{}/{}".format(item["package_key"],
                                                      item["capability"]["id"])), None)
        if frozen is None or frozen["capability"]["kind"] != "tool":
            raise ContractError("该工具未冻结在员工发布版本中")
        with self.repository.connect() as connection:
            workflow = connection.execute(
                "SELECT snapshot_json FROM workflow_runs WHERE id=?",
                (run["workflow_run_id"],)).fetchone()
        snapshot = json.loads(workflow["snapshot_json"])
        unavailable = trial_unavailable_capability(
            snapshot, run["position_key"], employee)
        if unavailable and reference.split("/", 1)[0] == unavailable.split("/", 1)[0]:
            raise ContractError("能力在本次验证场景中不可用：{}".format(reference))
        tool_arguments = [str(value) for value in (arguments.get("arguments") or [])]
        if (len(tool_arguments) > 50 or
                any("\0" in value or len(value) > 1000 for value in tool_arguments)):
            raise ContractError("能力参数无效")
        effect = (frozen["capability"].get("runtime") or {}).get("effect") or "operation"
        local_ref = self.workspace / ".runteams" / "capabilities" / frozen["package_key"]
        local_ref.parent.mkdir(parents=True, exist_ok=True)
        self.package_store.materialize_frozen(frozen["digest"], local_ref)
        required = frozen["capability"].get("credentials") or []
        credentials = (self.credential_resolver(required)
                       if required and self.credential_resolver is not None else {})
        missing = [name for name in required if not credentials.get(name)]
        if missing:
            raise ContractError("工具缺少凭据：{}".format("、".join(missing)))
        claim = None
        if effect == "operation":
            claim = self._claim_operation(
                run, reference, tool_arguments, arguments.get("invocation_id"))
            if claim.get("state") == "completed":
                self.repository.event(
                    self.stream, "capability.invocation_reused",
                    {"invocation_id": claim["invocation_id"],
                     "capability_ref": reference,
                     "request_digest": claim["request_digest"]})
                return {"ok": True, "result": claim["result"],
                        "invocation_id": claim["invocation_id"], "reused": True}
        result = self.package_store.run_tool(local_ref, frozen["capability"],
                                             tool_arguments, self.workspace,
                                             tool_id=reference, credentials=credentials,
                                             invocation_id=(claim or {}).get("invocation_id"))
        workspace_digest = self._workspace_digest()
        if claim is not None:
            self._complete_operation(claim, result, workspace_digest)
            return {"ok": True, "result": result,
                    "invocation_id": claim["invocation_id"], "reused": False}
        self.repository.event(self.stream, "capability.executed",
                              {"capability_ref": reference, "result": result,
                               "workspace_digest": workspace_digest})
        return {"ok": True, "result": result}

    def _complete(self, employee, arguments):
        completed = {item["data_json"].get("step_id") for item in self.events()
                     if item["type"] == "step.completed"}
        missing = [item["id"] for item in employee["program"]["steps"]
                   if item["id"] not in completed]
        if missing:
            raise ContractError("必需步骤尚未完成：{}".format("、".join(missing)))
        verifier_events = [item["data_json"] for item in self.events()
                           if item["type"] == "capability.executed"]
        for frozen in self._runtime_capabilities(employee):
            if not frozen.get("package_key"):
                continue
            capability = frozen["capability"]
            if (capability.get("kind") != "tool" or
                    (capability.get("runtime") or {}).get("effect") != "verifier"):
                continue
            reference = "{}/{}".format(frozen["package_key"], capability["id"])
            latest = next((item for item in reversed(verifier_events)
                           if item.get("capability_ref") == reference), None)
            if latest is None or not failure_protocol.passed(latest.get("result")):
                raise ContractError("最终验收工具尚未通过：{}".format(reference))
            if latest.get("workspace_digest") != self._workspace_digest():
                raise ContractError("最终验收证据已因工作区修改失效：{}".format(reference))
        self._publish_declared_deliverables(employee)
        result = normalize_work_result({"status": "completed",
                                        "summary": arguments.get("summary"),
                                        "output": arguments.get("output") or {},
                                        "artifacts": self._artifacts(), "issues": []})
        self._terminal(result)
        return result

    DOCUMENT_MODELS = {
        ".md": "markdown", ".markdown": "markdown", ".csv": "table", ".tsv": "table",
        ".json": "json", ".txt": "text", ".log": "text", ".yaml": "text",
        ".yml": "text", ".xml": "text", ".html": "text", ".htm": "text",
    }

    @classmethod
    def _content_model_for_path(cls, path):
        return cls.DOCUMENT_MODELS.get(Path(str(path or "")).suffix.lower(), "binary")

    def _publish_declared_deliverables(self, employee):
        """按岗位声明登记交付文档：产出了就自动入库，必需的缺了就不许完成。"""
        declared = (employee.get("program") or {}).get("deliverables") or []
        missing = []
        for item in declared:
            relative = str(item.get("path") or "")
            source = (self.workspace / relative).resolve()
            if not str(source).startswith(str(self.workspace) + os.sep) or not source.is_file():
                if item.get("required", True):
                    missing.append(relative)
                continue
            self._publish_document(relative, item.get("name"))
        if missing:
            raise ContractError(
                "声明的交付文档还没产出，请先在工作区写出这些文件：{}".format("、".join(missing)))

    def _publish_document(self, relative, title):
        """登记原始文件；格式适配只在明确的边界发生，不在发布时改写正文。"""
        return self._publish_file(relative, title)

    def _terminal(self, result):
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("UPDATE employee_runs SET state=?,output_json=?,updated_at=? WHERE id=?",
                               (result["status"], json.dumps(result, ensure_ascii=False), now,
                                self.employee_run_id))
            self.repository.event(self.stream, "employee.terminal", {"state": result["status"]},
                                  connection=connection)

    def _publish_artifact(self, arguments):
        return self._publish_file(str(arguments.get("path") or ""),
                                  arguments.get("title"))

    def _publish_file(self, path, title=None):
        relative = str(path or "").replace("\\", "/").strip().strip("/")
        source = (self.workspace / relative).resolve()
        if (not relative or not str(source).startswith(str(self.workspace) + os.sep)
                or not source.is_file()):
            raise ContractError("产物必须是工作区内已存在的文件")
        body = source.read_bytes()
        sha256 = hashlib.sha256(body).hexdigest()
        with self.repository.connect() as connection:
            existing = connection.execute(
                "SELECT name,ref,meta_json FROM artifacts WHERE employee_run_id=? "
                "ORDER BY id", (self.employee_run_id,)).fetchall()
        for row in existing:
            meta = json.loads(row["meta_json"])
            if meta.get("path") == relative and meta.get("sha256") == sha256:
                return dict({"name": row["name"], "ref": row["ref"]}, **meta)
        directory = Path(self.repository.path).resolve().parent / "artifacts" / str(self.employee_run_id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "{}-{}".format(sha256[:12], source.name)
        if not destination.exists():
            shutil.copyfile(source, destination)
        item = {"name": str(title or source.name), "ref": str(destination),
                "path": relative, "sha256": sha256, "size": len(body),
                "content_model": self._content_model_for_path(relative)}
        with self.repository.connect() as connection:
            connection.execute(
                "INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) VALUES(?,?,?,?,?)",
                (self.employee_run_id, item["name"], item["ref"],
                 json.dumps({"path": relative, "sha256": sha256, "size": len(body),
                             "content_model": item["content_model"]},
                            ensure_ascii=False), utc_now()))
            self.repository.event(self.stream, "artifact.published", item, connection=connection)
        return item

    def _artifacts(self):
        with self.repository.connect() as connection:
            rows = connection.execute("SELECT name,ref,meta_json FROM artifacts WHERE employee_run_id=?",
                                      (self.employee_run_id,)).fetchall()
        return [dict({"name": row["name"], "ref": row["ref"]},
                     **json.loads(row["meta_json"])) for row in rows]

    def _workspace_digest(self):
        value = hashlib.sha256()
        for path in sorted(self.workspace.rglob("*")):
            relative = path.relative_to(self.workspace)
            if not relative.parts or relative.parts[0] == ".runteams" or not path.is_file():
                continue
            name = relative.as_posix().encode("utf-8")
            body = path.read_bytes()
            value.update(len(name).to_bytes(4, "big"))
            value.update(name)
            value.update(len(body).to_bytes(8, "big"))
            value.update(body)
        return value.hexdigest()


def tool_definitions(protocol):
    task = protocol.task()
    step_ids = [item["id"] for item in task["employee"]["program"]["steps"]]
    capability_refs = [item["ref"] for item in task["capabilities"] if item["kind"] == "tool"]
    return [
        {"name": "get_task", "description": "读取工作单、员工程序和冻结能力。必须最先调用。",
         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "report_progress", "description": "汇报有意义的工作进展。",
         "inputSchema": {"type": "object", "properties": {
             "summary": {"type": "string"}, "percent": {"type": "integer", "minimum": 0,
                                                         "maximum": 100}},
             "required": ["summary"], "additionalProperties": False}},
        {"name": "advance_step", "description": "按员工程序顺序提交完成的步骤。",
         "inputSchema": {"type": "object", "properties": {
             "step_id": {"type": "string", "enum": step_ids}, "summary": {"type": "string"}},
             "required": ["step_id", "summary"], "additionalProperties": False}},
        {"name": "run_capability", "description": (
            "运行员工发布版本中冻结的确定性工具。effect=operation 时必须提供稳定的 "
            "invocation_id；重试同一操作必须复用该 ID。"),
         "inputSchema": {"type": "object", "properties": {
             "capability_ref": {"type": "string", "enum": capability_refs},
             "arguments": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
             "invocation_id": {"type": "string", "minLength": 1, "maxLength": 120,
                               "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$"}},
             "required": ["capability_ref", "arguments"], "additionalProperties": False}},
        {"name": "publish_artifact", "description": "发布工作区中的最终文件。工作单 expected_output.documents 里声明的文档会在提交时自动登记，这里只用于登记额外产出。",
         "inputSchema": {"type": "object", "properties": {
             "path": {"type": "string"}, "title": {"type": "string"}},
             "required": ["path", "title"], "additionalProperties": False}},
        {"name": "complete", "description": "提交结构化工作结果并结束运行。",
         "inputSchema": {"type": "object", "properties": {
             "summary": {"type": "string"}, "output": {"type": "object"}},
             "required": ["summary", "output"], "additionalProperties": False}},
        {"name": "request_human", "description": "缺少用户决定或信息时暂停。",
         "inputSchema": {"type": "object", "properties": {
             "question": {"type": "string"}, "context": {"type": "string"}},
             "required": ["question"], "additionalProperties": False}},
        {"name": "report_blocked", "description": "报告无法自行解除的客观阻塞。",
         "inputSchema": {"type": "object", "properties": {
             "reason": {"type": "string"}, "recovery": {"type": "string"}},
             "required": ["reason"], "additionalProperties": False}},
        {"name": "report_failed", "description": "报告能力或运行环境导致的技术失败。",
         "inputSchema": {"type": "object", "properties": {
             "reason": {"type": "string"}, "recovery": {"type": "string"}},
             "required": ["reason"], "additionalProperties": False}},
    ]


def dispatch(protocol, message):
    method, request_id = message.get("method"), message.get("id")
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion") or "2024-11-05"
        result = {"protocolVersion": requested, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "runteams", "version": "2.0.0"},
                  "instructions": "先调用 get_task，并用一个终态工具结束运行。"}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_definitions(protocol)}
    elif method == "tools/call":
        params = message.get("params") or {}
        result = protocol.call(params.get("name"), params.get("arguments") or {})
    else:
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "Method not found"}}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main(database, employee_run_id, workspace, credential_resolver=None):
    protocol = EmployeeProtocol(database, employee_run_id, workspace,
                                credential_resolver=credential_resolver)
    for line in sys.stdin:
        message = None
        try:
            message = json.loads(line)
            response = dispatch(protocol, message)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            request_id = message.get("id") if isinstance(message, dict) else None
            if request_id is not None:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32603, "message": str(exc)}}, ensure_ascii=False) + "\n")
                sys.stdout.flush()
