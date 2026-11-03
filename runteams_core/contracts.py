"""Small canonical contracts shared by storage, UI and Agent Runtime adapters."""

import copy
import hashlib
import json
from pathlib import PurePosixPath
import re


class ContractError(ValueError):
    pass


class DocumentLossError(ContractError):
    """永久删除会销毁已发布的文档；调用方必须先确认份数。"""

    def __init__(self, message, documents):
        super().__init__(message)
        self.documents = int(documents)


_KEY = re.compile(r"^[a-z][a-z0-9-]{0,79}$")
_CREDENTIAL_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,119}$")
_RUN_STATES = ("completed", "blocked", "needs_human", "failed")
_PIPELINE_COLUMN_COLORS = {
    "gray", "brown", "orange", "yellow", "green", "blue", "purple", "pink", "red",
}
_PIPELINE_PARAMETER_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")
_PIPELINE_PARAMETER_TYPES = {
    "text", "textarea", "number", "select", "multiselect", "checklist",
    "checkbox", "date", "secret",
}
_PIPELINE_PARAMETER_SOURCES = {"user", "employee"}
_PIPELINE_PARAMETER_DISPLAYS = {"input", "handoff", "reference", "output", "setup"}
HANDOFF_RESOURCE_TYPES = (
    "text", "number", "url", "boolean", "date",
    "markdown", "word", "pdf", "image", "table", "json", "txt", "folder",
)
HANDOFF_TYPE_EXTENSIONS = {
    ".md": "markdown", ".markdown": "markdown",
    ".doc": "word", ".docx": "word",
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image", ".svg": "image",
    ".csv": "table", ".tsv": "table", ".xls": "table", ".xlsx": "table",
    ".json": "json",
    ".txt": "txt", ".log": "txt",
}
DEFAULT_EMPLOYEE_AVATAR = "preset:bottts:nova"


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _object(value, label):
    if not isinstance(value, dict):
        raise ContractError("{}必须是对象".format(label))
    return copy.deepcopy(value)


def _text(value, label, required=True, limit=8000):
    text = str(value or "").strip()
    if required and not text:
        raise ContractError("{}不能为空".format(label))
    if len(text) > limit:
        raise ContractError("{}过长".format(label))
    return text


def _key(value, label):
    value = _text(value, label, limit=80).lower()
    if not _KEY.fullmatch(value):
        raise ContractError("{}只能包含小写字母、数字和连字符".format(label))
    return value


def employee_direct_assignment(draft):
    from .definition_contracts import validate_definition
    return validate_definition("employee_draft", draft)["direct_assignment"]


def normalize_employee_avatar(value):
    from .definition_contracts import validate_definition
    return validate_definition("identity", {"id": 1, "name": "员工", "avatar": value})["avatar"]


