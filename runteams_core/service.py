"""Application service for packages, employees and durable structured handoffs."""

import base64
import copy
import datetime
import hashlib
import inspect
import json
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from errors import Cancelled, RateLimited, Transient

from .contracts import (ContractError, DocumentLossError, digest, employee_coverage_targets,
                        json_schema_violations, normalize_capability_references, work_order_payload,
                        normalize_employee_avatar, normalize_employee_draft,
                        normalize_employee_interface,
                        normalize_package_key,
                        normalize_pipeline_definition, normalize_work_order,
                        normalize_work_result, pipeline_order)
from .packages import PackageStore, PackageVerificationError
from .repository import Repository, utc_now
from . import task_inputs

_PLACEHOLDER_POSITION = re.compile(r"^第\s*\d+\s*岗$")


WORKFLOW_TERMINAL_STATES = ("completed", "blocked", "needs_human", "failed", "canceled")
WORKFLOW_MAX_VISITS = 50
EMPLOYEE_TRIAL_SAMPLE_COUNT = 3
PACKAGE_IMAGE_PREVIEW_MAX_BYTES = 12 * 1024 * 1024
AGENT_DOCUMENT_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
DOCUMENT_VIEW_KINDS = frozenset(("opportunities",))
DOCUMENT_VIEW_COLUMNS = frozenset((
    "title", "product", "analysis_decision", "decision_reason", "target_user",
    "jtbd", "problem", "evidence_count", "summary", "employee_name",
    "pipeline_name", "updated_at",
))


def _normalize_agent_document_key(value, fallback=""):
    """Normalize the stable user-facing key used by Agent-created documents."""
    raw = str(value or "").strip().casefold()
    raw = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-._")
    if not raw:
        raw = re.sub(r"[^a-z0-9._-]+", "-", str(fallback or "").casefold()).strip("-._")
    if not raw and str(fallback or "").strip():
        # 中文标题没有可直接落盘的 ASCII slug；用标题摘要的稳定短 hash，
        # 让 Agent 不必额外学习 document_key，同时仍保持可寻址和可复用。
        raw = "doc-{}".format(hashlib.sha256(
            str(fallback).strip().encode("utf-8")).hexdigest()[:16])
    if not raw or not AGENT_DOCUMENT_KEY.fullmatch(raw[:120]):
        raise ContractError("文档标识只能包含小写字母、数字、点、下划线和连字符")
    return raw[:120]


def _normalize_document_data_view(value):
    """Validate the small, provider-neutral data binding contract.

    The document may bind to a named product projection, never to arbitrary SQL
    or a file path.  Adding another projection later only extends this allowlist.
    """
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise ContractError("文档数据视图必须是对象")
    kind = str(value.get("kind") or "").strip().casefold()
    if kind not in DOCUMENT_VIEW_KINDS:
        raise ContractError("暂不支持这种文档数据视图")
    query = str(value.get("query") or "").strip()
    if len(query) > 240:
        raise ContractError("文档数据视图查询不能超过 240 个字符")
    raw_columns = value.get("columns")
    if raw_columns in (None, ""):
        columns = []
    elif isinstance(raw_columns, list):
        columns = []
        for column in raw_columns:
            name = str(column or "").strip()
            if name not in DOCUMENT_VIEW_COLUMNS:
                raise ContractError("文档数据视图包含未知字段：{}".format(name or "(空)"))
            if name not in columns:
                columns.append(name)
        if len(columns) > 12:
            raise ContractError("文档数据视图最多展示 12 个字段")
    else:
        raise ContractError("文档数据视图字段必须是数组")
    return {"kind": kind, "query": query, "columns": columns}


