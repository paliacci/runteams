"""Shared document service: immutable revisions, catalog, editing and trash."""
import copy
import datetime
import hashlib
import json
from pathlib import Path
import re

from .contracts import ContractError
from .repository_service import RepositoryService
from .repository import utc_now
from . import employee_documents
from .document_views import normalize_data_view as _normalize_document_data_view

_PLACEHOLDER_POSITION = re.compile(r"^第\s*\d+\s*岗$")
AGENT_DOCUMENT_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")

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


class Documents(RepositoryService):
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

    def _document_owner_names(self, connection, owner_ids):
        if not owner_ids:
            return {}
        placeholders = ",".join("?" for _ in owner_ids)
        return {int(row["id"]): str(row["name"]) for row in connection.execute(
            "SELECT id,name FROM employees WHERE id IN ({})".format(placeholders), list(owner_ids))}

    def _document_position_employee(self, position):
        return position.get("employee") or {}

    def _document_employee_owner(self):
        return {}

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
            owner=self._document_employee_owner().get('employee_reference')
            if owner is not None or meta.get('employee_reference') is not None:
                from .employee_references import same
                if owner is None or meta.get('employee_reference') is None or not same(owner,meta['employee_reference']):continue
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
        """Create a rich document from model-authored Markdown."""
        from . import rich_documents
        if not isinstance(content,str) or not content.strip():
            raise ContractError("文档内容不能为空")
        key = _normalize_agent_document_key(document_key, str(name or '').strip())
        with self.repository.definition_lock():
            with self.repository.connect() as connection:
                current=self._find_agent_document(connection,key)
            if current is not None:
                return self.update_agent_document(int(current['id']),name,content,data_view,note)
            value=rich_documents.from_markdown(content);value['blocks'][0]['id']='document-body'
            return rich_documents.write(self,name=name,document=value,
                document_key=key,base_revision=0,author='agent',data_view=data_view,note=note)

    def update_agent_document(self, document_id, name=None, content=None,
                              data_view=None, note=""):
        """Markdown updates cannot silently discard structured editor content."""
        from . import rich_documents
        with self.repository.definition_lock():
            with self.repository.connect() as connection:
                chain=self._document_chain(connection,document_id)
            if not chain:raise ContractError("文档不存在")
            latest=chain[-1];meta=self._decode_meta(latest['meta_json'])
            if meta.get('source')!='agent_chat':
                raise ContractError("只有对话创建的文档可以通过此动作更新")
            if meta.get('content_model')!=rich_documents.MODEL:
                raise ContractError("请新建文档，原测试格式不再支持编辑。")
            old=rich_documents.validate(self._read_document_body(latest))
            if content is None:
                value=old
            else:
                if not isinstance(content,str) or not content.strip():raise ContractError("文档内容不能为空")
                if any(block['type']!='markdown' for block in old['blocks']):
                    raise ContractError("文档含有可视化编辑内容，请读取完整结构后通过新版文档接口保存。")
                value=rich_documents.from_markdown(content)
                value['blocks'][0]['id']=old['blocks'][0]['id']
            result=rich_documents.write(self,name=name if name is not None else latest['name'],document=value,
                document_id=int(latest['id']),base_revision=int(meta.get('revision') or 1),author='agent',
                data_view=meta.get('data_view') if data_view is None else data_view,note=note)
            if result.get('conflict'):raise ContractError(result['error'])
            return result

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
            "editable": self.is_document_artifact(current_meta, current["name"]) and (current_meta.get('content_model')=='rich-document' or self.document_can_edit(current_path)),
            "employee_run_id": int(current["employee_run_id"]) if current["employee_run_id"] else 0,
            "workflow_id": 0, "task_id": 0, "pipeline_id": 0,
            "pipeline_name": "", "task_title": "", "position_name": "",
            "employee_id": 0,
            "employee_name": "Agent Chat" if current_meta.get("source") == "agent_chat" else "员工",
            "run_sequence": 0,
            # Presentation metadata belongs to the document revision, not to
            # a browser profile.  Keep it beside the Markdown bytes so a
            # reload, another device, or a newly-created revision sees the
            # same block styles.
        }
        if current_meta.get("source") == employee_documents.SOURCE:
            owner_id = int(current_meta.get("employee_id") or 0)
            with self.repository.connect() as connection:
                owner_names = self._document_owner_names(connection, [owner_id])
            # workflow_id/task_title stay unset: this document spans many runs,
            # so there is no single run to jump back to (unlike a deliverable).
            item.update({
                "employee_id": owner_id,
                "employee_name": owner_names.get(owner_id, "已删除的员工"),
                "employee_run_id": int(current_meta.get("employee_run_id") or 0),
                "run_sequence": int(current_meta.get("run_sequence") or 0),
            })
        elif current["employee_run_id"]:
            with self.repository.connect() as connection:
                lineage = connection.execute(
                    "SELECT er.workflow_run_id,er.position_key,wr.task_id,wr.snapshot_json "
                    "FROM employee_runs er JOIN workflow_runs wr ON wr.id=er.workflow_run_id "
                    "WHERE er.id=?", (int(current["employee_run_id"]),)).fetchone()
            if lineage:
                snapshot = self._decode_meta(lineage["snapshot_json"])
                positions = (snapshot.get("definition") or {}).get("positions") or []
                position = next((p for p in positions if p.get("key") == lineage["position_key"]), {})
                employee = self._document_position_employee(position)
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
            elif isinstance(view, dict) and view.get("kind") == "work_items":
                item["data"] = {"work_items": self.work_item_catalog(view["repository_key"])}
        return item

    def historical_document_detail(self, document_id):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=? AND trashed_at IS NULL", (int(document_id),)).fetchone()
        if row is None:
            return None
        item = self.document_detail(document_id, include_content=False)
        saved = self._decode_meta(row["meta_json"])
        item.update({"id": int(row["id"]), "name": row["name"], "created_at": row["created_at"],
                     "revision": int(saved.get("revision") or 1), "content": self._read_document_body(row),
                     "editable": False})
        return item

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
            chain = self._document_chain(connection, artifact_id)
            ids = [int(row["id"]) for row in chain]
            changed = 0
            for identifier in ids:
                changed += connection.execute("UPDATE artifacts SET trashed_at=? WHERE id=? AND trashed_at IS NULL", (now, identifier)).rowcount
        if not changed:
            raise ContractError("文档不存在或已经在垃圾箱里")
        return True

    def restore_document(self, artifact_id):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=? AND trashed_at IS NOT NULL", (int(artifact_id),)).fetchone()
            changed = 0
            if row:
                root = self._document_root_id(row)
                for candidate in self._document_rows(connection, include_trashed=True):
                    if self._document_root_id(candidate) == root:
                        changed += connection.execute("UPDATE artifacts SET trashed_at=NULL WHERE id=?", (candidate["id"],)).rowcount
        if not changed:
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
        seen = set()
        for row in rows:
            root = self._document_root_id(row)
            if root in seen:
                continue
            seen.add(root)
            snapshot = self._decode_meta(row["snapshot_json"])
            meta = self._decode_meta(row["meta_json"])
            task = snapshot.get("task") or {}
            trashed = datetime.datetime.fromisoformat(row["trashed_at"])
            items.append({
                "id": int(row["id"]),
                "kind": "document",
                "title": str(row["name"] or "文档"),
                "location": str(task.get("title") or (
                    "Agent Chat" if meta.get("source") == "agent_chat" else
                    "长期文档" if meta.get("source") == employee_documents.SOURCE else "任务")),
                "count": 0,
                "trashed_at": row["trashed_at"],
                "expires_at": (trashed + datetime.timedelta(days=30)).isoformat(
                    timespec="seconds"),
            })
        return items

    def delete_trashed_document(self, artifact_id):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=? AND trashed_at IS NOT NULL", (int(artifact_id),)).fetchone()
            if row is None:
                raise ContractError("垃圾箱中没有这份文档")
            root = self._document_root_id(row)
            rows = [candidate for candidate in self._document_rows(connection, include_trashed=True)
                    if self._document_root_id(candidate) == root]
            if any(candidate["trashed_at"] is None for candidate in rows):
                raise ContractError("请先将整份文档移入垃圾箱")
            for candidate in rows:
                connection.execute("DELETE FROM artifacts WHERE id=?", (candidate["id"],))
        self._delete_artifact_files([candidate["ref"] for candidate in rows])
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
                        and meta.get("source") not in ("agent_chat", employee_documents.SOURCE)
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
        with self.repository.connect() as c:
            rich_chain=self._document_chain(c,artifact_id)
        if rich_chain and self._decode_meta(rich_chain[-1]['meta_json']).get('content_model')=='rich-document':
            from . import rich_documents
            latest=rich_chain[-1];m=self._decode_meta(latest['meta_json'])
            value=rich_documents.validate(content)
            result=rich_documents.write(self,name=latest['name'],document=value,
                document_id=artifact_id,base_revision=int(m.get('revision') or 1))
            if result.get('conflict'):raise ContractError(result['error'])
            return result['id']
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
            if not self.is_document_artifact(latest_meta, latest["name"]):
                raise ContractError("证据与交付附件只读，不能当作文档修订")
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
            elif latest_meta.get("source") == employee_documents.SOURCE:
                key = employee_documents.normalize_key(latest_meta.get("document_key"))
                destination = employee_documents.storage_path(
                    self.root, latest_meta.get("employee_id"), key, digest_value)
            else:
                directory = (self.root / "artifacts" / str(latest["employee_run_id"])).resolve()
                directory.mkdir(parents=True, exist_ok=True)
                destination = directory / "{}-{}".format(
                    digest_value[:12], Path(filename).name)
            destination.write_bytes(body)
            meta = {"path": filename, "content_model": self.document_model_for_path(filename),
                    "sha256": digest_value, "size": len(body),
                    "revision": revision, "revision_of": root,
                    "author": "human", "note": note, "purpose": "document"}
            if latest_meta.get("source") == "agent_chat":
                meta.update({"path": "{}.md".format(key),
                             "document_key": key, "source": "agent_chat",
                             "data_view": copy.deepcopy(latest_meta.get("data_view")),
                             **{key:latest_meta[key] for key in ("employee_reference","workflow_id","work_report") if key in latest_meta}})
            elif latest_meta.get("source") == employee_documents.SOURCE:
                # A human edit stays in the employee's namespace so the next
                # run keeps maintaining the same chain from this revision.
                meta.update({"path": "{}.md".format(key), "document_key": key,
                             "source": employee_documents.SOURCE,
                             "employee_id": int(latest_meta.get("employee_id") or 0)})
            if latest_meta.get('work_report'):
                meta['work_report']=copy.deepcopy(latest_meta['work_report'])
            new_id = connection.execute(
                "INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) "
                "VALUES(?,?,?,?,?)",
                (latest["employee_run_id"], latest["name"], str(destination),
                 json.dumps(meta, ensure_ascii=False), utc_now())).lastrowid
            self.repository.event(
                ("document:{}".format(root)
                 if latest_meta.get("source") in ("agent_chat", employee_documents.SOURCE)
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
    def is_document_artifact(cls, meta, name=""):
        # Purpose is the document identity; suffixes only select a viewer.
        return meta.get("purpose") == "document"

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
            owner_ids = set()
            for row in all_rows:
                meta = self._decode_meta(row["meta_json"])
                root = int(meta.get("revision_of") or row["id"])
                chain_sizes[root] = chain_sizes.get(root, 0) + 1
                if meta.get("source") == employee_documents.SOURCE and meta.get("employee_id"):
                    owner_ids.add(int(meta["employee_id"]))
            owner_names = {}
            if owner_ids:
                owner_names = self._document_owner_names(connection, owner_ids)
        return self._document_catalog_projection(rows, current_by_ref, chain_sizes, owner_names, limit, query)

    def document_page(self, limit=40, query='', cursor=None, sort='created_at', descending=True):
        from .read_pages import scope_key, cursor_after, cursor_for, page_size
        size=page_size(limit)
        if sort not in ('created_at','name') or type(descending) is not bool:
            raise ContractError('文档排序无效')
        query=str(query or '').strip().lower()
        scope=scope_key('documents',self._actor(),self.repository.data_epoch(),query,sort,descending)
        after=cursor_after(cursor,scope)
        if after is not None and (len(after)!=2 or not isinstance(after[0],str) or type(after[1]) is not int):
            raise ContractError('文档分页位置无效')
        direction='DESC' if descending else 'ASC';operator='<' if descending else '>'
        expression='lower(a.name)' if sort=='name' else 'a.created_at'
        collected=[];sort_values={}
        with self.repository.connect() as connection:
            while len(collected)<=size:
                params=[];position=''
                if after is not None:
                    position=f' AND ({expression},a.id) {operator} (?,?)';params.extend(after)
                rows=connection.execute(
                    'SELECT a.id,a.name,a.ref,a.meta_json,a.created_at,a.employee_run_id,'
                    f'er.position_key,er.workflow_run_id,wr.task_id,wr.snapshot_json,{expression} AS page_sort, '
                    "(SELECT count(*) FROM artifacts rev WHERE rev.trashed_at IS NULL AND coalesce(json_extract(rev.meta_json,'$.revision_of'),rev.id)=coalesce(json_extract(a.meta_json,'$.revision_of'),a.id)) AS chain_size "
                    'FROM artifacts a LEFT JOIN employee_runs er ON er.id=a.employee_run_id '
                    'LEFT JOIN workflow_runs wr ON wr.id=er.workflow_run_id '
                    'WHERE a.trashed_at IS NULL AND NOT EXISTS(SELECT 1 FROM artifacts newer WHERE newer.trashed_at IS NULL '
                    "AND coalesce(json_extract(newer.meta_json,'$.revision_of'),newer.id)=coalesce(json_extract(a.meta_json,'$.revision_of'),a.id) AND newer.id>a.id)"
                    +position+f' ORDER BY {expression} {direction},a.id {direction} LIMIT 64',params).fetchall()
                if not rows:break
                owner_ids={int(self._decode_meta(row['meta_json']).get('employee_id') or 0) for row in rows}
                owners=self._document_owner_names(connection, owner_ids)
                chain_sizes={int(self._decode_meta(row['meta_json']).get('revision_of') or row['id']):int(row['chain_size']) for row in rows}
                items=self._document_catalog_projection(rows,{},chain_sizes,owners,size+1-len(collected),query)
                collected.extend(items)
                sort_values.update({int(row['id']):row['page_sort'] for row in rows})
                after=[rows[-1]['page_sort'],int(rows[-1]['id'])]
                if len(rows)<64:break
        more=len(collected)>size;items=collected[:size]
        next_cursor=cursor_for(scope,[sort_values[items[-1]['id']],items[-1]['id']]) if more else None
        return {'documents':items,'has_more':more,'next_cursor':next_cursor}

    def _document_catalog_projection(self, rows, current_by_ref, chain_sizes, owner_names, limit, query):
        items = []
        for row in rows:
            try:
                snapshot = json.loads(row["snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                meta = {}
            if not self.is_document_artifact(meta, row["name"]):
                continue   # 只有受支持的文本文档进入文档阅读器
            current = current_by_ref.get(row["ref"]) or {}
            if current and int(current.get("id") or 0) != int(row["id"]):
                continue  # 旧版本不占列表位置，从阅读器的版本历史里进
            root = int(meta.get("revision_of") or row["id"])
            positions = (snapshot.get("definition") or {}).get("positions") or []
            position = next((item for item in positions
                             if item.get("key") == row["position_key"]), {})
            employee = self._document_position_employee(position)
            task = snapshot.get("task") or {}
            source = str(meta.get("source") or "employee")
            is_agent_document = source == "agent_chat"
            is_employee_document = source == employee_documents.SOURCE
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
                "employee_run_id": (int(meta.get("employee_run_id") or 0) if is_employee_document
                                    else (int(row["employee_run_id"]) if row["employee_run_id"] else 0)),
                # workflow_id stays 0 for employee documents: they span many
                # runs, so there is no single run for the reader's "回到运行
                # 记录" trail to jump back to (unlike a one-run deliverable).
                "workflow_id": (0 if is_employee_document
                                else (int(row["workflow_run_id"]) if row["workflow_run_id"] else 0)),
                "task_id": int(row["task_id"] or 0),
                "task_title": str(task.get("title") or (
                    "Agent Chat" if is_agent_document else
                    "长期文档" if is_employee_document else "未命名任务")),
                "pipeline_id": int(snapshot.get("pipeline_id") or 0),
                "pipeline_name": str(snapshot.get("pipeline_name") or
                                      ("" if is_agent_document or is_employee_document
                                       else "未命名流水线")),
                "position_key": str(row["position_key"] or ""),
                "position_name": self.position_display_name(position) if position else str(row["position_key"] or ""),
                "employee_id": (int(meta.get("employee_id") or 0) if is_employee_document
                                else int(position.get("employee_id") or 0)),
                "employee_name": ("Agent Chat" if is_agent_document
                                   else owner_names.get(int(meta.get("employee_id") or 0), "已删除的员工")
                                   if is_employee_document else str(employee.get("name") or "员工")),
                "run_sequence": int(meta.get("run_sequence") or 0) if is_employee_document else 0,
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

    def employee_document_summaries(self, employee_id):
        """Long-lived documents this employee maintains, newest revision first.

        Used only by the employee detail page — the catalog list must not pay
        for this per employee, so it is a separate call, not part of
        ``employee()``/``employee_catalog()``.
        """
        with self.repository.connect() as connection:
            owned = employee_documents.owned_documents(connection, int(employee_id))
        items = [employee_documents.summary(row, length) for row, length in owned.values()]
        items.sort(key=lambda item: item["updated_at"], reverse=True)
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

    def artifact(self, artifact_id):
        with self.repository.connect() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE id=?",
                                     (int(artifact_id),)).fetchone()
        return self.repository.decode(row, "meta_json")
