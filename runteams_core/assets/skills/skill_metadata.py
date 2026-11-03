"""Pure declarations from the original skill bytes; no installation or execution."""
import json
import re
import yaml
from runteams_core.foundation.contracts import ContractError


def frontmatter(text):
    """Read actual YAML, including multiline scalars and arbitrary metadata."""
    lines = text.replace("\r\n", "\n").splitlines()
    if not lines or lines[0] != "---":
        raise ContractError("SKILL.md 必须包含 YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ContractError("SKILL.md frontmatter 未闭合") from exc
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        result = {}
        for key, value in node.value:
            name = loader.construct_object(key)
            if not isinstance(name, str) or name in result:
                raise ContractError("SKILL.md frontmatter 字段无效或重复")
            result[name] = loader.construct_object(value)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        values = yaml.load("\n".join(lines[1:end]), Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise ContractError("SKILL.md frontmatter 不是有效 YAML") from exc
    if not isinstance(values, dict):
        raise ContractError("SKILL.md frontmatter 必须是对象")
    name, description = values.get("name"), values.get("description")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ContractError("SKILL.md name 不符合 Agent Skills 规范")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ContractError("SKILL.md description 必须是非空文本，最多 1024 字符")
    for field in ("license", "compatibility", "allowed-tools"):
        if field in values and (not isinstance(values[field], str) or not values[field].strip()):
            raise ContractError("SKILL.md " + field + " 必须是非空文本")
    if len(values.get("compatibility", "")) > 500:
        raise ContractError("SKILL.md compatibility 超过 500 字符")
    if "metadata" in values and (not isinstance(values["metadata"], dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in values["metadata"].items())):
        raise ContractError("SKILL.md metadata 必须是文本键值映射")
    try:
        json.dumps(values, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError("SKILL.md frontmatter 包含不可保存的值") from exc
    return values


def extension(files, meta):
    from runteams_core.authoring.definition_contracts import validate_definition
    if "runteams.json" not in files:
        display = meta.get("metadata", {}).get("display_name") or meta["name"]
        if len(display) > 160:
            display = meta["name"]
        return validate_definition("skill_extension", {"schema": "runteams.package-extension/v3", "display_name": display,
                "tools": [], "execution": {}})
    try:
        value = json.loads(files["runteams.json"].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContractError("runteams.json 不是有效的 UTF-8 JSON") from exc
    return validate_definition("skill_extension", value)