def _package_image_media_type(body):
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if body.startswith(b"RIFF") and len(body) >= 12 and body[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _utc_after(seconds):
    value = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
    return value.isoformat(timespec="seconds")


def _rate_limit_available_at(message):
    """Parse the reset shape emitted by current Agent CLIs; otherwise back off safely."""
    match = re.search(
        r"resets?\s+([A-Za-z]{3})\s+(\d{1,2})\s+at\s+(\d{1,2})"
        r"(?::(\d{2}))?\s*(am|pm)(?:\s*\(([^)]+)\))?", str(message or ""), re.I)
    if not match:
        return _utc_after(15 * 60)
    months = {name.lower(): index for index, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
    month = months.get(match.group(1).lower())
    if month is None:
        return _utc_after(15 * 60)
    try:
        zone = ZoneInfo(match.group(6)) if match.group(6) else datetime.datetime.now().astimezone().tzinfo
    except ZoneInfoNotFoundError:
        zone = datetime.timezone.utc
    now = datetime.datetime.now(datetime.timezone.utc)
    hour = int(match.group(3)) % 12 + (12 if match.group(5).lower() == "pm" else 0)
    try:
        candidate = datetime.datetime(
            now.astimezone(zone).year, month, int(match.group(2)), hour,
            int(match.group(4) or 0), tzinfo=zone).astimezone(datetime.timezone.utc)
        if candidate <= now:
            candidate = candidate.replace(year=candidate.year + 1)
    except ValueError:
        return _utc_after(15 * 60)
    if candidate - now > datetime.timedelta(days=45):
        return _utc_after(15 * 60)
    return candidate.isoformat(timespec="seconds")


class RunTeamsCore:
    def __init__(self, root, credential_names_provider=None,
                 native_dependency_resolver=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.repository = Repository(self.root / "runteams.db")
        self.packages = PackageStore(self.root / "packages")
        self.credential_names_provider = credential_names_provider
        self.native_dependency_resolver = native_dependency_resolver
        self._cancel_events = {}
        self._cancel_lock = threading.Lock()
        self._trial_start_lock = threading.RLock()
        self._repair_claim_lock = threading.Lock()
        self.repository.initialize()

    def _native_dependency(self, provider, plugin_id, refresh=False):
        if self.native_dependency_resolver is None:
            raise ContractError("当前环境不能验证模型渠道扩展")
        try:
            return self.native_dependency_resolver(
                provider, plugin_id, refresh=refresh)
        except TypeError:
            # Small embedders and tests may provide the original two-argument callable.
            return self.native_dependency_resolver(provider, plugin_id)

    def reset_workspace(self):
        """Delete all core business assets after proving no workflow is active."""
        with self.repository.connect() as connection:
            active = connection.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE state NOT IN "
                "('completed','blocked','needs_human','failed','canceled')"
            ).fetchone()[0]
            if active:
                raise ContractError("仍有运行中的任务，请先终止任务")
            counts = {
                "packages": connection.execute("SELECT COUNT(*) FROM packages").fetchone()[0],
                "employees": connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0],
                "pipelines": connection.execute("SELECT COUNT(*) FROM pipelines").fetchone()[0],
                "tasks": connection.execute(
                    "SELECT COUNT(*) FROM tasks WHERE pipeline_id IS NOT NULL").fetchone()[0],
                "workflows": connection.execute(
                    "SELECT COUNT(*) FROM workflow_runs WHERE "
                    "json_extract(snapshot_json,'$.trial') IS NULL").fetchone()[0],
                "employee_runs": connection.execute(
                    "SELECT COUNT(*) FROM employee_runs er JOIN workflow_runs wr "
                    "ON wr.id=er.workflow_run_id WHERE "
                    "json_extract(wr.snapshot_json,'$.trial') IS NULL").fetchone()[0],
                "artifacts": connection.execute(
                    "SELECT COUNT(*) FROM artifacts a JOIN employee_runs er "
                    "ON er.id=a.employee_run_id JOIN workflow_runs wr "
                    "ON wr.id=er.workflow_run_id WHERE "
                    "json_extract(wr.snapshot_json,'$.trial') IS NULL").fetchone()[0],
            }
            for table in ("artifacts", "employee_runs", "workflow_runs", "tasks", "pipelines",
                          "employee_releases", "employees", "package_revisions", "packages", "events"):
                connection.execute("DELETE FROM " + table)
        for name in ("packages", "workspaces", "artifacts", "task-inputs"):
            target = (self.root / name).resolve()
            if target.parent != self.root:
                raise ContractError("核心工作区目录不安全")
            if target.exists():
                shutil.rmtree(target)
        self.packages = PackageStore(self.root / "packages")
        with self._cancel_lock:
            self._cancel_events.clear()
        return counts

    def inspect_package(self, source):
        return self.packages.inspect_agent_skill(source)

    def import_package(self, key, source, confirmed_digest=None):
        key = normalize_package_key(key)
        prepared = self.packages.import_agent_skill(
            source, confirmed_digest=confirmed_digest)
        now = utc_now()
        with self.repository.connect() as connection:
            package = connection.execute("SELECT * FROM packages WHERE key=?", (key,)).fetchone()
            if package is None:
                package_id = connection.execute(
                    "INSERT INTO packages(key,source_json,created_at,updated_at) VALUES(?,?,?,?)",
                    (key, json.dumps({"kind": "directory", "path": str(Path(source).resolve())},
                                     ensure_ascii=False), now, now),
                ).lastrowid
            else:
                package_id = package["id"]
            existing = connection.execute(
                "SELECT * FROM package_revisions WHERE package_id=? AND digest=?",
                (package_id, prepared["digest"]),).fetchone()
            if existing is None:
                version = connection.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM package_revisions WHERE package_id=?",
                    (package_id,),).fetchone()[0]
                revision_id = connection.execute(
                    "INSERT INTO package_revisions(package_id,version,digest,manifest_json,blob_ref,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (package_id, version, prepared["digest"],
                     json.dumps(prepared["manifest"], ensure_ascii=False),
                     prepared["blob_ref"], now),).lastrowid
            else:
                revision_id, version = existing["id"], existing["version"]
            connection.execute(
                "UPDATE packages SET active_revision_id=?,source_json=?,updated_at=? WHERE id=?",
                (revision_id, json.dumps({"kind": "directory",
                                         "path": str(Path(source).resolve())}, ensure_ascii=False),
                 now, package_id))
        result = {"package_id": package_id, "revision_id": revision_id, "version": version,
                  **prepared}
        self.repository.event("package_revision:{}".format(revision_id), "package.verified",
                              {"status": "verified", "checks": prepared["checks"],
                               "digest": prepared["digest"],
                               "runner": self.packages.verification_runner()})
        return result

    def package(self, package_id):
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT p.*,r.id AS revision_id,r.version,r.digest,r.manifest_json,r.blob_ref,"
                "r.created_at AS revision_created_at "
                "FROM packages p LEFT JOIN package_revisions r ON r.id=COALESCE("
                "p.active_revision_id,(SELECT latest.id FROM package_revisions latest "
                "WHERE latest.package_id=p.id ORDER BY latest.version DESC LIMIT 1)) WHERE p.id=?",
                (int(package_id),),).fetchone()
        item = self.repository.decode(row, "source_json", "manifest_json")
        if item is not None:
            item["enabled"] = item.get("active_revision_id") is not None
        return item

    def package_detail(self, package_id, verify=False):
        package = self.package(package_id)
        if package is None:
            return None
        revision_id = package["active_revision_id"] or package["revision_id"]
        if verify:
            if not package["enabled"]:
                raise ContractError("能力包已停用，请先重新启用")
            stream = "package_revision:{}".format(revision_id)
            try:
                checks = self.packages.verify_manifest(
                    package["blob_ref"], package["manifest_json"])
            except (ContractError, OSError, TypeError, ValueError) as exc:
                self.repository.event(
                    stream, "package.verification_failed",
                    {"status": "failed",
                     "checks": (exc.checks if isinstance(exc, PackageVerificationError) else []),
                     "digest": package["digest"],
                     "runner": self.packages.verification_runner(), "error": str(exc)})
            else:
                self.repository.event(
                    stream, "package.verified",
                    {"status": "verified", "checks": checks, "digest": package["digest"],
                     "runner": self.packages.verification_runner()})
        events = self.repository.events(
            "package_revision:{}".format(revision_id))
        latest = next((item for item in reversed(events) if item["type"] in
                       ("package.verified", "package.verification_failed")), None)
        package["verification"] = ({"status": latest["data_json"].get("status") or
                                              ("verified" if latest["type"] == "package.verified"
                                               else "failed"),
                                    "checked_at": latest["created_at"],
                                    "runner": latest["data_json"].get("runner") or
                                              "RunTeams managed runtime",
                                    "checks": latest["data_json"].get("checks") or [],
                                    "error": latest["data_json"].get("error") or ""}
                                   if latest else {"status": "unverified", "checks": []})
        return package

    def package_file(self, package_id, relative_path):
        """Read one manifest-listed file from the package's immutable object."""
        package = self.package(package_id)
        if package is None:
            return None
        requested = str(relative_path or "").strip().replace("\\", "/")
        manifest_files = (package.get("manifest_json") or {}).get("files") or []
        metadata = next((item for item in manifest_files
                         if item.get("path") == requested), None)
        if metadata is None:
            raise ContractError("能力包文件不存在")
        root = Path(package["blob_ref"]).resolve()
        path = (root / requested).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ContractError("能力包文件路径无效") from exc
        if not path.is_file():
            raise ContractError("能力包文件不可用")
        body = path.read_bytes()
        actual_digest = hashlib.sha256(body).hexdigest()
        if actual_digest != metadata.get("sha256") or len(body) != int(metadata.get("size") or 0):
            raise ContractError("能力包不可变文件与清单不一致")
        text = None
        image_media_type = _package_image_media_type(body)
        if not image_media_type and b"\x00" not in body:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                pass
        preview_limit = 1024 * 1024
        if image_media_type:
            if len(body) > PACKAGE_IMAGE_PREVIEW_MAX_BYTES:
                return {"path": requested, "size": len(body), "sha256": actual_digest,
                        "kind": "large", "content": "", "truncated": False}
            return {"path": requested, "size": len(body), "sha256": actual_digest,
                    "kind": "image", "media_type": image_media_type,
                    "content": base64.b64encode(body).decode("ascii"), "truncated": False}
        return {
            "path": requested,
            "size": len(body),
            "sha256": actual_digest,
            "kind": "text" if text is not None else "binary",
            "content": (text[:preview_limit] if text is not None else ""),
            "truncated": bool(text is not None and len(text) > preview_limit),
        }

    def package_catalog(self):
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM packages ORDER BY key")]
        return [self.package_detail(package_id) for package_id in ids]

    @staticmethod
    def _snapshot_uses_package(snapshot, package_key):
        return any(item.get("package_key") == package_key
                   for item in (snapshot or {}).get("capabilities") or [])

    def _package_impact(self, connection, package_id):
        package = connection.execute(
            "SELECT id,key,active_revision_id FROM packages WHERE id=?",
            (int(package_id),)).fetchone()
        if package is None:
            raise ContractError("能力包不存在")
        employees, employee_ids = [], set()
        rows = connection.execute(
            "SELECT e.id,e.name,e.draft_json,r.version AS release_version,"
            "r.snapshot_json AS release_snapshot FROM employees e "
            "LEFT JOIN employee_releases r ON r.id=e.active_release_id ORDER BY e.name,e.id"
        ).fetchall()
        for row in rows:
            draft = json.loads(row["draft_json"])
            draft_uses = any(int(item.get("package_id") or 0) == int(package_id)
                             for item in draft.get("capabilities") or [])
            release_snapshot = (json.loads(row["release_snapshot"])
                                if row["release_snapshot"] else {})
            release_uses = self._snapshot_uses_package(release_snapshot, package["key"])
            if not draft_uses and not release_uses:
                continue
            employee_ids.add(row["id"])
            employees.append({"id": row["id"], "name": row["name"],
                              "draft": draft_uses, "published": release_uses,
                              "release_version": row["release_version"] if release_uses else None})
        pipelines = []
        for row in connection.execute(
                "SELECT id,name,definition_json FROM pipelines "
                "WHERE trashed_at IS NULL ORDER BY name,id").fetchall():
            definition = json.loads(row["definition_json"])
            if any(int(position.get("employee_id") or 0) in employee_ids
                   for position in definition.get("positions") or []):
                pipelines.append({"id": row["id"], "name": row["name"]})
        workflows = []
        active_states = ("completed", "blocked", "needs_human", "failed", "canceled")
        placeholders = ",".join("?" for _ in active_states)
        rows = connection.execute(
            "SELECT wr.id,wr.state,wr.snapshot_json,t.title FROM workflow_runs wr "
            "JOIN tasks t ON t.id=wr.task_id WHERE wr.state NOT IN ({}) "
            "ORDER BY wr.id DESC".format(placeholders), active_states).fetchall()
        for row in rows:
            snapshot = json.loads(row["snapshot_json"])
            positions = ((snapshot.get("definition") or {}).get("positions") or [])
            if any(self._snapshot_uses_package(position.get("employee") or {}, package["key"])
                   for position in positions):
                workflows.append({"id": row["id"], "title": row["title"],
                                  "state": row["state"]})
        return {"package_id": package["id"], "enabled": package["active_revision_id"] is not None,
                "employees": employees, "pipelines": pipelines, "workflows": workflows,
                "can_disable": not employees}

    def package_impact(self, package_id):
        with self.repository.connect() as connection:
            return self._package_impact(connection, package_id)

    def disable_package(self, package_id):
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            impact = self._package_impact(connection, package_id)
            if not impact["enabled"]:
                return impact
            if not impact["can_disable"]:
                raise ContractError("请先从受影响员工草稿中移除能力，并发布不再引用它的新版本")
            package = connection.execute(
                "SELECT key,active_revision_id FROM packages WHERE id=?", (int(package_id),)
            ).fetchone()
            connection.execute(
                "UPDATE packages SET active_revision_id=NULL,updated_at=? WHERE id=?",
                (utc_now(), int(package_id)))
            self.repository.event(
                "package:{}".format(int(package_id)), "package.disabled",
                {"key": package["key"], "revision_id": package["active_revision_id"]},
                connection=connection)
        return self.package_impact(package_id)

    def enable_package(self, package_id):
        package = self.package(package_id)
        if package is None:
            raise ContractError("能力包不存在")
        if package["enabled"]:
            return self.package_detail(package_id)
        checks = self.packages.verify_manifest(package["blob_ref"], package["manifest_json"])
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT id FROM package_revisions WHERE package_id=? ORDER BY version DESC LIMIT 1",
                (int(package_id),)).fetchone()
            if latest is None:
                raise ContractError("能力包没有可重新启用的版本")
            if latest["id"] != package["revision_id"]:
                raise ContractError("能力包版本已更新，请重试重新启用")
            changed = connection.execute(
                "UPDATE packages SET active_revision_id=?,updated_at=? "
                "WHERE id=? AND active_revision_id IS NULL",
                (latest["id"], now, int(package_id))).rowcount
            if changed:
                self.repository.event(
                    "package_revision:{}".format(latest["id"]), "package.verified",
                    {"status": "verified", "checks": checks, "digest": package["digest"],
                     "runner": self.packages.verification_runner()}, connection=connection)
                self.repository.event(
                    "package:{}".format(int(package_id)), "package.enabled",
                    {"revision_id": latest["id"]}, connection=connection)
        return self.package_detail(package_id)

    def create_employee(self, name, draft, avatar="a1"):
        normalized = normalize_employee_draft(draft)
        name = str(name or "").strip()
        if not name:
            raise ContractError("员工名称不能为空")
        avatar = normalize_employee_avatar(avatar)
        now = utc_now()
        with self.repository.connect() as connection:
            employee_id = connection.execute(
                "INSERT INTO employees(name,avatar,draft_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?)",
                (name, avatar, json.dumps(normalized, ensure_ascii=False), now, now),
            ).lastrowid
            self.repository.event(
                "employee:{}".format(employee_id), "employee.created",
                {"employee_id": employee_id, "after": {
                    "name": name, "avatar": avatar, "draft": normalized,
                    "active_release_id": None, "trashed_at": None}},
                connection=connection)
        return employee_id

    @staticmethod
    def _employee_test_spec(draft):
        """Return the finalized job contract from which validation cases are derived."""
        value = normalize_employee_draft(draft)
        return {key: value[key] for key in (
            "role", "program", "interface", "capabilities")}

    def update_employee(self, employee_id, name, draft, preserve_tests=False,
                        avatar=None):
        normalized = normalize_employee_draft(draft)
        name = str(name or "").strip()
        if not name:
            raise ContractError("员工名称不能为空")
        current = self.employee(employee_id)
        if current is None:
            raise ContractError("员工不存在")
        avatar = normalize_employee_avatar(
            current.get("avatar") if avatar is None else avatar)
        if (not preserve_tests and
                digest(self._employee_test_spec(current["draft_json"])) != digest(
                    self._employee_test_spec(normalized))):
            # Tests are derived only after the employee contract is finalized.
            normalized["tests"] = []
        before = {
            "name": current["name"], "avatar": current.get("avatar") or "a1",
            "draft": copy.deepcopy(current["draft_json"]),
            "active_release_id": current.get("active_release_id"),
            "trashed_at": current.get("trashed_at"),
        }
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE employees SET name=?,avatar=?,draft_json=?,updated_at=? "
                "WHERE id=? AND trashed_at IS NULL",
                (name, avatar, json.dumps(normalized, ensure_ascii=False), utc_now(),
                 int(employee_id))).rowcount
            if changed == 1:
                self.repository.event(
                    "employee:{}".format(int(employee_id)), "employee.draft_updated",
                    {"employee_id": int(employee_id), "before": before, "after": {
                        "name": name, "avatar": avatar, "draft": normalized,
                        "active_release_id": before["active_release_id"],
                        "trashed_at": before["trashed_at"]}}, connection=connection)
        if changed != 1:
            raise ContractError("员工不存在")
        return self.employee(employee_id)

    def employee(self, employee_id, include_trashed=False):
        with self.repository.connect() as connection:
            query = "SELECT * FROM employees WHERE id=?"
            if not include_trashed:
                query += " AND trashed_at IS NULL"
            row = connection.execute(query, (int(employee_id),)).fetchone()
            if row is None:
                return None
            item = self.repository.decode(row, "draft_json")
            release = connection.execute(
                "SELECT * FROM employee_releases WHERE id=?", (item["active_release_id"],)
            ).fetchone() if item["active_release_id"] else None
        item["active_release"] = self.repository.decode(release, "snapshot_json")
        if item["active_release"] is None:
            item["has_unpublished_changes"] = True
        else:
            try:
                candidate, _checks = self._release_snapshot(item, verify=False)
                item["has_unpublished_changes"] = (
                    digest(candidate) != item["active_release"]["digest"])
            except ContractError:
                item["has_unpublished_changes"] = True
        return item

    def employee_catalog(self):
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM employees WHERE trashed_at IS NULL ORDER BY name,id")]
        return [self.employee(employee_id) for employee_id in ids]

    def employee_coverage(self, employee_or_id, trials=None):
        employee = (employee_or_id if isinstance(employee_or_id, dict)
                    else self.employee(employee_or_id))
        if employee is None:
            raise ContractError("员工不存在")
        draft = normalize_employee_draft(employee["draft_json"])
        targets = employee_coverage_targets(draft)
        target_ids = {item["id"] for item in targets}
        skill_packages = {}
        for reference in draft["capabilities"]:
            if reference.get("plugin_id"):
                continue
            package = self.package(reference["package_id"])
            if package is not None:
                skill_packages[str(reference["package_id"])] = package.get("key")
        covered_by = {}
        for case in draft["tests"]:
            for coverage_id in case.get("covers") or []:
                if coverage_id in target_ids:
                    covered_by.setdefault(coverage_id, []).append(case["id"])
        verified = set()
        run_counts = {}
        if trials is not None:
            histories = {}
            for trial in trials:
                test_id = ((trial.get("snapshot_json") or {}).get("trial") or {}).get("test_id")
                result = trial.get("trial_result") or {}
                if test_id and not result.get("stale"):
                    histories.setdefault(test_id, []).append(trial)
            for case in draft["tests"]:
                history = histories.get(case["id"]) or []
                running = [item for item in history
                           if item.get("state") not in WORKFLOW_TERMINAL_STATES]
                settled = [item for item in history
                           if (item.get("trial_result") or {}).get("verdict")
                           in ("matched", "mismatched")]
                evaluated = [(item, self._evidenced_trial_coverage(
                    case, item, draft, skill_packages))
                    for item in settled]
                claimed = set(case.get("covers") or [])
                matched = [(item, evidence) for item, evidence in evaluated
                           if (item.get("trial_result") or {}).get("verdict") == "matched"
                           and claimed <= evidence]
                mismatched = [(item, evidence) for item, evidence in evaluated
                              if (item.get("trial_result") or {}).get("verdict") != "matched"
                              or not claimed <= evidence]
                run_counts[case["id"]] = {
                    "passed": len(matched), "failed": len(mismatched),
                    "running": len(running),
                }
                if (not running and not mismatched and
                        len(matched) >= EMPLOYEE_TRIAL_SAMPLE_COUNT):
                    evidence = [item[1] for item in matched]
                    if evidence:
                        verified.update(set.intersection(*evidence))
        missing = [item for item in targets if item["id"] not in covered_by]
        unverified = [item for item in targets
                      if item["id"] in covered_by and item["id"] not in verified]
        categories = []
        for category in ("input", "output", "program", "skill", "result", "handoff"):
            items = [item for item in targets if item["category"] == category]
            if items:
                categories.append({
                    "id": category, "total": len(items),
                    "covered": sum(item["id"] in covered_by for item in items),
                    "verified": sum(item["id"] in verified for item in items),
                })
        return {
            "total": len(targets), "covered": len(covered_by),
            "verified": len(verified & target_ids),
            "complete": len(covered_by) == len(targets),
            "passed": bool(targets) and len(verified & target_ids) == len(targets),
            "required_runs": EMPLOYEE_TRIAL_SAMPLE_COUNT,
            "runs": run_counts,
            "missing": missing, "unverified": unverified,
            "categories": categories,
        }

    @staticmethod
    def _evidenced_trial_coverage(case, trial, draft, skill_packages=None):
        skill_packages = skill_packages or {}
        runs = trial.get("employee_runs") or []
        subject = next((item for item in reversed(runs)
                        if item.get("position_key") == "subject"), None)
        if subject is None:
            return set()
        actual = subject.get("state")
        input_value = subject.get("input_json") or {}
        output_value = (subject.get("output_json") or {}).get("output")
        output_valid = not json_schema_violations(
            output_value, draft["interface"]["output"], path="$.output")
        events = subject.get("events") or []
        completed_steps = {str((item.get("data_json") or {}).get("step_id") or "")
                           for item in events if item.get("type") == "step.completed"}
        executed_capabilities = {
            str((item.get("data_json") or {}).get("capability_ref") or "")
            for item in events if item.get("type") == "capability.executed"
        }
        context = input_value.get("context") if isinstance(input_value, dict) else {}
        context = context if isinstance(context, dict) else {}
        has_position = bool(context.get("upstream_position"))
        has_output = "upstream_output" in context
        evidenced = set()
        for coverage_id in case.get("covers") or []:
            if coverage_id == "input.valid":
                if not json_schema_violations(
                        work_order_payload(input_value, draft["interface"]["input"]),
                        draft["interface"]["input"], path="$.input"):
                    evidenced.add(coverage_id)
            elif coverage_id.startswith("input."):
                evidenced.add(coverage_id)
            elif coverage_id.startswith("output."):
                if actual == "completed" and output_valid:
                    evidenced.add(coverage_id)
            elif coverage_id.startswith("program."):
                if coverage_id.split(".", 1)[1] in completed_steps:
                    evidenced.add(coverage_id)
            elif coverage_id.startswith("result."):
                if coverage_id == "result.{}".format(actual):
                    evidenced.add(coverage_id)
            elif coverage_id == "handoff.upstream.valid":
                if has_position and has_output:
                    evidenced.add(coverage_id)
            elif coverage_id == "handoff.upstream.missing":
                if not has_position and not has_output:
                    evidenced.add(coverage_id)
            elif coverage_id == "handoff.upstream.invalid":
                if has_position != has_output:
                    evidenced.add(coverage_id)
            elif coverage_id == "handoff.output.valid":
                if actual == "completed" and output_valid:
                    evidenced.add(coverage_id)
            elif coverage_id.startswith("skill."):
                marker, outcome = coverage_id[len("skill."):].rsplit(".", 1)
                if outcome == "success":
                    package_key = skill_packages.get(marker)
                    executed = any(reference.split("/", 1)[0] == package_key
                                   for reference in executed_capabilities)
                    if executed or actual == "completed":
                        evidenced.add(coverage_id)
                elif outcome == "failure" and actual == "failed":
                    signal = context.get("test_signal")
                    if (isinstance(signal, dict) and
                            signal.get("state") == "unavailable"):
                        signal_ref = str(signal.get("capability_ref") or "")
                        signal_package = signal_ref.split("/", 1)[0]
                        # Validation removes the whole frozen package, not only the
                        # named entry point.  Therefore one unavailable signal is
                        # evidence for every selected Skill and Tool in that package.
                        if signal_package and signal_package == skill_packages.get(marker):
                            evidenced.add(coverage_id)
        return evidenced

    def duplicate_employee(self, employee_id):
        source = self.employee(employee_id)
        if source is None:
            raise ContractError("员工不存在")
        name = "{} 副本".format(str(source["name"] or "员工").strip()[:150])
        duplicate_id = self.create_employee(
            name, source["draft_json"], avatar=source.get("avatar") or "a1")
        return self.employee(duplicate_id)

    def employee_avatar_in_use(self, avatar):
        avatar = normalize_employee_avatar(avatar)
        with self.repository.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM employees WHERE avatar=? LIMIT 1", (avatar,)
            ).fetchone() is not None

    def discard_employee_draft(self, employee_id):
        employee = self.employee(employee_id)
        if employee is None:
            raise ContractError("员工不存在")
        release = employee.get("active_release")
        if release is None:
            raise ContractError("这名员工还没有可恢复的已发布版本")
        snapshot = release.get("snapshot_json") or {}
        references = []
        with self.repository.connect() as connection:
            for frozen in snapshot.get("capabilities") or []:
                if frozen.get("plugin_id"):
                    references.append({"provider": frozen.get("provider"),
                                       "plugin_id": frozen.get("plugin_id")})
                    continue
                package = connection.execute(
                    "SELECT id FROM packages WHERE key=?",
                    (str(frozen.get("package_key") or ""),),
                ).fetchone()
                if package is None:
                    raise ContractError("当前发布版本引用的能力包已经不可用")
                reference = {"package_id": package["id"]}
                if reference not in references:
                    references.append(reference)
        draft = {
            "role": snapshot.get("role") or "",
            "program": snapshot.get("program") or {},
            "interface": snapshot.get("interface") or normalize_employee_interface(None),
            "capabilities": references,
            "runtime": snapshot.get("runtime") or {},
            "tests": (employee.get("draft_json") or {}).get("tests") or [],
        }
        return self.update_employee(
            employee_id, snapshot.get("name") or employee["name"], draft)

    def employee_pipeline_usage(self, employee_id):
        employee_id = int(employee_id)
        return [
            {"id": item["id"], "name": item["name"]}
            for item in self.pipeline_catalog()
            if any(int(position.get("employee_id") or 0) == employee_id
                   for position in (item.get("definition_json") or {}).get("positions") or [])
        ]

    def trash_employee(self, employee_id):
        employee_id = int(employee_id)
        usage = self.employee_pipeline_usage(employee_id)
        if usage:
            raise ContractError("员工仍用于 {} 条流水线，请先从流水线中移除".format(len(usage)))
        now = utc_now()
        with self.repository.connect() as connection:
            current = connection.execute(
                "SELECT name,avatar,draft_json,active_release_id,trashed_at FROM employees "
                "WHERE id=? AND trashed_at IS NULL", (employee_id,)).fetchone()
            if current is None:
                raise ContractError("员工不存在")
            changed = connection.execute(
                "UPDATE employees SET trashed_at=?,updated_at=? "
                "WHERE id=? AND trashed_at IS NULL",
                (now, now, employee_id),
            ).rowcount
            if changed == 1:
                self.repository.event(
                    "employee:{}".format(employee_id), "employee.trashed",
                    {"employee_id": employee_id, "before": {
                        "name": current["name"], "avatar": current["avatar"],
                        "draft": json.loads(current["draft_json"]),
                        "active_release_id": current["active_release_id"],
                        "trashed_at": current["trashed_at"]},
                     "after": {"trashed_at": now}}, connection=connection)
        if changed != 1:
            raise ContractError("员工不存在")
        return self.employee(employee_id, include_trashed=True)

    def employee_trash_catalog(self):
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT e.*,(SELECT COUNT(DISTINCT wr.id) FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id LEFT JOIN employee_runs er "
                "ON er.workflow_run_id=wr.id LEFT JOIN employee_releases rel "
                "ON rel.id=er.employee_release_id "
                "WHERE (t.employee_id=e.id OR rel.employee_id=e.id) "
                "AND json_extract(wr.snapshot_json,'$.trial') IS NULL) AS run_count,"
                "(SELECT COUNT(*) FROM artifacts a "
                " JOIN employee_runs er2 ON er2.id=a.employee_run_id "
                " JOIN workflow_runs wr2 ON wr2.id=er2.workflow_run_id "
                " JOIN tasks t2 ON t2.id=wr2.task_id "
                " LEFT JOIN employee_releases rel2 ON rel2.id=er2.employee_release_id "
                " WHERE (t2.employee_id=e.id OR rel2.employee_id=e.id) "
                " AND json_extract(wr2.snapshot_json,'$.trial') IS NULL) AS document_count "
                "FROM employees e WHERE e.trashed_at IS NOT NULL "
                "ORDER BY e.trashed_at DESC,e.id DESC"
            ).fetchall()
        items = []
        for row in rows:
            item = self.repository.decode(row, "draft_json")
            trashed = datetime.datetime.fromisoformat(item["trashed_at"])
            item.update({
                "kind": "employee",
                "title": item["name"],
                "location": "团队",
                "count": int(item.pop("run_count") or 0),
                "document_count": int(item.pop("document_count") or 0),
                "expires_at": (trashed + datetime.timedelta(days=30)).isoformat(
                    timespec="seconds"),
            })
            items.append(item)
        return items

    def restore_employee(self, employee_id):
        now = utc_now()
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE employees SET trashed_at=NULL,updated_at=? "
                "WHERE id=? AND trashed_at IS NOT NULL",
                (now, int(employee_id)),
            ).rowcount
            if changed == 1:
                self.repository.event(
                    "employee:{}".format(int(employee_id)), "employee.restored",
                    {"employee_id": int(employee_id), "after": {"trashed_at": None}},
                    connection=connection)
        if changed != 1:
            raise ContractError("垃圾箱中没有这名员工")
        return self.employee(employee_id)

    def _document_count_for_workflows(self, connection, workflow_ids):
        """Count the published documents a deletion would destroy."""
        workflow_ids = [int(value) for value in workflow_ids]
        if not workflow_ids:
            return 0
        placeholders = ",".join("?" for _ in workflow_ids)
        return int(connection.execute(
            "SELECT COUNT(*) FROM artifacts a "
            "JOIN employee_runs er ON er.id=a.employee_run_id "
            "JOIN workflow_runs wr ON wr.id=er.workflow_run_id "
            "WHERE er.workflow_run_id IN ({}) AND a.trashed_at IS NULL "
            "AND json_extract(wr.snapshot_json,'$.trial') IS NULL".format(placeholders),
            workflow_ids).fetchone()[0] or 0)

    def _pipeline_workflow_ids(self, connection, pipeline_id):
        return [row[0] for row in connection.execute(
            "SELECT wr.id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
            "WHERE t.pipeline_id=?", (int(pipeline_id),)).fetchall()]

    def _guard_document_loss(self, documents, acknowledged, subject):
        """Refuse to silently destroy documents; the caller must name the count."""
        if not documents:
            return
        try:
            confirmed = int(acknowledged)
        except (TypeError, ValueError):
            confirmed = -1
        if confirmed != documents:
            raise DocumentLossError(
                "{}名下还有 {} 份文档，永久删除会一并销毁且无法恢复。"
                "请先导出需要留下的文档，再确认删除".format(subject, documents), documents)

    def _delete_workflows(self, connection, workflow_ids):
        workflow_ids = [int(value) for value in workflow_ids]
        if not workflow_ids:
            return [], []
        placeholders = ",".join("?" for _ in workflow_ids)
        employee_run_ids = [row[0] for row in connection.execute(
            "SELECT id FROM employee_runs WHERE workflow_run_id IN ({})".format(
                placeholders), workflow_ids).fetchall()]
        artifact_rows = connection.execute(
            "SELECT a.id,a.ref FROM artifacts a JOIN employee_runs er "
            "ON er.id=a.employee_run_id WHERE er.workflow_run_id IN ({})".format(
                placeholders), workflow_ids).fetchall()
        artifact_refs = [row["ref"] for row in artifact_rows]
        task_ids = [row[0] for row in connection.execute(
            "SELECT task_id FROM workflow_runs WHERE id IN ({})".format(placeholders),
            workflow_ids).fetchall()]
        # Keep the event ledger intact even when business rows are permanently
        # purged.  The tombstones preserve the fact that a run/task existed;
        # artifact bytes may still be removed only after the explicit loss
        # acknowledgement required by the existing retention policy.
        for workflow_id in workflow_ids:
            workflow = connection.execute(
                "SELECT task_id,state FROM workflow_runs WHERE id=?", (workflow_id,)
            ).fetchone()
            if workflow is None:
                continue
            self.repository.event(
                "workflow_run:{}".format(workflow_id), "workflow.deleted",
                {"workflow_run_id": workflow_id, "task_id": workflow["task_id"],
                 "state": workflow["state"]}, connection=connection)
            self.repository.event(
                "task:{}".format(workflow["task_id"]), "task.workflow_deleted",
                {"task_id": workflow["task_id"], "workflow_run_id": workflow_id},
                connection=connection)
        connection.execute(
            "DELETE FROM artifacts WHERE employee_run_id IN ("
            "SELECT id FROM employee_runs WHERE workflow_run_id IN ({}))".format(
                placeholders), workflow_ids)
        connection.execute(
            "DELETE FROM employee_runs WHERE workflow_run_id IN ({})".format(placeholders),
            workflow_ids)
        connection.execute(
            "DELETE FROM workflow_runs WHERE id IN ({})".format(placeholders), workflow_ids)
        if task_ids:
            connection.execute(
                "DELETE FROM tasks WHERE id IN ({})".format(
                    ",".join("?" for _ in task_ids)), task_ids)
        return artifact_refs, task_ids

    def _delete_artifact_files(self, artifact_refs):
        artifact_root = (self.root / "artifacts").resolve()
        refs = [raw_ref for raw_ref in artifact_refs if raw_ref]
        if not refs:
            return
        # 产物文件按内容寻址，内容一样的两个版本共用同一个文件；
        # 还有别的记录指着它就不能删，否则删掉一版会把另一版的正文一起抹掉。
        with self.repository.connect() as connection:
            still_referenced = {row[0] for row in connection.execute(
                "SELECT ref FROM artifacts WHERE ref IN ({})".format(
                    ",".join("?" * len(refs))), refs).fetchall()}
        for raw_ref in refs:
            if raw_ref in still_referenced:
                continue
            try:
                path = Path(raw_ref).resolve()
                if path != artifact_root and artifact_root in path.parents and path.is_file():
                    path.unlink()
                    parent = path.parent
                    while parent != artifact_root:
                        try:
                            parent.rmdir()
                        except OSError:
                            break
                        parent = parent.parent
            except (OSError, RuntimeError):
                continue

    def _delete_task_input_files(self, task_ids):
        for task_id in task_ids or []:
            task_inputs.discard_task(self.root, task_id)

    def delete_trashed_employee(self, employee_id, acknowledged_documents=None):
        employee_id = int(employee_id)
        artifact_refs = []
        with self.repository.connect() as connection:
            employee = connection.execute(
                "SELECT id,name,avatar,draft_json,active_release_id,trashed_at FROM employees "
                "WHERE id=? AND trashed_at IS NOT NULL",
                (employee_id,),
            ).fetchone()
            if employee is None:
                raise ContractError("垃圾箱中没有这名员工")
            referenced_by = []
            for row in connection.execute(
                    "SELECT id,name,definition_json FROM pipelines ORDER BY id").fetchall():
                try:
                    definition = json.loads(row["definition_json"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    definition = {}
                if any(int(position.get("employee_id") or 0) == employee_id
                       for position in definition.get("positions") or []):
                    referenced_by.append(row["name"])
            if referenced_by:
                raise ContractError(
                    "员工仍被 {} 条流水线引用，请先永久删除或修改这些流水线".format(
                        len(referenced_by)))
            release_ids = [row[0] for row in connection.execute(
                "SELECT id FROM employee_releases WHERE employee_id=?", (employee_id,)
            ).fetchall()]
            release_set = set(release_ids)
            affected = []
            for row in connection.execute(
                    "SELECT wr.id,wr.state,wr.snapshot_json,t.employee_id "
                    "FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                    "ORDER BY wr.id").fetchall():
                try:
                    snapshot = json.loads(row["snapshot_json"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    snapshot = {}
                positions = ((snapshot.get("definition") or {}).get("positions") or [])
                if (int(row["employee_id"] or 0) == employee_id or
                        any(int(position.get("employee_id") or 0) == employee_id or
                            int(position.get("employee_release_id") or 0) in release_set
                            for position in positions)):
                    affected.append((row["id"], row["state"]))
            if any(state not in WORKFLOW_TERMINAL_STATES for _id, state in affected):
                raise ContractError("员工仍有运行中的任务，暂时不能永久删除")
            affected_ids = [workflow_id for workflow_id, _state in affected]
            self._guard_document_loss(
                self._document_count_for_workflows(connection, affected_ids),
                acknowledged_documents, "这名员工")
            self.repository.event(
                "employee:{}".format(employee_id), "employee.deleted",
                {"employee_id": employee_id, "name": employee["name"],
                 "avatar": employee["avatar"],
                 "draft": json.loads(employee["draft_json"]),
                 "active_release_id": employee["active_release_id"],
                 "trashed_at": employee["trashed_at"]}, connection=connection)
            artifact_refs, task_ids = self._delete_workflows(connection, affected_ids)
            connection.execute(
                "DELETE FROM employee_releases WHERE employee_id=?", (employee_id,))
            connection.execute("DELETE FROM employees WHERE id=?", (employee_id,))
        self._delete_artifact_files(artifact_refs)
        self._delete_task_input_files(task_ids)
        return True

    def purge_expired_employees(self, retention_days=30):
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=max(1, int(retention_days)))).isoformat(
                      timespec="seconds")
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM employees WHERE trashed_at IS NOT NULL AND trashed_at<=?",
                (cutoff,),
            ).fetchall()]
        purged = []
        for employee_id in ids:
            try:
                self.delete_trashed_employee(employee_id, acknowledged_documents=0)
                purged.append(employee_id)
            except ContractError:
                continue
        return purged

    def _resolve_capabilities(self, references, verify, runtime_provider=""):
        frozen_capabilities, checks = [], []
        for reference in normalize_capability_references(references):
            if reference.get("plugin_id"):
                provider = reference["provider"]
                if runtime_provider and provider != runtime_provider:
                    raise ContractError("员工只能使用当前模型渠道的扩展")
                try:
                    dependency = self._native_dependency(
                        provider, reference["plugin_id"], refresh=verify)
                except Exception as exc:
                    raise ContractError(str(exc)) from exc
                frozen_capabilities.append({
                    key: dependency.get(key) for key in
                    ("provider", "plugin_id", "name", "version", "fingerprint")
                })
                checks.append({"kind": "extension", "provider": provider,
                               "plugin_id": dependency.get("plugin_id"), "ok": True})
                continue
            package = self.package(reference["package_id"])
            if package is None or package.get("active_revision_id") is None:
                raise ContractError("员工引用的技能不存在")
            capabilities = package["manifest_json"]["capabilities"]
            if verify:
                checks.extend(self.packages.verify_manifest(
                    package["blob_ref"], package["manifest_json"]))
            frozen_capabilities.append({
                "package_key": package["key"],
                "revision_id": package["active_revision_id"],
                "digest": package["digest"],
                "skill": {
                    "name": package["manifest_json"].get("display_name") or
                    package["manifest_json"].get("name") or package["key"],
                    "description": package["manifest_json"].get("description") or "",
                },
                "capabilities": capabilities,
            })
        return frozen_capabilities, checks

    def freeze_capabilities(self, references):
        """Verify employee capability references and freeze their active revisions."""
        return self._resolve_capabilities(references, verify=True)

    def _release_snapshot(self, employee, verify):
        draft = normalize_employee_draft(employee["draft_json"])
        frozen_capabilities, checks = self._resolve_capabilities(
            draft["capabilities"], verify=verify,
            runtime_provider=(draft.get("runtime") or {}).get("channel") or "")
        return ({"schema": "runteams.employee-release/v2", "name": employee["name"],
                 "role": draft["role"], "program": draft["program"],
                 "interface": draft["interface"],
                 "runtime": draft["runtime"], "capabilities": frozen_capabilities}, checks)

    @staticmethod
    def required_credentials(snapshot):
        names = []
        for frozen in (snapshot or {}).get("capabilities") or []:
            capabilities = frozen.get("capabilities") or [frozen.get("capability") or {}]
            for capability in capabilities:
                for name in capability.get("credentials") or []:
                    if name not in names:
                        names.append(name)
        return names

    def _assert_credentials_ready(self, snapshot):
        if self.credential_names_provider is None:
            return
        available = set(self.credential_names_provider() or [])
        missing = [name for name in self.required_credentials(snapshot) if name not in available]
        if missing:
            raise ContractError("缺少能力凭据：{}；请先到设置 → 凭据填写".format("、".join(missing)))

    def _assert_native_dependencies_ready(self, snapshot):
        for frozen in (snapshot or {}).get("capabilities") or []:
            if not frozen.get("plugin_id"):
                continue
            try:
                current = self._native_dependency(
                    frozen.get("provider"), frozen.get("plugin_id"), refresh=True)
            except Exception as exc:
                raise ContractError(str(exc)) from exc
            if (str(current.get("fingerprint") or "") !=
                    str(frozen.get("fingerprint") or "")):
                raise ContractError("扩展 {} 已发生变化，请重新验证并发布员工".format(
                    frozen.get("name") or frozen.get("plugin_id")))

    def _employee_validation_digest(self, employee):
        """Identify the exact draft and test suite whose behavior was verified."""
        snapshot, _checks = self._release_snapshot(employee, verify=False)
        tests = normalize_employee_draft(employee["draft_json"])["tests"]
        return digest({"employee": snapshot, "tests": tests})

    def publish_employee(self, employee_id):
        employee = self.employee(employee_id)
        if employee is None:
            raise ContractError("员工不存在")
        snapshot, checks = self._release_snapshot(employee, verify=True)
        self._assert_credentials_ready(snapshot)
        trials = self.employee_trials(employee["id"])
        coverage = self.employee_coverage(employee, trials=trials)
        if not coverage["complete"]:
            raise ContractError(
                "发布前必须完成员工验证：还有 {} 个场景没有测试用例".format(
                    len(coverage["missing"])))
        if not coverage["passed"]:
            raise ContractError(
                "发布前必须通过员工自查：当前已验证 {}/{} 个场景；请运行全部用例并修复不符合预期的结果".format(
                    coverage["verified"], coverage["total"]))
        release_digest, now = digest(snapshot), utc_now()
        with self.repository.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM employee_releases WHERE employee_id=? AND digest=?",
                (employee["id"], release_digest),).fetchone()
            if existing is None:
                version = connection.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM employee_releases WHERE employee_id=?",
                    (employee["id"],),).fetchone()[0]
                release_id = connection.execute(
                    "INSERT INTO employee_releases(employee_id,version,digest,snapshot_json,created_at) "
                    "VALUES(?,?,?,?,?)", (employee["id"], version, release_digest,
                    json.dumps(snapshot, ensure_ascii=False), now),).lastrowid
            else:
                release_id, version = existing["id"], existing["version"]
            connection.execute("UPDATE employees SET active_release_id=?,updated_at=? WHERE id=?",
                               (release_id, now, employee["id"]))
            self.repository.event(
                "employee_release:{}".format(release_id), "employee.published",
                {"employee_id": employee["id"], "release_id": release_id,
                 "version": version, "digest": release_digest, "checks": checks,
                 "snapshot": snapshot}, connection=connection)
        return {"employee_id": employee["id"], "release_id": release_id,
                "version": version, "digest": release_digest, "snapshot": snapshot,
                "checks": checks}

    def create_pipeline(self, name, definition):
        normalized = normalize_pipeline_definition(definition)
        pipeline_order(normalized)
        name = str(name or "").strip()
        if not name:
            raise ContractError("流水线名称不能为空")
        now = utc_now()
        with self.repository.connect() as connection:
            pipeline_id = connection.execute(
                "INSERT INTO pipelines(name,definition_json,created_at,updated_at) VALUES(?,?,?,?)",
                (name, json.dumps(normalized, ensure_ascii=False), now, now),
            ).lastrowid
            self.repository.event(
                "pipeline:{}".format(pipeline_id), "pipeline.created",
                {"pipeline_id": pipeline_id, "after": {
                    "name": name, "definition": normalized, "trashed_at": None,
                    "paused_at": None}}, connection=connection)
        return pipeline_id

    def update_pipeline(self, pipeline_id, name, definition):
        normalized = normalize_pipeline_definition(definition)
        pipeline_order(normalized)
        name = str(name or "").strip()
        if not name:
            raise ContractError("流水线名称不能为空")
        now = utc_now()
        with self.repository.connect() as connection:
            previous = connection.execute(
                "SELECT name,definition_json,trashed_at,paused_at FROM pipelines "
                "WHERE id=? AND trashed_at IS NULL", (int(pipeline_id),)).fetchone()
            if previous is None:
                raise ContractError("流水线不存在")
            changed = connection.execute(
                "UPDATE pipelines SET name=?,definition_json=?,updated_at=? "
                "WHERE id=? AND trashed_at IS NULL",
                (name, json.dumps(normalized, ensure_ascii=False), now,
                int(pipeline_id)),
            ).rowcount
            if changed == 1:
                self.repository.event(
                    "pipeline:{}".format(int(pipeline_id)), "pipeline.updated",
                    {"pipeline_id": int(pipeline_id), "before": {
                        "name": previous["name"],
                        "definition": json.loads(previous["definition_json"]),
                        "trashed_at": previous["trashed_at"],
                        "paused_at": previous["paused_at"]},
                     "after": {"name": name, "definition": normalized,
                               "trashed_at": None,
                               "paused_at": previous["paused_at"]}}, connection=connection)
        if changed != 1:
            raise ContractError("流水线不存在")
        return self.pipeline(pipeline_id)

    def pipeline(self, pipeline_id, include_trashed=False):
        with self.repository.connect() as connection:
            query = "SELECT * FROM pipelines WHERE id=?"
            if not include_trashed:
                query += " AND trashed_at IS NULL"
            row = connection.execute(query, (int(pipeline_id),)).fetchone()
        return self.repository.decode(row, "definition_json")

    def pipeline_catalog(self):
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM pipelines WHERE trashed_at IS NULL "
                "ORDER BY updated_at DESC,id DESC").fetchall()
        return [self.repository.decode(row, "definition_json") for row in rows]

    def pipeline_check(self, pipeline_id):
        """Return the small set of facts that can actually prevent execution."""
        pipeline = self.pipeline(pipeline_id)
        if pipeline is None:
            raise ContractError("流水线不存在")
        issues = []
        try:
            definition = normalize_pipeline_definition(pipeline["definition_json"])
        except ContractError as exc:
            return {"ready": False, "issues": [str(exc)], "checked": 0}
        checked = 0
        with self.repository.connect() as connection:
            for position in definition["positions"]:
                if position.get("kind") == "approval":
                    checked += 1
                    continue
                employee = connection.execute(
                    "SELECT * FROM employees WHERE id=? AND trashed_at IS NULL",
                    (position["employee_id"],)).fetchone()
                if employee is None:
                    issues.append("{}：员工不存在".format(position["name"]))
                    continue
                if employee["active_release_id"] is None:
                    issues.append("{}：员工尚未发布".format(position["name"]))
                    continue
                release = connection.execute(
                    "SELECT snapshot_json FROM employee_releases WHERE id=?",
                    (employee["active_release_id"],)).fetchone()
                try:
                    snapshot = json.loads(release["snapshot_json"])
                    self._assert_credentials_ready(snapshot)
                    self._assert_native_dependencies_ready(snapshot)
                    checked += 1
                except ContractError as exc:
                    issues.append("{}：{}".format(position["name"], exc))
        return {"ready": not issues, "issues": issues, "checked": checked,
                "paused": bool(pipeline.get("paused_at"))}

    def pause_pipeline(self, pipeline_id):
        pipeline_id, now = int(pipeline_id), utc_now()
        running = []
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE pipelines SET paused_at=?,updated_at=? "
                "WHERE id=? AND trashed_at IS NULL AND paused_at IS NULL",
                (now, now, pipeline_id)).rowcount
            if not changed and connection.execute(
                    "SELECT 1 FROM pipelines WHERE id=? AND trashed_at IS NULL",
                    (pipeline_id,)).fetchone() is None:
                raise ContractError("流水线不存在")
            if changed:
                self.repository.event(
                    "pipeline:{}".format(pipeline_id), "pipeline.paused",
                    {"pipeline_id": pipeline_id, "paused_at": now}, connection=connection)
            rows = connection.execute(
                "SELECT wr.id,wr.task_id,wr.state FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id WHERE t.pipeline_id=? "
                "AND wr.state IN ('ready','running','waiting_retry')", (pipeline_id,)).fetchall()
            for row in rows:
                if row["state"] == "running":
                    running.append(int(row["id"]))
                    connection.execute(
                        "UPDATE employee_runs SET state='interrupted',updated_at=? "
                        "WHERE workflow_run_id=? AND state='running'", (now, row["id"]))
                connection.execute(
                    "UPDATE workflow_runs SET state='paused',available_at=NULL,updated_at=? WHERE id=?",
                    (now, row["id"]))
                connection.execute("UPDATE tasks SET state='paused',updated_at=? WHERE id=?",
                                   (now, row["task_id"]))
                self.repository.event(
                    "workflow_run:{}".format(row["id"]), "workflow.paused",
                    {"from_state": row["state"]}, connection=connection)
        for workflow_id in running:
            self._cancel_event(workflow_id).set()
        return self.pipeline(pipeline_id)

    def resume_pipeline(self, pipeline_id):
        pipeline_id, now = int(pipeline_id), utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE pipelines SET paused_at=NULL,updated_at=? "
                "WHERE id=? AND trashed_at IS NULL", (now, pipeline_id)).rowcount
            if changed != 1:
                raise ContractError("流水线不存在")
            self.repository.event(
                "pipeline:{}".format(pipeline_id), "pipeline.resumed",
                {"pipeline_id": pipeline_id, "paused_at": None}, connection=connection)
            rows = connection.execute(
                "SELECT wr.id,wr.task_id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                "WHERE t.pipeline_id=? AND wr.state='paused'", (pipeline_id,)).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE workflow_runs SET state='ready',available_at=?,updated_at=? WHERE id=?",
                    (now, now, row["id"]))
                connection.execute("UPDATE tasks SET state='ready',updated_at=? WHERE id=?",
                                   (now, row["task_id"]))
                self.repository.event(
                    "workflow_run:{}".format(row["id"]), "workflow.resumed", {},
                    connection=connection)
                self._cancel_event(row["id"], reset=True)
        return self.pipeline(pipeline_id)

    def trash_pipeline(self, pipeline_id):
        now = utc_now()
        with self.repository.connect() as connection:
            current = connection.execute(
                "SELECT name,definition_json,trashed_at,paused_at FROM pipelines "
                "WHERE id=? AND trashed_at IS NULL", (int(pipeline_id),)).fetchone()
            if current is None:
                raise ContractError("流水线不存在")
            changed = connection.execute(
                "UPDATE pipelines SET trashed_at=?,updated_at=? "
                "WHERE id=? AND trashed_at IS NULL",
                (now, now, int(pipeline_id)),
            ).rowcount
            if changed == 1:
                self.repository.event(
                    "pipeline:{}".format(int(pipeline_id)), "pipeline.trashed",
                    {"pipeline_id": int(pipeline_id), "before": {
                        "name": current["name"],
                        "definition": json.loads(current["definition_json"]),
                        "trashed_at": current["trashed_at"],
                        "paused_at": current["paused_at"]},
                     "after": {"trashed_at": now}}, connection=connection)
        if changed != 1:
            raise ContractError("流水线不存在")
        return self.pipeline(pipeline_id, include_trashed=True)

    def pipeline_trash_catalog(self):
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT p.*,COUNT(DISTINCT t.id) AS task_count,"
                "(SELECT COUNT(*) FROM artifacts a "
                " JOIN employee_runs er ON er.id=a.employee_run_id "
                " JOIN workflow_runs wr ON wr.id=er.workflow_run_id "
                " JOIN tasks t2 ON t2.id=wr.task_id "
                " WHERE t2.pipeline_id=p.id "
                " AND json_extract(wr.snapshot_json,'$.trial') IS NULL) AS document_count "
                "FROM pipelines p "
                "LEFT JOIN tasks t ON t.pipeline_id=p.id "
                "WHERE p.trashed_at IS NOT NULL GROUP BY p.id "
                "ORDER BY p.trashed_at DESC,p.id DESC"
            ).fetchall()
        items = []
        for row in rows:
            item = self.repository.decode(row, "definition_json")
            trashed = datetime.datetime.fromisoformat(item["trashed_at"])
            item.update({
                "kind": "pipeline",
                "title": item["name"],
                "location": "流水线",
                "count": int(item.pop("task_count") or 0),
                "document_count": int(item.pop("document_count") or 0),
                "expires_at": (trashed + datetime.timedelta(days=30)).isoformat(
                    timespec="seconds"),
            })
            items.append(item)
        return items

    def restore_pipeline(self, pipeline_id):
        now = utc_now()
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE pipelines SET trashed_at=NULL,updated_at=? "
                "WHERE id=? AND trashed_at IS NOT NULL",
                (now, int(pipeline_id)),
            ).rowcount
            if changed == 1:
                self.repository.event(
                    "pipeline:{}".format(int(pipeline_id)), "pipeline.restored",
                    {"pipeline_id": int(pipeline_id), "after": {"trashed_at": None}},
                    connection=connection)
        if changed != 1:
            raise ContractError("垃圾箱中没有这条流水线")
        return self.pipeline(pipeline_id)

    def delete_trashed_pipeline(self, pipeline_id, acknowledged_documents=None):
        pipeline_id = int(pipeline_id)
        artifact_refs = []
        with self.repository.connect() as connection:
            pipeline = connection.execute(
                "SELECT id FROM pipelines WHERE id=? AND trashed_at IS NOT NULL",
                (pipeline_id,),
            ).fetchone()
            if pipeline is None:
                raise ContractError("垃圾箱中没有这条流水线")
            active = connection.execute(
                "SELECT COUNT(*) FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id "
                "WHERE t.pipeline_id=? AND wr.state NOT IN "
                "('completed','blocked','needs_human','failed','canceled')",
                (pipeline_id,),
            ).fetchone()[0]
            if active:
                raise ContractError("流水线仍有运行中的任务，暂时不能永久删除")
            workflow_ids = self._pipeline_workflow_ids(connection, pipeline_id)
            self._guard_document_loss(
                self._document_count_for_workflows(connection, workflow_ids),
                acknowledged_documents, "这条流水线")
            pipeline_row = connection.execute(
                "SELECT name,definition_json,trashed_at FROM pipelines WHERE id=?",
                (pipeline_id,)).fetchone()
            self.repository.event(
                "pipeline:{}".format(pipeline_id), "pipeline.deleted",
                {"pipeline_id": pipeline_id, "name": pipeline_row["name"],
                 "definition": json.loads(pipeline_row["definition_json"]),
                 "trashed_at": pipeline_row["trashed_at"]}, connection=connection)
            artifact_refs, task_ids = self._delete_workflows(connection, workflow_ids)
            connection.execute("DELETE FROM tasks WHERE pipeline_id=?", (pipeline_id,))
            connection.execute("DELETE FROM pipelines WHERE id=?", (pipeline_id,))
        self._delete_artifact_files(artifact_refs)
        self._delete_task_input_files(task_ids)
        return True

    def purge_expired_pipelines(self, retention_days=30):
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=max(1, int(retention_days)))).isoformat(
                      timespec="seconds")
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM pipelines WHERE trashed_at IS NOT NULL AND trashed_at<=?",
                (cutoff,),
            ).fetchall()]
        purged = 0
        for pipeline_id in ids:
            try:
                self.delete_trashed_pipeline(pipeline_id, acknowledged_documents=0)
                purged += 1
            except ContractError:
                continue
        return purged

    @staticmethod
    def _current_employee_runs(workflow):
        """Return attempts belonging to the task revision currently being executed."""
        floor = 0
        for event in workflow.get("events") or []:
            if event.get("type") != "workflow.task_recompiled":
                continue
            data = event.get("data_json") or {}
            floor = max(floor, int(data.get("after_employee_run_id") or 0))
        return [item for item in workflow.get("employee_runs") or []
                if int(item.get("id") or 0) > floor]

    @staticmethod
    def _workflow_board_column(workflow):
        """Derive the same visible board column used by the web client."""
        snapshot = workflow.get("snapshot_json") or {}
        definition = snapshot.get("definition") or {}
        positions = definition.get("positions") or []
        position_keys = [str(item.get("key") or "") for item in positions]
        states = definition.get("states") or []
        state_by_key = {str(item.get("key") or ""): item for item in states}
        state = str(workflow.get("state") or "")
        manual = str(workflow.get("manual_column_key") or "")
        if manual and (state in ("ready", "running", "waiting_retry") or
                       manual in state_by_key):
            return manual
        cursor = str(workflow.get("cursor_key") or "")
        if cursor in position_keys and state in (
                "ready", "running", "waiting_retry", "needs_approval", "paused"):
            return cursor
        if state == "completed":
            return next((str(item.get("key")) for item in states
                         if item.get("kind") == "done"), "__completed")
        runs = RunTeamsCore._current_employee_runs(workflow)
        latest = runs[-1] if runs else None
        if state == "canceled":
            return (next((str(item.get("key")) for item in states
                          if item.get("kind") == "dropped"), "") or
                    str((latest or {}).get("position_key") or "") or
                    (position_keys[0] if position_keys else "__completed"))
        if latest is None:
            task = snapshot.get("task") or {}
            return (str(task.get("start_column_key") or "") or
                    (position_keys[0] if position_keys else "__completed"))
        if state in ("failed", "blocked", "needs_human"):
            return (next((str(item.get("key")) for item in states
                          if item.get("kind") == "pool"), "") or
                    str(latest.get("position_key") or ""))
        if state == "waiting_retry":
            return str(latest.get("position_key") or "")
        active = next((item for item in reversed(runs)
                       if item.get("state") == "running"), None)
        if active:
            return str(active.get("position_key") or "")
        completed = {str(item.get("position_key") or "") for item in runs
                     if item.get("state") == "completed"}
        return (next((key for key in position_keys if key not in completed), "") or
                str(latest.get("position_key") or ""))

    def _pipeline_visible_workflows(self, pipeline_id):
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT wr.id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                "WHERE t.pipeline_id=? AND t.trashed_at IS NULL "
                "AND json_extract(wr.snapshot_json,'$.trial') IS NULL ORDER BY wr.id",
                (int(pipeline_id),),
            ).fetchall()
        return [self.workflow(row["id"]) for row in rows]

    def trash_pipeline_position(self, pipeline_id, position_key):
        pipeline_id = int(pipeline_id)
        position_key = str(position_key or "").strip()
        pipeline = self.pipeline(pipeline_id)
        if pipeline is None:
            raise ContractError("流水线不存在")
        definition = pipeline.get("definition_json") or {}
        positions = list(definition.get("positions") or [])
        position = next((item for item in positions
                         if str(item.get("key")) == position_key), None)
        if position is None:
            raise ContractError("岗位不存在")
        if len(positions) <= 1:
            raise ContractError("流水线至少需要保留一个岗位")
        order = pipeline_order(definition)
        index = order.index(position_key)
        previous_key = order[index - 1] if index > 0 else None
        next_key = order[index + 1] if index + 1 < len(order) else None
        workflows = self._pipeline_visible_workflows(pipeline_id)
        affected = [item for item in workflows
                    if self._workflow_board_column(item) == position_key]
        for workflow in affected:
            if workflow.get("state") not in WORKFLOW_TERMINAL_STATES:
                self.cancel_workflow(workflow["id"])
        task_ids = [int(item["task"]["id"]) for item in affected]
        workflow_ids = [int(item["id"]) for item in affected]
        remaining = [item for item in positions
                     if str(item.get("key")) != position_key]
        remaining_order = [key for key in order if key != position_key]
        by_key = {str(item.get("key")): item for item in remaining}
        remaining = [by_key[key] for key in remaining_order]
        updated = dict(definition, positions=remaining,
                       edges=[{"from": source, "to": target}
                              for source, target in zip(remaining_order,
                                                        remaining_order[1:])])
        normalized = normalize_pipeline_definition(updated)
        now = utc_now()
        employee = self.employee(position.get("employee_id"))
        title = self.position_display_name(dict(position, employee=employee))
        snapshot = {"pipeline_id": pipeline_id, "position_key": position_key,
                    "position": position, "index": index,
                    "previous_key": previous_key, "next_key": next_key,
                    "task_ids": task_ids, "workflow_ids": workflow_ids,
                    "title": title}
        stream = "pipeline_position:{}:{}".format(pipeline_id, position_key)
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT type FROM events WHERE stream=? ORDER BY id DESC LIMIT 1",
                (stream,)).fetchone()
            if latest is not None and latest["type"] == "pipeline.position_trashed":
                raise ContractError("岗位已经在垃圾箱中")
            trash_id = self.repository.event(
                stream, "pipeline.position_trashed", snapshot, connection=connection)
            connection.execute(
                "UPDATE pipelines SET definition_json=?,updated_at=? WHERE id=? "
                "AND trashed_at IS NULL",
                (json.dumps(normalized, ensure_ascii=False), now, pipeline_id))
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                connection.execute(
                    "UPDATE tasks SET trashed_at=?,updated_at=? WHERE id IN ({})".format(
                        placeholders), (now, now) + tuple(task_ids))
        return self.pipeline_position_trash(trash_id)

    def pipeline_position_trash(self, trash_id):
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT e.*,p.name AS pipeline_name,p.trashed_at AS pipeline_trashed_at "
                "FROM events e JOIN pipelines p "
                "ON p.id=CAST(json_extract(e.data_json,'$.pipeline_id') AS INTEGER) "
                "WHERE e.id=? AND e.type='pipeline.position_trashed'",
                (int(trash_id),)).fetchone()
            latest = (connection.execute(
                "SELECT id,type FROM events WHERE stream=? ORDER BY id DESC LIMIT 1",
                (row["stream"],)).fetchone() if row is not None else None)
        if row is None or latest is None or latest["id"] != row["id"] or \
                latest["type"] != "pipeline.position_trashed":
            return None
        item = self.repository.decode(row, "data_json")
        snapshot = item.get("data_json") or {}
        trashed = datetime.datetime.fromisoformat(item["created_at"])
        workflow_ids = [int(value) for value in snapshot.get("workflow_ids") or []]
        with self.repository.connect() as connection:
            documents = self._document_count_for_workflows(connection, workflow_ids)
        item.update({"pipeline_id": int(snapshot.get("pipeline_id") or 0),
                     "position_key": str(snapshot.get("position_key") or ""),
                     "snapshot_json": snapshot, "trashed_at": item["created_at"],
                     "kind": "position",
                     "title": snapshot.get("title") or snapshot.get("position_key") or "岗位",
                     "location": item.get("pipeline_name") or "流水线",
                     "count": len(workflow_ids), "document_count": documents,
                     "expires_at": (trashed + datetime.timedelta(days=30)).isoformat(
                         timespec="seconds")})
        return item

    def pipeline_position_trash_catalog(self):
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT e.id FROM events e "
                "JOIN (SELECT stream,MAX(id) AS id FROM events "
                "WHERE stream LIKE 'pipeline_position:%' GROUP BY stream) latest "
                "ON latest.id=e.id JOIN pipelines p "
                "ON p.id=CAST(json_extract(e.data_json,'$.pipeline_id') AS INTEGER) "
                "WHERE e.type='pipeline.position_trashed' AND p.trashed_at IS NULL "
                "ORDER BY e.created_at DESC,e.id DESC"
            ).fetchall()]
        return [self.pipeline_position_trash(trash_id) for trash_id in ids]

    def restore_pipeline_position(self, trash_id):
        item = self.pipeline_position_trash(trash_id)
        if item is None:
            raise ContractError("垃圾箱中没有这个岗位")
        pipeline = self.pipeline(item["pipeline_id"])
        if pipeline is None:
            raise ContractError("请先恢复岗位所属的流水线")
        snapshot = item.get("snapshot_json") or {}
        position = dict(snapshot.get("position") or {})
        employee_id = int(position.get("employee_id") or 0)
        if self.employee(employee_id) is None:
            raise ContractError("请先恢复这个岗位使用的员工")
        definition = pipeline.get("definition_json") or {}
        positions = list(definition.get("positions") or [])
        key = str(position.get("key") or "")
        if any(str(row.get("key")) == key for row in positions):
            raise ContractError("流水线中已经存在同名岗位")
        keys = [str(row.get("key")) for row in positions]
        previous_key = str(snapshot.get("previous_key") or "")
        next_key = str(snapshot.get("next_key") or "")
        if previous_key in keys:
            index = keys.index(previous_key) + 1
        elif next_key in keys:
            index = keys.index(next_key)
        else:
            index = max(0, min(int(snapshot.get("index") or 0), len(positions)))
        positions.insert(index, position)
        order = [str(row.get("key")) for row in positions]
        normalized = normalize_pipeline_definition(dict(
            definition, positions=positions,
            edges=[{"from": source, "to": target}
                   for source, target in zip(order, order[1:])]))
        task_ids = [int(value) for value in snapshot.get("task_ids") or []]
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE pipelines SET definition_json=?,updated_at=? WHERE id=? "
                "AND trashed_at IS NULL",
                (json.dumps(normalized, ensure_ascii=False), now, int(item["pipeline_id"])))
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                connection.execute(
                    "UPDATE tasks SET trashed_at=NULL,updated_at=? "
                    "WHERE id IN ({}) AND trashed_at IS NOT NULL".format(placeholders),
                    (now,) + tuple(task_ids))
            self.repository.event(
                item["stream"], "pipeline.position_restored",
                {"trash_id": int(trash_id)}, connection=connection)
        return self.pipeline(item["pipeline_id"])

    def delete_trashed_pipeline_position(self, trash_id, acknowledged_documents=None):
        item = self.pipeline_position_trash(trash_id)
        if item is None:
            raise ContractError("垃圾箱中没有这个岗位")
        workflow_ids = [int(value) for value in
                        (item.get("snapshot_json") or {}).get("workflow_ids") or []]
        artifact_refs = []
        with self.repository.connect() as connection:
            self._guard_document_loss(
                self._document_count_for_workflows(connection, workflow_ids),
                acknowledged_documents, "这个岗位")
            artifact_refs, task_ids = self._delete_workflows(connection, workflow_ids)
            self.repository.event(
                item["stream"], "pipeline.position_deleted",
                {"trash_id": int(trash_id)}, connection=connection)
        self._delete_artifact_files(artifact_refs)
        self._delete_task_input_files(task_ids)
        return True

    def purge_expired_pipeline_positions(self, retention_days=30):
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=max(1, int(retention_days)))).isoformat(
                      timespec="seconds")
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT e.id FROM events e JOIN ("
                "SELECT stream,MAX(id) AS id FROM events "
                "WHERE stream LIKE 'pipeline_position:%' GROUP BY stream"
                ") latest ON latest.id=e.id "
                "WHERE e.type='pipeline.position_trashed' AND e.created_at<=?",
                (cutoff,)
            ).fetchall()]
        purged = 0
        for trash_id in ids:
            try:
                self.delete_trashed_pipeline_position(trash_id, acknowledged_documents=0)
                purged += 1
            except ContractError:
                continue
        return purged

    def create_task(self, pipeline_id, title, payload, start_column_key=None):
        title = str(title or "").strip()
        if not title:
            raise ContractError("任务名称不能为空")
        now = utc_now()
        with self.repository.connect() as connection:
            pipeline = connection.execute(
                "SELECT definition_json FROM pipelines WHERE id=? AND trashed_at IS NULL",
                (int(pipeline_id),)).fetchone()
            if pipeline is None:
                raise ContractError("流水线不存在")
            definition = json.loads(pipeline["definition_json"])
            position_keys = {item["key"] for item in definition["positions"]}
            completed_keys = {item["key"] for item in definition.get("states") or []
                              if item.get("kind") == "done"}
            completed_keys.add("__completed")
            start_column_key = str(start_column_key or "").strip() or None
            if (start_column_key is not None and
                    start_column_key not in position_keys | completed_keys):
                raise ContractError("任务起始列不存在")
            try:
                task_id = connection.execute(
                    "INSERT INTO tasks(pipeline_id,start_column_key,opportunity_key,title,payload_json,state,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)", (int(pipeline_id), start_column_key,
                    self._opportunity_key_from_payload(payload), title,
                    json.dumps(payload or {}, ensure_ascii=False), "ready", now, now),).lastrowid
                task_state = {"pipeline_id": int(pipeline_id), "employee_id": None,
                              "title": title, "payload": copy.deepcopy(payload or {}),
                              "state": "ready", "trashed_at": None,
                              "start_column_key": start_column_key}
                self.repository.event(
                    "task:{}".format(task_id), "task.created",
                    {"task_id": task_id, "after": task_state}, connection=connection)
            except sqlite3.IntegrityError:
                key = self._opportunity_key_from_payload(payload)
                if not key:
                    raise
                existing = connection.execute(
                    "SELECT id FROM tasks WHERE pipeline_id=? AND opportunity_key=? "
                    "ORDER BY id LIMIT 1", (int(pipeline_id), key)).fetchone()
                if existing is None:
                    raise
                return int(existing["id"])
        return task_id
        
    def _create_task_atomic(self, connection, pipeline_id, title, payload, start_column_key, now):
        """Unused compatibility hook retained for embedders overriding creation."""
        return connection.execute(
            "INSERT INTO tasks(pipeline_id,start_column_key,opportunity_key,title,payload_json,state,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)", (int(pipeline_id), start_column_key,
            self._opportunity_key_from_payload(payload), title,
            json.dumps(payload or {}, ensure_ascii=False), "ready", now, now),).lastrowid

    def find_task_by_context(self, pipeline_id, key, value, include_trashed=False):
        """Find a live task by one small, caller-owned context identity value."""
        key = str(key or "").strip()
        value = str(value or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) or not value:
            return None
        with self.repository.connect() as connection:
            trash_clause = "" if include_trashed else " AND trashed_at IS NULL"
            if key == "opportunity_key":
                row = connection.execute(
                    "SELECT * FROM tasks WHERE pipeline_id=? AND opportunity_key=? "
                    "{} ORDER BY id LIMIT 1".format(trash_clause),
                    (int(pipeline_id), value),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM tasks WHERE pipeline_id=? {} "
                    "AND json_extract(payload_json,?)=? ORDER BY id DESC LIMIT 1".format(trash_clause),
                    (int(pipeline_id), "$.context.{}".format(key), value),
                ).fetchone()
        return self.repository.decode(row, "payload_json")

    def find_employee_task_by_context(self, employee_id, key, value, include_trashed=False):
        """Find a live direct employee task by one caller-owned identity value."""
        key = str(key or "").strip()
        value = str(value or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key) or not value:
            return None
        with self.repository.connect() as connection:
            trash_clause = "" if include_trashed else " AND trashed_at IS NULL"
            if key == "opportunity_key":
                row = connection.execute(
                    "SELECT * FROM tasks WHERE employee_id=? AND pipeline_id IS NULL "
                    "AND opportunity_key=? {} ORDER BY id LIMIT 1".format(trash_clause),
                    (int(employee_id), value),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM tasks WHERE employee_id=? AND pipeline_id IS NULL {} "
                    "AND json_extract(payload_json,?)=? ORDER BY id DESC LIMIT 1".format(trash_clause),
                    (int(employee_id), "$.context.{}".format(key), value),
                ).fetchone()
        return self.repository.decode(row, "payload_json")

    @staticmethod
    def _opportunity_key_from_payload(payload):
        payload = payload if isinstance(payload, dict) else {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        value = str(context.get("opportunity_key") or "").strip()
        return value[:240] or None

    def opportunity_identity_catalog(self, owner_type, owner_id):
        """Return the complete, unpaginated identity ledger for one owner."""
        owner_type = str(owner_type or "").strip()
        if owner_type not in ("pipeline", "employee"):
            raise ContractError("机会归属类型无效")
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT t.opportunity_key,t.id AS task_id,t.created_at,t.trashed_at,"
                "t.state,t.title,t.payload_json,wr.id AS workflow_id,wr.state AS workflow_state "
                "FROM tasks t LEFT JOIN workflow_runs wr ON wr.task_id=t.id "
                "WHERE ((?='pipeline' AND t.pipeline_id=?) OR "
                "(?='employee' AND t.employee_id=? AND t.pipeline_id IS NULL)) "
                "AND t.opportunity_key IS NOT NULL ORDER BY t.id",
                (owner_type, int(owner_id), owner_type, int(owner_id)),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                payload = json.loads(item.pop("payload_json") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
            item["analysis_decision"] = context.get("analysis_decision") or ""
            item["source_urls"] = [str(source.get("url") or "") for source in
                                    (context.get("evidence") or [])
                                    if isinstance(source, dict) and source.get("url")]
            item["trashed"] = bool(item.get("trashed_at"))
            result.append(item)
        return result

    def opportunity_catalog(self, query="", limit=0, include_output=False):
        """Project durable opportunity facts for the result/document surfaces.

        Opportunities intentionally remain ordinary employee or pipeline tasks;
        this is a read model over the existing task, workflow, employee-run and
        artifact facts, not a second source-of-truth table.  ``limit=0`` scans
        the complete live ledger so recurring discovery never silently drops
        older identities.  A positive limit only limits the returned view after
        the full scan and filtering have completed.
        """
        query = str(query or "").strip().casefold()
        try:
            limit = int(limit or 0)
        except (TypeError, ValueError):
            limit = 0
        if limit < 0:
            raise ContractError("机会目录 limit 不能小于 0")
        limit = min(limit, 10000) if limit else 0
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT t.id AS task_id,t.pipeline_id,t.employee_id,t.opportunity_key,"
                "t.title,t.payload_json,t.state AS task_state,t.created_at,t.updated_at,"
                "wr.id AS workflow_id,wr.state AS workflow_state,"
                "e.name AS employee_name,p.name AS pipeline_name "
                "FROM tasks t "
                "LEFT JOIN workflow_runs wr ON wr.task_id=t.id "
                "LEFT JOIN employees e ON e.id=t.employee_id "
                "LEFT JOIN pipelines p ON p.id=t.pipeline_id "
                "WHERE t.opportunity_key IS NOT NULL AND t.trashed_at IS NULL "
                "ORDER BY t.id DESC").fetchall()
            workflow_ids = [int(row["workflow_id"]) for row in rows
                            if row["workflow_id"] is not None]
            run_rows = []
            artifact_rows = []
            # Keep the scan unbounded while batching SQLite bind parameters.  A
            # single IN clause would hit SQLite's variable limit once a local
            # workspace grows beyond a few hundred workflow runs.
            for offset in range(0, len(workflow_ids), 500):
                chunk = workflow_ids[offset:offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                run_rows.extend(connection.execute(
                    "SELECT er.id,er.workflow_run_id,er.output_json "
                    "FROM employee_runs er WHERE er.workflow_run_id IN ({}) "
                    "ORDER BY er.id DESC".format(placeholders), chunk).fetchall())
                artifact_rows.extend(connection.execute(
                    "SELECT a.id,a.employee_run_id,a.name,a.ref,a.meta_json,a.created_at,"
                    "er.workflow_run_id FROM artifacts a JOIN employee_runs er "
                    "ON er.id=a.employee_run_id WHERE er.workflow_run_id IN ({}) "
                    "AND a.trashed_at IS NULL ORDER BY a.id DESC".format(placeholders),
                    chunk).fetchall())

        latest_result = {}
        for row in run_rows:
            workflow_id = int(row["workflow_run_id"])
            if workflow_id in latest_result:
                continue
            try:
                result = json.loads(row["output_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                result = {}
            latest_result[workflow_id] = result if isinstance(result, dict) else {}

        documents_by_workflow = {}
        for row in artifact_rows:
            workflow_id = int(row["workflow_run_id"])
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                meta = {}
            path = str(meta.get("path") or row["name"] or "")
            if not self.is_document(path):
                continue
            documents_by_workflow.setdefault(workflow_id, []).append({
                "id": int(row["id"]), "name": str(row["name"] or "产物"),
                "path": path, "ref": "artifact://{}".format(int(row["id"])),
                "created_at": row["created_at"],
            })

        raw_items = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            context = payload.get("context") if isinstance(payload, dict) else {}
            context = context if isinstance(context, dict) else {}
            workflow_id = int(row["workflow_id"]) if row["workflow_id"] is not None else 0
            result = latest_result.get(workflow_id) or {}
            evidence = [item for item in (context.get("evidence") or [])
                        if isinstance(item, dict)]
            item = {
                "opportunity_key": str(row["opportunity_key"] or ""),
                "task_id": int(row["task_id"]), "workflow_id": workflow_id,
                "title": str(row["title"] or "未命名机会"),
                "product": str(context.get("product") or ""),
                "marketplace_keyword": str(context.get("marketplace_keyword") or ""),
                "analysis_decision": str(context.get("analysis_decision") or ""),
                "decision_reason": str(context.get("decision_reason") or ""),
                "target_user": str(context.get("target_user") or ""),
                "jtbd": str(context.get("jtbd") or ""),
                "problem": str(context.get("problem") or ""),
                "evidence": copy.deepcopy(evidence),
                "evidence_count": len(evidence),
                "source_urls": [str(source.get("url") or "") for source in evidence
                                if source.get("url")],
                "summary": str(result.get("summary") or ""),
                "task_state": str(row["task_state"] or ""),
                "workflow_state": str(row["workflow_state"] or ""),
                "employee_id": int(row["employee_id"]) if row["employee_id"] is not None else 0,
                "employee_name": str(row["employee_name"] or ""),
                "pipeline_id": int(row["pipeline_id"]) if row["pipeline_id"] is not None else 0,
                "pipeline_name": str(row["pipeline_name"] or ""),
                "created_at": row["created_at"], "updated_at": row["updated_at"],
                "documents": copy.deepcopy(documents_by_workflow.get(workflow_id, [])),
            }
            if include_output:
                item["output"] = copy.deepcopy(result.get("output") or {})
            item["related_workflows"] = [{
                "workflow_id": workflow_id,
                "task_id": int(row["task_id"]),
                "employee_id": item["employee_id"],
                "employee_name": item["employee_name"],
                "pipeline_id": item["pipeline_id"],
                "pipeline_name": item["pipeline_name"],
                "task_state": item["task_state"],
                "workflow_state": item["workflow_state"],
                "updated_at": item["updated_at"],
            }]
            item["_search_text"] = " ".join([
                item["opportunity_key"], item["title"], item["product"],
                item["marketplace_keyword"], item["analysis_decision"],
                item["decision_reason"], item["target_user"], item["jtbd"],
                item["problem"], item["summary"],
                " ".join(str(source.get("title") or "") for source in evidence),
            ]).casefold()
            raw_items.append(item)

        # The same opportunity may legitimately have one discovery task and
        # one or more downstream pipeline tasks.  They share the durable key,
        # so the result surface must show one opportunity instead of making the
        # user reconcile duplicate rows.  Keep every related workflow as a
        # derived reference for drill-down and audit; only the richest record
        # supplies the headline fields.
        grouped = {}
        for candidate in raw_items:
            key = candidate["opportunity_key"]
            current = grouped.get(key)
            if current is None:
                grouped[key] = candidate
                continue
            current["related_workflows"].extend(candidate["related_workflows"])
            current["documents"].extend(candidate["documents"])
            current["_search_text"] += " " + candidate["_search_text"]
            # Prefer a direct employee analysis over a pipeline execution, then
            # prefer evidence/conclusion/summary and finally the newer record.
            score = lambda item: (
                1 if item.get("employee_id") else 0,
                1 if item.get("analysis_decision") else 0,
                int(item.get("evidence_count") or 0),
                1 if item.get("summary") else 0,
                str(item.get("updated_at") or ""),
            )
            if score(candidate) > score(current):
                promoted = candidate
                promoted["related_workflows"] = current["related_workflows"]
                promoted["documents"] = current["documents"]
                promoted["_search_text"] = current["_search_text"]
                grouped[key] = promoted

        items = []
        for item in grouped.values():
            # A document can be reachable through both the discovery and
            # downstream task.  Preserve each artifact once in the result.
            unique_documents = []
            seen_documents = set()
            for document in item.get("documents") or []:
                marker = document.get("id") or document.get("ref")
                if marker in seen_documents:
                    continue
                seen_documents.add(marker)
                unique_documents.append(document)
            item["documents"] = unique_documents
            item["related_workflows"] = sorted(
                item.get("related_workflows") or [],
                key=lambda value: (str(value.get("updated_at") or ""),
                                   int(value.get("workflow_id") or 0)),
                reverse=True)
            if query and query not in item.get("_search_text", ""):
                continue
            item.pop("_search_text", None)
            items.append(item)
        items.sort(key=lambda item: (str(item.get("updated_at") or ""),
                                     int(item.get("task_id") or 0)), reverse=True)
        # Always scan and filter the complete ledger before applying a caller's
        # presentation limit.  This keeps the identity/result read model honest:
        # a small UI page can be bounded without silently skipping older matches.
        return items[:limit] if limit else items

    def opportunity_detail(self, opportunity_key):
        """Return one opportunity with its full structured result and documents."""
        key = str(opportunity_key or "").strip()
        if not key:
            return None
        for item in self.opportunity_catalog(limit=0, include_output=True):
            if item.get("opportunity_key") == key:
                return item
        return None

    def opportunity_keys_missing_in_pipeline(self, employee_id, pipeline_id):
        """Find every employee opportunity that has no matching key in a pipeline."""
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT e.opportunity_key,e.id AS task_id,e.payload_json,e.state,wr.id AS workflow_id "
                "FROM tasks e LEFT JOIN workflow_runs wr ON wr.task_id=e.id "
                "WHERE e.employee_id=? AND e.pipeline_id IS NULL AND e.opportunity_key IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM tasks p WHERE p.pipeline_id=? "
                "AND p.opportunity_key=e.opportunity_key) ORDER BY e.id",
                (int(employee_id), int(pipeline_id)),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_task_inputs(self, task_id, items):
        """Replace a not-yet-compiled task's managed input snapshot metadata."""
        task_id = int(task_id)
        normalized = self._normalized_task_inputs(task_id, items)
        now = utc_now()
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM tasks WHERE id=? AND trashed_at IS NULL",
                (task_id,),).fetchone()
            if row is None:
                raise ContractError("任务不存在")
            payload = json.loads(row["payload_json"] or "{}")
            before_inputs = copy.deepcopy(payload.get("inputs") or [])
            payload["inputs"] = normalized
            connection.execute(
                "UPDATE tasks SET payload_json=?,updated_at=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), now, task_id))
            self.repository.event(
                "task:{}".format(task_id), "task.inputs_replaced",
                {"task_id": task_id, "before": {"inputs": before_inputs},
                 "after": {"inputs": copy.deepcopy(normalized)}}, connection=connection)
        return self.task(task_id)

    def _normalized_task_inputs(self, task_id, items):
        task_id = int(task_id)
        normalized = task_inputs.public(items)
        for item in normalized:
            match = task_inputs.INPUT_REF.fullmatch(str(item.get("ref") or ""))
            if not match or int(match.group(1)) != task_id:
                raise ContractError("任务资料引用无效")
        return normalized

    def delete_unstarted_task(self, task_id):
        task_id = int(task_id)
        with self.repository.connect() as connection:
            if connection.execute(
                    "SELECT 1 FROM workflow_runs WHERE task_id=?", (task_id,)).fetchone():
                raise ContractError("任务已经开始，不能撤销创建")
            row = connection.execute(
                "SELECT title,payload_json,state,trashed_at FROM tasks WHERE id=?",
                (task_id,)).fetchone()
            if row is None:
                raise ContractError("任务不存在")
            now = utc_now()
            changed = connection.execute(
                "UPDATE tasks SET state='canceled',trashed_at=?,updated_at=? "
                "WHERE id=? AND trashed_at IS NULL", (now, now, task_id)).rowcount
            if changed != 1:
                raise ContractError("任务不存在")
            self.repository.event(
                "task:{}".format(task_id), "task.trashed",
                {"task_id": task_id, "reason": "unstarted_deleted",
                 "before": {"title": row["title"],
                            "payload": json.loads(row["payload_json"] or "{}"),
                            "state": row["state"], "trashed_at": row["trashed_at"]},
                 "after": {"state": "canceled", "trashed_at": now}},
                connection=connection)
        self._delete_task_input_files([task_id])

    def _workflow_task_for_inputs(self, connection, workflow_run_id):
        row = connection.execute(
            "SELECT wr.state,t.id,t.payload_json FROM workflow_runs wr "
            "JOIN tasks t ON t.id=wr.task_id WHERE wr.id=? AND t.trashed_at IS NULL",
            (int(workflow_run_id),),).fetchone()
        if row is None:
            raise ContractError("任务不存在")
        return row

    def _editable_workflow_task(self, connection, workflow_run_id):
        row = self._workflow_task_for_inputs(connection, workflow_run_id)
        if row["state"] not in ("blocked", "failed", "canceled"):
            raise ContractError("请先停止任务，再修改任务资料")
        return row

    def workflow_task_for_inputs(self, workflow_run_id):
        with self.repository.connect() as connection:
            return dict(self._workflow_task_for_inputs(connection, workflow_run_id))

    def workflow_task_inputs_editable(self, workflow_run_id):
        with self.repository.connect() as connection:
            return dict(self._editable_workflow_task(connection, workflow_run_id))

    def workflow_task_input_file(self, workflow_run_id, input_id):
        """Return the immutable source path for one task attachment."""
        input_id = str(input_id or "")
        with self.repository.connect() as connection:
            row = self._workflow_task_for_inputs(connection, workflow_run_id)
            payload = json.loads(row["payload_json"] or "{}")
            item = next((value for value in payload.get("inputs") or []
                         if isinstance(value, dict) and str(value.get("id") or "") == input_id), None)
            if item is None:
                raise ContractError("任务资料不存在")
            source = task_inputs.source_for_item(self.root, int(row["id"]), item)
            return dict(item), source

    def append_workflow_task_inputs(self, workflow_run_id, items):
        now = utc_now()
        with self.repository.connect() as connection:
            row = self._workflow_task_for_inputs(connection, workflow_run_id)
            payload = json.loads(row["payload_json"] or "{}")
            current = task_inputs.public(payload.get("inputs") or [])
            before_inputs = copy.deepcopy(current)
            added = self._normalized_task_inputs(row["id"], items)
            known = {item.get("id") for item in current}
            current.extend(item for item in added if item.get("id") not in known)
            payload["inputs"] = current
            connection.execute(
                "UPDATE tasks SET payload_json=?,updated_at=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), now, int(row["id"])))
            self.repository.event(
                "workflow_run:{}".format(int(workflow_run_id)), "workflow.task_inputs_updated",
                {"task_id": int(row["id"]), "before": {"inputs": before_inputs},
                 "after": {"inputs": copy.deepcopy(current)},
                 "count": len(current)}, connection=connection)
            self.repository.event(
                "task:{}".format(int(row["id"])), "task.inputs_updated",
                {"workflow_run_id": int(workflow_run_id), "before": {"inputs": before_inputs},
                 "after": {"inputs": copy.deepcopy(current)}}, connection=connection)
        return self.workflow(workflow_run_id)

    def remove_workflow_task_input(self, workflow_run_id, input_id):
        input_id = str(input_id or "")
        now = utc_now()
        with self.repository.connect() as connection:
            row = self._editable_workflow_task(connection, workflow_run_id)
            payload = json.loads(row["payload_json"] or "{}")
            current = task_inputs.public(payload.get("inputs") or [])
            before_inputs = copy.deepcopy(current)
            removed = next((item for item in current if item.get("id") == input_id), None)
            if removed is None:
                raise ContractError("任务资料不存在")
            payload["inputs"] = [item for item in current if item.get("id") != input_id]
            connection.execute(
                "UPDATE tasks SET payload_json=?,updated_at=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), now, int(row["id"])))
            self.repository.event(
                "workflow_run:{}".format(int(workflow_run_id)), "workflow.task_inputs_updated",
                {"task_id": int(row["id"]), "before": {"inputs": before_inputs},
                 "after": {"inputs": copy.deepcopy(payload["inputs"])},
                 "removed": copy.deepcopy(removed),
                 "count": len(payload["inputs"])}, connection=connection)
            self.repository.event(
                "task:{}".format(int(row["id"])), "task.inputs_updated",
                {"workflow_run_id": int(workflow_run_id),
                 "before": {"inputs": before_inputs},
                 "after": {"inputs": copy.deepcopy(payload["inputs"])},
                 "removed": copy.deepcopy(removed)}, connection=connection)
        return self.workflow(workflow_run_id), int(row["id"]), removed

    def create_employee_task(self, employee_id, title, payload, index_identity=True):
        title = str(title or "").strip()
        if not title:
            raise ContractError("任务名称不能为空")
        now = utc_now()
        with self.repository.connect() as connection:
            if connection.execute(
                    "SELECT 1 FROM employees WHERE id=? AND trashed_at IS NULL",
                    (int(employee_id),)).fetchone() is None:
                raise ContractError("员工不存在")
            try:
                task_id = connection.execute(
                    "INSERT INTO tasks(pipeline_id,employee_id,opportunity_key,title,payload_json,state,created_at,updated_at) "
                    "VALUES(NULL,?,?,?,?,?,?,?)", (int(employee_id),
                    self._opportunity_key_from_payload(payload) if index_identity else None, title,
                    json.dumps(payload or {}, ensure_ascii=False), "ready", now, now),).lastrowid
                self.repository.event(
                    "task:{}".format(task_id), "task.created",
                    {"task_id": task_id, "after": {
                        "pipeline_id": None, "employee_id": int(employee_id),
                        "title": title, "payload": copy.deepcopy(payload or {}),
                        "state": "ready", "trashed_at": None}}, connection=connection)
            except sqlite3.IntegrityError:
                key = self._opportunity_key_from_payload(payload)
                if not key:
                    raise
                existing = connection.execute(
                    "SELECT id FROM tasks WHERE employee_id=? AND pipeline_id IS NULL "
                    "AND opportunity_key=? ORDER BY id LIMIT 1", (int(employee_id), key)).fetchone()
                if existing is None:
                    raise
                return int(existing["id"])
        return task_id

    # Employee validation cases use the same durable task storage, but keep the
    # private alias so their existing call sites remain explicit.
    def _create_employee_task(self, employee_id, title, payload):
        # Test cases are intentionally allowed to reuse one opportunity key;
        # they are validation samples, not production opportunity records.
        return self.create_employee_task(employee_id, title, payload, index_identity=False)

    def task(self, task_id):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?",
                                     (int(task_id),)).fetchone()
        return self.repository.decode(row, "payload_json")

    def audit_timeline(self, subject_type, subject_id):
        """Reconstruct the durable history for one pipeline asset.

        The timeline deliberately returns source events rather than a second
        mutable projection.  Consumers can explain a Bot answer and link back
        to the exact task/run/employee/artifact records that produced it.
        """
        subject_type = str(subject_type or "").strip().casefold()
        subject_id = int(subject_id)
        streams = set()
        subject = {"type": subject_type, "id": subject_id}
        all_events = None

        def ledger():
            nonlocal all_events
            if all_events is None:
                all_events = self.repository.events_all()
            return all_events

        def event_data(event):
            data = event.get("data_json") or {}
            return data if isinstance(data, dict) else {}

        def value_from_events(events, key):
            for event in reversed(events):
                data = event_data(event)
                if data.get(key) is not None:
                    return data[key]
                after = data.get("after")
                if isinstance(after, dict) and after.get(key) is not None:
                    return after[key]
            return None

        def stream_ids(events, prefix):
            result = set()
            for event in events:
                stream = str(event.get("stream") or "")
                if stream.startswith(prefix):
                    try:
                        result.add(int(stream[len(prefix):]))
                    except (TypeError, ValueError):
                        pass
            return result

        with self.repository.connect() as connection:
            if subject_type == "task":
                row = connection.execute(
                    "SELECT id,pipeline_id,employee_id FROM tasks WHERE id=?",
                    (subject_id,)).fetchone()
                if row is None:
                    task_events = [event for event in ledger()
                                   if event.get("stream") == "task:{}".format(subject_id)]
                    if not task_events:
                        return None
                    pipeline_id = value_from_events(task_events, "pipeline_id")
                    employee_id = value_from_events(task_events, "employee_id")
                    workflow_ids = {int(data["workflow_run_id"])
                                    for data in (event_data(event) for event in task_events)
                                    if data.get("workflow_run_id") is not None}
                else:
                    task_events = []
                    pipeline_id, employee_id = row["pipeline_id"], row["employee_id"]
                    workflow_rows = connection.execute(
                        "SELECT id FROM workflow_runs WHERE task_id=?", (subject_id,)).fetchall()
                    workflow_ids = {int(item["id"]) for item in workflow_rows}
                streams.add("task:{}".format(subject_id))
                streams.update("workflow_run:{}".format(item) for item in workflow_ids)
                employee_run_ids = {int(data["employee_run_id"])
                                    for data in (event_data(event) for event in ledger())
                                    if data.get("workflow_run_id") in workflow_ids
                                    and data.get("employee_run_id") is not None}
                streams.update("employee_run:{}".format(item) for item in employee_run_ids)
                subject.update({"pipeline_id": pipeline_id,
                                "employee_id": employee_id,
                                "workflow_run_ids": sorted(workflow_ids),
                                "employee_run_ids": sorted(employee_run_ids)})
            elif subject_type == "workflow":
                row = connection.execute(
                    "SELECT id,task_id FROM workflow_runs WHERE id=?", (subject_id,)).fetchone()
                if row is None:
                    workflow_events = [event for event in ledger()
                                       if event.get("stream") == "workflow_run:{}".format(subject_id)]
                    if not workflow_events:
                        return None
                    task_id = value_from_events(workflow_events, "task_id")
                else:
                    workflow_events = []
                    task_id = row["task_id"]
                streams.add("workflow_run:{}".format(subject_id))
                if task_id is not None:
                    streams.add("task:{}".format(task_id))
                employee_run_ids = {int(data["employee_run_id"])
                                    for data in (event_data(event) for event in ledger())
                                    if data.get("workflow_run_id") == subject_id
                                    and data.get("employee_run_id") is not None}
                streams.update("employee_run:{}".format(item) for item in employee_run_ids)
                subject.update({"task_id": task_id,
                                "employee_run_ids": sorted(employee_run_ids)})
            elif subject_type == "pipeline":
                row = connection.execute(
                    "SELECT id FROM pipelines WHERE id=?", (subject_id,)).fetchone()
                if row is None:
                    pipeline_events = [event for event in ledger()
                                       if event.get("stream") == "pipeline:{}".format(subject_id)]
                    if not pipeline_events:
                        return None
                else:
                    pipeline_events = []
                streams.add("pipeline:{}".format(subject_id))
                tasks = connection.execute(
                    "SELECT id FROM tasks WHERE pipeline_id=?", (subject_id,)).fetchall()
                task_ids = [item["id"] for item in tasks]
                related = [event for event in ledger()
                           if value_from_events([event], "pipeline_id") == subject_id]
                task_ids = sorted(set(task_ids) | stream_ids(related, "task:"))
                streams.update("task:{}".format(item) for item in task_ids)
                workflows = connection.execute(
                    "SELECT wr.id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                    "WHERE t.pipeline_id=?", (subject_id,)).fetchall()
                workflow_ids = [item["id"] for item in workflows]
                workflow_ids = sorted(set(workflow_ids) | stream_ids(related, "workflow_run:"))
                streams.update("workflow_run:{}".format(item) for item in workflow_ids)
                employee_run_ids = {int(data["employee_run_id"])
                                    for data in (event_data(event) for event in ledger())
                                    if data.get("workflow_run_id") in set(workflow_ids)
                                    and data.get("employee_run_id") is not None}
                streams.update("employee_run:{}".format(item) for item in employee_run_ids)
                subject.update({"task_ids": task_ids, "workflow_run_ids": workflow_ids,
                                "employee_run_ids": sorted(employee_run_ids)})
            elif subject_type == "employee":
                row = connection.execute(
                    "SELECT id FROM employees WHERE id=?", (subject_id,)).fetchone()
                if row is None:
                    employee_events = [event for event in ledger()
                                       if event.get("stream") == "employee:{}".format(subject_id)]
                    if not employee_events:
                        return None
                else:
                    employee_events = []
                streams.add("employee:{}".format(subject_id))
                releases = connection.execute(
                    "SELECT id FROM employee_releases WHERE employee_id=?", (subject_id,)).fetchall()
                release_ids = [item["id"] for item in releases]
                related = [event for event in ledger()
                           if value_from_events([event], "employee_id") == subject_id]
                release_ids = sorted(set(release_ids) | stream_ids(related, "employee_release:"))
                streams.update("employee_release:{}".format(item) for item in release_ids)
                tasks = connection.execute(
                    "SELECT id FROM tasks WHERE employee_id=?", (subject_id,)).fetchall()
                task_ids = sorted(set(item["id"] for item in tasks) | stream_ids(related, "task:"))
                streams.update("task:{}".format(item) for item in task_ids)
                run_rows = connection.execute(
                    "SELECT er.id FROM employee_runs er "
                    "JOIN employee_releases r ON r.id=er.employee_release_id "
                    "WHERE r.employee_id=?", (subject_id,)).fetchall()
                employee_run_ids = {int(item["id"]) for item in run_rows}
                employee_run_ids |= {int(data["employee_run_id"])
                                    for data in (event_data(event) for event in ledger())
                                    if data.get("employee_id") == subject_id
                                    and data.get("employee_run_id") is not None}
                streams.update("employee_run:{}".format(item) for item in employee_run_ids)
                subject.update({"task_ids": task_ids,
                                "employee_run_ids": sorted(employee_run_ids)})
            else:
                raise ContractError("不支持的审计对象类型")
        events = self.repository.events_for_streams(sorted(streams))
        return {"subject": subject, "events": events,
                "integrity": self.repository.verify_event_chain()}

    def start_workflow(self, task_id, source=None):
        source = source if isinstance(source, dict) else {}
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if task is None:
                raise ContractError("任务不存在")
            existing = connection.execute(
                "SELECT id FROM workflow_runs WHERE task_id=? ORDER BY id DESC LIMIT 1",
                (task["id"],)).fetchone()
            if existing is not None:
                return existing["id"]
            pipeline = None
            if task["pipeline_id"] is not None:
                pipeline = connection.execute(
                    "SELECT * FROM pipelines WHERE id=? AND trashed_at IS NULL",
                    (task["pipeline_id"],)).fetchone()
                if pipeline is None:
                    raise ContractError("流水线已移到垃圾箱")
                definition = json.loads(pipeline["definition_json"])
                start_key = self._pipeline_start(definition)
            else:
                employee = connection.execute(
                    "SELECT * FROM employees WHERE id=? AND trashed_at IS NULL",
                    (task["employee_id"],)).fetchone()
                if employee is None or employee["active_release_id"] is None:
                    raise ContractError("员工尚未发布")
                definition = {
                    "schema": "runteams.pipeline/v1",
                    "positions": [{"key": "employee", "name": employee["name"],
                                   "employee_id": employee["id"]}],
                    "edges": [],
                }
                start_key = "employee"
            order = pipeline_order(definition)
            start_column_key = str(task["start_column_key"] or "").strip() or start_key
            states = {item["key"]: item for item in definition.get("states") or []}
            manually_completed = (start_column_key == "__completed" or
                                  states.get(start_column_key, {}).get("kind") == "done")
            if start_column_key not in order and not manually_completed:
                raise ContractError("任务起始列已不在工作流中")
            positions = []
            if manually_completed:
                positions = list(definition["positions"])
            else:
                for position in definition["positions"]:
                    if position.get("kind") == "approval":
                        positions.append(dict(position))
                        continue
                    employee = connection.execute(
                        "SELECT * FROM employees WHERE id=? AND trashed_at IS NULL",
                        (position["employee_id"],)).fetchone()
                    if employee is None or employee["active_release_id"] is None:
                        raise ContractError("岗位 {} 的员工尚未发布".format(position["name"]))
                    release = connection.execute("SELECT * FROM employee_releases WHERE id=?",
                                                 (employee["active_release_id"],)).fetchone()
                    release_snapshot = json.loads(release["snapshot_json"])
                    self._assert_credentials_ready(release_snapshot)
                    self._assert_native_dependencies_ready(release_snapshot)
                    positions.append(dict(position, employee_release_id=release["id"],
                                          release_digest=release["digest"],
                                          employee=release_snapshot))
            source_ref = {key: source[key] for key in (
                "kind", "chat_id", "conversation_id", "automation_id",
                "automation_run_id") if source.get(key) not in (None, "")}
            request_context = self.repository.current_audit_context()
            for key in ("actor_id", "correlation_id"):
                if request_context.get(key) and key not in source_ref:
                    source_ref[key] = request_context[key]
            snapshot = {"schema": "runteams.workflow-run/v1",
                        "pipeline_id": pipeline["id"] if pipeline is not None else None,
                        "pipeline_name": pipeline["name"] if pipeline is not None else "",
                        "employee_id": task["employee_id"],
                        "source": source_ref,
                        "definition": dict(definition, positions=positions),
                        "task": {"id": task["id"], "title": task["title"],
                                 "start_column_key": start_column_key,
                                 "payload": json.loads(task["payload_json"])}}
            now = utc_now()
            workflow_state = ("completed" if manually_completed else
                              "paused" if pipeline is not None and pipeline["paused_at"]
                              else "ready")
            run_id = connection.execute(
                "INSERT INTO workflow_runs(task_id,state,available_at,cursor_key,snapshot_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)", (task["id"], workflow_state,
                None if manually_completed else now,
                None if manually_completed else start_column_key,
                json.dumps(snapshot, ensure_ascii=False), now, now),).lastrowid
            connection.execute("UPDATE tasks SET state=?,updated_at=? WHERE id=?",
                               (workflow_state, now, task["id"]))
            self.repository.event(
                "workflow_run:{}".format(run_id), "workflow.compiled",
                {"task_id": int(task["id"]),
                 "pipeline_id": int(pipeline["id"]) if pipeline is not None else None,
                 "employee_release_ids": [item.get("employee_release_id") for item in positions
                                          if item.get("employee_release_id")],
                 "initial_state": start_column_key if manually_completed else None,
                 "source": source_ref},
                connection=connection)
            self.repository.event(
                "task:{}".format(int(task["id"])), "task.workflow_compiled",
                {"task_id": int(task["id"]), "workflow_run_id": int(run_id),
                 "pipeline_id": int(pipeline["id"]) if pipeline is not None else None,
                 "snapshot_digest": digest(snapshot), "source": source_ref},
                connection=connection)
            automation_id = source.get("automation_id")
            if automation_id not in (None, ""):
                event_payload = {
                    "workflow_run_id": int(run_id), "task_id": int(task["id"]),
                    "automation_run_id": int(source.get("automation_run_id") or 0),
                }
                if pipeline is not None:
                    event_payload["pipeline_id"] = int(pipeline["id"])
                else:
                    event_payload["employee_id"] = int(task["employee_id"])
                self.repository.event(
                    "automation:{}".format(int(automation_id)),
                    "automation.workflow_started",
                    event_payload,
                    connection=connection)
        return run_id

    def _assert_employee_trial_start_allowed(self, employee_id, repair_validation=False):
        if repair_validation:
            return
        repair = self.employee_repair_status(employee_id)
        if repair and repair["state"] in ("queued", "repairing", "validating"):
            raise ContractError("AI 正在修复员工，重新验证完成前不能另外运行用例")

    def start_employee_trial(self, employee_id, test_id, allow_parallel=False,
                             repair_validation=False, draft_override=None):
        """Compile one saved employee case into an ordinary durable Workflow."""
        employee = self.employee(employee_id)
        if employee is None:
            raise ContractError("员工不存在")
        self._assert_employee_trial_start_allowed(
            employee_id, repair_validation=repair_validation)
        candidate_employee = copy.deepcopy(employee)
        if draft_override is not None:
            candidate_employee["draft_json"] = normalize_employee_draft(draft_override)
        draft = normalize_employee_draft(candidate_employee["draft_json"])
        test_id = str(test_id or "").strip()
        case = next((item for item in draft["tests"] if item["id"] == test_id), None)
        if case is None:
            raise ContractError("测试用例不存在")
        candidate, checks = self._release_snapshot(candidate_employee, verify=True)
        self._assert_credentials_ready(candidate)
        candidate_digest = self._employee_validation_digest(candidate_employee)

        # Direct callers keep idempotent single-run behavior. Stability batches
        # explicitly opt into independent parallel samples.
        if not allow_parallel:
            for existing in self.employee_trials(employee["id"]):
                trial = (existing.get("snapshot_json") or {}).get("trial") or {}
                if (trial.get("test_id") == test_id and
                        trial.get("candidate_digest") == candidate_digest and
                        existing.get("state") not in WORKFLOW_TERMINAL_STATES):
                    return existing

        positions = [{
            "key": "subject", "name": employee["name"],
            "employee_id": employee["id"], "employee_release_id": None,
            "release_digest": None, "employee": candidate,
        }]
        edges = []
        downstream_id = case.get("downstream_employee_id")
        if downstream_id is not None:
            if int(downstream_id) == int(employee["id"]):
                raise ContractError("下游员工不能与被测试员工相同")
            downstream = self.employee(downstream_id)
            if downstream is None or not downstream.get("active_release_id"):
                raise ContractError("下游员工不存在或尚未发布")
            release = downstream["active_release"]
            downstream_snapshot = release["snapshot_json"]
            self._assert_credentials_ready(downstream_snapshot)
            positions.append({
                "key": "downstream", "name": downstream["name"],
                "employee_id": downstream["id"],
                "employee_release_id": release["id"],
                "release_digest": release["digest"],
                "employee": downstream_snapshot,
            })
            edges.append({"from": "subject", "to": "downstream"})

        task_id = self._create_employee_task(employee["id"], case["name"], case["work_order"])
        now = utc_now()
        snapshot = {
            "schema": "runteams.workflow-run/v1",
            "pipeline_id": None,
            "pipeline_name": "",
            "definition": {"schema": "runteams.pipeline/v1",
                           "positions": positions, "edges": edges},
            "task": {"id": task_id, "title": case["name"],
                     "payload": case["work_order"]},
            "trial": {"employee_id": employee["id"], "test_id": test_id,
                      "candidate_digest": candidate_digest,
                      "expected_status": case["expected_status"],
                      "expected_route": case.get("expected_route"),
                      "covers": case.get("covers") or [],
                      "fixtures": case.get("fixtures") or []},
        }
        with self.repository.connect() as connection:
            run_id = connection.execute(
                "INSERT INTO workflow_runs(task_id,state,available_at,cursor_key,snapshot_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)", (task_id, "ready", now, "subject",
                json.dumps(snapshot, ensure_ascii=False), now, now),).lastrowid
            self.repository.event(
                "workflow_run:{}".format(run_id), "workflow.compiled",
                {"employee_release_ids": [item["employee_release_id"] for item in positions
                                          if item["employee_release_id"] is not None],
                 "trial_employee_id": employee["id"], "checks": checks},
                connection=connection)
        return self._trial_result(self.workflow(run_id), employee)

    def start_employee_trial_samples(self, employee_id, test_id, fresh=False,
                                     repair_validation=False, draft_override=None):
        """Start the independent samples required for one stable case result."""
        with self._trial_start_lock:
            employee = self.employee(employee_id)
            if employee is None:
                raise ContractError("员工不存在")
            self._assert_employee_trial_start_allowed(
                employee_id, repair_validation=repair_validation)
            candidate_employee = copy.deepcopy(employee)
            if draft_override is not None:
                candidate_employee["draft_json"] = normalize_employee_draft(
                    draft_override)
            draft = normalize_employee_draft(candidate_employee["draft_json"])
            test_id = str(test_id or "").strip()
            if not any(item["id"] == test_id for item in draft["tests"]):
                raise ContractError("测试用例不存在")
            candidate_digest = self._employee_validation_digest(candidate_employee)
            history = []
            for existing in self.employee_trials(employee["id"]):
                trial = (existing.get("snapshot_json") or {}).get("trial") or {}
                if (trial.get("test_id") == test_id and
                        trial.get("candidate_digest") == candidate_digest):
                    history.append(existing)
            active = [item for item in history
                      if item.get("state") not in WORKFLOW_TERMINAL_STATES]
            if active:
                return active
            settled = [item for item in history
                       if (item.get("trial_result") or {}).get("verdict")
                       in ("matched", "mismatched")]
            count = (EMPLOYEE_TRIAL_SAMPLE_COUNT if fresh else
                     max(0, EMPLOYEE_TRIAL_SAMPLE_COUNT - len(settled)))
            return [self.start_employee_trial(
                employee_id, test_id, allow_parallel=True, repair_validation=True,
                draft_override=draft)
                    for _index in range(count)]

    def start_all_employee_trials(self, employee_id, repair_validation=False,
                                  draft_override=None):
        employee = self.employee(employee_id)
        if employee is None:
            raise ContractError("员工不存在")
        self._assert_employee_trial_start_allowed(
            employee_id, repair_validation=repair_validation)
        draft = normalize_employee_draft(
            draft_override if draft_override is not None else employee["draft_json"])
        tests = draft["tests"]
        if not tests:
            raise ContractError("这名员工还没有测试用例")
        started = []
        for item in tests:
            started.extend(self.start_employee_trial_samples(
                employee_id, item["id"], repair_validation=True,
                draft_override=draft))
        return started

    def employee_trials(self, employee_id, candidate_digest=None):
        employee = self.employee(employee_id)
        if employee is None:
            raise ContractError("员工不存在")
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT wr.id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                "WHERE t.employee_id=? ORDER BY wr.id DESC", (int(employee_id),)).fetchall()]
        return [self._trial_result(
            self.workflow(run_id), employee, candidate_digest=candidate_digest)
                for run_id in ids]

    def _employee_repair_events(self, employee_id=None):
        arguments = []
        where = "type LIKE 'employee.repair_%'"
        if employee_id is not None:
            where += " AND CAST(json_extract(data_json,'$.employee_id') AS INTEGER)=?"
            arguments.append(int(employee_id))
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE {} ORDER BY id".format(where),
                tuple(arguments)).fetchall()
        return [self.repository.decode(row, "data_json") for row in rows]

    @staticmethod
    def _employee_repair_record(events):
        if not events:
            return None
        latest = events[-1]
        data = dict(latest.get("data_json") or {})
        initial = dict((events[0].get("data_json") or {}))
        base_digest = (data.get("base_digest") or initial.get("base_digest") or
                       initial.get("candidate_digest") or "")
        return {
            "id": latest["stream"].split(":", 1)[-1],
            "stream": latest["stream"],
            "employee_id": int(data.get("employee_id") or 0),
            "state": latest["type"].split("employee.repair_", 1)[-1],
            "message": str(data.get("message") or ""),
            "phase": str(data.get("phase") or ""),
            "base_digest": base_digest,
            "candidate_digest": data.get("candidate_digest") or base_digest,
            "candidate_draft": copy.deepcopy(data.get("candidate_draft")),
            "workflow_ids": [int(value) for value in data.get("workflow_ids") or []],
            "failed_test_ids": [str(value) for value in data.get("failed_test_ids") or []],
            "created_at": events[0]["created_at"],
            "updated_at": latest["created_at"],
        }

    @staticmethod
    def _employee_repair_data(repair, **updates):
        data = {
            "employee_id": repair["employee_id"],
            "base_digest": repair.get("base_digest") or repair.get("candidate_digest") or "",
            "candidate_digest": repair.get("candidate_digest") or "",
            "failed_test_ids": list(repair.get("failed_test_ids") or []),
            "workflow_ids": list(repair.get("workflow_ids") or []),
            "phase": repair.get("phase") or "",
            "message": repair.get("message") or "",
        }
        if repair.get("candidate_draft") is not None:
            data["candidate_draft"] = copy.deepcopy(repair["candidate_draft"])
        data.update(updates)
        return data

    def _employee_repair_records(self, employee_id=None):
        grouped = {}
        for event in self._employee_repair_events(employee_id):
            grouped.setdefault(event["stream"], []).append(event)
        return [self._employee_repair_record(events) for events in grouped.values()]

    def _refresh_employee_repair(self, repair):
        if not repair or repair["state"] != "validating":
            return repair
        # Several browser polls may observe the same terminal validation batch.
        # Serialize the final transition and re-read the stream inside the lock so
        # only one durable completed/failed event is written.
        with self._repair_claim_lock:
            current = self._employee_repair_record(
                self.repository.events(repair["stream"]))
            if not current or current["state"] != "validating":
                return current or repair
            if not current["workflow_ids"]:
                return current
            if not current.get("candidate_draft"):
                self.repository.event(
                    current["stream"], "employee.repair_failed",
                    self._employee_repair_data(
                        current, message="旧版候选修复无法安全恢复，已停止。"))
                return self._employee_repair_record(
                    self.repository.events(current["stream"]))
            placeholders = ",".join("?" for _value in current["workflow_ids"])
            with self.repository.connect() as connection:
                rows = connection.execute(
                    "SELECT id,state FROM workflow_runs WHERE id IN ({})".format(
                        placeholders), tuple(current["workflow_ids"])).fetchall()
            if len(rows) != len(current["workflow_ids"]) or any(
                    row["state"] not in WORKFLOW_TERMINAL_STATES for row in rows):
                return current
            employee = self.employee(current["employee_id"])
            if employee is None:
                message = "员工不存在，候选修复已丢弃。"
                self.repository.event(current["stream"], "employee.repair_failed",
                                      self._employee_repair_data(
                                          current, message=message))
                return self._employee_repair_record(
                    self.repository.events(current["stream"]))
            if self._employee_validation_digest(employee) != current["base_digest"]:
                message = "员工草稿已经变化，候选修复已丢弃，没有覆盖你的修改。"
                self.repository.event(current["stream"], "employee.repair_failed",
                                      self._employee_repair_data(
                                          current, message=message))
                return self._employee_repair_record(
                    self.repository.events(current["stream"]))
            candidate = copy.deepcopy(employee)
            candidate["draft_json"] = normalize_employee_draft(
                current["candidate_draft"])
            trials = self.employee_trials(
                current["employee_id"],
                candidate_digest=current["candidate_digest"])
            coverage = self.employee_coverage(candidate, trials=trials)
            if current.get("phase") == "targeted":
                required = int(coverage.get("required_runs") or
                               EMPLOYEE_TRIAL_SAMPLE_COUNT)
                targeted_passed = all(
                    int((coverage.get("runs") or {}).get(test_id, {}).get("passed") or 0)
                    >= required and
                    int((coverage.get("runs") or {}).get(test_id, {}).get("failed") or 0) == 0
                    for test_id in current["failed_test_ids"])
                if not targeted_passed:
                    message = ("候选修复没有通过原失败场景，已丢弃；"
                               "员工和原验证结果保持不变。")
                    self.repository.event(
                        current["stream"], "employee.repair_failed",
                        self._employee_repair_data(current, message=message))
                    return self._employee_repair_record(
                        self.repository.events(current["stream"]))
                started = self.start_all_employee_trials(
                    current["employee_id"], repair_validation=True,
                    draft_override=current["candidate_draft"])
                workflow_ids = [item["id"] for item in started]
                if not workflow_ids:
                    workflow_ids = current["workflow_ids"]
                data = self._employee_repair_data(
                    current, phase="regression", workflow_ids=workflow_ids,
                    message="失败场景已通过，正在验证其他场景没有回归。")
                self.repository.event(
                    current["stream"], "employee.repair_validating", data)
                return self._employee_repair_record(
                    self.repository.events(current["stream"]))
            if coverage["passed"]:
                self.update_employee(
                    employee["id"], employee["name"], current["candidate_draft"],
                    preserve_tests=True)
                message = "AI 修复已通过完整验证并应用，全部场景稳定通过。"
                self.repository.event(
                    current["stream"], "employee.repair_completed",
                    self._employee_repair_data(current, message=message))
            else:
                baseline = self.employee_coverage(
                    employee, trials=self.employee_trials(employee["id"]))
                baseline_passed = {test_id for test_id, facts in
                                   (baseline.get("runs") or {}).items()
                                   if int(facts.get("passed") or 0) >=
                                   int(baseline.get("required_runs") or
                                       EMPLOYEE_TRIAL_SAMPLE_COUNT)
                                   and int(facts.get("failed") or 0) == 0}
                regressed = sorted(test_id for test_id in baseline_passed
                                   if int((coverage.get("runs") or {}).get(
                                       test_id, {}).get("failed") or 0) > 0)
                suffix = (" 回归失败：{}。".format("、".join(regressed))
                          if regressed else "")
                message = ("候选修复没有通过完整回归，已丢弃；"
                           "员工和原验证结果保持不变。" + suffix)
                self.repository.event(
                    current["stream"], "employee.repair_failed",
                    self._employee_repair_data(current, message=message))
            return self._employee_repair_record(
                self.repository.events(current["stream"]))

    def refresh_employee_repairs(self):
        refreshed = []
        for repair in self._employee_repair_records():
            if repair["state"] == "validating":
                try:
                    refreshed.append(self._refresh_employee_repair(repair))
                except Exception as exc:
                    latest = self._employee_repair_record(
                        self.repository.events(repair["stream"]))
                    if latest and latest["state"] == "validating":
                        self.repository.event(
                            latest["stream"], "employee.repair_failed",
                            self._employee_repair_data(
                                latest, message=(str(exc)[:360] or
                                                 "候选修复验证失败")))
                        latest = self._employee_repair_record(
                            self.repository.events(repair["stream"]))
                    refreshed.append(latest)
        return refreshed

    def employee_repair_status(self, employee_id):
        employee = self.employee(employee_id)
        if employee is None:
            raise ContractError("员工不存在")
        records = sorted(self._employee_repair_records(employee_id),
                         key=lambda item: item["updated_at"])
        if not records:
            return None
        try:
            return self._refresh_employee_repair(records[-1])
        except Exception as exc:
            latest = self._employee_repair_record(
                self.repository.events(records[-1]["stream"]))
            if latest and latest["state"] == "validating":
                self.repository.event(
                    latest["stream"], "employee.repair_failed",
                    self._employee_repair_data(
                        latest, message=(str(exc)[:360] or "候选修复验证失败")))
                latest = self._employee_repair_record(
                    self.repository.events(latest["stream"]))
            return latest

    def start_employee_repair(self, employee_id):
        employee = self.employee(employee_id)
        if employee is None:
            raise ContractError("员工不存在")
        current = self.employee_repair_status(employee_id)
        if current and current["state"] in ("queued", "repairing", "validating"):
            return current
        trials = self.employee_trials(employee_id)
        candidate_digest = self._employee_validation_digest(employee)
        if any(item.get("state") not in WORKFLOW_TERMINAL_STATES and
               ((item.get("snapshot_json") or {}).get("trial") or {}).get(
                   "candidate_digest") == candidate_digest
               for item in trials):
            raise ContractError("请等待当前验证完成后再使用 AI 修复")
        coverage = self.employee_coverage(employee, trials=trials)
        failed_test_ids = [test_id for test_id, facts in coverage["runs"].items()
                           if int(facts.get("failed") or 0) > 0]
        if not failed_test_ids:
            raise ContractError("当前没有需要 AI 修复的失败场景")
        repair_id = uuid.uuid4().hex
        stream = "employee_repair:" + repair_id
        data = {"employee_id": int(employee_id),
                "base_digest": candidate_digest,
                "candidate_digest": candidate_digest,
                "failed_test_ids": failed_test_ids,
                "message": "AI 修复已排队。"}
        self.repository.event(stream, "employee.repair_queued", data)
        return self._employee_repair_record(self.repository.events(stream))

    def claim_employee_repair(self):
        with self._repair_claim_lock:
            queued = sorted((item for item in self._employee_repair_records()
                             if item["state"] == "queued"),
                            key=lambda item: item["created_at"])
            if not queued:
                return None
            repair = queued[0]
            data = self._employee_repair_data(
                repair, message="AI 正在分析失败原因并修复员工。")
            self.repository.event(
                repair["stream"], "employee.repair_repairing", data)
            repair = dict(repair)
            repair.update({"state": "repairing", "message": data["message"]})
            return repair

    def recover_interrupted_repairs(self):
        recovered = []
        for repair in self._employee_repair_records():
            if repair["state"] != "repairing":
                continue
            data = self._employee_repair_data(
                repair, message="服务恢复后重新开始 AI 修复。")
            self.repository.event(repair["stream"], "employee.repair_queued", data)
            recovered.append(repair["id"])
        return recovered

    def _employee_repair_failures(self, employee, failed_test_ids):
        draft = normalize_employee_draft(employee["draft_json"])
        cases = {item["id"]: item for item in draft["tests"]}
        histories = {test_id: [] for test_id in failed_test_ids}
        for trial in self.employee_trials(employee["id"]):
            result = trial.get("trial_result") or {}
            test_id = result.get("test_id")
            if test_id not in histories or result.get("stale") or result.get("verdict") != "mismatched":
                continue
            subject_runs = [item for item in trial.get("employee_runs") or []
                            if item.get("position_key") == "subject"]
            subject = subject_runs[-1] if subject_runs else {}
            histories[test_id].append({
                "expected_status": result.get("expected_status"),
                "actual_status": result.get("actual_status"),
                "expected_route": result.get("expected_route"),
                "actual_route": result.get("actual_route"),
                "output": subject.get("output_json") or {},
            })
        return [{"test": copy.deepcopy(cases[test_id]),
                 "failed_samples": histories.get(test_id, [])[:6]}
                for test_id in failed_test_ids if test_id in cases]

    def _employee_repair_protected_tests(self, employee, failed_test_ids):
        draft = normalize_employee_draft(employee["draft_json"])
        cases = {item["id"]: item for item in draft["tests"]}
        trials = self.employee_trials(employee["id"])
        coverage = self.employee_coverage(employee, trials=trials)
        required = int(coverage.get("required_runs") or EMPLOYEE_TRIAL_SAMPLE_COUNT)
        protected = []
        for test_id, facts in (coverage.get("runs") or {}).items():
            if (test_id in failed_test_ids or
                    int(facts.get("passed") or 0) < required or
                    int(facts.get("failed") or 0) > 0 or test_id not in cases):
                continue
            samples = []
            for trial in trials:
                result = trial.get("trial_result") or {}
                if (result.get("test_id") != test_id or result.get("stale") or
                        result.get("verdict") != "matched"):
                    continue
                subject_runs = [item for item in trial.get("employee_runs") or []
                                if item.get("position_key") == "subject"]
                subject = subject_runs[-1] if subject_runs else {}
                samples.append({"actual_status": result.get("actual_status"),
                                "output": subject.get("output_json") or {}})
                if len(samples) >= EMPLOYEE_TRIAL_SAMPLE_COUNT:
                    break
            protected.append({"test": copy.deepcopy(cases[test_id]),
                              "passing_samples": samples})
        return protected

    def _employee_repair_capability_contract(self, employee):
        """Describe the exact skill/tool boundary the repair model must preserve."""
        contract = []
        draft = normalize_employee_draft(employee["draft_json"])
        for reference in draft["capabilities"]:
            if reference.get("plugin_id"):
                continue
            package = self.package(reference["package_id"])
            if package is None:
                continue
            capabilities = (package.get("manifest_json") or {}).get("capabilities") or []
            contract.append({
                "package": package["key"],
                "skill": package.get("manifest_json", {}).get("display_name") or
                         package.get("manifest_json", {}).get("name") or package["key"],
                "callable_tools": ["{}/{}".format(package["key"], item["id"])
                                   for item in capabilities
                                   if item.get("kind") == "tool"],
            })
        return contract

    @staticmethod
    def _merge_employee_repair(employee, proposed):
        original = normalize_employee_draft(employee["draft_json"])
        proposed = proposed if isinstance(proposed, dict) else {}
        proposed_program = proposed.get("program") if isinstance(
            proposed.get("program"), dict) else {}
        proposed_steps = {str(item.get("id") or ""): item for item in
                          proposed_program.get("steps") or [] if isinstance(item, dict)}
        repaired = copy.deepcopy(original)
        role = str(proposed.get("role") or proposed.get("instructions") or "").strip()
        if role:
            repaired["role"] = role
        objective = str(proposed_program.get("objective") or "").strip()
        if objective:
            repaired["program"]["objective"] = objective
        for step in repaired["program"]["steps"]:
            candidate = proposed_steps.get(step["id"]) or {}
            instruction = str(candidate.get("instruction") or
                              candidate.get("instructions") or "").strip()
            if instruction:
                step["instruction"] = instruction
        acceptance = proposed_program.get("acceptance")
        if acceptance is None:
            delivery = proposed_program.get("delivery") or {}
            acceptance = str(delivery.get("acceptance_criteria") or "").splitlines()
        if isinstance(acceptance, list):
            values = [str(item).strip() for item in acceptance if str(item).strip()]
            if values:
                repaired["program"]["acceptance"] = values
        # Tests and business contracts are the immutable acceptance target.  A repair
        # may improve behavior instructions, but cannot move the goalposts.
        repaired["tests"] = copy.deepcopy(original["tests"])
        repaired["interface"] = copy.deepcopy(original["interface"])
        repaired["capabilities"] = copy.deepcopy(original["capabilities"])
        repaired["runtime"] = copy.deepcopy(original["runtime"])
        return normalize_employee_draft(repaired)

    def execute_employee_repair(self, repair, runtime):
        try:
            employee = self.employee(repair["employee_id"])
            if employee is None:
                raise ContractError("员工不存在")
            if self._employee_validation_digest(employee) != repair["base_digest"]:
                raise ContractError("员工草稿已经变化，请根据最新验证结果重新修复")
            failures = self._employee_repair_failures(
                employee, repair["failed_test_ids"])
            protected = self._employee_repair_protected_tests(
                employee, repair["failed_test_ids"])
            repair_input = copy.deepcopy(employee)
            repair_input["repair_capability_contract"] = \
                self._employee_repair_capability_contract(employee)
            proposed = runtime(repair_input, failures, protected)
            current = self.employee(repair["employee_id"])
            if self._employee_validation_digest(current) != repair["base_digest"]:
                raise ContractError("员工草稿已经变化，AI 修复没有覆盖你的修改")
            repaired = self._merge_employee_repair(current, proposed)
            if digest(repaired) == digest(normalize_employee_draft(current["draft_json"])):
                raise ContractError("AI 没有产生有效的员工修复")
            candidate = copy.deepcopy(current)
            candidate["draft_json"] = repaired
            candidate_digest = self._employee_validation_digest(candidate)
            started = []
            for test_id in repair["failed_test_ids"]:
                started.extend(self.start_employee_trial_samples(
                    current["id"], test_id, fresh=True, repair_validation=True,
                    draft_override=repaired))
            data = self._employee_repair_data(
                repair, base_digest=repair["base_digest"],
                candidate_digest=candidate_digest,
                candidate_draft=copy.deepcopy(repaired), phase="targeted",
                workflow_ids=[item["id"] for item in started],
                message="候选修复已生成，正在复测原失败场景。")
            self.repository.event(
                repair["stream"], "employee.repair_validating", data)
            return self._employee_repair_record(self.repository.events(repair["stream"]))
        except Exception as exc:
            data = self._employee_repair_data(
                repair, message=str(exc)[:360] or "AI 自动修复失败")
            self.repository.event(repair["stream"], "employee.repair_failed", data)
            raise

    def _trial_result(self, workflow, employee=None, candidate_digest=None):
        if workflow is None:
            return None
        snapshot = workflow.get("snapshot_json") or {}
        trial = snapshot.get("trial") or {}
        if not trial:
            return workflow
        employee = employee or self.employee(trial.get("employee_id"))
        current_digest = candidate_digest
        if current_digest is None and employee is not None:
            try:
                current_digest = self._employee_validation_digest(employee)
            except ContractError:
                pass
        subject_runs = [item for item in workflow.get("employee_runs") or []
                        if item.get("position_key") == "subject"]
        downstream_runs = [item for item in workflow.get("employee_runs") or []
                           if item.get("position_key") == "downstream"]
        subject = subject_runs[-1] if subject_runs else None
        downstream = downstream_runs[-1] if downstream_runs else None
        actual_status = (subject or {}).get("state")
        expected_status = trial.get("expected_status") or "completed"
        expected_route = str(trial.get("expected_route") or "").strip()
        subject_result = (subject or {}).get("output_json") or {}
        subject_output = (subject_result.get("output")
                          if isinstance(subject_result, dict) else {}) or {}
        actual_route = (str(subject_output.get("route") or "").strip()
                        if isinstance(subject_output, dict) else "")
        settled = actual_status in ("completed", "blocked", "needs_human", "failed")
        status_matched = settled and actual_status == expected_status
        route_matched = not expected_route or actual_route == expected_route
        value = dict(workflow)
        value["trial_result"] = {
            "test_id": trial.get("test_id"),
            "expected_status": expected_status,
            "actual_status": actual_status,
            "expected_route": expected_route or None,
            "actual_route": actual_route or None,
            "verdict": ("matched" if status_matched and route_matched
                        else "mismatched" if settled else "pending"),
            "stale": bool(current_digest and
                          current_digest != trial.get("candidate_digest")),
            "downstream_status": (downstream or {}).get("state"),
            "covers": trial.get("covers") or [],
        }
        return value

    def automation_workflows(self, automation_id):
        """Return workflows created by one automation without adding ownership columns."""
        events = self.repository.events("automation:{}".format(int(automation_id)))
        workflow_ids = []
        for event in events:
            if event["type"] != "automation.workflow_started":
                continue
            workflow_id = int((event.get("data_json") or {}).get("workflow_run_id") or 0)
            if workflow_id and workflow_id not in workflow_ids:
                workflow_ids.append(workflow_id)
        if not workflow_ids:
            return []
        placeholders = ",".join("?" for _ in workflow_ids)
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT id,task_id,state,created_at,updated_at FROM workflow_runs "
                "WHERE id IN ({}) ORDER BY id DESC".format(placeholders),
                tuple(workflow_ids)).fetchall()
        return [dict(row) for row in rows]

    def automation_has_open_work(self, automation_id):
        return any(item["state"] not in ("completed", "failed", "canceled")
                   for item in self.automation_workflows(automation_id))

    def claim_workflow(self, workflow_run_id=None):
        """Atomically claim one due workflow for this local executor."""
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            arguments = [now]
            where = ("wr.state IN ('ready','waiting_retry') "
                     "AND (wr.available_at IS NULL OR wr.available_at<=?) "
                     "AND (t.pipeline_id IS NULL OR p.paused_at IS NULL)")
            if workflow_run_id is not None:
                where += " AND wr.id=?"
                arguments.append(int(workflow_run_id))
            row = connection.execute(
                "SELECT wr.id,wr.task_id,wr.state FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id "
                "LEFT JOIN pipelines p ON p.id=t.pipeline_id "
                "WHERE {} ORDER BY wr.id LIMIT 1".format(where),
                tuple(arguments)).fetchone()
            if row is None:
                return None
            self._cancel_event(row["id"], reset=True)
            changed = connection.execute(
                "UPDATE workflow_runs SET state='running',available_at=NULL,updated_at=? "
                "WHERE id=? AND state=?", (now, row["id"], row["state"])).rowcount
            if changed != 1:
                return None
            connection.execute("UPDATE tasks SET state='running',updated_at=? WHERE id=?",
                               (now, row["task_id"]))
            self.repository.event(
                "workflow_run:{}".format(row["id"]), "workflow.claimed",
                {"from_state": row["state"]}, connection=connection)
        return row["id"]

    def run_next(self, runtime, max_attempts=3, retry_delay_sec=5):
        workflow_run_id = self.claim_workflow()
        if workflow_run_id is None:
            return None
        return self._execute_claimed_workflow(
            workflow_run_id, runtime, max_attempts=max_attempts,
            retry_delay_sec=retry_delay_sec)

    def execute_claimed_workflow(self, workflow_run_id, runtime, max_attempts=3,
                                 retry_delay_sec=5):
        return self._execute_claimed_workflow(
            workflow_run_id, runtime, max_attempts=max_attempts,
            retry_delay_sec=retry_delay_sec)

    def run_workflow(self, workflow_run_id, runtime, max_attempts=3, retry_delay_sec=5):
        """Run one linear handoff chain through a complete Agent Runtime boundary.

        ``runtime`` is callable(snapshot, work_order, emit) -> WorkResult.  It is
        deliberately not a model API: production adapters invoke Codex/Claude
        and implement the RunTeams collaboration protocol.
        """
        claimed = self.claim_workflow(workflow_run_id)
        if claimed is None:
            with self.repository.connect() as connection:
                row = connection.execute("SELECT state,available_at FROM workflow_runs WHERE id=?",
                                         (int(workflow_run_id),)).fetchone()
            if row is None:
                raise ContractError("工作流运行不存在")
            if row["state"] == "running":
                raise ContractError("工作流运行已被执行器认领")
            if row["state"] == "waiting_retry":
                raise ContractError("工作流尚未到重试时间：{}".format(row["available_at"]))
            if row["state"] in WORKFLOW_TERMINAL_STATES:
                return self._workflow_result(workflow_run_id)
            raise ContractError("工作流当前不能执行：{}".format(row["state"]))
        return self._execute_claimed_workflow(
            claimed, runtime, max_attempts=max_attempts, retry_delay_sec=retry_delay_sec)

    @staticmethod
    def _pipeline_start(definition):
        targets = {edge["to"] for edge in definition.get("edges") or []}
        starts = [item["key"] for item in definition.get("positions") or []
                  if item["key"] not in targets]
        if not starts and definition.get("positions"):
            starts = [definition["positions"][0]["key"]]
        if len(starts) != 1:
            raise ContractError("流水线必须有且只有一个起点")
        return starts[0]

    @staticmethod
    def _matching_edge(definition, position_key, result):
        edges = [item for item in definition.get("edges") or []
                 if item.get("from") == position_key]
        output = result.get("output") if isinstance(result, dict) else {}
        route = str(output.get("route") or "").strip() if isinstance(output, dict) else ""
        status = str(result.get("status") or "") if isinstance(result, dict) else ""
        exception = "exception" if status in ("failed", "blocked") else ""
        for value in (route, status, exception, "always"):
            if not value:
                continue
            match = next((item for item in edges
                          if str(item.get("when") or "completed") == value), None)
            if match is not None:
                return match
        return None

    def _latest_position_run(self, workflow_run_id, position_key):
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM employee_runs WHERE workflow_run_id=? AND position_key=? "
                "ORDER BY id DESC LIMIT 1", (int(workflow_run_id), position_key)).fetchone()
        return dict(row) if row is not None else None

    def _previous_result_for_cursor(self, workflow_run_id, cursor_key):
        events = self.repository.events("workflow_run:{}".format(int(workflow_run_id)))
        routed = next((item for item in reversed(events)
                       if item.get("type") == "workflow.routed" and
                       (item.get("data_json") or {}).get("to") == cursor_key), None)
        data = (routed or {}).get("data_json") or {}
        employee_run_id = int(data.get("employee_run_id") or 0)
        if not employee_run_id:
            return None, ""
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT position_key,output_json FROM employee_runs WHERE id=?",
                (employee_run_id,)).fetchone()
        if row is None:
            return None, ""
        try:
            result = json.loads(row["output_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            result = None
        return result if isinstance(result, dict) else None, str(row["position_key"])

    def _route_workflow(self, workflow_run_id, edge, employee_run_id=None):
        now = utc_now()
        data = {"from": edge["from"], "to": edge["to"],
                "when": edge.get("when") or "completed"}
        if employee_run_id:
            data["employee_run_id"] = int(employee_run_id)
        with self.repository.connect() as connection:
            connection.execute(
                "UPDATE workflow_runs SET cursor_key=?,manual_column_key=NULL,updated_at=? "
                "WHERE id=?", (edge["to"], now, int(workflow_run_id)))
            self.repository.event(
                "workflow_run:{}".format(workflow_run_id), "workflow.routed", data,
                connection=connection)

    def _workflow_visit_count(self, workflow_run_id):
        with self.repository.connect() as connection:
            employee_visits = int(connection.execute(
                "SELECT COUNT(*) FROM employee_runs WHERE workflow_run_id=?",
                (int(workflow_run_id),)).fetchone()[0])
            approvals = int(connection.execute(
                "SELECT COUNT(*) FROM events WHERE stream=? AND type='workflow.approval_decided'",
                ("workflow_run:{}".format(int(workflow_run_id)),)).fetchone()[0])
        return employee_visits + approvals

    def _execute_claimed_workflow(self, workflow_run_id, runtime, max_attempts, retry_delay_sec):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM workflow_runs WHERE id=?",
                                     (int(workflow_run_id),)).fetchone()
        if row is None or row["state"] != "running":
            raise ContractError("工作流没有被当前执行器认领")
        snapshot = json.loads(row["snapshot_json"])
        definition = snapshot["definition"]
        positions = {item["key"]: item for item in definition["positions"]}
        task = snapshot["task"]
        cursor_key = str(row["cursor_key"] or task.get("start_column_key") or
                         self._pipeline_start(definition))
        while cursor_key:
            if self._workflow_visit_count(workflow_run_id) >= WORKFLOW_MAX_VISITS:
                self._set_workflow_state(
                    workflow_run_id, "blocked", event_type="workflow.loop_guarded",
                    data={"limit": WORKFLOW_MAX_VISITS, "position_key": cursor_key})
                return {"schema": "runteams.workflow-control/v1", "status": "blocked",
                        "issues": ["流水线循环次数超过安全上限"]}
            position = positions.get(cursor_key)
            if position is None:
                raise ContractError("当前岗位已不在流水线中")
            if position.get("kind") == "approval":
                self._set_workflow_state(
                    workflow_run_id, "needs_approval", event_type="workflow.approval_requested",
                    data={"position_key": cursor_key, "name": position.get("name"),
                          "prompt": position.get("prompt") or "请确认是否继续"})
                return {"schema": "runteams.workflow-control/v1",
                        "status": "needs_approval", "position_key": cursor_key}
            previous_result, previous_key = self._previous_result_for_cursor(
                workflow_run_id, cursor_key)
            latest_run = self._latest_position_run(workflow_run_id, cursor_key)
            route_order = [previous_key, cursor_key] if previous_result is not None else [cursor_key]
            work_order = self._work_order(
                workflow_run_id, task, position, route_order,
                1 if previous_result is not None else 0, previous_result,
                latest_run, definition)
            employee_run_id = self._start_employee_run(workflow_run_id, position, work_order)
            cancel_event = self._cancel_event(workflow_run_id)

            def emit(event_type, data):
                if cancel_event.is_set():
                    raise Cancelled("运行已停止")
                self.repository.event("employee_run:{}".format(employee_run_id),
                                      str(event_type), data if isinstance(data, dict) else {"value": data})

            try:
                raw_result = self._invoke_runtime(
                    runtime, position["employee"], work_order, emit,
                    employee_run_id, cancel_event)
                result = normalize_work_result(raw_result)
                if result["status"] == "completed":
                    interface = (position["employee"].get("interface") or
                                 normalize_employee_interface(None))
                    violations = json_schema_violations(
                        result["output"], interface["output"], path="$.output")
                    if violations:
                        result = normalize_work_result({
                            "status": "failed", "summary": "", "output": result["output"],
                            "artifacts": result["artifacts"],
                            "issues": ["员工输出不符合接口：{}".format(item)
                                       for item in violations],
                        })
            except Cancelled:
                if self._workflow_state_value(workflow_run_id) == "canceled":
                    self._cancel_employee_run(employee_run_id)
                    return self._canceled_result(workflow_run_id)
                self._interrupt_employee_run(employee_run_id)
                return {"schema": "runteams.workflow-control/v1", "status": "interrupted",
                        "workflow_run_id": int(workflow_run_id)}
            except RateLimited as exc:
                available_at = _rate_limit_available_at(exc)
                self._defer_employee_run(employee_run_id, exc)
                self._set_workflow_state(
                    workflow_run_id, "waiting_retry", available_at=available_at,
                    event_type="workflow.quota_waiting",
                    data={"employee_run_id": employee_run_id,
                          "available_at": available_at})
                return {"schema": "runteams.workflow-control/v1",
                        "status": "waiting_retry", "reason": "quota",
                        "available_at": available_at,
                        "workflow_run_id": int(workflow_run_id)}
            except Transient as exc:
                available_at = _utc_after(30)
                self._defer_employee_run(employee_run_id, exc)
                self._set_workflow_state(
                    workflow_run_id, "waiting_retry", available_at=available_at,
                    event_type="workflow.transient_waiting",
                    data={"employee_run_id": employee_run_id,
                          "available_at": available_at})
                return {"schema": "runteams.workflow-control/v1",
                        "status": "waiting_retry", "reason": "transient",
                        "available_at": available_at,
                        "workflow_run_id": int(workflow_run_id)}
            except Exception as exc:
                result = normalize_work_result({"status": "failed", "summary": "",
                                                "output": {}, "issues": [str(exc)]})
            workflow_state = self._workflow_state_value(workflow_run_id)
            if workflow_state == "canceled":
                self._cancel_employee_run(employee_run_id)
                return self._canceled_result(workflow_run_id)
            if workflow_state == "paused":
                self._interrupt_employee_run(employee_run_id)
                return {"schema": "runteams.workflow-control/v1", "status": "paused",
                        "workflow_run_id": int(workflow_run_id)}
            self._finish_employee_run(employee_run_id, result)
            for raw in result["artifacts"]:
                artifact = raw if isinstance(raw, dict) else {"name": str(raw), "ref": str(raw)}
                self._artifact(employee_run_id, artifact)
            edge = self._matching_edge(definition, cursor_key, result)
            if edge is not None:
                self._route_workflow(workflow_run_id, edge, employee_run_id)
                cursor_key = edge["to"]
                continue
            if result["status"] != "completed":
                expected_trial_failure = (
                    ((snapshot.get("trial") or {}).get("expected_status")) == "failed")
                if (result["status"] == "failed" and not expected_trial_failure and
                        self._employee_failure_count(employee_run_id) < max_attempts):
                    self._set_workflow_state(
                        workflow_run_id, "waiting_retry",
                        available_at=_utc_after(max(0, int(retry_delay_sec))),
                        event_type="workflow.retry_scheduled",
                        data={"employee_run_id": employee_run_id,
                              "attempt": self._employee_attempt(employee_run_id)})
                else:
                    self._set_workflow_state(workflow_run_id, result["status"])
                return result
            self._set_workflow_state(workflow_run_id, "completed")
            return result
        self._set_workflow_state(workflow_run_id, "completed")
        return self._workflow_result(workflow_run_id)

    def cancel_workflow(self, workflow_run_id):
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT task_id,state FROM workflow_runs WHERE id=?",
                                     (int(workflow_run_id),)).fetchone()
            if row is None:
                raise ContractError("工作流运行不存在")
            if row["state"] in ("completed", "canceled"):
                return self.workflow(workflow_run_id)
            connection.execute(
                "UPDATE workflow_runs SET state='canceled',available_at=NULL,updated_at=? WHERE id=?",
                (now, int(workflow_run_id)))
            connection.execute("UPDATE tasks SET state='canceled',updated_at=? WHERE id=?",
                               (now, row["task_id"]))
            connection.execute(
                "UPDATE employee_runs SET state='canceled',updated_at=? "
                "WHERE workflow_run_id=? AND state='running'", (now, int(workflow_run_id)))
            self._cancel_event(workflow_run_id).set()
            self.repository.event("workflow_run:{}".format(workflow_run_id),
                                  "workflow.canceled", {}, connection=connection)
        return self.workflow(workflow_run_id)

    def trash_workflow(self, workflow_run_id):
        """Move one task and its frozen run history to the recoverable trash."""
        workflow_run_id = int(workflow_run_id)
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT wr.task_id,wr.state,t.trashed_at FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id WHERE wr.id=?",
                (workflow_run_id,),
            ).fetchone()
        if row is None or row["trashed_at"]:
            raise ContractError("任务不存在")
        if row["state"] not in WORKFLOW_TERMINAL_STATES:
            self.cancel_workflow(workflow_run_id)
        now = utc_now()
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE tasks SET trashed_at=?,updated_at=? "
                "WHERE id=? AND trashed_at IS NULL",
                (now, now, int(row["task_id"])),
            ).rowcount
            if changed == 1:
                self.repository.event(
                    "task:{}".format(int(row["task_id"])), "task.trashed",
                    {"task_id": int(row["task_id"]),
                     "workflow_run_id": workflow_run_id,
                     "before": {"trashed_at": row["trashed_at"],
                                "state": row["state"]},
                     "after": {"trashed_at": now}}, connection=connection)
        if changed != 1:
            raise ContractError("任务不存在")
        return self.workflow(workflow_run_id)

    def rename_workflow_task(self, workflow_run_id, title):
        return self.update_workflow_task(workflow_run_id, title)

    def update_workflow_task(self, workflow_run_id, title, objective=None,
                             parameters=None):
        """Update the reusable task brief without rewriting its frozen run snapshot."""
        title = str(title or "").strip()
        if not title:
            raise ContractError("任务名称不能为空")
        now = utc_now()
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT t.id,t.title,t.payload_json FROM tasks t JOIN workflow_runs wr "
                "ON wr.task_id=t.id WHERE wr.id=? AND t.trashed_at IS NULL",
                (int(workflow_run_id),),
            ).fetchone()
            if row is None:
                raise ContractError("任务不存在")
            payload = json.loads(row["payload_json"] or "{}")
            before = {"title": row["title"], "payload": copy.deepcopy(payload)}
            if objective is not None:
                payload["objective"] = str(objective or "").strip()
            if parameters is not None:
                if not isinstance(parameters, dict):
                    raise ContractError("团队参数必须是对象")
                payload["parameters"] = copy.deepcopy(parameters)
            changed = connection.execute(
                "UPDATE tasks SET title=?,payload_json=?,updated_at=? WHERE id=?",
                (title, json.dumps(payload, ensure_ascii=False), now, int(row["id"])),
            ).rowcount
            if changed == 1:
                self.repository.event(
                    "workflow_run:{}".format(int(workflow_run_id)),
                    "workflow.task_updated", {"task_id": int(row["id"]),
                    "before": before,
                    "after": {"title": title, "payload": copy.deepcopy(payload)}},
                    connection=connection)
                self.repository.event(
                    "task:{}".format(int(row["id"])), "task.updated",
                    {"workflow_run_id": int(workflow_run_id), "before": before,
                     "after": {"title": title, "payload": copy.deepcopy(payload)}},
                    connection=connection)
        if changed != 1:
            raise ContractError("任务不存在")
        return self.workflow(workflow_run_id)

    def move_workflow(self, workflow_run_id, column_key):
        """Move a stopped task; recompile its live task when work starts again."""
        workflow_run_id = int(workflow_run_id)
        column_key = str(column_key or "").strip()
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT wr.*,t.id AS current_task_id,t.title AS current_task_title,"
                "t.start_column_key AS current_task_start_column_key,"
                "t.payload_json AS current_task_payload_json,t.trashed_at "
                "FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id WHERE wr.id=?", (workflow_run_id,)
            ).fetchone()
        if row is None or row["trashed_at"]:
            raise ContractError("任务不存在")
        if row["state"] in ("ready", "running", "waiting_retry"):
            raise ContractError("任务运行中，请先停止后再移动")
        snapshot = json.loads(row["snapshot_json"])
        definition = snapshot["definition"]
        order = pipeline_order(definition)
        states = {item["key"]: item for item in definition.get("states") or []}
        if column_key == "__completed":
            target_state = {"kind": "done"}
        elif column_key in states:
            target_state = states[column_key]
        else:
            target_state = None
        if column_key not in order and target_state is None:
            raise ContractError("目标列不存在")
        now = utc_now()
        if column_key in order:
            target_index = order.index(column_key)
            affected = tuple(order[target_index:])
            placeholders = ",".join("?" for _ in affected)
            previous_task = snapshot.get("task") or {}
            snapshot["task"] = {
                "id": int(row["current_task_id"]),
                "title": str(row["current_task_title"] or ""),
                "start_column_key": str(row["current_task_start_column_key"] or
                                        previous_task.get("start_column_key") or ""),
                "payload": json.loads(row["current_task_payload_json"] or "{}"),
            }
            with self.repository.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE employee_runs SET state='superseded',updated_at=? "
                    "WHERE workflow_run_id=? AND position_key IN ({}) "
                    "AND state IN ('completed','blocked','needs_human','failed','canceled','interrupted')".format(
                        placeholders), (now, workflow_run_id) + affected)
                connection.execute(
                    "UPDATE workflow_runs SET state='ready',available_at=?,manual_column_key=?,cursor_key=?,"
                    "snapshot_json=?,updated_at=? "
                    "WHERE id=?", (now, column_key, column_key,
                                   json.dumps(snapshot, ensure_ascii=False), now,
                                   workflow_run_id))
                connection.execute(
                    "UPDATE tasks SET state='ready',updated_at=? WHERE id=?",
                    (now, row["current_task_id"]))
                self.repository.event(
                    "workflow_run:{}".format(workflow_run_id), "workflow.moved",
                    {"column_key": column_key, "kind": "position"}, connection=connection)
            self._cancel_event(workflow_run_id, reset=True)
        else:
            kind = target_state.get("kind")
            state = "completed" if kind == "done" else "canceled" if kind == "dropped" else "blocked"
            with self.repository.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE workflow_runs SET state=?,available_at=NULL,manual_column_key=?,updated_at=? "
                    "WHERE id=?", (state, column_key, now, workflow_run_id))
                connection.execute(
                    "UPDATE tasks SET state=?,updated_at=? WHERE id=?",
                    (state, now, row["current_task_id"]))
                self.repository.event(
                    "workflow_run:{}".format(workflow_run_id), "workflow.moved",
                    {"column_key": column_key, "kind": kind}, connection=connection)
        return self.workflow(workflow_run_id)

    def task_trash_catalog(self):
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT t.id,t.title,t.trashed_at,p.name AS pipeline_name,wr.id AS workflow_id," 
                "(SELECT COUNT(*) FROM employee_runs er WHERE er.workflow_run_id=wr.id) AS run_count," 
                "(SELECT COUNT(*) FROM artifacts a JOIN employee_runs er2 "
                " ON er2.id=a.employee_run_id WHERE er2.workflow_run_id=wr.id) AS document_count "
                "FROM tasks t JOIN workflow_runs wr ON wr.task_id=t.id "
                "LEFT JOIN pipelines p ON p.id=t.pipeline_id "
                "WHERE t.trashed_at IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM events position_event "
                "JOIN (SELECT stream,MAX(id) AS id FROM events "
                "WHERE stream LIKE 'pipeline_position:%' GROUP BY stream) latest "
                "ON latest.id=position_event.id, "
                "json_each(position_event.data_json,'$.task_ids') bundled "
                "WHERE position_event.type='pipeline.position_trashed' "
                "AND CAST(bundled.value AS INTEGER)=t.id) "
                "AND json_extract(wr.snapshot_json,'$.trial') IS NULL "
                "ORDER BY t.trashed_at DESC,t.id DESC"
            ).fetchall()
        items = []
        for row in rows:
            trashed = datetime.datetime.fromisoformat(row["trashed_at"])
            items.append({
                "id": int(row["workflow_id"]), "task_id": int(row["id"]),
                "kind": "task", "title": row["title"],
                "location": row["pipeline_name"] or "流水线任务",
                "count": int(row["run_count"] or 0),
                "document_count": int(row["document_count"] or 0),
                "trashed_at": row["trashed_at"],
                "expires_at": (trashed + datetime.timedelta(days=30)).isoformat(
                    timespec="seconds"),
            })
        return items

    def restore_workflow(self, workflow_run_id):
        now = utc_now()
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE tasks SET trashed_at=NULL,updated_at=? WHERE id=("
                "SELECT task_id FROM workflow_runs WHERE id=?) AND trashed_at IS NOT NULL",
                (now, int(workflow_run_id)),
            ).rowcount
        if changed != 1:
            raise ContractError("垃圾箱中没有这项任务")
        return self.workflow(workflow_run_id)

    def delete_trashed_workflow(self, workflow_run_id, acknowledged_documents=None):
        workflow_run_id = int(workflow_run_id)
        artifact_refs = []
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT wr.id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                "WHERE wr.id=? AND t.trashed_at IS NOT NULL",
                (workflow_run_id,),
            ).fetchone()
            if row is None:
                raise ContractError("垃圾箱中没有这项任务")
            self._guard_document_loss(
                self._document_count_for_workflows(connection, [workflow_run_id]),
                acknowledged_documents, "这项任务")
            artifact_refs, task_ids = self._delete_workflows(connection, [workflow_run_id])
        self._delete_artifact_files(artifact_refs)
        self._delete_task_input_files(task_ids)
        return True

    def purge_expired_tasks(self, retention_days=30):
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=max(1, int(retention_days)))).isoformat(
                      timespec="seconds")
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT wr.id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                "WHERE t.trashed_at IS NOT NULL AND t.trashed_at<=?", (cutoff,)).fetchall()]
        purged = 0
        for workflow_run_id in ids:
            try:
                self.delete_trashed_workflow(workflow_run_id, acknowledged_documents=0)
                purged += 1
            except ContractError:
                continue
        return purged

    def respond_to_human(self, workflow_run_id, response):
        response = str(response or "").strip()
        if not response:
            raise ContractError("请填写回复内容")
        if len(response) > 8000:
            raise ContractError("回复内容不能超过 8000 个字符")
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT task_id,state FROM workflow_runs WHERE id=?",
                                     (int(workflow_run_id),)).fetchone()
            if row is None:
                raise ContractError("工作流运行不存在")
            if row["state"] != "needs_human":
                raise ContractError("当前任务不在等待人工回复")
            employee_run = connection.execute(
                "SELECT id,position_key,state FROM employee_runs WHERE workflow_run_id=? "
                "ORDER BY id DESC LIMIT 1", (int(workflow_run_id),)).fetchone()
            if employee_run is None or employee_run["state"] != "needs_human":
                raise ContractError("找不到等待回复的员工运行")
            self.repository.event(
                "workflow_run:{}".format(workflow_run_id), "workflow.human_responded",
                {"employee_run_id": int(employee_run["id"]),
                 "position_key": employee_run["position_key"], "response": response},
                connection=connection)
            connection.execute(
                "UPDATE workflow_runs SET state='ready',available_at=?,updated_at=? WHERE id=?",
                (now, now, int(workflow_run_id)))
            connection.execute("UPDATE tasks SET state='ready',updated_at=? WHERE id=?",
                               (now, row["task_id"]))
        self._cancel_event(workflow_run_id, reset=True)
        return self.workflow(workflow_run_id)

    def decide_workflow_approval(self, workflow_run_id, approved, note=""):
        """Resolve a fixed human approval position and continue on its declared route."""
        workflow_run_id = int(workflow_run_id)
        decision = "approved" if bool(approved) else "rejected"
        note = str(note or "").strip()
        if len(note) > 4000:
            raise ContractError("审批说明不能超过 4000 个字符")
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT wr.task_id,wr.state,wr.cursor_key,wr.snapshot_json "
                "FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                "WHERE wr.id=? AND t.trashed_at IS NULL", (workflow_run_id,)).fetchone()
        if row is None:
            raise ContractError("工作流运行不存在")
        if row["state"] != "needs_approval":
            raise ContractError("当前任务不在等待人工审批")
        snapshot = json.loads(row["snapshot_json"] or "{}")
        definition = snapshot.get("definition") or {}
        position_key = str(row["cursor_key"] or "")
        position = next((item for item in definition.get("positions") or []
                         if item.get("key") == position_key), None)
        if not position or position.get("kind") != "approval":
            raise ContractError("找不到等待处理的审批岗位")
        synthetic = {"status": decision, "output": {"route": decision}}
        edge = self._matching_edge(definition, position_key, synthetic)
        prior_result, _prior_key = self._previous_result_for_cursor(
            workflow_run_id, position_key)
        upstream_run_id = 0
        if prior_result is not None:
            routed = next((item for item in reversed(self.repository.events(
                "workflow_run:{}".format(workflow_run_id)))
                if item.get("type") == "workflow.routed" and
                (item.get("data_json") or {}).get("to") == position_key), None)
            upstream_run_id = int(((routed or {}).get("data_json") or {}).get(
                "employee_run_id") or 0)
        now = utc_now()
        with self.repository.connect() as connection:
            self.repository.event(
                "workflow_run:{}".format(workflow_run_id), "workflow.approval_decided",
                {"position_key": position_key, "decision": decision, "note": note},
                connection=connection)
        if edge is not None:
            self._route_workflow(workflow_run_id, edge, upstream_run_id or None)
            self._set_workflow_state(workflow_run_id, "ready", available_at=now,
                                     event_type="workflow.approval_continued",
                                     data={"decision": decision})
        else:
            self._set_workflow_state(
                workflow_run_id, "completed" if approved else "blocked",
                event_type="workflow.approval_completed",
                data={"decision": decision, "note": note})
        self._cancel_event(workflow_run_id, reset=True)
        return self.workflow(workflow_run_id)

    def retry_workflow(self, workflow_run_id):
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT wr.task_id,wr.state,wr.snapshot_json,t.title,t.start_column_key,"
                "t.payload_json FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id "
                "WHERE wr.id=? AND t.trashed_at IS NULL",
                (int(workflow_run_id),)).fetchone()
            if row is None:
                raise ContractError("工作流运行不存在")
            if row["state"] == "completed":
                raise ContractError("已完成的工作流不能重试")
            if row["state"] == "running":
                raise ContractError("正在运行的工作流不能重试")
            if row["state"] == "needs_human":
                raise ContractError("请先回复员工的问题")
            if row["state"] == "needs_approval":
                raise ContractError("请先处理人工审批")
            now = utc_now()
            self._cancel_event(workflow_run_id, reset=True)
            snapshot = json.loads(row["snapshot_json"] or "{}")
            previous_task = snapshot.get("task") or {}
            current_task = {
                "id": int(row["task_id"]),
                "title": str(row["title"] or ""),
                "start_column_key": str(row["start_column_key"] or
                                        previous_task.get("start_column_key") or ""),
                "payload": json.loads(row["payload_json"] or "{}"),
            }
            task_recompiled = previous_task != current_task
            if task_recompiled:
                after_employee_run_id = int(connection.execute(
                    "SELECT COALESCE(MAX(id),0) FROM employee_runs WHERE workflow_run_id=?",
                    (int(workflow_run_id),)).fetchone()[0])
                snapshot["task"] = current_task
                cursor_key = str(current_task.get("start_column_key") or
                                 self._pipeline_start(snapshot["definition"]))
                connection.execute(
                    "UPDATE workflow_runs SET state='ready',available_at=?,"
                    "manual_column_key=NULL,cursor_key=?,snapshot_json=?,updated_at=? WHERE id=?",
                    (now, cursor_key, json.dumps(snapshot, ensure_ascii=False), now,
                     int(workflow_run_id)))
                self.repository.event(
                    "workflow_run:{}".format(workflow_run_id),
                    "workflow.task_recompiled",
                    {"after_employee_run_id": after_employee_run_id,
                     "previous_task": previous_task, "task": current_task},
                    connection=connection)
            else:
                connection.execute(
                    "UPDATE workflow_runs SET state='ready',available_at=?,updated_at=? WHERE id=?",
                    (now, now, int(workflow_run_id)))
            connection.execute("UPDATE tasks SET state='ready',updated_at=? WHERE id=?",
                               (now, row["task_id"]))
            self.repository.event(
                "workflow_run:{}".format(workflow_run_id), "workflow.retry_requested",
                {"from_state": row["state"], "task_recompiled": task_recompiled},
                connection=connection)
        return self.workflow(workflow_run_id)

    def recover_interrupted_workflows(self):
        """Requeue work owned by a previous app process. Call once during startup."""
        recovered = []
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id,task_id FROM workflow_runs WHERE state='running' ORDER BY id").fetchall()
            now = utc_now()
            for row in rows:
                connection.execute(
                    "UPDATE employee_runs SET state='interrupted',updated_at=? "
                    "WHERE workflow_run_id=? AND state='running'", (now, row["id"]))
                connection.execute(
                    "UPDATE workflow_runs SET state='ready',available_at=?,updated_at=? WHERE id=?",
                    (now, now, row["id"]))
                connection.execute("UPDATE tasks SET state='ready',updated_at=? WHERE id=?",
                                   (now, row["task_id"]))
                self.repository.event(
                    "workflow_run:{}".format(row["id"]), "workflow.recovered", {},
                    connection=connection)
                recovered.append(row["id"])
        return recovered

    def recover_interrupted_workflow(self, workflow_run_id):
        """Requeue only the workflow whose live executor exited unexpectedly."""
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id,task_id FROM workflow_runs WHERE id=? AND state='running'",
                (int(workflow_run_id),)).fetchone()
            if row is None:
                return False
            now = utc_now()
            connection.execute(
                "UPDATE employee_runs SET state='interrupted',updated_at=? "
                "WHERE workflow_run_id=? AND state='running'", (now, row["id"]))
            connection.execute(
                "UPDATE workflow_runs SET state='ready',available_at=?,updated_at=? WHERE id=?",
                (now, now, row["id"]))
            connection.execute("UPDATE tasks SET state='ready',updated_at=? WHERE id=?",
                               (now, row["task_id"]))
            self.repository.event(
                "workflow_run:{}".format(row["id"]), "workflow.recovered", {},
                connection=connection)
        return True

    def interrupt_workflow(self, workflow_run_id):
        """Stop the local Runtime and leave durable recovery to the next startup."""
        if self._workflow_state_value(workflow_run_id) != "running":
            return False
        self._cancel_event(workflow_run_id).set()
        return True

    def workflow_catalog(self, limit=100):
        limit = max(1, min(500, int(limit)))
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT wr.id,wr.snapshot_json FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id WHERE t.trashed_at IS NULL "
                "ORDER BY wr.id DESC LIMIT ?",
                (max(limit, min(2000, limit * 10)),)).fetchall()
        ids = []
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            if snapshot.get("trial"):
                continue
            ids.append(row["id"])
            if len(ids) >= limit:
                break
        return [self.workflow(workflow_run_id) for workflow_run_id in ids]

    def employee_workflow_catalog(self, employee_id, limit=100):
        """Production work assigned directly to one employee, newest first."""
        limit = max(1, min(500, int(limit)))
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT wr.id,wr.snapshot_json FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id "
                "WHERE t.employee_id=? AND t.pipeline_id IS NULL "
                "AND t.trashed_at IS NULL ORDER BY wr.id DESC LIMIT ?",
                (int(employee_id), max(limit, min(2000, limit * 10))),
            ).fetchall()
        ids = []
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            if snapshot.get("trial"):
                continue
            ids.append(row["id"])
            if len(ids) >= limit:
                break
        return [self.workflow(workflow_run_id) for workflow_run_id in ids]

    DOCUMENT_REVISION_MAX_BYTES = 2 * 1024 * 1024

    def _agent_document_path(self, key, digest_value):
        """Return a safe immutable path for a document authored from Agent Chat."""
        root = (self.root / "artifacts" / "agent-documents").resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = (root / "{}-{}.md".format(key, digest_value[:12])).resolve()
        if root not in destination.parents:
            raise ContractError("文档路径不安全")
        return destination

    def _document_rows(self, connection, include_trashed=False):
        """Load artifact rows once for lineage-aware document projections."""
        clause = "" if include_trashed else " WHERE trashed_at IS NULL"
        return connection.execute(
            "SELECT * FROM artifacts{} ORDER BY id".format(clause)).fetchall()

    def _document_root_id(self, row):
        meta = self._decode_meta(row["meta_json"])
        return int(meta.get("revision_of") or row["id"])

    def _find_agent_document(self, connection, key_or_name):
        value = str(key_or_name or "").strip().casefold()
        if not value:
            return None
        rows = self._document_rows(connection)
        candidates = []
        for row in rows:
            meta = self._decode_meta(row["meta_json"])
            if meta.get("source") != "agent_chat":
                continue
            key = str(meta.get("document_key") or "").casefold()
            if key == value or str(row["name"] or "").casefold() == value:
                candidates.append(row)
        if not candidates:
            return None
        # Revisions are immutable rows; return the current row for the chain.
        root = self._document_root_id(candidates[0])
        chain = [row for row in rows if self._document_root_id(row) == root]
        return chain[-1] if chain else candidates[-1]

    def _read_document_body(self, row):
        path = Path(str(row["ref"] or "")).resolve()
        root = (self.root / "artifacts").resolve()
        try:
            safe = path != root and root in path.parents
        except ValueError:
            safe = False
        if not safe or not path.is_file():
            raise ContractError("文档文件不可用")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ContractError("文档内容无法读取") from exc

    def create_agent_document(self, name, content, document_key=None,
                              data_view=None, note=""):
        """Create or update a document authored by Agent Chat.

        This deliberately reuses ``artifacts`` instead of creating a second
        document table.  The row is independent from employee execution while
        revisions stay immutable and readable through the existing reader.
        """
        title = str(name or "").strip()
        if not title or len(title) > 200:
            raise ContractError("文档标题不能为空且不能超过 200 个字符")
        if not isinstance(content, str) or not content.strip():
            raise ContractError("文档内容不能为空")
        body = content.encode("utf-8")
        if len(body) > self.DOCUMENT_REVISION_MAX_BYTES:
            raise ContractError("文档内容超过 2 MB")
        key = _normalize_agent_document_key(document_key, title)
        view = _normalize_document_data_view(data_view)
        with self.repository.connect() as connection:
            current = self._find_agent_document(connection, key)
        if current is not None:
            return self.update_agent_document(
                int(current["id"]), title, content, data_view=view, note=note)
        digest_value = hashlib.sha256(body).hexdigest()
        destination = self._agent_document_path(key, digest_value)
        if not destination.exists():
            destination.write_bytes(body)
        now = utc_now()
        meta = {"path": "{}.md".format(key), "content_model": "markdown", "sha256": digest_value,
                "size": len(body), "revision": 1, "document_key": key,
                "source": "agent_chat", "data_view": view,
                "author": "agent", "note": str(note or "").strip()[:500]}
        with self.repository.connect() as connection:
            new_id = connection.execute(
                "INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) "
                "VALUES(NULL,?,?,?,?)", (title, str(destination),
                                           json.dumps(meta, ensure_ascii=False), now),
            ).lastrowid
            meta["revision_of"] = int(new_id)
            connection.execute("UPDATE artifacts SET meta_json=? WHERE id=?",
                               (json.dumps(meta, ensure_ascii=False), int(new_id)))
            self.repository.event(
                "document:{}".format(int(new_id)), "document.created",
                {"document_id": int(new_id), "document_key": key,
                 "title": title, "source": "agent_chat"}, connection=connection)
        return self.document_detail(new_id, include_content=False)

    def update_agent_document(self, document_id, name=None, content=None,
                              data_view=None, note=""):
        """Create a new immutable revision of an Agent-authored document."""
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=?",
                                     (int(document_id),)).fetchone()
            if row is None:
                raise ContractError("文档不存在")
            meta = self._decode_meta(row["meta_json"])
            if meta.get("source") != "agent_chat":
                raise ContractError("只有 Agent Chat 创建的文档可以通过此动作更新")
            root = self._document_root_id(row)
            chain = [candidate for candidate in self._document_rows(connection)
                     if self._document_root_id(candidate) == root]
            latest = chain[-1] if chain else row
            latest_meta = self._decode_meta(latest["meta_json"])
            existing_view = latest_meta.get("data_view")
        title = str(name if name is not None else latest["name"] or "").strip()
        if not title or len(title) > 200:
            raise ContractError("文档标题不能为空且不能超过 200 个字符")
        if content is None:
            content = self._read_document_body(latest)
        if not isinstance(content, str) or not content.strip():
            raise ContractError("文档内容不能为空")
        body = content.encode("utf-8")
        if len(body) > self.DOCUMENT_REVISION_MAX_BYTES:
            raise ContractError("文档内容超过 2 MB")
        view = (_normalize_document_data_view(data_view)
                if data_view is not None else _normalize_document_data_view(existing_view))
        digest_value = hashlib.sha256(body).hexdigest()
        if digest_value == str(latest_meta.get("sha256") or "") and title == str(latest["name"] or "") \
                and view == existing_view:
            return self.document_detail(int(latest["id"]), include_content=False)
        key = _normalize_agent_document_key(latest_meta.get("document_key"), title)
        destination = self._agent_document_path(key, digest_value)
        if not destination.exists():
            destination.write_bytes(body)
        revision = int(latest_meta.get("revision") or len(chain) or 1) + 1
        new_meta = {"path": "{}.md".format(key), "content_model": "markdown", "sha256": digest_value,
                    "size": len(body), "revision": revision,
                    "revision_of": root, "document_key": key,
                    "source": "agent_chat", "data_view": view,
                    "author": "agent", "note": str(note or "").strip()[:500],
                    "editor_styles": copy.deepcopy(latest_meta.get("editor_styles") or {})}
        with self.repository.connect() as connection:
            new_id = connection.execute(
                "INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) "
                "VALUES(NULL,?,?,?,?)", (title, str(destination),
                                           json.dumps(new_meta, ensure_ascii=False), utc_now()),
            ).lastrowid
            self.repository.event(
                "document:{}".format(root), "document.revised",
                {"document_id": int(new_id), "revision_of": root,
                 "revision": revision, "source": "agent_chat"}, connection=connection)
        return self.document_detail(new_id, include_content=False)

    def document_detail(self, document_id, include_content=True):
        """Return metadata and optional live data bindings for one document."""
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=? AND trashed_at IS NULL",
                                     (int(document_id),)).fetchone()
            if row is None:
                return None
            meta = self._decode_meta(row["meta_json"])
            root = self._document_root_id(row)
            chain = [candidate for candidate in self._document_rows(connection)
                     if self._document_root_id(candidate) == root]
        if not chain:
            chain = [row]
        current = chain[-1]
        current_meta = self._decode_meta(current["meta_json"])
        current_path = str(current_meta.get("path") or current["name"] or "")
        item = {
            "id": int(current["id"]), "name": str(current["name"] or "文档"),
            "path": str(current_meta.get("path") or ""),
            "size": int(current_meta.get("size") or 0),
            "created_at": current["created_at"],
            "revision": int(current_meta.get("revision") or 1),
            "revision_count": len(chain),
            "source": str(current_meta.get("source") or "employee"),
            "document_key": str(current_meta.get("document_key") or ""),
            "data_view": copy.deepcopy(current_meta.get("data_view")),
            "content_model": current_meta.get("content_model") or self.document_model_for_path(current_path),
            "editable": self.document_can_edit(current_path),
            "employee_run_id": int(current["employee_run_id"]) if current["employee_run_id"] else 0,
            "workflow_id": 0, "task_id": 0, "pipeline_id": 0,
            "pipeline_name": "", "task_title": "", "position_name": "",
            "employee_id": 0,
            "employee_name": "Agent Chat" if current_meta.get("source") == "agent_chat" else "员工",
            # Presentation metadata belongs to the document revision, not to
            # a browser profile.  Keep it beside the Markdown bytes so a
            # reload, another device, or a newly-created revision sees the
            # same block styles.
            "editor_styles": copy.deepcopy(current_meta.get("editor_styles") or {}),
        }
        if current["employee_run_id"]:
            with self.repository.connect() as connection:
                lineage = connection.execute(
                    "SELECT er.workflow_run_id,er.position_key,wr.task_id,wr.snapshot_json "
                    "FROM employee_runs er JOIN workflow_runs wr ON wr.id=er.workflow_run_id "
                    "WHERE er.id=?", (int(current["employee_run_id"]),)).fetchone()
            if lineage:
                snapshot = self._decode_meta(lineage["snapshot_json"])
                positions = (snapshot.get("definition") or {}).get("positions") or []
                position = next((p for p in positions if p.get("key") == lineage["position_key"]), {})
                employee = position.get("employee") or {}
                item.update({"workflow_id": int(lineage["workflow_run_id"]),
                             "task_id": int(lineage["task_id"] or 0),
                             "pipeline_id": int(snapshot.get("pipeline_id") or 0),
                             "pipeline_name": str(snapshot.get("pipeline_name") or ""),
                             "task_title": str((snapshot.get("task") or {}).get("title") or ""),
                             "position_name": self.position_display_name(position) if position else "",
                             "employee_id": int(position.get("employee_id") or 0),
                             "employee_name": str(employee.get("name") or "员工")})
        if include_content:
            item["content"] = self._read_document_body(current)
            view = item.get("data_view")
            if isinstance(view, dict) and view.get("kind") == "opportunities":
                item["data"] = {"opportunities": self.opportunity_catalog(
                    query=view.get("query") or "", limit=0)}
        return item

    def save_document_block_style(self, document_id, style):
        """Persist one editor block style on the current document revision.

        Markdown remains the interchange format, while styles that Markdown
        cannot represent (alignment, color, indentation, background) live in
        the same durable artifact metadata.  The browser is only a cache and
        is never the source of truth.
        """
        if not isinstance(style, dict):
            raise ContractError("样式必须是对象")
        anchor = str(style.get("anchor") or "").strip()[:240]
        if not anchor:
            raise ContractError("样式缺少段落锚点")
        signature = str(style.get("signature") or "").strip()[:700]
        clear = bool(style.get("clear"))
        allowed_align = {"left", "center", "right"}
        value = {}
        if style.get("align") is not None:
            align = str(style.get("align") or "left")
            if align not in allowed_align:
                raise ContractError("不支持的对齐方式")
            value["align"] = align
        if style.get("indent") is not None:
            try:
                value["indent"] = max(0, min(6, int(style.get("indent") or 0)))
            except (TypeError, ValueError):
                raise ContractError("缩进值无效")
        for key in ("color", "background"):
            if style.get(key) is not None:
                raw = str(style.get(key) or "")
                if len(raw) > 40:
                    raise ContractError("颜色值无效")
                value[key] = raw
        if not value and not clear:
            raise ContractError("样式没有可保存的字段")
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=? AND trashed_at IS NULL",
                                     (int(document_id),)).fetchone()
            if row is None:
                raise ContractError("文档不存在")
            chain = self._document_chain(connection, int(document_id))
            current = chain[-1] if chain else row
            meta = self._decode_meta(current["meta_json"])
            current_path = str(meta.get("path") or current["name"] or "")
            if not self.document_can_edit(current_path):
                raise ContractError(self.document_edit_error(current_path))
            styles = meta.get("editor_styles")
            if not isinstance(styles, dict):
                styles = {}
            if clear:
                styles.pop(anchor, None)
                if signature and not signature.startswith("DIV|"):
                    styles.pop("sig:" + signature, None)
                meta["editor_styles"] = styles
                connection.execute("UPDATE artifacts SET meta_json=? WHERE id=?",
                                   (json.dumps(meta, ensure_ascii=False), int(current["id"])))
                return copy.deepcopy(styles)
            previous = styles.get(anchor)
            merged = dict(previous) if isinstance(previous, dict) else {}
            merged.update(value)
            styles[anchor] = merged
            # Text signatures are only a compatibility fallback for ordinary
            # blocks.  List-item wrappers can repeat the same text and must
            # never become a global style key.
            if signature and not signature.startswith("DIV|"):
                styles["sig:" + signature] = dict(merged)
            if len(styles) > 10000:
                raise ContractError("文档样式数量超过限制")
            meta["editor_styles"] = styles
            connection.execute("UPDATE artifacts SET meta_json=? WHERE id=?",
                               (json.dumps(meta, ensure_ascii=False), int(current["id"])))
        return copy.deepcopy(styles)

    def _document_chain(self, connection, artifact_id):
        """One document's full revision chain, oldest first.

        A revision never rewrites the published artifact: it is a new immutable
        row that points back at the chain root, so every earlier run keeps
        pointing at the exact bytes it consumed.
        """
        row = connection.execute("SELECT * FROM artifacts WHERE id=?",
                                 (int(artifact_id),)).fetchone()
        if row is None:
            return []
        meta = self._decode_meta(row["meta_json"])
        root = int(meta.get("revision_of") or row["id"])
        # A document chain may be employee-owned or authored from Agent Chat.
        # Lineage is the immutable revision_of marker, not the optional owner.
        rows = connection.execute(
            "SELECT * FROM artifacts WHERE trashed_at IS NULL ORDER BY id").fetchall()
        chain = []
        for candidate in rows:
            candidate_meta = self._decode_meta(candidate["meta_json"])
            if int(candidate_meta.get("revision_of") or candidate["id"]) == root:
                chain.append(candidate)
        return chain

    @staticmethod
    def position_display_name(position):
        """岗位名。「第 N 岗」只是新建时的占位，不该当成真名显示——退回员工名。"""
        position = position or {}
        name = str(position.get("name") or "").strip()
        if name and not _PLACEHOLDER_POSITION.fullmatch(name):
            return name
        employee = position.get("employee") or {}
        return str(employee.get("name") or "").strip() or name or "岗位"

    @staticmethod
    def _decode_meta(value):
        try:
            meta = json.loads(value or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return meta if isinstance(meta, dict) else {}

    def trash_document(self, artifact_id):
        """把一份文档移到垃圾箱。可逆，30 天后由清理流程永久删除。"""
        now = utc_now()
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE artifacts SET trashed_at=? WHERE id=? AND trashed_at IS NULL",
                (now, int(artifact_id))).rowcount
        if changed != 1:
            raise ContractError("文档不存在或已经在垃圾箱里")
        return True

    def restore_document(self, artifact_id):
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE artifacts SET trashed_at=NULL WHERE id=? AND trashed_at IS NOT NULL",
                (int(artifact_id),)).rowcount
        if changed != 1:
            raise ContractError("垃圾箱中没有这份文档")
        return True

    def document_trash_catalog(self):
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT a.*,er.position_key,wr.snapshot_json FROM artifacts a "
                "LEFT JOIN employee_runs er ON er.id=a.employee_run_id "
                "LEFT JOIN workflow_runs wr ON wr.id=er.workflow_run_id "
                "WHERE a.trashed_at IS NOT NULL ORDER BY a.trashed_at DESC,a.id DESC"
            ).fetchall()
        items = []
        for row in rows:
            snapshot = self._decode_meta(row["snapshot_json"])
            meta = self._decode_meta(row["meta_json"])
            task = snapshot.get("task") or {}
            trashed = datetime.datetime.fromisoformat(row["trashed_at"])
            items.append({
                "id": int(row["id"]),
                "kind": "document",
                "title": str(row["name"] or "文档"),
                "location": str(task.get("title") or
                                 ("Agent Chat" if meta.get("source") == "agent_chat" else "任务")),
                "count": 0,
                "trashed_at": row["trashed_at"],
                "expires_at": (trashed + datetime.timedelta(days=30)).isoformat(
                    timespec="seconds"),
            })
        return items

    def delete_trashed_document(self, artifact_id):
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT ref FROM artifacts WHERE id=? AND trashed_at IS NOT NULL",
                (int(artifact_id),)).fetchone()
            if row is None:
                raise ContractError("垃圾箱中没有这份文档")
            connection.execute("DELETE FROM artifacts WHERE id=?", (int(artifact_id),))
        self._delete_artifact_files([row["ref"]])
        return True

    def purge_expired_documents(self, retention_days=30):
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=max(1, int(retention_days)))).isoformat(
                      timespec="seconds")
        with self.repository.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT id FROM artifacts WHERE trashed_at IS NOT NULL AND trashed_at<=?",
                (cutoff,)).fetchall()]
        purged = 0
        for artifact_id in ids:
            try:
                self.delete_trashed_document(artifact_id)
                purged += 1
            except ContractError:
                continue
        return purged

    def document_revisions(self, artifact_id):
        with self.repository.connect() as connection:
            chain = self._document_chain(connection, artifact_id)
        items = []
        for index, row in enumerate(chain):
            meta = self._decode_meta(row["meta_json"])
            items.append({
                "id": int(row["id"]),
                "revision": int(meta.get("revision") or index + 1),
                "author": str(meta.get("author") or "employee"),
                "note": str(meta.get("note") or ""),
                "size": int(meta.get("size") or 0),
                "created_at": row["created_at"],
                "is_current": index == len(chain) - 1,
            })
        return items

    def _revision_was_handed_off(self, connection, artifact):
        """这一版是否已经交给过下游岗位。交出去了就不能再原地改。"""
        if not artifact["employee_run_id"]:
            return False
        rows = connection.execute(
            "SELECT er.input_json FROM employee_runs er WHERE er.workflow_run_id=("
            "SELECT workflow_run_id FROM employee_runs WHERE id=?)",
            (int(artifact["employee_run_id"]),)).fetchall()
        ref = str(artifact["ref"])
        for row in rows:
            if ref and ref in str(row["input_json"] or ""):
                return True
        return False

    def save_document_edit(self, artifact_id, content):
        """自动保存：同一次编辑合并进同一个版本，交接出去之后才开新版本。

        这样既有"边写边存"的手感，又不会把版本历史刷成一堆碎片，
        而且任何已经被下游消费过的字节仍然不可变。
        """
        if not isinstance(content, str):
            raise ContractError("内容必须是文本")
        body = content.encode("utf-8")
        if len(body) > self.DOCUMENT_REVISION_MAX_BYTES:
            raise ContractError("内容超过 2 MB，请在电脑上直接编辑原文件")
        with self.repository.connect() as connection:
            chain = self._document_chain(connection, artifact_id)
            if not chain:
                raise ContractError("文档不存在")
            latest = chain[-1]
            meta = self._decode_meta(latest["meta_json"])
            filename = str(meta.get("path") or latest["name"] or "document.txt")
            if not self.document_can_edit(filename):
                raise ContractError(self.document_edit_error(filename))
            reusable = (str(meta.get("author") or "") == "human"
                        and meta.get("source") != "agent_chat"
                        and self.document_can_edit(filename)
                        and not self._revision_was_handed_off(connection, latest))
            if not reusable:
                return {"id": self.create_document_revision(artifact_id, content),
                        "created_revision": True}
            digest_value = hashlib.sha256(body).hexdigest()
            if digest_value == str(meta.get("sha256") or ""):
                return {"id": int(latest["id"]), "created_revision": False}
            directory = (self.root / "artifacts" / str(latest["employee_run_id"])).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / "{}-{}".format(digest_value[:12], Path(filename).name)
            destination.write_bytes(body)
            previous = Path(str(latest["ref"]))
            meta.update({"sha256": digest_value, "size": len(body)})
            connection.execute(
                "UPDATE artifacts SET ref=?,meta_json=? WHERE id=?",
                (str(destination), json.dumps(meta, ensure_ascii=False), int(latest["id"])))
        if previous != destination and previous.is_file():
            self._delete_artifact_files([str(previous)])
        return {"id": int(latest["id"]), "created_revision": False}

    def revert_document(self, artifact_id):
        """把旧的一版重新放到链尾：读的是服务器上那一版的字节，不信客户端传来的内容。"""
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE id=?", (int(artifact_id),)).fetchone()
            if not row:
                raise ContractError("文档不存在")
            meta = self._decode_meta(row["meta_json"])
            created_at = str(row["created_at"] or "")
        filename = str(meta.get("path") or row["name"] or "document.md")
        if not self.is_document(filename):
            raise ContractError("这类文件不能在产品内编辑，请用系统应用打开")
        try:
            text = Path(row["ref"]).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise ContractError("这一版的文件读不出来，可能已经被移动或删除")
        # 备注用时间指认那一版，不用序号——序号只是链上的位置，不是这份内容的身份
        return self.create_document_revision(
            artifact_id, text, note="恢复自 {}".format(created_at) if created_at else "恢复历史版本")

    def create_document_revision(self, artifact_id, content, note=""):
        """Save a human edit as a new revision; the earlier bytes stay readable."""
        if not isinstance(content, str):
            raise ContractError("修订内容必须是文本")
        body = content.encode("utf-8")
        if not body.strip():
            raise ContractError("修订内容不能为空")
        if len(body) > self.DOCUMENT_REVISION_MAX_BYTES:
            raise ContractError("修订内容超过 2 MB，请在电脑上直接编辑原文件")
        note = str(note or "").strip()[:500]
        with self.repository.connect() as connection:
            chain = self._document_chain(connection, artifact_id)
            if not chain:
                raise ContractError("文档不存在")
            latest = chain[-1]
            latest_meta = self._decode_meta(latest["meta_json"])
            filename = str(latest_meta.get("path") or latest["name"] or "document.txt")
            if not self.is_document(filename):
                raise ContractError("这类文件不能在产品内编辑，请用系统应用打开")
            if not self.document_can_edit(filename):
                raise ContractError(self.document_edit_error(filename))
            root = int(latest_meta.get("revision_of") or chain[0]["id"])
            revision = int(latest_meta.get("revision") or len(chain)) + 1
            digest_value = hashlib.sha256(body).hexdigest()
            if latest_meta.get("source") == "agent_chat":
                key = _normalize_agent_document_key(
                    latest_meta.get("document_key"), latest["name"])
                destination = self._agent_document_path(key, digest_value)
            else:
                directory = (self.root / "artifacts" / str(latest["employee_run_id"])).resolve()
                directory.mkdir(parents=True, exist_ok=True)
                destination = directory / "{}-{}".format(
                    digest_value[:12], Path(filename).name)
            destination.write_bytes(body)
            meta = {"path": filename, "content_model": self.document_model_for_path(filename),
                    "sha256": digest_value, "size": len(body),
                    "revision": revision, "revision_of": root,
                    "author": "human", "note": note,
                    # Carry presentation metadata with the revision.  The
                    # Markdown body alone cannot represent alignment/color.
                    "editor_styles": copy.deepcopy(latest_meta.get("editor_styles") or {})}
            if latest_meta.get("source") == "agent_chat":
                meta.update({"path": "{}.md".format(key),
                             "document_key": key, "source": "agent_chat",
                             "data_view": copy.deepcopy(latest_meta.get("data_view"))})
            new_id = connection.execute(
                "INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) "
                "VALUES(?,?,?,?,?)",
                (latest["employee_run_id"], latest["name"], str(destination),
                 json.dumps(meta, ensure_ascii=False), utc_now())).lastrowid
            self.repository.event(
                ("document:{}".format(root) if latest_meta.get("source") == "agent_chat"
                 else "employee_run:{}".format(latest["employee_run_id"])), "artifact.revised",
                {"artifact_id": int(new_id), "revision_of": root, "revision": revision,
                 "note": note}, connection=connection)
        return int(new_id)

    def _latest_revision_by_ref(self, connection, employee_run_ids, same_format_only=True):
        """Map every stored ref to the current revision of its document."""
        if employee_run_ids is None:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE trashed_at IS NULL ORDER BY id"
            ).fetchall()
        else:
            employee_run_ids = [int(value) for value in employee_run_ids if value]
            if not employee_run_ids:
                return {}
            placeholders = ",".join("?" for _ in employee_run_ids)
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE employee_run_id IN ({}) AND trashed_at IS NULL "
                "ORDER BY id".format(placeholders), employee_run_ids).fetchall()
        chains, meta_by_id = {}, {}
        for row in rows:
            meta = self._decode_meta(row["meta_json"])
            meta_by_id[int(row["id"])] = meta
            chains.setdefault(int(meta.get("revision_of") or row["id"]), []).append(row)
        by_ref = {}
        for chain in chains.values():
            root_suffix = self._suffix_of(
                (meta_by_id[int(chain[0]["id"])].get("path")) or chain[0]["name"])
            # 机器交接跟着"同一格式"的最新版走；人把它改成 markdown 不该喂给等 JSON 的下游
            same_format = [row for row in chain
                           if self._suffix_of((meta_by_id[int(row["id"])].get("path"))
                                              or row["name"]) == root_suffix]
            current = (same_format or chain)[-1] if same_format_only else chain[-1]
            for row in chain:
                by_ref[row["ref"]] = {
                    "id": int(current["id"]), "ref": current["ref"],
                    "name": current["name"],
                    "revision": int(meta_by_id[int(current["id"])].get("revision") or 1),
                    "revised": int(current["id"]) != int(row["id"]),
                }
        return by_ref

    DOCUMENT_FORMATS = (".md", ".markdown")
    # Markdown 和 CSV/TSV 各自拥有原生编辑模型；其它格式先保持只读。
    DOCUMENT_EDITABLE_MODELS = frozenset(("markdown", "table"))
    DOCUMENT_TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".json", ".csv", ".tsv",
                              ".log", ".yaml", ".yml", ".xml", ".html", ".htm")

    @classmethod
    def _suffix_of(cls, path_or_name):
        name = str(path_or_name or "")
        dot = name.rfind(".")
        return name[dot:].lower() if dot >= 0 else ""

    @classmethod
    def is_document(cls, path_or_name):
        """文本类产物都算文档；格式保留原样，编辑能力由模型决定。"""
        return cls._suffix_of(path_or_name) in cls.DOCUMENT_TEXT_SUFFIXES

    @classmethod
    def is_native_markdown(cls, path_or_name):
        """兼容旧调用方：原生 Markdown 才是当前富文本编辑模型。"""
        return cls._suffix_of(path_or_name) in cls.DOCUMENT_FORMATS

    @classmethod
    def document_model_for_path(cls, path_or_name):
        """Return a stable content model, independent of rendered markup."""
        suffix = cls._suffix_of(path_or_name)
        if suffix in cls.DOCUMENT_FORMATS:
            return "markdown"
        if suffix in (".csv", ".tsv"):
            return "table"
        if suffix == ".json":
            return "json"
        if suffix in cls.DOCUMENT_TEXT_SUFFIXES:
            return "text"
        return "binary"

    @classmethod
    def document_can_edit(cls, path_or_name):
        return cls.document_model_for_path(path_or_name) in cls.DOCUMENT_EDITABLE_MODELS

    @classmethod
    def document_edit_error(cls, path_or_name):
        model = cls.document_model_for_path(path_or_name)
        labels = {"table": "表格", "json": "JSON", "text": "文本", "binary": "此格式"}
        return "{}目前是只读预览；请使用系统应用编辑原文件".format(
            labels.get(model, model))
    DOCUMENT_SEARCH_MAX_BYTES = 2 * 1024 * 1024

    def document_catalog(self, limit=500, query=""):
        """Project every published artifact with the lineage needed to read it.

        Ownership stays on the immutable run chain; pipeline and employee are
        only reported so the reader can offer them as filters.
        """
        limit = max(1, min(2000, int(limit)))
        query = str(query or "").strip().lower()
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT a.id,a.name,a.ref,a.meta_json,a.created_at,"
                "a.employee_run_id,er.position_key,er.workflow_run_id,"
                "wr.task_id,wr.snapshot_json "
                "FROM artifacts a "
                "LEFT JOIN employee_runs er ON er.id=a.employee_run_id "
                "LEFT JOIN workflow_runs wr ON wr.id=er.workflow_run_id "
                "WHERE a.trashed_at IS NULL "
                "ORDER BY a.id DESC LIMIT ?",
                (max(limit, min(4000, limit * 4)),)).fetchall()
        with self.repository.connect() as connection:
            current_by_ref = self._latest_revision_by_ref(
                connection, None,
                same_format_only=False)   # 包括 Agent Chat 文档
            all_rows = self._document_rows(connection)
            chain_sizes = {}
            for row in all_rows:
                meta = self._decode_meta(row["meta_json"])
                root = int(meta.get("revision_of") or row["id"])
                chain_sizes[root] = chain_sizes.get(root, 0) + 1
        items = []
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            if snapshot.get("trial"):
                continue
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                meta = {}
            if not self.is_document(meta.get("path") or row["name"]):
                continue   # 只有受支持的文本文档进入文档阅读器
            current = current_by_ref.get(row["ref"]) or {}
            if current and int(current.get("id") or 0) != int(row["id"]):
                continue  # 旧版本不占列表位置，从阅读器的版本历史里进
            root = int(meta.get("revision_of") or row["id"])
            positions = (snapshot.get("definition") or {}).get("positions") or []
            position = next((item for item in positions
                             if item.get("key") == row["position_key"]), {})
            employee = position.get("employee") or {}
            task = snapshot.get("task") or {}
            source = str(meta.get("source") or "employee")
            is_agent_document = source == "agent_chat"
            item = {
                "id": int(row["id"]),
                "name": str(row["name"] or "产物"),
                "path": str(meta.get("path") or ""),
                "size": int(meta.get("size") or 0),
                "created_at": row["created_at"],
                "revision": int(meta.get("revision") or 1),
                "revision_count": int(chain_sizes.get(root, 1)),
                "revised_by_human": str(meta.get("author") or "") == "human",
                "editable": self.document_can_edit(meta.get("path") or row["name"]),
                "content_model": meta.get("content_model") or self.document_model_for_path(
                    meta.get("path") or row["name"]),
                "source_format": self._suffix_of(meta.get("path") or row["name"]).lstrip("."),
                # 最后编辑者：当前版本可能是人修订出来的，而不是最初产出它的员工。
                "last_editor_kind": ("human" if str(meta.get("author") or "") == "human"
                                     else "employee"),
                "employee_run_id": int(row["employee_run_id"]) if row["employee_run_id"] else 0,
                "workflow_id": int(row["workflow_run_id"]) if row["workflow_run_id"] else 0,
                "task_id": int(row["task_id"] or 0),
                "task_title": str(task.get("title") or ("Agent Chat" if is_agent_document else "未命名任务")),
                "pipeline_id": int(snapshot.get("pipeline_id") or 0),
                "pipeline_name": str(snapshot.get("pipeline_name") or
                                      ("" if is_agent_document else "未命名流水线")),
                "position_key": str(row["position_key"] or ""),
                "position_name": self.position_display_name(position) if position else str(row["position_key"] or ""),
                "employee_id": int(position.get("employee_id") or 0),
                "employee_name": ("Agent Chat" if is_agent_document
                                   else str(employee.get("name") or "员工")),
                "source": source,
                "document_key": str(meta.get("document_key") or ""),
                "data_view": copy.deepcopy(meta.get("data_view")),
            }
            if query and not self._document_matches(row["ref"], item, query):
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def _document_matches(self, ref, item, query):
        """Match a document by its labels first, then by its text content."""
        for field in ("name", "path", "document_key", "task_title", "pipeline_name",
                      "position_name", "employee_name"):
            if query in str(item.get(field) or "").lower():
                return True
        suffix = Path(str(item.get("path") or item.get("name") or "")).suffix.lower()
        if suffix not in self.DOCUMENT_TEXT_SUFFIXES:
            return False
        try:
            path = Path(str(ref or "")).resolve()
            root = (self.root / "artifacts").resolve()
            if root not in path.parents or not path.is_file():
                return False
            if path.stat().st_size > self.DOCUMENT_SEARCH_MAX_BYTES:
                return False
            return query in path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            return False

    def attention_catalog(self, limit=100):
        """Project workflows requiring a human without creating intervention rows."""
        limit = max(1, min(500, int(limit)))
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT wr.id,wr.snapshot_json FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id "
                "WHERE t.trashed_at IS NULL "
                "AND wr.state IN ('needs_human','blocked','failed') "
                "ORDER BY wr.updated_at DESC,wr.id DESC LIMIT ?",
                (max(limit, min(2000, limit * 10)),)).fetchall()
        ids = []
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            if snapshot.get("trial"):
                continue
            ids.append(row["id"])
            if len(ids) >= limit:
                break
        return [self._workflow_attention(self.workflow(workflow_run_id))
                for workflow_run_id in ids]

    def failure_reasons(self, limit=2000):
        """Read failure facts from employee attempts; no aggregate state is persisted."""
        limit = max(1, min(10000, int(limit)))
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT er.state,er.output_json,wr.snapshot_json FROM employee_runs er "
                "JOIN workflow_runs wr ON wr.id=er.workflow_run_id "
                "WHERE er.state IN ('failed','blocked','interrupted') "
                "ORDER BY er.updated_at DESC,er.id DESC LIMIT ?",
                (max(limit, min(10000, limit * 10)),)).fetchall()
        reasons = []
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            if snapshot.get("trial"):
                continue
            try:
                result = json.loads(row["output_json"] or "{}")
            except (TypeError, ValueError):
                result = {}
            output = result.get("output") if isinstance(result.get("output"), dict) else {}
            issues = result.get("issues") if isinstance(result.get("issues"), list) else []
            reason = output.get("reason") or next((
                item if isinstance(item, str) else item.get("message")
                for item in issues if item), "") or result.get("summary")
            if reason:
                reasons.append(str(reason))
                if len(reasons) >= limit:
                    break
        return reasons

    @staticmethod
    def _workflow_attention(workflow):
        snapshot = workflow.get("snapshot_json") or {}
        task = snapshot.get("task") or {}
        employee_runs = RunTeamsCore._current_employee_runs(workflow)
        latest = (employee_runs or [{}])[-1]
        result = latest.get("output_json") or {}
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        issues = result.get("issues") if isinstance(result.get("issues"), list) else []
        issue_text = "；".join(
            str(item if isinstance(item, str) else item.get("message") or item)
            for item in issues if item)
        state = workflow.get("state")
        position_key = latest.get("position_key")
        positions = (snapshot.get("definition") or {}).get("positions", [])
        position = next((item for item in positions
                         if item.get("key") == position_key), {})
        position_names = {
            item.get("key"): str(item.get("name") or item.get("key") or "当前岗位")
            for item in positions
        }
        state_labels = {
            "ready": "等待运行",
            "running": "正在工作",
            "waiting_retry": "等待重试",
            "completed": "已完成",
            "needs_human": "需要处理",
            "blocked": "已阻塞",
            "failed": "运行失败",
            "interrupted": "意外中断",
            "canceled": "已停止",
        }
        attempted = [
            "{}：第 {} 次运行，{}".format(
                position_names.get(item.get("position_key"),
                                   item.get("position_key") or "当前岗位"),
                int(item.get("attempt") or 1),
                state_labels.get(item.get("state"), item.get("state") or "状态未知"),
            )
            for item in employee_runs
        ]
        node_name = (RunTeamsCore.position_display_name(position)
                     if position else str(position_key or "当前岗位"))
        if state == "needs_human":
            kind, title = "information", "员工需要你的回复"
            reason = output.get("question") or "员工需要你补充信息后才能继续。"
            recovery = "回复后会从当前岗位继续运行。"
            actions = [
                {"id": "respond", "label": "回复并继续", "style": "primary"},
                {"id": "terminate", "label": "终止任务", "style": "danger"},
            ]
            resume_from = "回复后从「{}」继续；已完成的上游岗位不会重新运行。".format(
                node_name)
        else:
            kind = state
            title = "任务已阻塞" if state == "blocked" else "任务运行失败"
            reason = output.get("reason") or issue_text or result.get("summary") or title
            recovery = (output.get("recovery") or
                        ("补充所需条件后重新运行。" if state == "blocked"
                         else "检查失败原因后重新运行。"))
            actions = [
                {"id": "retry", "label": "重新运行", "style": "primary"},
                {"id": "terminate", "label": "终止任务", "style": "danger"},
            ]
            resume_from = "重新运行会从「{}」继续；已完成的上游岗位不会重新运行。".format(
                node_name)
        context = output.get("context") or ""
        if not isinstance(context, str):
            context = json.dumps(context, ensure_ascii=False)
        return {
            "id": "workflow:{}".format(workflow["id"]),
            "target_type": "workflow",
            "workflow_id": int(workflow["id"]),
            "pipeline_id": int(snapshot.get("pipeline_id") or 0),
            "card_id": 0,
            "automation_id": None,
            "kind": kind,
            "title": title,
            "reason": str(reason),
            "context": context,
            "recovery": str(recovery),
            "attempted": attempted,
            "resume_from": resume_from,
            "pipeline_name": str(snapshot.get("pipeline_name") or "未命名流水线"),
            "node_name": node_name,
            "card_title": str(task.get("title") or "未命名任务"),
            "attempt_count": latest.get("attempt"),
            "artifact_count": sum(len(item.get("artifacts") or [])
                                  for item in workflow.get("employee_runs") or []),
            "created_at": latest.get("updated_at") or workflow.get("updated_at"),
            "actions": actions,
        }

    def workflow(self, workflow_run_id):
        with self.repository.connect() as connection:
            run = connection.execute("SELECT * FROM workflow_runs WHERE id=?",
                                     (int(workflow_run_id),)).fetchone()
            task = connection.execute(
                "SELECT id,title,payload_json,state,trashed_at FROM tasks WHERE id=("
                "SELECT task_id FROM workflow_runs WHERE id=?)", (int(workflow_run_id),)
            ).fetchone()
            employee_runs = connection.execute(
                "SELECT * FROM employee_runs WHERE workflow_run_id=? ORDER BY id",
                (int(workflow_run_id),)).fetchall()
            all_artifacts = connection.execute(
                "SELECT a.* FROM artifacts a JOIN employee_runs e ON e.id=a.employee_run_id "
                "WHERE e.workflow_run_id=? AND a.trashed_at IS NULL ORDER BY a.id",
                (int(workflow_run_id),)).fetchall()
        if run is None:
            return None
        item = self.repository.decode(run, "snapshot_json")
        item["task"] = self.repository.decode(task, "payload_json")
        artifact_rows = [self.repository.decode(row, "meta_json") for row in all_artifacts]
        artifacts_by_run = {}
        ref_map = {}
        for artifact in artifact_rows:
            ref_map[artifact["ref"]] = "artifact://{}".format(artifact["id"])
            artifacts_by_run.setdefault(artifact["employee_run_id"], []).append(artifact)
        decoded_runs = []
        for row in employee_runs:
            employee_run = self.repository.decode(row, "input_json", "output_json")
            employee_run["input_json"] = self._public_artifact_refs(
                employee_run["input_json"], ref_map)
            employee_run["output_json"] = self._public_artifact_refs(
                employee_run["output_json"], ref_map)
            employee_run["artifacts"] = [self._public_artifact_refs(artifact, ref_map)
                                         for artifact in artifacts_by_run.get(employee_run["id"], [])]
            employee_run["events"] = self.repository.events(
                "employee_run:{}".format(employee_run["id"]))
            decoded_runs.append(employee_run)
        item["employee_runs"] = decoded_runs
        definition = (item.get("snapshot_json") or {}).get("definition") or {}
        task_payload = (item.get("task") or {}).get("payload_json") or {}
        item["team_parameters"] = self._collect_team_parameter_values(
            definition, task_payload, decoded_runs)
        item["events"] = self.repository.events("workflow_run:{}".format(workflow_run_id))
        item["artifacts"] = [self._public_artifact_refs(artifact, ref_map)
                             for artifact in artifact_rows]
        if item.get("state") == "needs_approval":
            cursor = str(item.get("cursor_key") or "")
            position = next((value for value in
                             (item.get("snapshot_json") or {}).get(
                                 "definition", {}).get("positions", [])
                             if value.get("key") == cursor), None)
            if position:
                item["approval"] = {
                    "position_key": cursor,
                    "name": position.get("name") or "人工审批",
                    "prompt": position.get("prompt") or "请确认是否继续",
                }
        return item

    @classmethod
    def _public_artifact_refs(cls, value, ref_map):
        if isinstance(value, list):
            return [cls._public_artifact_refs(item, ref_map) for item in value]
        if isinstance(value, dict):
            return {key: (ref_map.get(item, item) if key == "ref" else
                          cls._public_artifact_refs(item, ref_map))
                    for key, item in value.items()}
        return value

    def artifact(self, artifact_id):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=?",
                                     (int(artifact_id),)).fetchone()
        return self.repository.decode(row, "meta_json")

    def _position_runs(self, workflow_run_id):
        with self.repository.connect() as connection:
            floor = int(connection.execute(
                "SELECT COALESCE(MAX(CAST(json_extract(data_json,'$.after_employee_run_id') "
                "AS INTEGER)),0) FROM events WHERE stream=? "
                "AND type='workflow.task_recompiled'",
                ("workflow_run:{}".format(int(workflow_run_id)),)).fetchone()[0])
            rows = connection.execute(
                "SELECT * FROM employee_runs WHERE workflow_run_id=? AND id>? ORDER BY id",
                (int(workflow_run_id), floor)).fetchall()
        completed, latest = {}, {}
        for row in rows:
            item = dict(row)
            latest[item["position_key"]] = item
            if item["state"] == "completed":
                completed[item["position_key"]] = json.loads(item["output_json"])
        return completed, latest

    def _human_response(self, workflow_run_id, employee_run_id):
        for event in reversed(self.repository.events(
                "workflow_run:{}".format(int(workflow_run_id)))):
            if event["type"] != "workflow.human_responded":
                continue
            data = event.get("data_json") or {}
            if int(data.get("employee_run_id") or 0) == int(employee_run_id):
                return str(data.get("response") or "").strip()
        return ""

    @staticmethod
    def _expected_output_with_deliverables(expected_output, position):
        """把岗位声明的交付文档写进工作单：员工要先知道该产出什么，才可能产出。"""
        declared = (((position.get("employee") or {}).get("program") or {})
                    .get("deliverables") or [])
        if not declared:
            return expected_output
        values = dict(expected_output or {})
        values["documents"] = [
            {"path": item["path"], "name": item["name"],
             "required": bool(item.get("required", True))}
            for item in declared]
        return values

    def _inputs_at_current_revision(self, workflow_run_id, artifacts):
        """Hand the downstream employee the revision a human left standing."""
        inputs = copy.deepcopy(artifacts) if isinstance(artifacts, list) else []
        if not inputs:
            return inputs
        with self.repository.connect() as connection:
            run_ids = [row[0] for row in connection.execute(
                "SELECT id FROM employee_runs WHERE workflow_run_id=?",
                (int(workflow_run_id),)).fetchall()]
            by_ref = self._latest_revision_by_ref(connection, run_ids)
            trashed_refs = {row[0] for row in connection.execute(
                "SELECT a.ref FROM artifacts a JOIN employee_runs er "
                "ON er.id=a.employee_run_id WHERE er.workflow_run_id=? "
                "AND a.trashed_at IS NOT NULL", (int(workflow_run_id),)).fetchall()}
        kept = []
        current_artifact_ids = set()
        for item in inputs:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            ref = str(item.get("ref") or "")
            current = by_ref.get(ref)
            if current is None:
                if ref and ref in trashed_refs:
                    continue   # 老板扔进垃圾箱的文档不再交给下游
                kept.append(item)
                continue
            # The cumulative handoff query can contain both the employee's
            # original artifact and a later human revision.  They are one
            # logical document, so downstream receives only the current
            # revision while history remains available in the document view.
            current_id = int(current["id"])
            if current_id in current_artifact_ids:
                continue
            current_artifact_ids.add(current_id)
            if current["revised"]:
                item["ref"] = current["ref"]
                item["revision"] = current["revision"]
                item["revised_by_human"] = True
            kept.append(item)
        return kept

    def _workflow_handoff_artifacts(self, workflow_run_id):
        """Return every published artifact in the task's current compiled revision."""
        stream = "workflow_run:{}".format(int(workflow_run_id))
        with self.repository.connect() as connection:
            floor = int(connection.execute(
                "SELECT COALESCE(MAX(CAST(json_extract(data_json,'$.after_employee_run_id') "
                "AS INTEGER)),0) FROM events WHERE stream=? "
                "AND type='workflow.task_recompiled'", (stream,)).fetchone()[0])
            rows = connection.execute(
                "SELECT a.name,a.ref,a.meta_json FROM artifacts a "
                "JOIN employee_runs er ON er.id=a.employee_run_id "
                "WHERE er.workflow_run_id=? AND er.id>? AND er.state='completed' "
                "AND a.trashed_at IS NULL ORDER BY a.id",
                (int(workflow_run_id), floor),
            ).fetchall()
        return [dict({"name": row["name"], "ref": row["ref"]},
                     **self._decode_meta(row["meta_json"])) for row in rows]

    @staticmethod
    def _result_team_parameters(result):
        """Read employee-produced values from the normal WorkResult output."""
        if not isinstance(result, dict):
            return {}
        output = result.get("output")
        if not isinstance(output, dict):
            return {}
        raw = output.get("team_parameters")
        if isinstance(raw, dict):
            return copy.deepcopy(raw)
        if isinstance(raw, list):
            values = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if key and "value" in item:
                    values[key] = copy.deepcopy(item["value"])
            return values
        return {}

    @classmethod
    def _collect_team_parameter_values(cls, definition, payload, employee_runs):
        declarations = {item["key"]: item for item in
                        (definition.get("parameters") or [])
                        if item.get("type") != "secret"}
        supplied = payload.get("parameters") or {}
        values = {key: copy.deepcopy(value) for key, value in supplied.items()
                  if key in declarations and declarations[key].get("source") == "user"}
        for key, declaration in declarations.items():
            if (declaration.get("source") == "user" and key not in values and
                    "default" in declaration):
                values[key] = copy.deepcopy(declaration["default"])
        for run in employee_runs or []:
            if str(run.get("state") or "") != "completed":
                continue
            position_key = str(run.get("position_key") or "")
            result = run.get("output_json") or {}
            for key, value in cls._result_team_parameters(result).items():
                declaration = declarations.get(key)
                if not declaration or declaration.get("source") != "employee":
                    continue
                writers = declaration.get("writers") or []
                if writers and position_key not in writers:
                    continue
                values[key] = copy.deepcopy(value)
        return values

    def _workflow_team_parameter_values(self, workflow_run_id, definition, payload):
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT position_key,state,output_json FROM employee_runs "
                "WHERE workflow_run_id=? ORDER BY id", (int(workflow_run_id),)
            ).fetchall()
        runs = [self.repository.decode(row, "output_json") for row in rows]
        return self._collect_team_parameter_values(definition, payload, runs)

    @staticmethod
    def _team_parameters(definition, payload, position_key, values=None):
        values = values if isinstance(values, dict) else payload.get("parameters") or {}
        if not isinstance(values, dict):
            values = {}
        context, expected = [], []
        for parameter in definition.get("parameters") or []:
            if parameter.get("type") == "secret":
                continue
            visible = parameter.get("visible_to") or []
            if visible and position_key not in visible:
                continue
            declaration = {key: parameter[key] for key in
                           ("key", "label", "type", "note") if key in parameter}
            if parameter.get("source") == "employee":
                if parameter["key"] in values:
                    context.append(dict(
                        declaration,
                        value=copy.deepcopy(values[parameter["key"]]),
                    ))
                writers = parameter.get("writers") or []
                if not writers or position_key in writers:
                    expected.append(declaration)
                continue
            declaration["value"] = values.get(
                parameter["key"], parameter.get("default"))
            context.append(declaration)
        return context, expected

    @staticmethod
    def _team_standards(definition, employee_id):
        """Return the frozen pipeline rules that apply to this employee."""
        employee_id = int(employee_id or 0)
        result = []
        for standard in definition.get("standards") or []:
            selected = {int(value) for value in
                        standard.get("employee_ids") or []}
            if selected and employee_id not in selected:
                continue
            result.append({key: copy.deepcopy(standard[key]) for key in
                           ("key", "name", "description", "instructions")
                           if key in standard})
        return result

    def _work_order(self, workflow_run_id, task, position, order, position_index,
                    previous_result, latest_run, definition):
        team_values = self._workflow_team_parameter_values(
            workflow_run_id, definition, task["payload"])
        parameter_context, parameter_output = self._team_parameters(
            definition, task["payload"], position["key"], team_values)
        team_standards = self._team_standards(
            definition, position.get("employee_id"))
        if position_index == 0:
            context = dict(task["payload"].get("context") or {})
            if parameter_context:
                context["team_parameters"] = parameter_context
            if team_standards:
                context["team_standards"] = team_standards
            expected_output = self._expected_output_with_deliverables(
                task["payload"].get("expected_output") or {}, position)
            if parameter_output:
                expected_output["team_parameters"] = parameter_output
            values = {
                "objective": task["payload"].get("objective") or task["title"],
                "context": context,
                "inputs": task["payload"].get("inputs") or [],
                "expected_output": expected_output,
                "acceptance": task["payload"].get("acceptance") or [],
            }
        else:
            if previous_result is None:
                raise ContractError("已完成的上游员工缺少结构化结果")
            context = {
                "upstream_position": order[position_index - 1],
                "upstream_summary": previous_result["summary"],
                "upstream_output": previous_result["output"],
            }
            if parameter_context:
                context["team_parameters"] = parameter_context
            if team_standards:
                context["team_standards"] = team_standards
            expected_output = self._expected_output_with_deliverables({}, position)
            if parameter_output:
                expected_output["team_parameters"] = parameter_output
            inputs = copy.deepcopy(task["payload"].get("inputs") or [])
            seen_input_refs = {str(item.get("ref") or "") for item in inputs
                               if isinstance(item, dict) and item.get("ref")}
            for item in self._inputs_at_current_revision(
                    workflow_run_id, self._workflow_handoff_artifacts(workflow_run_id)):
                ref = str(item.get("ref") or "") if isinstance(item, dict) else ""
                if ref and ref in seen_input_refs:
                    continue
                inputs.append(item)
                if ref:
                    seen_input_refs.add(ref)
            values = {
                "objective": position["employee"]["program"]["objective"],
                "context": context,
                "inputs": inputs,
                "expected_output": expected_output,
                "acceptance": position["employee"]["program"]["acceptance"],
            }
        if latest_run is not None and latest_run["state"] in (
                "failed", "interrupted", "blocked"):
            try:
                previous_output = json.loads(latest_run["output_json"])
            except (TypeError, ValueError):
                previous_output = {}
            result_output = previous_output.get("output") or {}
            instruction = "保留工作区已有成果，先诊断上次中断原因，再继续当前岗位。"
            if latest_run["state"] == "blocked":
                instruction = (str(result_output.get("recovery") or "").strip()
                               or "保留工作区已有成果，根据上次阻塞原因重新检查后继续。")
            context["recovery_context"] = {
                "state": latest_run["state"], "attempt": latest_run["attempt"],
                "issues": previous_output.get("issues") or [],
                "instruction": instruction,
            }
        if latest_run is not None and latest_run["state"] == "needs_human":
            response = self._human_response(workflow_run_id, latest_run["id"])
            if response:
                try:
                    previous_output = json.loads(latest_run["output_json"])
                except (TypeError, ValueError):
                    previous_output = {}
                request = previous_output.get("output") or {}
                context["human_response"] = {
                    "question": str(request.get("question") or ""),
                    "context": request.get("context") or "",
                    "response": response,
                }
                # Preserve a human reply as a first-class work input as well
                # as context.  Employees whose contract validates structured
                # inputs (rather than reading free-form context) can now use
                # the supplied fields when a needs_human run is resumed.
                values["inputs"] = list(values.get("inputs") or [])
                values["inputs"].append({
                    "name": "human-response.txt",
                    "content": response,
                    "source": "human",
                })
        return normalize_work_order(values)

    def _invoke_runtime(self, runtime, employee, work_order, emit, employee_run_id, cancel_event):
        method = getattr(runtime, "run", None)
        if not callable(method):
            return runtime(employee, work_order, emit)
        keywords = {"employee_run_id": employee_run_id, "database": self.repository.path}
        try:
            parameters = inspect.signature(method).parameters.values()
            accepts_any = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters)
            names = {item.name for item in parameters}
        except (TypeError, ValueError):
            accepts_any, names = False, set(keywords)
        if accepts_any or "cancel_event" in names:
            keywords["cancel_event"] = cancel_event
        return method(employee, work_order, emit, **keywords)

    def _set_workflow_state(self, workflow_run_id, state, available_at=None,
                            event_type=None, data=None):
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT task_id,state FROM workflow_runs WHERE id=?",
                                     (int(workflow_run_id),)).fetchone()
            if row is None:
                raise ContractError("工作流运行不存在")
            if row["state"] == "canceled" and state != "canceled":
                return False
            connection.execute(
                "UPDATE workflow_runs SET state=?,available_at=?,updated_at=? WHERE id=?",
                (state, available_at, now, int(workflow_run_id)))
            connection.execute("UPDATE tasks SET state=?,updated_at=? WHERE id=?",
                               (state, now, row["task_id"]))
            self.repository.event(
                "workflow_run:{}".format(workflow_run_id),
                event_type or "workflow.{}".format(state), data or {}, connection=connection)
        return True

    def _workflow_state_value(self, workflow_run_id):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT state FROM workflow_runs WHERE id=?",
                                     (int(workflow_run_id),)).fetchone()
        return row["state"] if row is not None else None

    def _workflow_result(self, workflow_run_id):
        with self.repository.connect() as connection:
            workflow = connection.execute("SELECT state FROM workflow_runs WHERE id=?",
                                          (int(workflow_run_id),)).fetchone()
            employee_run = connection.execute(
                "SELECT output_json FROM employee_runs WHERE workflow_run_id=? "
                "AND output_json!='{}' ORDER BY id DESC LIMIT 1",
                (int(workflow_run_id),)).fetchone()
        if employee_run is not None:
            return json.loads(employee_run["output_json"])
        return {"schema": "runteams.workflow-control/v1", "status": workflow["state"],
                "workflow_run_id": int(workflow_run_id)}

    def _employee_attempt(self, employee_run_id):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT attempt FROM employee_runs WHERE id=?",
                                     (int(employee_run_id),)).fetchone()
        return int(row["attempt"])

    def _employee_failure_count(self, employee_run_id):
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT workflow_run_id,position_key FROM employee_runs WHERE id=?",
                (int(employee_run_id),)).fetchone()
            return int(connection.execute(
                "SELECT COUNT(*) FROM employee_runs WHERE workflow_run_id=? "
                "AND position_key=? AND state='failed'",
                (row["workflow_run_id"], row["position_key"])).fetchone()[0])

    def _cancel_event(self, workflow_run_id, reset=False):
        key = int(workflow_run_id)
        with self._cancel_lock:
            event = self._cancel_events.get(key)
            if event is None:
                event = threading.Event()
                self._cancel_events[key] = event
            if reset:
                event.clear()
            return event

    def _cancel_employee_run(self, employee_run_id):
        now = utc_now()
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT workflow_run_id FROM employee_runs WHERE id=?", (int(employee_run_id),)
            ).fetchone()
            connection.execute(
                "UPDATE employee_runs SET state='canceled',updated_at=? "
                "WHERE id=? AND state='running'", (now, int(employee_run_id)))
            if row is not None:
                self.repository.event(
                    "employee_run:{}".format(employee_run_id), "employee.canceled", {},
                    connection=connection)

    def _interrupt_employee_run(self, employee_run_id):
        now = utc_now()
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE employee_runs SET state='interrupted',updated_at=? "
                "WHERE id=? AND state='running'", (now, int(employee_run_id))).rowcount
            if changed:
                self.repository.event(
                    "employee_run:{}".format(employee_run_id), "employee.interrupted", {},
                    connection=connection)

    def _defer_employee_run(self, employee_run_id, exc):
        now = utc_now()
        output = {"schema": "runteams.external-wait/v1", "status": "interrupted",
                  "output": {}, "artifacts": [], "issues": [str(exc)[:1000]]}
        with self.repository.connect() as connection:
            changed = connection.execute(
                "UPDATE employee_runs SET state='interrupted',output_json=?,updated_at=? "
                "WHERE id=? AND state='running'",
                (json.dumps(output, ensure_ascii=False), now, int(employee_run_id))).rowcount
            if changed:
                self.repository.event(
                    "employee_run:{}".format(employee_run_id), "employee.deferred",
                    {"reason": exc.__class__.__name__}, connection=connection)

    @staticmethod
    def _canceled_result(workflow_run_id):
        return {"schema": "runteams.workflow-control/v1", "status": "canceled",
                "workflow_run_id": int(workflow_run_id)}

    def _start_employee_run(self, workflow_run_id, position, work_order):
        now = utc_now()
        with self.repository.connect() as connection:
            attempt = connection.execute(
                "SELECT COALESCE(MAX(attempt),0)+1 FROM employee_runs "
                "WHERE workflow_run_id=? AND position_key=?",
                (int(workflow_run_id), position["key"]),).fetchone()[0]
            run_id = connection.execute(
                "INSERT INTO employee_runs(workflow_run_id,position_key,employee_release_id,attempt,state,"
                "input_json,output_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (int(workflow_run_id), position["key"], position.get("employee_release_id"), attempt,
                 "running", json.dumps(work_order, ensure_ascii=False), "{}", now, now),).lastrowid
            self.repository.event(
                "workflow_run:{}".format(workflow_run_id), "employee.started",
                {"employee_run_id": run_id, "position_key": position["key"],
                 "employee_release_id": position.get("employee_release_id"),
                 "attempt": attempt,
                 "runtime": {key: (position.get("employee") or {}).get("runtime", {}).get(key)
                             for key in ("channel", "model", "effort")
                             if (position.get("employee") or {}).get("runtime", {}).get(key)},
                 "input_digest": digest(work_order)},
                connection=connection)
        return run_id

    def _finish_employee_run(self, employee_run_id, result):
        now = utc_now()
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT workflow_run_id,position_key,state FROM employee_runs WHERE id=?",
                (employee_run_id,)).fetchone()
            if row["state"] == "canceled":
                return False
            connection.execute("UPDATE employee_runs SET state=?,output_json=?,updated_at=? WHERE id=?",
                               (result["status"], json.dumps(result, ensure_ascii=False), now,
                                employee_run_id))
            self.repository.event(
                "workflow_run:{}".format(row["workflow_run_id"]), "employee.finished",
                {"employee_run_id": employee_run_id, "position_key": row["position_key"],
                 "state": result["status"],
                 "output_digest": digest(result)}, connection=connection)
        return True

    def _artifact(self, employee_run_id, artifact):
        name, ref = str(artifact.get("name") or "产物"), str(artifact.get("ref") or "")
        with self.repository.connect() as connection:
            if connection.execute(
                    "SELECT 1 FROM artifacts WHERE employee_run_id=? AND ref=?",
                    (employee_run_id, ref)).fetchone() is not None:
                return
            connection.execute(
                "INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) VALUES(?,?,?,?,?)",
                (employee_run_id, name, ref,
                 json.dumps({key: value for key, value in artifact.items()
                             if key not in ("name", "ref")}, ensure_ascii=False), utc_now()))
