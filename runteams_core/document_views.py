"""Allowlisted named projections shared by human and employee document writers."""
from .contracts import ContractError

DOCUMENT_VIEW_KINDS = frozenset(("opportunities", "work_items"))
DOCUMENT_VIEW_COLUMNS = frozenset((
    "title", "product", "analysis_decision", "decision_reason", "target_user",
    "jtbd", "problem", "evidence_count", "summary", "employee_name",
    "pipeline_name", "updated_at",
))


def normalize_data_view(value):
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
    if kind == "work_items":
        import re
        key = str(value.get("repository_key") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", key):
            raise ContractError("问题视图需要明确的仓库标识")
        return {"kind": kind, "repository_key": key}
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

