"""Verify portable skill bundle declarations from complete immutable bytes."""
import base64
import json
from .contracts import ContractError
from .definition_contracts import validate_definition


def extension(bundle):
    """Read the actual resource bytes, never a caller supplied work projection."""
    bundle = validate_definition("portable_skill_bundle", bundle)
    files = {f["path"]: base64.b64decode(f["content_base64"], validate=True)
             for f in bundle["files"]}
    if "runteams.json" not in files:
        raise ContractError("市场技能缺少v2工作声明")
    try:
        def unique_object(pairs):
            result = {}
            for key, child in pairs:
                if key in result: raise ValueError("技能声明JSON字段重复")
                result[key] = child
            return result
        def invalid_constant(value):
            raise ValueError("声明包含非JSON数值")
        extension = json.loads(files["runteams.json"].decode("utf-8"), object_pairs_hook=unique_object,
                               parse_constant=invalid_constant)
        from .skill_metadata import frontmatter as _frontmatter
        _frontmatter(files["SKILL.md"].decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ContractError("市场技能声明不是有效UTF-8 JSON") from exc
    extension = validate_definition("skill_extension", extension)
    if not extension.get("work"):
        raise ContractError("市场员工技能必须有正式工作声明")
    for tool in extension["tools"]:
        if tool["entry"] not in files:
            raise ContractError("市场技能工具入口不存在")
    return extension