def normalize_pipeline_parameters(value, position_keys):
    """Normalize the small, pipeline-owned schema shared by every task in a team."""
    result, seen = [], set()
    for raw in value or []:
        item = _object(raw, "团队参数")
        parameter_type = _text(item.get("type") or "text", "参数类型", limit=40)
        if parameter_type not in _PIPELINE_PARAMETER_TYPES:
            raise ContractError("参数类型无效：{}".format(parameter_type))
        key = _text(item.get("key"), "参数 key", limit=120)
        if parameter_type == "secret":
            if not _CREDENTIAL_KEY.fullmatch(key):
                raise ContractError("凭据参数 key 只能包含字母、数字和下划线，且不能以数字开头")
        else:
            key = key.lower()
            if not _PIPELINE_PARAMETER_KEY.fullmatch(key):
                raise ContractError("参数 key 只能包含小写字母、数字、连字符和下划线")
        if key in seen:
            raise ContractError("参数 key 重复：{}".format(key))
        seen.add(key)
        source = _text(item.get("source") or "user", "参数来源", limit=40)
        if source not in _PIPELINE_PARAMETER_SOURCES:
            raise ContractError("参数来源无效：{}".format(source))
        display = _text(
            item.get("display") or ("setup" if parameter_type == "secret" else
                                    "handoff" if source == "employee" else "input"),
            "参数显示位置", limit=40)
        if display not in _PIPELINE_PARAMETER_DISPLAYS:
            raise ContractError("参数显示位置无效：{}".format(display))

        def positions(field, label):
            selected, selected_keys = [], set()
            for raw_key in item.get(field) or []:
                position_key = _key(raw_key, label)
                if position_key not in position_keys:
                    raise ContractError("{}引用了无效岗位：{}".format(label, position_key))
                if position_key not in selected_keys:
                    selected.append(position_key)
                    selected_keys.add(position_key)
            return selected

        normalized = {
            "key": key,
            "label": _text(item.get("label") or key, "参数名称", limit=160),
            "type": parameter_type,
            "source": source,
            "display": "setup" if parameter_type == "secret" else display,
        }
        note = _text(item.get("note"), "参数说明", required=False, limit=1000)
        if note:
            normalized["note"] = note
        if parameter_type in ("select", "multiselect", "checklist"):
            options = []
            for option in item.get("options") or []:
                option = _text(option, "参数选项", limit=160)
                if option not in options:
                    options.append(option)
            normalized["options"] = options
        default = item.get("default")
        if parameter_type != "secret" and default not in (None, "", []):
            if not isinstance(default, (str, int, float, bool, list)):
                raise ContractError("参数默认值必须是文本、数字、勾选状态或列表")
            normalized["default"] = copy.deepcopy(default)
        for field, label in (
                ("writers", "可填写岗位"),
                ("visible_to", "可见岗位"),
                ("producers", "产出岗位")):
            selected = positions(field, label)
            if selected:
                normalized[field] = selected
        result.append(normalized)
        if len(result) >= 40:
            break
    return result


def normalize_pipeline_standards(value):
    """Normalize pipeline-owned working rules shared by its employees."""
    result, seen = [], set()
    for raw in value or []:
        item = _object(raw, "团队规范")
        key = _key(item.get("key"), "团队规范 key")
        if key in seen:
            raise ContractError("团队规范 key 重复：{}".format(key))
        seen.add(key)
        standard = {
            "key": key,
            "name": _text(item.get("name"), "团队规范名称", limit=160),
            "instructions": _text(
                item.get("instructions"), "团队规范内容", limit=12000),
        }
        description = _text(
            item.get("description"), "团队规范使用场景",
            required=False, limit=1000)
        if description:
            standard["description"] = description
        employee_ids, selected = [], set()
        for raw_employee_id in item.get("employee_ids") or []:
            try:
                employee_id = int(raw_employee_id)
            except (TypeError, ValueError):
                raise ContractError("团队规范引用了无效员工")
            if employee_id <= 0:
                raise ContractError("团队规范引用了无效员工")
            if employee_id not in selected:
                selected.add(employee_id)
                employee_ids.append(employee_id)
        if employee_ids:
            standard["employee_ids"] = employee_ids
        result.append(standard)
        if len(result) >= 100:
            break
    return result


def normalize_package_key(value):
    return _key(value, "能力包 key")


# Platform tools a skill package may request in runteams.json ``platform_tools``.
# The platform never grants them by package name: an employee gets exactly the
# platform tools declared by the skills it mounts (see protocol.tool_definitions).
PLATFORM_TOOLS = ("list_documents", "get_document", "write_document",
                  "list_work_items", "get_work_item", "write_work_item")


def normalize_platform_tools(value):
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ContractError("platform_tools 必须是平台工具名称数组")
    names = []
    for raw in value:
        name = str(raw or "").strip()
        if name not in PLATFORM_TOOLS:
            raise ContractError("未知的平台工具：{}".format(name or "(空)"))
        if name not in names:
            names.append(name)
    return names


def resolve_deliverable_text(value, day):
    """Fill ``{date}`` or ``{{date}}`` in a deliverable path or name.

    Recurring work (for example a daily report) declares ``报告-{date}.md`` so
    each run delivers its own dated document instead of a pile of same-named ones.
    """
    # Consume the complete double-brace token first, so it cannot leave a
    # literal pair of braces around the resolved date.
    return str(value or "").replace("{{date}}", day).replace("{date}", day)


