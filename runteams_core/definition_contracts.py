"""Strict product definitions for the new model; no legacy translations.

Storage and HTTP integration are owned by the main architecture session. All
module sessions use these validators and the deterministic release compiler.
"""
from __future__ import annotations
from runteams_core.resources import root as resource_root

import copy
import base64
import hashlib
from functools import lru_cache
import json
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .contracts import ContractError, digest

SCHEMA_PATH = resource_root() / "contracts" / "product-model-v2.json"


@lru_cache(maxsize=1)
def _bundle():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def skill_fields(value):
    """Fields derived from actual bytes in the current immutable skill contract."""
    return ('display_name', 'work', 'tools', 'execution')


def contract_catalog():
    value = copy.deepcopy(_bundle())
    extensions = {"marketplace_pipeline": json.loads(
        (SCHEMA_PATH.parent / "marketplace-pipeline-v2.json").read_text(encoding="utf-8"))}
    return {"schema": "runteams.contract-catalog/v1", "digest": digest({"definitions":value,"extensions":extensions}),
            "definitions": value, "extensions": extensions,
            "integration": "canonical definitions, immutable releases and pinned-work dispatch"}


def definition_schema(kind):
    bundle = _bundle()
    if kind not in bundle["$defs"]:
        raise ContractError("未知新架构合同：" + str(kind))
    return {"$schema": bundle["$schema"], "$defs": copy.deepcopy(bundle["$defs"]),
            "$ref": "#/$defs/" + kind}


def _unique(rows, field, label):
    values = [row[field] for row in rows]
    if len(values) != len(set(values)):
        raise ContractError(label + "重复")


def _relative(path):
    parts = PurePosixPath(path).parts
    if "\\" in path or path.startswith("/") or ":" in path or not parts or any(
            part in (".", "..") for part in path.split("/")):
        raise ContractError("包内路径无效：" + path)


def _business_schema(schema):
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ContractError("工作接口JSON Schema无效：" + error.message) from error
    # References stay within this document. Neither validation nor an Agent
    # receives permission to fetch or execute a schema-controlled URL.
    def walk(node):
        if isinstance(node, dict):
            if "$id" in node:
                raise ContractError("工作接口不设置独立引用地址")
            for name in ("$ref", "$dynamicRef"):
                if name in node and not str(node[name]).startswith("#"):
                    raise ContractError("工作接口只能引用自身定义")
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(schema)
    try:
        resolver = Registry().with_resource("urn:runteams:work-schema",
            Resource.from_contents(schema, default_specification=DRAFT202012)).resolver("urn:runteams:work-schema")
        # Resolve every literal local reference, including ones in unused
        # branches. Do not defer broken definitions until a real task starts.
        def resolve(node):
            if isinstance(node, dict):
                for name in ("$ref", "$dynamicRef"):
                    if name in node:
                        resolver.lookup(node[name])
                for child in node.values():
                    resolve(child)
            elif isinstance(node, list):
                for child in node:
                    resolve(child)
        resolve(schema)
    except Exception as error:
        raise ContractError("工作接口引用不存在") from error


def _work(value):
    envelope = {'schema','objective','context','parameters','inputs','module_bindings','asset_bindings','skill_key','recovery'}
    for schema in (value['input_schema'],):
        if envelope & (set(schema.get('properties',{})) | set(schema.get('required',[]))):
            raise ContractError('工作输入只声明业务参数，不能再包一层任务信封')
    _business_schema(value["input_schema"])
    _business_schema(value["output_schema"])
    for field, key in (("steps", "id"), ("acceptance", "id"),
                       ("assets", "name"), ("deliverables", "path"),
                       ("result_actions", "id")):
        _unique(value[field], key, field)
    for item in value["deliverables"]:
        _relative(item["path"])
    for action in value["result_actions"]:
        schema = action["input_schema"]
        _business_schema(schema)
        properties = schema.get("properties", {})
        reserved = {"work_item", "result_action", "recovery", "human_response"}
        if set(properties) & reserved or set(action["bindings"]) & (set(properties) | reserved):
            raise ContractError("后续动作不能覆盖用户输入或平台恢复字段")
        if set(schema.get("required", [])) - set(properties):
            raise ContractError("后续动作必填信息没有对应字段")
        if any(item.get("type") not in ("string", "number", "integer", "boolean")
               for item in properties.values()):
            raise ContractError("后续动作表单只使用已有基本控件")
        if set(action["asset_bindings"].values()) - {item["name"] for item in value["assets"]}:
            raise ContractError("后续动作引用了未声明的来源资产槽")


