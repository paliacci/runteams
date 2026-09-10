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
_RESERVED_AGENT_CREDENTIALS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_ACCESS_TOKEN"}
_RUN_STATES = ("completed", "blocked", "needs_human", "failed")
_TRIAL_EXPECTED_STATES = ("completed", "blocked", "needs_human", "failed")
_TRIAL_EXPECTED_ROUTES = ("completed", "exception")
_COVERAGE_ID = re.compile(r"^[a-z][a-z0-9._:-]{0,159}$")
_SCHEMA_TYPES = {"null", "boolean", "object", "array", "number", "integer", "string"}
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
_EMPLOYEE_AVATAR = re.compile(
    r"^(?:a[1-6]|preset:bottts:[a-z0-9-]+|upload:[a-f0-9]{24}\.webp)$")
_TRIAL_FIXTURE_MAX_FILES = 100
_TRIAL_FIXTURE_MAX_FILE_BYTES = 256 * 1024
_TRIAL_FIXTURE_MAX_TOTAL_BYTES = 2 * 1024 * 1024

DEFAULT_EMPLOYEE_INTERFACE = {
    "input": {
        "type": "object",
        "required": ["objective", "context", "inputs", "expected_output", "acceptance"],
        "properties": {
            "objective": {"type": "string", "minLength": 1},
            "context": {"type": "object"},
            "inputs": {"type": "array"},
            "expected_output": {"type": "object"},
            "acceptance": {"type": "array", "items": {"type": "string"}},
        },
    },
    "output": {"type": "object"},
}


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


def normalize_employee_avatar(value):
    """Normalize the employee's mutable visual identity outside release behavior."""
    avatar = str(value or "a1").strip()
    if not _EMPLOYEE_AVATAR.fullmatch(avatar):
        raise ContractError("员工头像无效")
    return avatar


def normalize_trial_fixtures(value):
    """Normalize text files materialized only inside one validation workspace."""
    fixtures, seen, total = [], set(), 0
    for raw in value or []:
        if len(fixtures) >= _TRIAL_FIXTURE_MAX_FILES:
            raise ContractError("测试夹具文件过多")
        item = _object(raw, "测试夹具")
        raw_path = _text(item.get("path"), "测试夹具路径", limit=500).replace("\\", "/")
        path = PurePosixPath(raw_path)
        if (path.is_absolute() or re.match(r"^[A-Za-z]:/", raw_path) or
                "//" in raw_path or any(part in ("", ".", "..") for part in path.parts) or
                not path.parts or path.parts[0] == ".runteams"):
            raise ContractError("测试夹具路径必须位于用例工作区内：{}".format(raw_path))
        normalized_path = path.as_posix()
        if normalized_path.casefold() in seen:
            raise ContractError("测试夹具路径重复：{}".format(normalized_path))
        content = item.get("content")
        if not isinstance(content, str):
            raise ContractError("测试夹具内容必须是文本")
        size = len(content.encode("utf-8"))
        if size > _TRIAL_FIXTURE_MAX_FILE_BYTES:
            raise ContractError("测试夹具文件过大：{}".format(normalized_path))
        total += size
        if total > _TRIAL_FIXTURE_MAX_TOTAL_BYTES:
            raise ContractError("测试夹具总大小过大")
        fixture = {"path": normalized_path, "content": content}
        if bool(item.get("executable", False)):
            fixture["executable"] = True
        fixtures.append(fixture)
        seen.add(normalized_path.casefold())
    return fixtures


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


