"""Long-lived documents that an employee maintains across runs.

These documents reuse the ``artifacts`` immutable revision chain exactly like
Agent Chat documents: ``employee_run_id`` stays NULL so deleting a run or a
workflow never destroys them, and provenance lives in ``meta_json``
(``source=employee_run``, stable ``employee_id``, the writing run).  No new
business table is introduced.

Ownership follows the employee's stable identity (``employees.id``), so a
re-published employee keeps its namespace.  ``document_key`` is unique within
one employee. Documents keep that stable owner across published revisions.
"""

import hashlib
import json
from pathlib import Path
import re

from .contracts import ContractError
from .document_views import normalize_data_view
from .repository import utc_now


SOURCE = "employee_run"
MAX_BYTES = 2 * 1024 * 1024
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
# Only complete canonical document links identify a document reference.
REFERENCE_PATTERN = re.compile(
    r"(?<![\w:/?=&%#.-])runteams://document/([1-9][0-9]*)"
    r"(?:#[a-zA-Z0-9._:-]+)?(?=$|[\s\"'\]\[()<>{}。，；！？])")


class DocumentConflict(ContractError):
    """Optimistic concurrency failure: the caller wrote from a stale revision."""

    def __init__(self, message, current_revision):
        super().__init__(message)
        self.current_revision = int(current_revision)