def normalize_action_offers(value, work):
    if not isinstance(value, list):
        raise ContractError("建议动作必须是数组")
    declarations = {a["id"] for a in work.get("result_actions") or []}
    if any(not isinstance(a, str) or a not in declarations for a in value):
        raise ContractError("只能建议本次冻结工作合同已声明的动作")
    if len(value) != len(set(value)):
        raise ContractError("建议动作不能重复")
    return list(value)


def json_schema_violations(value, schema, path="$", limit=50):
    """Validate complete local JSON Schema, including refs and compound branches."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(value))
    except SchemaError as exc:
        raise ContractError("业务接口JSON Schema无效：" + exc.message) from exc
    errors.sort(key=lambda error: tuple(str(v) for v in error.absolute_path))
    return [(path + ''.join('['+str(v)+']' if isinstance(v, int) else '.'+str(v) for v in error.absolute_path)
             + '：' + error.message) for error in errors[:limit]]


def normalize_pipeline_definition(value):
    value = _object(value, "流水线定义")
    positions, position_keys = [], set()
    for raw in value.get("positions") or []:
        item = _object(raw, "岗位")
        key = _key(item.get("key"), "岗位 key")
        if key in position_keys:
            raise ContractError("岗位 key 重复：{}".format(key))
        position_keys.add(key)
        kind = _text(item.get("kind") or "employee", "岗位类型", limit=40)
        if kind not in ("employee", "approval"):
            raise ContractError("岗位类型无效：{}".format(kind))
        position = {"key": key,
                    "name": _text(item.get("name") or key, "岗位名称", limit=160)}
        if kind == "employee":
            employee_id = int(item.get("employee_id") or 0)
            if employee_id <= 0:
                raise ContractError("员工岗位必须引用员工")
            position["kind"] = "employee"
            position["employee_id"] = employee_id
            skill_key = _text(item.get("skill_key"), "岗位技能", required=False, limit=80)
            if skill_key:
                position["skill_key"] = normalize_package_key(skill_key)
            if "skill_id" in item:
                raise ContractError("流水线岗位已改用skill_key")

        else:
            position["kind"] = "approval"
            prompt = _text(item.get("prompt"), "审批说明", required=False, limit=1000)
            if prompt:
                position["prompt"] = prompt
        color = _text(item.get("color"), "岗位颜色", required=False, limit=20).lower()
        if color and color not in _PIPELINE_COLUMN_COLORS:
            raise ContractError("岗位颜色无效：{}".format(color))
        if color:
            position["color"] = color
        positions.append(position)
    if not positions:
        raise ContractError("流水线至少需要一个岗位")
    states, state_keys = [], set()
    for raw in value.get("states") or []:
        item = _object(raw, "状态列")
        key = _key(item.get("key"), "状态列 key")
        if key in position_keys or key in state_keys:
            raise ContractError("流水线列 key 重复：{}".format(key))
        kind = _text(item.get("kind") or "pool", "状态列类型", limit=40)
        if kind not in ("pool", "done", "dropped"):
            raise ContractError("状态列类型无效：{}".format(kind))
        state_keys.add(key)
        state = {"key": key,
                 "name": _text(item.get("name") or key, "状态列名称", limit=160),
                 "kind": kind}
        color = _text(item.get("color"), "状态列颜色", required=False, limit=20).lower()
        if color and color not in _PIPELINE_COLUMN_COLORS:
            raise ContractError("状态列颜色无效：{}".format(color))
        if color:
            state["color"] = color
        states.append(state)
    route_keys = position_keys | state_keys
    edges, edge_keys = [], set()
    for raw in value.get("edges") or []:
        item = _object(raw, "交接关系")
        source, target = _key(item.get("from"), "上游岗位"), _key(item.get("to"), "下游环节")
        if source not in position_keys or target not in route_keys or source == target:
            raise ContractError("交接关系引用了无效环节")
        when = _text(item.get("when"), "交接条件", required=False, limit=120)
        marker = (source, when or "completed")
        if marker in edge_keys:
            raise ContractError("同一岗位的交接条件不能重复")
        edge_keys.add(marker)
        edge = {"from": source, "to": target}
        if when and when != "completed":
            edge["when"] = when
        edges.append(edge)
    targets = {edge["to"] for edge in edges if edge["to"] in position_keys}
    starts = [item["key"] for item in positions if item["key"] not in targets]
    if not starts:
        starts = [positions[0]["key"]]
    if len(starts) != 1:
        raise ContractError("流水线必须有且只有一个起点")
    reachable, pending = set(), [starts[0]]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        pending.extend(edge["to"] for edge in edges
                       if edge["from"] == current and edge["to"] in position_keys)
    if reachable != position_keys:
        raise ContractError("流水线存在无法到达的岗位")
    result = {"schema": "runteams.pipeline/v1", "positions": positions, "edges": edges}
    if states:
        result["states"] = states
    parameters = normalize_pipeline_parameters(value.get("parameters"), position_keys)
    if parameters:
        result["parameters"] = parameters
    standards = normalize_pipeline_standards(value.get("standards"))
    if standards:
        result["standards"] = standards
    return result


def repair_pipeline_definition(value, drop_keys=None):
    """Drop routing that still points at removed positions, then normalize.

    Position deletion must clear 工作下游 / 参数岗位引用. Remaining custom
    edges are kept when they still form a valid graph; otherwise the chain is
    rebuilt so the pipeline stays runnable.
    """
    value = dict(value or {})
    drop = {str(key).strip() for key in (drop_keys or []) if str(key or "").strip()}
    positions = [item for item in list(value.get("positions") or [])
                 if str(item.get("key") or "").strip() not in drop]
    live = {str(item.get("key") or "").strip() for item in positions}
    live.discard("")
    route_live = live | {
        str(item.get("key") or "").strip()
        for item in list(value.get("states") or [])
        if str(item.get("key") or "").strip()
    }
    edges, seen = [], set()
    for raw in value.get("edges") or []:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("from") or "").strip()
        target = str(raw.get("to") or "").strip()
        if source not in live or target not in route_live or source == target:
            continue
        when = str(raw.get("when") or "completed").strip() or "completed"
        marker = (source, when)
        if marker in seen:
            continue
        seen.add(marker)
        edge = {"from": source, "to": target}
        if when != "completed":
            edge["when"] = when
        edges.append(edge)
    parameters = []
    for raw in value.get("parameters") or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        for field in ("writers", "visible_to", "producers"):
            refs = item.get(field)
            if not isinstance(refs, list):
                continue
            cleaned = [key for key in refs if str(key).strip() in live]
            if cleaned:
                item[field] = cleaned
            else:
                item.pop(field, None)
        parameters.append(item)
    updated = dict(value, positions=positions, edges=edges)
    if parameters:
        updated["parameters"] = parameters
    elif "parameters" in updated:
        updated["parameters"] = []
    try:
        return normalize_pipeline_definition(updated)
    except ContractError:
        order = [str(item.get("key") or "").strip() for item in positions]
        linear = [{"from": source, "to": target}
                  for source, target in zip(order, order[1:]) if source and target]
        return normalize_pipeline_definition(dict(updated, edges=linear))


def pipeline_order(definition):
    """Return stable board order; execution follows edges, not array adjacency."""
    normalized = normalize_pipeline_definition(definition)
    return [item["key"] for item in normalized["positions"]]


def normalize_work_result(value):
    value = _object(value, "工作结果")
    status = str(value.get("status") or "").strip()
    if status not in _RUN_STATES:
        raise ContractError("工作结果状态无效")
    output = value.get("output")
    if output is None:
        output = {}
    if not isinstance(output, (dict, list, str, int, float, bool)):
        raise ContractError("工作结果 output 必须可序列化")
    work_done = value.get("work_done")
    if work_done is not None:
        if not isinstance(work_done, list) or len(work_done) > 3:
            raise ContractError("已完成工作应为不超过三项的列表")
        work_done = [_text(item, "已完成工作", required=True, limit=240) for item in work_done]
    return {
        "schema": "runteams.work-result/v1",
        "status": status,
        "summary": _text(value.get("summary"), "结果摘要", required=status == "completed", limit=4000),
        **({"work_done": work_done} if work_done is not None else {}),
        "output": copy.deepcopy(output),
        "artifacts": list(value.get("artifacts") or []),
        "issues": list(value.get("issues") or []),
        **({"actions": copy.deepcopy(value["actions"])} if "actions" in value else {}),
    }