def normalize_package_manifest(value):
    value = _object(value, "能力包清单")
    if value.get("schema") != "runteams.package/v1":
        raise ContractError("能力包清单版本无效")
    capabilities, seen = [], set()
    for raw in value.get("capabilities") or []:
        item = _object(raw, "能力声明")
        capability_id = _key(item.get("id"), "能力 id")
        if capability_id in seen:
            raise ContractError("能力 id 重复：{}".format(capability_id))
        seen.add(capability_id)
        kind = str(item.get("kind") or "").strip()
        if kind not in ("skill", "tool"):
            raise ContractError("能力类型只能是 skill 或 tool")
        normalized = {"id": capability_id, "kind": kind,
                      "name": _text(item.get("name") or capability_id, "能力名称", limit=160),
                      "description": _text(item.get("description"), "能力说明",
                                           required=False, limit=1000),
                      "entry": _text(item.get("entry"), "能力入口", limit=500)}
        if kind == "tool":
            runtime = _object(item.get("runtime"), "工具运行契约")
            normalized["runtime"] = runtime
            credentials = []
            for raw_name in item.get("credentials") or []:
                name = _text(raw_name, "凭据 Key", limit=120)
                if not _CREDENTIAL_KEY.fullmatch(name):
                    raise ContractError("凭据 Key 只能包含字母、数字和下划线，且不能以数字开头")
                if name in _RESERVED_AGENT_CREDENTIALS:
                    raise ContractError("能力包不能声明 Agent Runtime 的模型凭据：{}".format(name))
                if name in credentials:
                    raise ContractError("凭据 Key 重复：{}".format(name))
                credentials.append(name)
            normalized["credentials"] = credentials
        elif item.get("credentials"):
            raise ContractError("Skill 不能声明运行时凭据；请把需要凭据的动作声明为 tool")
        capabilities.append(normalized)
    if not capabilities:
        raise ContractError("能力包必须至少声明一项能力")
    files = []
    for raw in value.get("files") or []:
        item = _object(raw, "能力包文件")
        files.append({"path": _text(item.get("path"), "文件路径", limit=500),
                      "sha256": _text(item.get("sha256"), "文件摘要", limit=64),
                      "size": int(item.get("size") or 0)})
    return {
        "schema": "runteams.package/v1",
        "format": _text(value.get("format") or "agent-skill", "能力包格式", limit=80),
        "name": _text(value.get("name"), "能力包名称", limit=160),
        "display_name": _text(value.get("display_name") or value.get("name"),
                              "能力包显示名称", limit=160),
        "description": _text(value.get("description"), "能力包说明", required=False, limit=2000),
        "capabilities": capabilities,
        "files": files,
        "extensions": _object(value.get("extensions") or {}, "扩展元数据"),
    }


def normalize_deliverables(value):
    """岗位声明「我会产出哪些文档」。收尾时按声明自动登记，不靠员工记得调工具。"""
    items, seen = [], set()
    for raw in value if isinstance(value, list) else []:
        item = _object(raw, "交付文档")
        path = str(item.get("path") or "").replace("\\", "/").strip().strip("/")
        if not path:
            raise ContractError("交付文档路径不能为空")
        if len(path) > 300:
            raise ContractError("交付文档路径过长")
        segments = [segment for segment in path.split("/") if segment]
        if not segments or any(segment in (".", "..") for segment in segments):
            raise ContractError("交付文档路径必须留在工作区内：{}".format(path))
        if path in seen:
            raise ContractError("交付文档路径重复：{}".format(path))
        seen.add(path)
        items.append({
            "path": path,
            "name": _text(item.get("name") or segments[-1], "交付文档名称", limit=200),
            "required": bool(item.get("required", True)),
        })
    if len(items) > 20:
        raise ContractError("一个岗位最多声明 20 份交付文档")
    return items