def validate_definition(kind, value):
    """Validate without coercing types, adding defaults or dropping fields."""
    errors = sorted(Draft202012Validator(definition_schema(kind)).iter_errors(value),
                    key=lambda error: str(list(error.absolute_path)))
    if errors:
        error = errors[0]
        path = "/".join(str(item) for item in error.absolute_path) or kind
        raise ContractError(path + "：" + error.message)
    result = copy.deepcopy(value)
    if kind == "work":
        _work(result)
    elif kind in ("skill_extension", "skill_revision"):
        _unique(result["tools"], "id", "工具")
        for tool in result["tools"]:
            _relative(tool["entry"])
            if set(tool["credentials"]) & {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_ACCESS_TOKEN"}:
                raise ContractError("产品技能不能声明模型执行凭据")
        if result.get("work"):
            _work(result["work"])
            declared = {tool["id"] for tool in result["tools"]
                        if tool["runtime"].get("effect") == "verifier"}
            if {item["verifier"] for item in result["work"]["acceptance"] if "verifier" in item} - declared:
                raise ContractError("完成标准引用了未声明的产品校验工具")
        if kind == "skill_revision":
            _unique(result["files"], "path", "资源路径")
            for file in result["files"]:
                _relative(file["path"])
            paths = {file["path"] for file in result["files"]}
            if "SKILL.md" not in paths or {tool["entry"] for tool in result["tools"]} - paths:
                raise ContractError("技能缺少SKILL.md或工具入口")
    elif kind == "employee_draft":
        _unique(result["skill_refs"], "package_key", "选用技能")
    elif kind == "work_unit":
        _work(result["work"])
    elif kind == "employee_release":
        _unique(result["skill_revisions"], "package_key", "冻结技能")
        _unique(result["work_units"], "skill_key", "已发布工作")
        revisions = [validate_definition("skill_revision", revision) for revision in result["skill_revisions"]]
        mapping = result["skill_key_map"]
        if len(set(mapping.values())) != len(mapping) or set(mapping.values()) != {r["package_key"] for r in revisions}:
            raise ContractError("技能名称映射必须与冻结修订一一对应")
        expected = [_work_unit(revision, mapping) for revision in revisions]
        if result["work_units"] != expected:
            raise ContractError("执行合同必须来自被冻结技能的编译结果")
        validate_employee_bundles(result)
    elif kind == "portable_skill_bundle":
        _unique(result["files"], "path", "打包资源")
        files = {}
        size = 0
        for file in result["files"]:
            _relative(file["path"])
            # Bound encoded input before allocating the decoded payload.
            if len(file["content_base64"]) > 45 * 1024 * 1024:
                raise ContractError("技能包超过32MB")
            try:
                content = base64.b64decode(file["content_base64"], validate=True)
            except ValueError as error:
                raise ContractError("技能资源base64无效") from error
            size += len(content)
            if size > 32 * 1024 * 1024:
                raise ContractError("技能包超过32MB")
            if len(content) != file["size"] or hashlib.sha256(content).hexdigest() != file["sha256"]:
                raise ContractError("技能资源大小或摘要不匹配")
            files[file["path"]] = content
        if "SKILL.md" not in files:
            raise ContractError("技能包缺少SKILL.md")
        tree = hashlib.sha256()
        for path, content in sorted(files.items()):
            encoded = path.encode("utf-8")
            tree.update(len(encoded).to_bytes(4, "big")); tree.update(encoded)
            tree.update(len(content).to_bytes(8, "big")); tree.update(content)
        if tree.hexdigest() != result["digest"]:
            raise ContractError("技能包内容摘要不匹配")
    elif kind == "marketplace_employee_asset":
        refs = result["employee"]["skill_refs"]
        _unique(refs, "package_key", "可移植技能引用")
        bundles = [validate_definition("portable_skill_bundle", bundle) for bundle in result["skill_bundles"]]
        _unique(bundles, "package_key", "可移植技能包")
        if {(r["package_key"], r["digest"]) for r in refs} != {(r["package_key"], r["digest"]) for r in bundles}:
            raise ContractError("市场技能包必须与员工选用摘要完全一致")
    elif kind == "origin":
        if result["kind"] == "marketplace" and not all(
                result.get(field) for field in ("listing_id", "listing_version")):
            raise ContractError("市场来源缺少可信资产和版本记录")
        if result["kind"] == "authored" and set(result) & {"listing_id", "listing_version"}:
            raise ContractError("作者来源不能夹带安装记录")
    elif kind == "page":
        if result["has_more"] != bool(result["next_cursor"]):
            raise ContractError("分页游标与has_more不一致")
        if "total" in result and result["total"] < len(result["items"]):
            raise ContractError("分页总数小于本次返回数量")
    elif kind == "action_receipt":
        if result["status"] == "confirmed" and result["error"]:
            raise ContractError("已确认操作不能带失败回执")
    return result


def validate_embedded_employee_payload(value):
    """Check a full embedded release, with its optional exact selected work."""
    release=validate_definition('employee_release',{k:v for k,v in value.items() if k!='selected_work'})
    if release['schema']!='runteams.employee-release/v4':
        raise ContractError('员工资产必须来自完整冻结员工')
    if 'selected_work' in value and value['selected_work'] not in release['work_units']:
        raise ContractError('派工工作必须来自完整冻结员工')
    return release


def validate_employee_bundles(release):
    """Match bytes, complete file lists and declarations, never just a digest."""
    from .skill_bundles import extension as _extension
    bundles = [validate_definition('portable_skill_bundle', b) for b in release['skill_bundles']]
    _unique(bundles, 'package_key', '员工随包技能')
    by_key = {b['package_key']: b for b in bundles}
    if set(by_key) != {r['package_key'] for r in release['skill_revisions']}:
        raise ContractError('员工随包资产必须与冻结技能完全一致')
    for revision in release['skill_revisions']:
        bundle = by_key[revision['package_key']]
        if bundle['digest'] != revision['digest']:
            raise ContractError('员工随包技能摘要不一致')
        files = [{k: f[k] for k in ('path', 'sha256', 'size')} for f in bundle['files']]
        if sorted(files, key=lambda f: f['path']) != sorted(revision['files'], key=lambda f: f['path']):
            raise ContractError('员工随包资源清单不一致')
        extension = _extension(bundle)
        for field in skill_fields(revision):
            if extension.get(field) != revision[field]:
                raise ContractError('员工随包技能声明不一致：' + field)


def _work_unit(revision, skill_key_map):
    if revision["work"] is None:
        raise ContractError("该方法资源没有稳定工作声明，不能作为正式派工工作")
    work = copy.deepcopy(revision["work"])
    for action in work["result_actions"]:
        source_key = action["target"]["skill_key"]
        if source_key not in skill_key_map:
            raise ContractError("后续动作的目标技能未被这名员工选用")
        action["target"]["skill_key"] = skill_key_map[source_key]
    return {"schema": "runteams.work-unit/3", "skill_key": revision["package_key"], "revision_id": revision["revision_id"],
            "work": work,
            "tool_ids": [tool["id"] for tool in revision["tools"]],
            "execution": copy.deepcopy(revision["execution"])}


def compile_employee_release(draft, employee, revisions, runtime, *, skill_key_map=None, skill_bundles=None):
    """Compile only pinned immutable product revisions; never infer work."""
    draft = validate_definition("employee_draft", draft)
    employee = validate_definition("identity", employee)
    runtime = validate_definition("runtime_snapshot", runtime)
    for field, value in draft["runtime"].items():
        if (field == 'channel_id' or value != '') and runtime.get(field) != value:
            raise ContractError("运行时快照与员工选用配置不一致：" + field)
    if not draft["skill_refs"]:
        raise ContractError("发布前至少选用一项有稳定工作声明的产品技能")
    supplied = [validate_definition("skill_revision", item) for item in revisions]
    _unique(supplied, "package_key", "冻结技能")
    by_key = {item["package_key"]: item for item in supplied}
    if set(by_key) != {ref["package_key"] for ref in draft["skill_refs"]}:
        raise ContractError("冻结技能必须与选用技能完全一致")
    skill_key_map = copy.deepcopy(skill_key_map if skill_key_map is not None else {key: key for key in by_key})
    frozen, units = [], []
    for reference in draft["skill_refs"]:
        revision = by_key[reference["package_key"]]
        if revision["revision_id"] != reference["revision_id"]:
            raise ContractError("技能修订与选用版本不一致")
        if revision["work"] is None:
            raise ContractError("该方法资源没有稳定工作声明，不能作为正式派工工作")
        frozen.append(revision)
        units.append(_work_unit(revision, skill_key_map))
    for unit in units:
        for action in unit["work"]["result_actions"]:
            if action["target"]["skill_key"] not in by_key:
                raise ContractError("后续动作的目标技能未被这名员工选用")
    release = {"skill_bundles": copy.deepcopy(skill_bundles), "schema": "runteams.employee-release/v4", "employee": employee,
               "soul": draft["soul"], "runtime": runtime, "skill_revisions": frozen,
               "work_units": units, "skill_key_map": skill_key_map}
    return validate_definition("employee_release", release)


def select_work_unit(release, skill_key=None):
    """Select one formal work. Ambiguity is a user choice, never a text guess."""
    release = validate_definition("employee_release", release)
    units = release["work_units"]
    if skill_key is None and len(units) == 1:
        return copy.deepcopy(units[0])
    matches = [item for item in units if item["skill_key"] == skill_key]
    if len(matches) != 1:
        raise ContractError("请指定已发布的工作技能")
    return copy.deepcopy(matches[0])


def require_author_access(origin, actor_id):
    """Origin must be loaded from trusted storage, never a request body."""
    origin = validate_definition("origin", origin)
    if origin["kind"] != "authored" or not actor_id or origin["author_id"] != actor_id:
        raise PermissionError("仅员工作者可访问定义原文")


def validate_work_parameters(work_unit, parameters):
    unit = validate_definition("work_unit", work_unit)
    _business_schema(unit["work"]["input_schema"])
    errors = list(Draft202012Validator(unit["work"]["input_schema"]).iter_errors(parameters))
    if errors:
        raise ContractError("工作输入不符合技能声明：" + errors[0].message)
    return copy.deepcopy(parameters)
