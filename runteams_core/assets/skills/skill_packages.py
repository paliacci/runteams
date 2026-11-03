"""Read-only admission of complete original skill bytes; never installs or executes."""
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import unquote,urlsplit
from runteams_core.foundation.contracts import ContractError
from runteams_core.assets.skills import skill_metadata
from runteams_core.assets.skills.skill_provenance import read_skill_provenance
from runteams_core.assets.skills.skill_icons import FILE_NAME as ICON_FILE, read_icon

IGNORED={".DS_Store","__pycache__",".git"}
MAX_FILES=500
MAX_BYTES=32*1024*1024


def safe_relative(value):
    value = str(value or "")
    if "\\" in value or ":" in value:
        raise ContractError("技能资源路径无效：" + value)
    normalized = os.path.normpath(value).replace("\\", "/")
    if (not value or value.startswith("/") or normalized in (".", "..") or
            normalized.startswith("../") or "\0" in value):
        raise ContractError("能力包路径不安全：{}".format(value or "(empty)"))
    return normalized


def validate_resources(files):
    """Resolve explicit Markdown file links; native remote tools stay available."""
    for path, body in files.items():
        if not path.endswith(".md"):
            continue
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError("Markdown 资源必须使用 UTF-8：" + path) from exc
        # Code samples are examples, not references of the installed package.
        text = re.sub(r"```.*?```|`[^`\n]+`", "", text, flags=re.S)
        links = re.findall(r"!?\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)", text)
        links += re.findall(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", text, flags=re.M)
        for link in links:
            link = link.strip("<>")
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            relative = safe_relative((Path(path).parent / unquote(parsed.path)).as_posix())
            if relative not in files and not any(name.startswith(relative.rstrip("/") + "/") for name in files):
                raise ContractError("引用资源不存在：{} → {}".format(path, relative))


def prepare(source):
    from runteams_core.agents import capability_runtime
    source = Path(source)
    if source.is_symlink():
        raise ContractError("技能包目录不能是符号链接")
    source = source.resolve()
    if not source.is_dir():
        raise ContractError("能力包目录不存在")
    skill_path = source / "SKILL.md"
    if not skill_path.is_file():
        raise ContractError("Agent Skill 能力包必须包含 SKILL.md")
    files, total = {}, 0
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        if any(part in IGNORED for part in path.relative_to(source).parts):
            continue
        if path.is_symlink():
            raise ContractError("能力包不能包含符号链接：{}".format(relative))
        if not path.is_file():
            continue
        if len(files) >= MAX_FILES:
            raise ContractError("能力包文件数量超过限制")
        body = path.read_bytes()
        total += len(body)
        if total > MAX_BYTES:
            raise ContractError("能力包大小超过 32 MB")
        files[safe_relative(relative)] = body
    try:
        skill_text = files["SKILL.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("SKILL.md 必须使用 UTF-8") from exc
    meta = skill_metadata.frontmatter(skill_text)
    if source.name != meta["name"]:
        raise ContractError("SKILL.md name 必须与能力包目录名一致")
    extension = skill_metadata.extension(files, meta)
    for tool in extension["tools"]:
        entry = safe_relative(tool["entry"])
        if entry not in files:
            raise ContractError("工具入口不存在：" + entry)
        if any(name.upper() in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_ACCESS_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "AZURE_OPENAI_API_KEY"} for name in tool["credentials"]):
            raise ContractError("产品技能不能声明模型执行凭据")
        raw = tool["runtime"]
        if not all(key in raw for key in ("runner", "effect", "healthcheck")):
            raise ContractError("产品工具必须明确声明 runner、effect 和 healthcheck")
        runtime = capability_runtime.normalize(raw, entry, files)
        if runtime.get("dependencies"):
            raise ContractError("产品工具只接受零外部依赖工具")
        healthcheck = runtime["healthcheck"]
        if not healthcheck.get("enabled") or not healthcheck.get("declared") or not healthcheck.get("cases"):
            raise ContractError("可执行工具必须声明真实 healthcheck 行为用例")
        overlap = set(healthcheck.get("fixture_files") or {}).intersection(files)
        if overlap:
            raise ContractError("行为用例文件不能覆盖技能文件：" + sorted(overlap)[0])
        if runtime["effect"] == "verifier" and {case["expected"] for case in healthcheck["cases"]} != {"passed", "failed"}:
            raise ContractError("校验工具必须同时覆盖通过和失败用例")
    validate_resources(files)
    # Catalog projection; frozen definitions are produced only by freeze_revision.
    manifest = {**extension, "name": meta["name"], "description": meta["description"],
        "files": [{"path": path, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
                  for path, body in sorted(files.items())],
        "extensions": {"agent_skills": meta,
            **({"skill_icon": read_icon(files)} if ICON_FILE in files else {}),
            **({"upstream_sources": read_skill_provenance(files)} if "upstream-sources.json" in files else {})}}
    return {"digest": tree_digest(files), "manifest": manifest,
            "files": files}


def tree_digest(files):
    value = hashlib.sha256()
    for path, body in sorted(files.items()):
        encoded = path.encode("utf-8")
        value.update(len(encoded).to_bytes(4, "big"))
        value.update(encoded)
        value.update(len(body).to_bytes(8, "big"))
        value.update(body)
    return value.hexdigest()