def normalize_capability_references(value):
    capabilities, seen = [], set()
    for raw in value if isinstance(value, list) else []:
        item = _object(raw, "员工能力引用")
        plugin_id = str(item.get("plugin_id") or "").strip()
        if plugin_id:
            provider = _key(item.get("provider"), "模型渠道")
            plugin_id = _text(plugin_id, "扩展 id", limit=240)
            marker = ("plugin", provider, plugin_id)
            if marker in seen:
                raise ContractError("员工扩展引用重复")
            seen.add(marker)
            capabilities.append({"provider": provider, "plugin_id": plugin_id})
            continue
        package_id = int(item.get("package_id") or 0)
        marker = ("package", package_id)
        if package_id <= 0:
            raise ContractError("员工技能引用无效")
        if marker in seen:
            continue
        seen.add(marker)
        # A RunTeams package is one user-visible Employee Skill.  Its Skill
        # instructions, scripts and tools are internal resources of that skill,
        # never independently bindable product assets.  Older drafts may still
        # carry capability_id; normalization intentionally collapses them here.
        capabilities.append({"package_id": package_id})
    return capabilities


def normalize_json_schema(value, label):
    schema = _object(value, label)
    schema_type = schema.get("type")
    if isinstance(schema_type, str) and schema_type not in _SCHEMA_TYPES:
        raise ContractError("{}包含无效 type".format(label))
    if isinstance(schema_type, list):
        if not schema_type or any(item not in _SCHEMA_TYPES for item in schema_type):
            raise ContractError("{}包含无效 type".format(label))
    elif schema_type is not None and not isinstance(schema_type, str):
        raise ContractError("{}的 type 无效".format(label))
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ContractError("{}的 properties 必须是对象".format(label))
        schema["properties"] = {
            _text(key, "字段名称", limit=160): normalize_json_schema(
                child, "{}字段 {}".format(label, key))
            for key, child in properties.items()
        }
    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list):
            raise ContractError("{}的 required 必须是数组".format(label))
        schema["required"] = list(dict.fromkeys(
            _text(item, "必填字段", limit=160) for item in required))
    items = schema.get("items")
    if items is not None:
        schema["items"] = normalize_json_schema(items, "{}数组项".format(label))
    canonical_json(schema)
    return schema


def normalize_employee_interface(value):
    source = value if isinstance(value, dict) else DEFAULT_EMPLOYEE_INTERFACE
    return {
        "input": normalize_json_schema(
            source.get("input") or DEFAULT_EMPLOYEE_INTERFACE["input"], "员工输入接口"),
        "output": normalize_json_schema(
            source.get("output") or DEFAULT_EMPLOYEE_INTERFACE["output"], "员工输出接口"),
    }


def _schema_coverage_targets(prefix, schema, path=""):
    targets = []
    location = prefix + ("." + path if path else "")
    if not path:
        targets.append({"id": "{}.valid".format(prefix), "category": prefix,
                        "label": "{}符合接口".format("输入" if prefix == "input" else "输出")})
    if schema.get("type") is not None and path:
        targets.append({"id": "{}.type".format(location), "category": prefix,
                        "label": "{}类型正确".format(location)})
    for name in schema.get("required") or []:
        child_path = "{}.{}".format(path, name) if path else name
        targets.append({"id": "{}.{}.required".format(prefix, child_path),
                        "category": prefix, "label": "{} 必填约束".format(child_path)})
    for rule in ("enum", "const", "minimum", "maximum", "exclusiveMinimum",
                 "exclusiveMaximum", "minLength", "maxLength", "pattern",
                 "minItems", "maxItems", "minProperties", "maxProperties"):
        if rule in schema:
            rule_id = re.sub(r"([a-z])([A-Z])", r"\1-\2", rule).lower()
            targets.append({"id": "{}.{}".format(location, rule_id), "category": prefix,
                            "label": "{} {} 边界".format(location, rule)})
    for name, child in (schema.get("properties") or {}).items():
        child_path = "{}.{}".format(path, name) if path else name
        targets.extend(_schema_coverage_targets(prefix, child, child_path))
    if isinstance(schema.get("items"), dict):
        child_path = "{}.items".format(path) if path else "items"
        targets.extend(_schema_coverage_targets(prefix, schema["items"], child_path))
    return targets


