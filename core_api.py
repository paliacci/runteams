"""HTTP-facing control plane for the employee/package kernel.

This module owns the new core database and its bounded local executors.  It
does not read or synchronize unrelated data-domain rows.
"""

from pathlib import Path
import copy
import threading
import time
import uuid

from runteams_core import ContractError, DocumentLossError, RunTeamsCore
from runteams_core.agent_runtime import AgentEmployeeRuntime, SYSTEM_INSTRUCTION
from runteams_core import task_inputs
from employee_repair import AgentEmployeeRepairRuntime


class CoreController:
    def __init__(self, root, runtime_factory=None, poll_seconds=0.5,
                 credential_names_provider=None, credential_vault_path=None,
                 channel_resolver=None, native_dependency_resolver=None,
                 worker_count=10, repair_runtime_factory=None):
        self.root = Path(root).resolve()
        self.credential_names_provider = credential_names_provider
        self.core = RunTeamsCore(
            self.root, credential_names_provider=credential_names_provider,
            native_dependency_resolver=native_dependency_resolver)
        self.runtime_factory = runtime_factory or (lambda: AgentEmployeeRuntime(
            self.root, channel_resolver=channel_resolver,
            native_dependency_resolver=native_dependency_resolver,
            credential_vault_path=credential_vault_path))
        self.repair_runtime_factory = repair_runtime_factory or (
            lambda: AgentEmployeeRepairRuntime(
                self.root, channel_resolver=channel_resolver))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.worker_count = max(1, min(10, int(worker_count)))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads = []
        self._active_lock = threading.Lock()
        self._active_workflow_ids = set()
        self._active_repair_ids = set()

    @property
    def running(self):
        return any(thread.is_alive() for thread in self._threads)

    @property
    def active_workflow_ids(self):
        with self._active_lock:
            return sorted(self._active_workflow_ids)

    @property
    def active_workflow_id(self):
        """Compatibility view for older status consumers."""
        active = self.active_workflow_ids
        return active[0] if active else None

    @property
    def active_repair_ids(self):
        with self._active_lock:
            return sorted(self._active_repair_ids)

    def start(self):
        if self.running:
            return []
        recovered = self.core.recover_interrupted_workflows()
        self.core.recover_interrupted_repairs()
        self._stop.clear()
        self._wake.clear()
        self._threads = [
            threading.Thread(
                target=self._loop, name="runteams-core-executor-{}".format(index + 1),
                daemon=True)
            for index in range(self.worker_count)
        ]
        for thread in self._threads:
            thread.start()
        return recovered

    def stop(self, timeout=15):
        self._stop.set()
        for workflow_run_id in self.active_workflow_ids:
            self.core.interrupt_workflow(workflow_run_id)
        self._wake.set()
        deadline = time.monotonic() + max(0, float(timeout))
        for thread in self._threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        self._threads = [thread for thread in self._threads if thread.is_alive()]

    def wake(self):
        self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            self.core.refresh_employee_repairs()
            repair = self.core.claim_employee_repair()
            if repair is not None:
                with self._active_lock:
                    self._active_repair_ids.add(repair["id"])
                try:
                    self.core.execute_employee_repair(
                        repair, self.repair_runtime_factory())
                    self._wake.set()
                except Exception:
                    pass
                finally:
                    with self._active_lock:
                        self._active_repair_ids.discard(repair["id"])
                continue
            workflow_run_id = self.core.claim_workflow()
            if workflow_run_id is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            with self._active_lock:
                self._active_workflow_ids.add(workflow_run_id)
            try:
                self.core.execute_claimed_workflow(
                    workflow_run_id, self.runtime_factory(), max_attempts=3,
                    retry_delay_sec=5)
            except Exception as exc:
                self.core.repository.event(
                    "workflow_run:{}".format(workflow_run_id), "workflow.executor_error",
                    {"message": str(exc)[:2000]})
                self.core.recover_interrupted_workflow(workflow_run_id)
            finally:
                with self._active_lock:
                    self._active_workflow_ids.discard(workflow_run_id)

    def overview(self):
        return {
            "packages": self.package_catalog(),
            "employees": self.employee_catalog(),
            "pipelines": self.core.pipeline_catalog(),
            "workflows": self.core.workflow_catalog(),
            "executor": {"running": self.running,
                         "worker_count": self.worker_count,
                         "active_workflow_ids": self.active_workflow_ids,
                         "active_repair_ids": self.active_repair_ids},
        }

    def board_overview(self):
        """Return the local facts needed to render and refresh pipeline boards.

        Employee validation and credential coverage are intentionally omitted here:
        they are expensive derived detail for the employee editor, not live board
        state.  The editor still loads the normal employee endpoint on demand.
        """
        employees = self.core.employee_catalog()
        for employee in employees:
            employee["summary_only"] = True
        return {
            "packages": self.package_catalog(),
            "employees": employees,
            "pipelines": self.core.pipeline_catalog(),
            "workflows": self.core.workflow_catalog(),
            "executor": {"running": self.running,
                         "worker_count": self.worker_count,
                         "active_workflow_ids": self.active_workflow_ids,
                         "active_repair_ids": self.active_repair_ids},
        }

    def _available_credentials(self):
        return (set(self.credential_names_provider() or [])
                if self.credential_names_provider is not None else set())

    def _decorate_package(self, package):
        if package is None:
            return None
        item = copy.deepcopy(package)
        available = self._available_credentials()
        for capability in (item.get("manifest_json") or {}).get("capabilities") or []:
            required = capability.get("credentials") or []
            missing = [name for name in required if name not in available]
            capability["credential_status"] = {
                "required": required, "missing": missing,
                "ready": not missing if self.credential_names_provider is not None else not required,
            }
        return item

    def _decorate_employee(self, employee):
        if employee is None:
            return None
        item = copy.deepcopy(employee)
        snapshot = (item.get("active_release") or {}).get("snapshot_json") or {}
        required = self.core.required_credentials(snapshot)
        available = self._available_credentials()
        missing = [name for name in required if name not in available]
        item["credential_status"] = {
            "required": required, "missing": missing,
            "ready": not missing if self.credential_names_provider is not None else not required,
        }
        trials = self.core.employee_trials(item["id"])
        item["validation"] = self.core.employee_coverage(item, trials=trials)
        return item

    def package_catalog(self):
        return [self._decorate_package(item) for item in self.core.package_catalog()]

    def package_detail(self, package_id, verify=False):
        return self._decorate_package(self.core.package_detail(package_id, verify=verify))

    def package_file(self, package_id, relative_path):
        return self.core.package_file(package_id, relative_path)

    def package_impact(self, package_id):
        return self.core.package_impact(package_id)

    def employee_catalog(self):
        return [self._decorate_employee(item) for item in self.core.employee_catalog()]

    def employee(self, employee_id):
        return self._decorate_employee(self.core.employee(employee_id))

    def create_task(self, pipeline_id, title, payload, start_column_key=None,
                    input_tokens=None):
        task_id = self.core.create_task(
            pipeline_id, title, payload, start_column_key=start_column_key)
        try:
            tokens = list(input_tokens or [])
            if tokens:
                self.core.set_task_inputs(
                    task_id, task_inputs.consume(self.root, task_id, tokens))
            workflow_run_id = self.core.start_workflow(task_id)
        except Exception:
            self.core.delete_unstarted_task(task_id)
            raise
        self.wake()
        return {"task": self.core.task(task_id),
                "workflow": self.core.workflow(workflow_run_id)}

    def append_workflow_task_inputs(self, workflow_run_id, input_tokens):
        task = self.core.workflow_task_for_inputs(workflow_run_id)
        task_id = int(task["id"])
        added = task_inputs.consume(self.root, task_id, input_tokens or [])
        try:
            return self.core.append_workflow_task_inputs(workflow_run_id, added)
        except Exception:
            for item in added:
                try:
                    task_inputs.remove(self.root, task_id, item.get("id"))
                except ValueError:
                    pass
            raise

    def remove_workflow_task_input(self, workflow_run_id, input_id):
        workflow, task_id, _removed = self.core.remove_workflow_task_input(
            workflow_run_id, input_id)
        try:
            task_inputs.remove(self.root, task_id, input_id)
        except ValueError:
            pass
        return workflow