def _meta(row):
    try:
        value = json.loads(row["meta_json"] or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _root_id(row):
    return int(_meta(row).get("revision_of") or row["id"])


def normalize_key(value):
    key = str(value or "").strip().casefold()
    if not KEY_PATTERN.fullmatch(key):
        raise ContractError("document_key 只能包含小写字母、数字、点、下划线和连字符，且以字母或数字开头")
    return key


def referenced_ids(work_order):
    """Document ids the work order explicitly links to."""
    text = json.dumps(work_order or {}, ensure_ascii=False)
    return sorted({int(value) for value in REFERENCE_PATTERN.findall(text)
                   if int(value) <= 2**53-1})


def storage_path(root, employee_id, key, digest_value):
    base = (Path(root) / "artifacts" / "employee-documents").resolve()
    directory = (base / str(int(employee_id))).resolve()
    destination = (directory / "{}-{}.rich.json".format(key, digest_value[:12])).resolve()
    if base not in destination.parents:
        raise ContractError("文档路径不安全")
    directory.mkdir(parents=True, exist_ok=True)
    return destination


def read_body(root, row):
    base = (Path(root) / "artifacts").resolve()
    path = Path(str(row["ref"] or "")).resolve()
    if path == base or base not in path.parents or not path.is_file():
        raise ContractError("文档文件不可用")
    try:
        content=path.read_text(encoding="utf-8")
        if _meta(row).get("content_model")=="rich-document":
            from .rich_documents import narrative
            return narrative(content)
        return content
    except (OSError, UnicodeDecodeError) as exc:
        raise ContractError("文档内容无法以文本读取") from exc


def is_owned(meta, employee_id):
    return (meta.get("purpose") == "document" and meta.get("source") == SOURCE
            and int(meta.get("employee_id") or 0) == int(employee_id))


def _chains(connection):
    chains = {}
    for row in connection.execute(
            "SELECT * FROM artifacts WHERE trashed_at IS NULL ORDER BY id").fetchall():
        chains.setdefault(_root_id(row), []).append(row)
    return chains


def owned_documents(connection, employee_id):
    """Current revision of each document the employee owns, keyed by document_key."""
    result = {}
    for chain in _chains(connection).values():
        current = chain[-1]
        meta = _meta(current)
        if is_owned(meta, employee_id):
            result[str(meta.get("document_key") or "")] = (current, len(chain))
    return result


def _trashed_conflict(connection, employee_id, key):
    """A trashed revision already owns this key.

    ``document_key`` must stay unique per employee even while the old chain
    sits in the (recoverable) trash, so a fresh write must not silently start
    a second, unrelated chain under the same key.
    """
    rows = connection.execute(
        "SELECT * FROM artifacts WHERE trashed_at IS NOT NULL").fetchall()
    for row in rows:
        meta = _meta(row)
        if (is_owned(meta, employee_id)
                and str(meta.get("document_key") or "") == key):
            return row
    return None


def current_revision(connection, document_id):
    """Resolve any revision id to (current row, chain length) or (None, 0)."""
    row = connection.execute("SELECT * FROM artifacts WHERE id=?",
                             (int(document_id),)).fetchone()
    if row is None:
        return None, 0
    chain = _chains(connection).get(_root_id(row)) or []
    return (chain[-1], len(chain)) if chain else (None, 0)


def summary(row, chain_length):
    meta = _meta(row)
    return {"document_id": int(row["id"]), "name": str(row["name"] or ""),
            "document_key": str(meta.get("document_key") or ""),
            "revision": int(meta.get("revision") or chain_length or 1),
            "revision_count": int(chain_length or 1),
            "source": str(meta.get("source") or "employee"),
            "author": str(meta.get("author") or ""),
            "content_model": str(meta.get("content_model") or ""),
            "data_view": meta.get("data_view"),
            "size": int(meta.get("size") or 0),
            "updated_at": row["created_at"],
            "updated_by_employee_run_id": int(meta.get("employee_run_id") or 0),
            "workflow_id": int(meta.get("workflow_run_id") or 0),
            # Frozen at write time so it stays meaningful even after the
            # writing run or its workflow is later deleted.
            "run_sequence": int(meta.get("run_sequence") or 0),
            "internal_link": "runteams://document/{}".format(int(row["id"]))}


def _run_ordinal(connection, employee_id, employee_run_id):
    """This run's 1-based position among every run of this employee that has
    ever written an owned document, frozen into the revision so it survives
    later deletion of the runs it is counting."""
    rows = connection.execute(
        "SELECT DISTINCT json_extract(meta_json,'$.employee_run_id') AS rid "
        "FROM artifacts WHERE json_extract(meta_json,'$.source')=? "
        "AND json_extract(meta_json,'$.employee_id')=?",
        (SOURCE, int(employee_id))).fetchall()
    ids = {int(row["rid"]) for row in rows if row["rid"] is not None}
    ids.add(int(employee_run_id))
    return sorted(ids).index(int(employee_run_id)) + 1

def write(repository, root, *, employee_id, employee_run_id, workflow_run_id,
          document_key, name, content, base_revision=None, note="", data_view=None):
    """Create or revise one owned document with optimistic concurrency.

    Identical content (same bytes and title) is a no-op so retries of the same
    run never mint duplicate revisions.  Otherwise ``base_revision`` must equal
    the current revision (or be absent/0 when the document does not exist yet).
    """
    view = normalize_data_view(data_view)
    key = normalize_key(document_key)
    title = str(name or "").strip()
    if len(title) > 200:
        raise ContractError("文档标题不能超过 200 个字符")
    if not isinstance(content, str) or not content.strip():
        raise ContractError("文档内容不能为空")
    from . import rich_documents
    value=rich_documents.from_markdown(content);value['blocks'][0]['id']='document-body'
    body = rich_documents.encode(value).encode("utf-8")
    if len(body) > MAX_BYTES:
        raise ContractError("文档内容超过 2 MB")
    try:
        base = int(base_revision or 0)
    except (TypeError, ValueError):
        raise ContractError("base_revision 必须是整数")
    digest_value = hashlib.sha256(body).hexdigest()
    # Content-addressed bytes are safe to write before the transaction.
    destination = storage_path(root, employee_id, key, digest_value)
    if not destination.exists():
        destination.write_bytes(body)
    with repository.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = owned_documents(connection, employee_id).get(key)
        if existing is None:
            trashed = _trashed_conflict(connection, employee_id, key)
            if trashed is not None:
                raise ContractError(
                    "文档 {} 已被移入垃圾箱，请先在文档垃圾箱中恢复后再写入，"
                    "避免出现两份同名文档".format(key))
            if base:
                raise DocumentConflict(
                    "文档 {} 不存在，不能基于第 {} 版更新；请用 base_revision=0 创建".format(
                        key, base), 0)
            if not title:
                raise ContractError("创建文档必须提供 name")
            revision, root_id, latest_meta = 1, None, {}
        else:
            latest, length = existing
            latest_meta = _meta(latest)
            current = int(latest_meta.get("revision") or length or 1)
            title = title or str(latest["name"] or "")
            if data_view is None:
                view = latest_meta.get("data_view")
            if (digest_value == str(latest_meta.get("sha256") or "")
                    and title == str(latest["name"] or "")
                    and view == latest_meta.get("data_view")):
                return dict(summary(latest, length), created_revision=False)
            if base != current:
                raise DocumentConflict(
                    "文档 {} 已更新到第 {} 版，你基于第 {} 版写入。"
                    "请重新调用 get_document 读取最新内容，合并后再写".format(
                        key, current, base), current)
            revision, root_id = current + 1, _root_id(latest)
        meta = {"path": "{}.rich.json".format(key), "content_model": "rich-document",
                "sha256": digest_value, "size": len(body), "revision": revision,
                "document_key": key, "source": SOURCE, "purpose": "document", "author": "employee", "data_view": view,
                "employee_id": int(employee_id),
                "employee_run_id": int(employee_run_id),
                "workflow_run_id": int(workflow_run_id),
                "run_sequence": _run_ordinal(connection, employee_id, employee_run_id),
                "note": str(note or "").strip()[:500]}
        if root_id:
            meta["revision_of"] = root_id
        # Never owned by the run row: deleting a run or workflow must not take
        # the document with it.
        new_id = connection.execute(
            "INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) "
            "VALUES(NULL,?,?,?,?)", (title, str(destination),
                                  json.dumps(meta, ensure_ascii=False), utc_now())).lastrowid
        if not root_id:
            root_id = int(new_id)
            meta["revision_of"] = root_id
            connection.execute("UPDATE artifacts SET meta_json=? WHERE id=?",
                               (json.dumps(meta, ensure_ascii=False), root_id))
        repository.event(
            "document:{}".format(root_id),
            "document.created" if revision == 1 else "document.revised",
            {"document_id": int(new_id), "revision_of": root_id, "revision": revision,
             "document_key": key, "source": SOURCE, "employee_id": int(employee_id),
             "employee_run_id": int(employee_run_id)}, connection=connection)
        repository.event(
            "employee_run:{}".format(int(employee_run_id)), "document.written",
            {"document_id": int(new_id), "document_key": key, "revision": revision},
            connection=connection)
        row = connection.execute("SELECT * FROM artifacts WHERE id=?", (int(new_id),)).fetchone()
    return dict(summary(row, revision), created_revision=True)