def employee_coverage_targets(value):
    interface = value.get("interface") or normalize_employee_interface(None)
    targets = (_schema_coverage_targets("input", interface["input"]) +
               _schema_coverage_targets("output", interface["output"]))
    for step in (value.get("program") or {}).get("steps") or []:
        targets.append({"id": "program.{}".format(step["id"]), "category": "program",
                        "label": "执行步骤：{}".format(step["instruction"][:80])})
    for status in _TRIAL_EXPECTED_STATES:
        labels = {"completed": "正常完成", "needs_human": "需要人工补充",
                  "blocked": "业务条件阻塞", "failed": "运行失败"}
        targets.append({"id": "result.{}".format(status), "category": "result",
                        "label": labels[status]})
    targets.extend([
        {"id": "handoff.upstream.valid", "category": "handoff", "label": "正常上游输入"},
        {"id": "handoff.upstream.missing", "category": "handoff", "label": "缺少上游输入"},
        {"id": "handoff.upstream.invalid", "category": "handoff", "label": "无效上游输入"},
        {"id": "handoff.output.valid", "category": "handoff", "label": "输出可结构化交接"},
    ])
    for reference in value.get("capabilities") or []:
        # 渠道扩展在发布与每次启动前做确定性可用性检查。它不是 RunTeams
        # 协议内可注入故障的工具，因此不制造无法被运行证据证明的用例覆盖项。
        if reference.get("plugin_id"):
            continue
        marker = str(reference["package_id"])
        targets.extend([
            {"id": "skill.{}.success".format(marker), "category": "skill",
             "label": "员工技能正常工作"},
            {"id": "skill.{}.failure".format(marker), "category": "skill",
             "label": "员工技能不可用"},
        ])
    unique = {}
    for target in targets:
        unique[target["id"]] = target
    return list(unique.values())


def json_schema_violations(value, schema, path="$", limit=50):
    """Validate the deterministic JSON-Schema subset used by employee interfaces."""
    problems = []

    def add(message):
        if len(problems) < limit:
            problems.append("{} {}".format(path_stack[-1], message))

    def matches_type(candidate, expected):
        if expected == "null":
            return candidate is None
        if expected == "boolean":
            return isinstance(candidate, bool)
        if expected == "object":
            return isinstance(candidate, dict)
        if expected == "array":
            return isinstance(candidate, list)
        if expected == "string":
            return isinstance(candidate, str)
        if expected == "integer":
            return isinstance(candidate, int) and not isinstance(candidate, bool)
        if expected == "number":
            return isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
        return True

    def visit(candidate, rule):
        expected = rule.get("type")
        expected_types = expected if isinstance(expected, list) else [expected] if expected else []
        if expected_types and not any(matches_type(candidate, item) for item in expected_types):
            add("类型应为 {}".format("/".join(expected_types)))
            return
        if "const" in rule and candidate != rule["const"]:
            add("不等于约定常量")
        if "enum" in rule and candidate not in rule["enum"]:
            add("不在允许值范围内")
        if isinstance(candidate, dict):
            for name in rule.get("required") or []:
                if name not in candidate:
                    path_stack.append("{}.{}".format(path_stack[-1], name))
                    add("缺少必填字段")
                    path_stack.pop()
            properties = rule.get("properties") or {}
            for name, child in properties.items():
                if name in candidate:
                    path_stack.append("{}.{}".format(path_stack[-1], name))
                    visit(candidate[name], child)
                    path_stack.pop()
            if rule.get("additionalProperties") is False:
                for name in candidate:
                    if name not in properties:
                        path_stack.append("{}.{}".format(path_stack[-1], name))
                        add("不允许额外字段")
                        path_stack.pop()
            if len(candidate) < int(rule.get("minProperties") or 0):
                add("字段数量不足")
            if rule.get("maxProperties") is not None and len(candidate) > int(rule["maxProperties"]):
                add("字段数量过多")
        if isinstance(candidate, list):
            if len(candidate) < int(rule.get("minItems") or 0):
                add("数组项目不足")
            if rule.get("maxItems") is not None and len(candidate) > int(rule["maxItems"]):
                add("数组项目过多")
            if isinstance(rule.get("items"), dict):
                for index, item in enumerate(candidate):
                    path_stack.append("{}[{}]".format(path_stack[-1], index))
                    visit(item, rule["items"])
                    path_stack.pop()
        if isinstance(candidate, str):
            if len(candidate) < int(rule.get("minLength") or 0):
                add("文本过短")
            if rule.get("maxLength") is not None and len(candidate) > int(rule["maxLength"]):
                add("文本过长")
            if rule.get("pattern") and re.search(str(rule["pattern"]), candidate) is None:
                add("文本格式不匹配")
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            if rule.get("minimum") is not None and candidate < rule["minimum"]:
                add("小于最小值")
            if rule.get("maximum") is not None and candidate > rule["maximum"]:
                add("大于最大值")
            if rule.get("exclusiveMinimum") is not None and candidate <= rule["exclusiveMinimum"]:
                add("不大于排他最小值")
            if rule.get("exclusiveMaximum") is not None and candidate >= rule["exclusiveMaximum"]:
                add("不小于排他最大值")

    path_stack = [path]
    visit(value, schema or {})
    return problems


