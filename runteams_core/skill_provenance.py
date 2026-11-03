"""Preserve pinned upstream attribution with immutable skill revisions."""

import hashlib
import json
from pathlib import PurePosixPath
import re
from urllib.parse import urlparse

from .contracts import ContractError


def read_skill_provenance(files):
    body = files.get("upstream-sources.json")
    if body is None:
        return None
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContractError("技能来源记录不是有效 JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != "runteams.skill-sources/v1":
        raise ContractError("技能来源记录版本无效")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources or len(sources) > 20:
        raise ContractError("技能来源必须包含固定版本记录")
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ContractError("技能来源字段无效")
        repository = source.get("repository")
        url = urlparse(repository) if isinstance(repository, str) else None
        if not url or url.scheme != "https" or not url.netloc or url.username or url.password:
            raise ContractError("技能上游仓库必须是无凭据 HTTPS 地址")
        revision = source.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ContractError("技能上游版本必须固定到完整 Git commit")
        path = source.get("path")
        if not _relative(path):
            raise ContractError("技能上游目录无效")
        marker = (repository, revision, path)
        if marker in seen:
            raise ContractError("技能来源记录重复")
        seen.add(marker)
        if source.get("distribution") == "reference-only":
            if source.get("vendored_path") or source.get("files"):
                raise ContractError("仅参考的上游不得声明已打包原文")
            continue
        if source.get("distribution") != "vendored":
            raise ContractError("技能来源分发状态无效")
        if not isinstance(source.get("license"), str) or source["license"] in ("", "unconfirmed"):
            raise ContractError("已打包技能必须记录明确许可证")
        prefix = source.get("vendored_path")
        recorded = source.get("files")
        if not _relative(prefix) or not isinstance(recorded, dict) or "SKILL.md" not in recorded:
            raise ContractError("已打包技能必须保留原入口与文件摘要")
        actual = {name[len(prefix) + 1:]: data for name, data in files.items()
                  if name.startswith(prefix + "/")}
        if set(actual) != set(recorded):
            raise ContractError("上游资源清单与实际文件不一致")
        for name, digest in recorded.items():
            if not _relative(name) or hashlib.sha256(actual[name]).hexdigest() != digest:
                raise ContractError("上游资源摘要不一致：" + str(name))
        license_path = source.get("license_path")
        if not _relative(license_path) or not files.get(prefix + "/" + license_path):
            raise ContractError("已打包技能缺少许可证原文")
    return value


def _relative(value):
    return (isinstance(value, str) and value and "\\" not in value and "\0" not in value
            and not PurePosixPath(value).is_absolute()
            and all(part not in (".", "..", "") for part in value.split("/")))
