"""Canonical immutable skill tree verification, without a tool executor."""
import hashlib
from .contracts import ContractError
from . import skill_packages as _skill_packages
class ManifestFiles:
    @staticmethod
    def _assert_manifest_files(root, manifest):
        expected = {item["path"]: (item["sha256"], int(item["size"]))
                    for item in manifest.get("files") or []}
        actual, bodies = {}, {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ContractError("能力包对象包含符号链接")
            if path.is_file():
                body = path.read_bytes()
                relative = path.relative_to(root).as_posix()
                bodies[relative] = body
                actual[relative] = (hashlib.sha256(body).hexdigest(), len(body))
        if actual != expected:
            raise ContractError("能力包对象与不可变 manifest 不一致")
        if manifest.get("digest") and _skill_packages.tree_digest(bodies) != manifest["digest"]:
            raise ContractError("技能资源与冻结树摘要不一致")