def normalize_employee_draft(value):
    value = _object(value, "员工草稿")
    program = _object(value.get("program"), "员工程序")
    steps = []
    for index, raw in enumerate(program.get("steps") or []):
        item = _object(raw, "员工步骤")
        steps.append({"id": _key(item.get("id") or "step-{}".format(index + 1), "步骤 id"),
                      "instruction": _text(item.get("instruction"), "步骤说明")})
    if not steps:
        raise ContractError("员工程序至少需要一个步骤")
    capabilities = normalize_capability_references(value.get("capabilities"))
    interface = normalize_employee_interface(value.get("interface"))
    output_properties = interface["output"].get("properties") or {}
    route_schema = output_properties.get("route")
    runtime = _object(value.get("runtime"), "员工运行配置")
    channel = _text(runtime.get("channel"), "Agent Channel", limit=80)
    coverage_target_ids = {item["id"] for item in employee_coverage_targets({
        "interface": interface, "program": {"steps": steps}, "capabilities": capabilities,
    })}
    tests, test_ids = [], set()
    for index, raw in enumerate(value.get("tests") or []):
        item = _object(raw, "员工测试用例")
        test_id = _key(item.get("id") or "case-{}".format(index + 1), "测试用例 id")
        if test_id in test_ids:
            raise ContractError("测试用例 id 重复：{}".format(test_id))
        test_ids.add(test_id)
        expected_status = str(item.get("expected_status") or "completed").strip()
        if expected_status not in _TRIAL_EXPECTED_STATES:
            raise ContractError("测试用例预期状态无效")
        expected_route = str(item.get("expected_route") or "").strip()
        if expected_route and expected_route not in _TRIAL_EXPECTED_ROUTES:
            raise ContractError("测试用例预期去向无效")
        if expected_route and expected_status != "completed":
            raise ContractError(
                "测试用例 {} 只有预期完成时才能声明业务去向".format(test_id))
        if expected_route and not isinstance(route_schema, dict):
            raise ContractError(
                "测试用例 {} 声明了预期去向，但员工输出接口没有 route 字段".format(test_id))
        if expected_route and "const" in route_schema and expected_route != route_schema["const"]:
            raise ContractError(
                "测试用例 {} 的预期去向不符合员工输出接口".format(test_id))
        if expected_route and route_schema.get("enum") is not None and expected_route not in route_schema["enum"]:
            raise ContractError(
                "测试用例 {} 的预期去向不符合员工输出接口".format(test_id))
        downstream_employee_id = item.get("downstream_employee_id")
        if downstream_employee_id in (None, ""):
            downstream_employee_id = None
        else:
            downstream_employee_id = int(downstream_employee_id)
            if downstream_employee_id <= 0:
                raise ContractError("下游员工无效")
        covers = []
        for raw_coverage in item.get("covers") or []:
            coverage_id = _text(raw_coverage, "覆盖场景", limit=160)
            legacy = re.fullmatch(
                r"capability\.(\d+):[A-Za-z0-9][A-Za-z0-9._-]*\.(success|failure)",
                coverage_id)
            if legacy:
                coverage_id = "skill.{}.{}".format(legacy.group(1), legacy.group(2))
            if not _COVERAGE_ID.fullmatch(coverage_id):
                raise ContractError("覆盖场景 id 无效：{}".format(coverage_id))
            if coverage_id not in coverage_target_ids:
                raise ContractError("覆盖场景不属于当前员工契约：{}".format(coverage_id))
            if coverage_id not in covers:
                covers.append(coverage_id)
        work_order = normalize_work_order(item.get("work_order") or {})
        context = work_order["context"]
        has_upstream_position = bool(context.get("upstream_position"))
        has_upstream_output = "upstream_output" in context
        input_violations = json_schema_violations(
            work_order_payload(work_order, interface["input"]),
            interface["input"], path="$.input")
        input_valid = not input_violations
        for coverage_id in covers:
            if coverage_id.startswith("result.") and coverage_id != "result.{}".format(
                    expected_status):
                raise ContractError("测试用例 {} 的结果状态与覆盖目标 {} 不一致".format(
                    test_id, coverage_id))
            if (coverage_id.startswith("output.") or
                    coverage_id.startswith("program.") or
                    coverage_id.endswith(".success") or
                    coverage_id == "handoff.output.valid") and expected_status != "completed":
                raise ContractError("测试用例 {} 只有预期完成时才能覆盖 {}".format(
                    test_id, coverage_id))
            if coverage_id.endswith(".failure") and expected_status != "failed":
                raise ContractError("测试用例 {} 只有预期失败时才能覆盖 {}".format(
                    test_id, coverage_id))
            if coverage_id == "input.valid" and not input_valid:
                raise ContractError(
                    "测试用例 {} 的输入不符合接口，不能覆盖 input.valid：{}".format(
                        test_id, "；".join(input_violations[:3])))
            upstream_shape = {
                "handoff.upstream.valid": has_upstream_position and has_upstream_output,
                "handoff.upstream.missing": (not has_upstream_position and
                                             not has_upstream_output),
                "handoff.upstream.invalid": has_upstream_position != has_upstream_output,
            }
            if coverage_id in upstream_shape and not upstream_shape[coverage_id]:
                raise ContractError("测试用例 {} 的上游信号与覆盖目标 {} 不一致".format(
                    test_id, coverage_id))
        normalized_test = {
            "id": test_id,
            "name": _text(item.get("name") or "用例 {}".format(index + 1),
                          "测试用例名称", limit=160),
            "work_order": work_order,
            "expected_status": expected_status,
            "downstream_employee_id": downstream_employee_id,
            "covers": covers,
        }
        if expected_route:
            normalized_test["expected_route"] = expected_route
        fixtures = normalize_trial_fixtures(item.get("fixtures"))
        if fixtures:
            normalized_test["fixtures"] = fixtures
        tests.append(normalized_test)
    return {
        "schema": "runteams.employee-draft/v1",
        "role": _text(value.get("role"), "员工职责", limit=2000),
        "program": {
            "objective": _text(program.get("objective"), "员工目标", limit=2000),
            "steps": steps,
            "acceptance": [_text(item, "验收标准", limit=1000)
                           for item in (program.get("acceptance") or [])],
            "deliverables": normalize_deliverables(program.get("deliverables")),
        },
        "interface": interface,
        "capabilities": capabilities,
        "runtime": {"channel": channel,
                    "model": _text(runtime.get("model"), "模型", required=False, limit=160),
                    "effort": _text(runtime.get("effort"), "思考程度", required=False, limit=40)},
        "tests": tests,
    }


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
            position["employee_id"] = employee_id
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
    edges, edge_keys = [], set()
    for raw in value.get("edges") or []:
        item = _object(raw, "交接关系")
        source, target = _key(item.get("from"), "上游岗位"), _key(item.get("to"), "下游岗位")
        if source not in position_keys or target not in position_keys or source == target:
            raise ContractError("交接关系引用了无效岗位")
        when = _text(item.get("when"), "交接条件", required=False, limit=120)
        marker = (source, when or "completed")
        if marker in edge_keys:
            raise ContractError("同一岗位的交接条件不能重复")
        edge_keys.add(marker)
        edge = {"from": source, "to": target}
        if when and when != "completed":
            edge["when"] = when
        edges.append(edge)
    targets = {edge["to"] for edge in edges}
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
        pending.extend(edge["to"] for edge in edges if edge["from"] == current)
    if reachable != position_keys:
        raise ContractError("流水线存在无法到达的岗位")
    result = {"schema": "runteams.pipeline/v1", "positions": positions, "edges": edges}
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
    if states:
        result["states"] = states
    parameters = normalize_pipeline_parameters(value.get("parameters"), position_keys)
    if parameters:
        result["parameters"] = parameters
    standards = normalize_pipeline_standards(value.get("standards"))
    if standards:
        result["standards"] = standards
    return result