def _id(match):
    return int(match.group(1))


def get_payload(controller, path, query, re_module):
    core = controller.core
    if path == "/api/core/overview":
        return controller.overview(), 200
    if path == "/api/core/board-overview":
        return controller.board_overview(), 200
    if path == "/api/core/packages":
        return {"packages": controller.package_catalog()}, 200
    match = re_module.match(r"^/api/core/packages/(\d+)/file$", path)
    if match:
        item = controller.package_file(_id(match), (query.get("path") or [""])[0])
        return (item if item else {"error": "能力包不存在"}), (200 if item else 404)
    match = re_module.match(r"^/api/core/packages/(\d+)$", path)
    if match:
        item = controller.package_detail(_id(match))
        return (item if item else {"error": "能力包不存在"}), (200 if item else 404)
    match = re_module.match(r"^/api/core/packages/(\d+)/impact$", path)
    if match:
        return controller.package_impact(_id(match)), 200
    if path == "/api/core/employees":
        return {"employees": controller.employee_catalog()}, 200
    match = re_module.match(r"^/api/core/employees/(\d+)/trials$", path)
    if match:
        employee_id = _id(match)
        repair = core.employee_repair_status(employee_id)
        employee = core.employee(employee_id)
        if (repair and repair.get("state") == "validating" and
                repair.get("candidate_draft")):
            employee = copy.deepcopy(employee)
            employee["draft_json"] = copy.deepcopy(repair["candidate_draft"])
            trials = core.employee_trials(
                employee_id, candidate_digest=repair.get("candidate_digest"))
        else:
            trials = core.employee_trials(employee_id)
        public_repair = ({key: repair.get(key) for key in (
            "id", "state", "phase", "message", "workflow_ids",
            "failed_test_ids", "created_at", "updated_at")}
            if repair else None)
        return {"trials": trials,
                "coverage": core.employee_coverage(employee, trials=trials),
                "repair": public_repair}, 200
    match = re_module.match(r"^/api/core/employees/(\d+)/system-instruction$", path)
    if match:
        employee = core.employee(_id(match))
        if employee is None:
            return {"error": "员工不存在"}, 404
        snapshot = ((employee.get("active_release") or {}).get("snapshot_json")
                    or employee.get("draft_json") or {})
        return {"instruction": SYSTEM_INSTRUCTION, "employee": snapshot}, 200
    match = re_module.match(r"^/api/core/employees/(\d+)$", path)
    if match:
        item = controller.employee(_id(match))
        return (item if item else {"error": "员工不存在"}), (200 if item else 404)
    if path == "/api/core/pipelines":
        return {"pipelines": core.pipeline_catalog()}, 200
    match = re_module.match(r"^/api/core/pipelines/(\d+)/check$", path)
    if match:
        return core.pipeline_check(_id(match)), 200
    match = re_module.match(r"^/api/core/pipelines/(\d+)$", path)
    if match:
        item = core.pipeline(_id(match))
        return (item if item else {"error": "流水线不存在"}), (200 if item else 404)
    match = re_module.match(r"^/api/core/artifacts/(\d+)/revisions$", path)
    if match:
        return {"revisions": core.document_revisions(_id(match))}, 200
    match = re_module.match(r"^/api/core/documents/(\d+)$", path)
    if match:
        item = core.document_detail(_id(match), include_content=True)
        return (item if item else {"error": "文档不存在"}), (200 if item else 404)
    match = re_module.match(r"^/api/core/artifacts/(\d+)/styles$", path)
    if match:
        item = core.document_detail(_id(match), include_content=False)
        return ({"styles": item.get("editor_styles") or {}} if item else {"error": "文档不存在"}), (200 if item else 404)
    if path == "/api/core/documents":
        raw_limit = (query.get("limit") or ["500"])[0]
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 500
        return {"documents": core.document_catalog(
            limit, (query.get("q") or [""])[0])}, 200
    if path == "/api/core/opportunities":
        raw_limit = (query.get("limit") or ["0"])[0]
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 0
        if limit < 0:
            return {"error": "机会目录 limit 不能小于 0"}, 400
        opportunities = core.opportunity_catalog(
            (query.get("q") or [""])[0], limit)
        return {"opportunities": opportunities,
                "count": len(opportunities),
                # The service always scans and filters the complete identity
                # ledger before applying a positive presentation limit.
                "complete_scan": not bool(limit)}, 200
    if path == "/api/core/opportunity":
        key = (query.get("key") or [""])[0]
        item = core.opportunity_detail(key)
        return (item if item else {"error": "机会不存在"}), (200 if item else 404)
    if path == "/api/core/workflows":
        raw_limit = (query.get("limit") or ["100"])[0]
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 100
        return {"workflows": core.workflow_catalog(limit)}, 200
    match = re_module.match(r"^/api/core/workflows/(\d+)$", path)
    if match:
        item = core.workflow(_id(match))
        return (item if item else {"error": "运行不存在"}), (200 if item else 404)
    match = re_module.match(r"^/api/core/audit/(pipeline|task|workflow|employee)/(\d+)$", path)
    if match:
        item = core.audit_timeline(match.group(1), _id(match))
        return (item if item else {"error": "审计对象不存在"}), (200 if item else 404)
    return None