def pipeline_order(definition):
    """Return stable board order; execution follows edges, not array adjacency."""
    normalized = normalize_pipeline_definition(definition)
    return [item["key"] for item in normalized["positions"]]


def normalize_work_order(value):
    value = _object(value, "工作单")
    return {
        "schema": "runteams.work-order/v1",
        "objective": _text(value.get("objective"), "工作目标", limit=4000),
        "context": _object(value.get("context") or {}, "工作上下文"),
        "inputs": list(value.get("inputs") or []),
        "expected_output": _object(value.get("expected_output") or {}, "预期输出"),
        "acceptance": [_text(item, "验收标准", limit=1000)
                       for item in (value.get("acceptance") or [])],
    }


_PLATFORM_CONTEXT_KEYS = frozenset((
    "upstream_position", "upstream_summary", "upstream_output",
    "team_parameters", "team_standards", "test_signal"))

_PLATFORM_EXPECTED_OUTPUT_KEYS = frozenset(("documents", "team_parameters"))


def work_order_payload(value, input_schema=None):
    """A work order's user-contract payload for interface validation.

    The envelope (schema) and the handoff-protocol context keys are owned by
    the platform; a strict (additionalProperties:false) contract must not be
    failed by them.  But an interface may legitimately declare any of these
    keys as part of its own contract (e.g. an employee designed to consume
    upstream handoff) — declared keys are kept and validated as usual."""
    payload = {key: item for key, item in (value or {}).items() if key != "schema"}
    context = payload.get("context")
    if isinstance(context, dict):
        declared = set()
        if isinstance(input_schema, dict):
            context_schema = (input_schema.get("properties") or {}).get("context") or {}
            declared = set((context_schema.get("properties") or {}).keys())
        payload["context"] = {key: item for key, item in context.items()
                              if key in declared or key not in _PLATFORM_CONTEXT_KEYS}
    expected_output = payload.get("expected_output")
    if isinstance(expected_output, dict):
        declared = set()
        if isinstance(input_schema, dict):
            expected_schema = ((input_schema.get("properties") or {})
                               .get("expected_output") or {})
            declared = set((expected_schema.get("properties") or {}).keys())
        payload["expected_output"] = {
            key: item for key, item in expected_output.items()
            if key in declared or key not in _PLATFORM_EXPECTED_OUTPUT_KEYS}
    return payload


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
    return {
        "schema": "runteams.work-result/v1",
        "status": status,
        "summary": _text(value.get("summary"), "结果摘要", required=status == "completed", limit=4000),
        "output": copy.deepcopy(output),
        "artifacts": list(value.get("artifacts") or []),
        "issues": list(value.get("issues") or []),
    }