def post_payload(controller, path, data, re_module):
    core = controller.core
    if path == "/api/core/documents":
        item = core.create_agent_document(
            data.get("name"), data.get("content"),
            document_key=data.get("document_key"),
            data_view=data.get("data_view"), note=data.get("note", ""))
        return item, 201
    match = re_module.match(r"^/api/core/documents/(\d+)$", path)
    if match:
        item = core.update_agent_document(
            _id(match), name=data.get("name"), content=data.get("content"),
            data_view=data.get("data_view"), note=data.get("note", ""))
        return item, 200
    if path == "/api/core/packages/inspect":
        source = str(data.get("path") or "").strip()
        if not source:
            raise ContractError("请选择能力包目录")
        return core.inspect_package(source), 200
    if path == "/api/core/packages/import":
        source = str(data.get("path") or "").strip()
        if not source:
            raise ContractError("请选择能力包目录")
        confirmed_digest = str(data.get("confirmed_digest") or "").strip()
        if not confirmed_digest:
            raise ContractError("请先检查能力包内容")
        imported = core.import_package(
            data.get("key"), source, confirmed_digest=confirmed_digest)
        return imported, 201
    match = re_module.match(r"^/api/core/packages/(\d+)/verify$", path)
    if match:
        item = controller.package_detail(_id(match), verify=True)
        return (item if item else {"error": "能力包不存在"}), (200 if item else 404)
    match = re_module.match(r"^/api/core/packages/(\d+)/(disable|enable)$", path)
    if match:
        item = (core.disable_package(_id(match)) if match.group(2) == "disable"
                else core.enable_package(_id(match)))
        return item, 200
    if path == "/api/core/employees":
        employee_id = core.create_employee(
            data.get("name"), data.get("draft"), avatar=data.get("avatar") or "a1")
        return core.employee(employee_id), 201
    match = re_module.match(r"^/api/core/employees/(\d+)$", path)
    if match:
        return core.update_employee(
            _id(match), data.get("name"), data.get("draft"),
            avatar=data.get("avatar")), 200
    match = re_module.match(r"^/api/core/employees/(\d+)/publish$", path)
    if match:
        return core.publish_employee(_id(match)), 200
    match = re_module.match(r"^/api/core/employees/(\d+)/trials/run-all$", path)
    if match:
        items = core.start_all_employee_trials(_id(match))
        controller.wake()
        return {"trials": items}, 201
    match = re_module.match(r"^/api/core/employees/(\d+)/repair$", path)
    if match:
        item = core.start_employee_repair(_id(match))
        controller.wake()
        return item, 202
    match = re_module.match(r"^/api/core/employees/(\d+)/trials/([a-z][a-z0-9-]{0,79})$", path)
    if match:
        items = core.start_employee_trial_samples(_id(match), match.group(2), fresh=True)
        controller.wake()
        return {"trials": items}, 201
    match = re_module.match(
        r"^/api/core/employees/(\d+)/(duplicate|discard|trash|restore|delete)$", path)
    if match:
        employee_id, action = _id(match), match.group(2)
        if action == "duplicate":
            return core.duplicate_employee(employee_id), 201
        if action == "discard":
            return core.discard_employee_draft(employee_id), 200
        if action == "trash":
            return core.trash_employee(employee_id), 200
        if action == "restore":
            return core.restore_employee(employee_id), 200
        core.delete_trashed_employee(
            employee_id, acknowledged_documents=data.get("acknowledged_documents"))
        return {"ok": True}, 200
    match = re_module.match(r"^/api/core/artifacts/(\d+)/revert$", path)
    if match:
        # 恢复旧版本：内容从服务器上那一版直接读，显式开新的一版，不并进当前那一版
        new_id = core.revert_document(_id(match))
        artifact = core.artifact(new_id) or {}
        return {"id": new_id, "created_revision": True,
                "path": (artifact.get("meta_json") or {}).get("path"),
                "revisions": core.document_revisions(new_id)}, 200
    match = re_module.match(r"^/api/core/artifacts/(\d+)/revisions$", path)
    if match:
        # 显式开一版（给外部调用留的口子，产品内的恢复走 /revert）
        new_id = core.create_document_revision(
            _id(match), data.get("content"), data.get("note", ""))
        artifact = core.artifact(new_id) or {}
        return {"id": new_id, "created_revision": True,
                "path": (artifact.get("meta_json") or {}).get("path"),
                "revisions": core.document_revisions(new_id)}, 200
    match = re_module.match(r"^/api/core/artifacts/(\d+)/content$", path)
    if match:
        saved = core.save_document_edit(_id(match), data.get("content"))
        artifact = core.artifact(saved["id"]) or {}
        return {"id": saved["id"], "created_revision": saved["created_revision"],
                "path": (artifact.get("meta_json") or {}).get("path"),
                "revisions": core.document_revisions(saved["id"])}, 200
    match = re_module.match(r"^/api/core/artifacts/(\d+)/styles$", path)
    if match:
        styles = core.save_document_block_style(_id(match), data.get("style"))
        return {"styles": styles}, 200
    match = re_module.match(r"^/api/core/artifacts/(\d+)/(trash|restore|delete)$", path)
    if match:
        artifact_id, action = _id(match), match.group(2)
        if action == "trash":
            core.trash_document(artifact_id)
        elif action == "restore":
            core.restore_document(artifact_id)
        else:
            core.delete_trashed_document(artifact_id)
        return {"ok": True}, 200
    if path == "/api/core/pipelines":
        pipeline_id = core.create_pipeline(data.get("name"), data.get("definition"))
        return core.pipeline(pipeline_id), 201
    match = re_module.match(r"^/api/core/pipelines/(\d+)$", path)
    if match:
        return core.update_pipeline(
            _id(match), data.get("name"), data.get("definition")), 200
    match = re_module.match(r"^/api/core/pipelines/(\d+)/positions/trash$", path)
    if match:
        return core.trash_pipeline_position(_id(match), data.get("position_key")), 200
    match = re_module.match(
        r"^/api/core/pipeline-positions/(\d+)/(restore|delete)$", path)
    if match:
        trash_id, action = _id(match), match.group(2)
        if action == "restore":
            return core.restore_pipeline_position(trash_id), 200
        core.delete_trashed_pipeline_position(
            trash_id, acknowledged_documents=data.get("acknowledged_documents"))
        return {"ok": True}, 200
    match = re_module.match(
        r"^/api/core/pipelines/(\d+)/(pause|resume|trash|restore|delete)$", path)
    if match:
        pipeline_id, action = _id(match), match.group(2)
        if action == "pause":
            return core.pause_pipeline(pipeline_id), 200
        if action == "resume":
            item = core.resume_pipeline(pipeline_id)
            controller.wake()
            return item, 200
        if action == "trash":
            return core.trash_pipeline(pipeline_id), 200
        if action == "restore":
            return core.restore_pipeline(pipeline_id), 200
        core.delete_trashed_pipeline(
            pipeline_id, acknowledged_documents=data.get("acknowledged_documents"))
        return {"ok": True}, 200
    if path == "/api/core/tasks":
        return controller.create_task(
            data.get("pipeline_id"), data.get("title"), data.get("payload") or {},
            start_column_key=data.get("start_column_key"),
            input_tokens=data.get("input_tokens") or []), 201
    match = re_module.match(r"^/api/core/workflows/(\d+)/inputs$", path)
    if match:
        return controller.append_workflow_task_inputs(
            _id(match), data.get("input_tokens") or []), 200
    match = re_module.match(
        r"^/api/core/workflows/(\d+)/inputs/([a-f0-9]{24})/remove$", path)
    if match:
        return controller.remove_workflow_task_input(
            int(match.group(1)), match.group(2)), 200
    match = re_module.match(
        r"^/api/core/workflows/(\d+)/(cancel|retry|respond|approve|reject|rename|update|move|trash|restore|delete)$", path)
    if match:
        workflow_run_id, action = int(match.group(1)), match.group(2)
        if action == "cancel":
            item = core.cancel_workflow(workflow_run_id)
        elif action == "respond":
            item = core.respond_to_human(workflow_run_id, data.get("response"))
        elif action in ("approve", "reject"):
            item = core.decide_workflow_approval(
                workflow_run_id, action == "approve", data.get("note"))
        elif action == "rename":
            item = core.rename_workflow_task(workflow_run_id, data.get("title"))
        elif action == "update":
            item = core.update_workflow_task(
                workflow_run_id, data.get("title"), data.get("objective"),
                data.get("parameters"))
        elif action == "move":
            item = core.move_workflow(workflow_run_id, data.get("column_key"))
        elif action == "trash":
            item = core.trash_workflow(workflow_run_id)
        elif action == "restore":
            item = core.restore_workflow(workflow_run_id)
        elif action == "delete":
            core.delete_trashed_workflow(
                workflow_run_id,
                acknowledged_documents=data.get("acknowledged_documents"))
            return {"ok": True}, 200
        else:
            item = core.retry_workflow(workflow_run_id)
        if action in ("retry", "respond", "approve", "reject", "move"):
            controller.wake()
        return item, 200
    return None


def safe_dispatch(callable_, controller, path, *args, audit_context=None):
    try:
        # Every HTTP dispatch gets a correlation id.  Individual business
        # events inherit it through the repository context, so one request can
        # be reconstructed even when it touches several entities.
        audit_context = audit_context if isinstance(audit_context, dict) else {}
        with controller.core.repository.audit_context(
                actor_id=audit_context.get("actor_id"),
                correlation_id=audit_context.get("correlation_id") or uuid.uuid4().hex,
                source=audit_context.get("source") or "http"):
            return callable_(controller, path, *args)
    except DocumentLossError as exc:
        return {"error": str(exc), "documents": exc.documents,
                "requires_confirmation": True}, 409
    except (ContractError, OSError, TypeError, ValueError) as exc:
        return {"error": str(exc)}, 400
