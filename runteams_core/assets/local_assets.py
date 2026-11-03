# -*- coding: utf-8 -*-
"""Local asset grants — platform-owned mount and clean-proof for one run.

Grants themselves (path, identity, exclusions) live in the shell's
``product_store.local_asset_grants`` table, on this machine only.  This
module never imports the shell: the caller (``runteams_core.agent_runtime``)
injects a ``grant_resolver`` callable, the same pattern already used for
credentials and Agent Channels.  See ``design/LOCAL_ASSET_GRANTS.md``.

Two access modes, chosen by what the bound directory actually is:
- ``git``: ``git clone --local`` to the commit captured at preflight time,
  overlay authorized working-tree changes, then remove the clone's ``origin``
  remote so ``.git/config`` cannot leak the original absolute path.
- ``snapshot``: a bounded copy that applies the grant's exclusion patterns
  (secrets, dependency directories, oversized binaries).

The platform fingerprints the original directory before and after the run
so a clean-proof comparison — never the model's own word — is what tells the
product whether anything on the user's disk changed.
"""
import fnmatch
import hashlib
import os
import shutil
import subprocess
from pathlib import Path


GIT_MAX_WORKTREE_BYTES = 2 * 1024 * 1024 * 1024
GIT_MAX_WORKTREE_FILES = 100_000
SNAPSHOT_MAX_BYTES = 1024 * 1024 * 1024
SNAPSHOT_MAX_FILES = 20_000
SNAPSHOT_MAX_FILE_BYTES = 100 * 1024 * 1024
_FINGERPRINT_MAX_ENTRIES = 20_000
_GIT_TIMEOUT = 30


class AssetError(RuntimeError):
    """A grant cannot be used for this run. Callers turn this into needs_human."""


def _git(path, *args, timeout=_GIT_TIMEOUT):
    try:
        result = subprocess.run(
            ["git", "-C", str(path)] + list(args),
            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return "", False
    return (result.stdout or "").strip(), result.returncode == 0


def git_root_commits(path):
    output, ok = _git(path, "rev-list", "--max-parents=0", "HEAD")
    if not ok:
        return []
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


def preflight(grant, slot_name):
    """Check a bound grant is still usable. Returns (ok, reason)."""
    if not grant:
        return False, "「{}」还没有绑定本地资产授权".format(slot_name)
    if grant.get("revoked"):
        return False, "「{}」绑定的授权已被撤销".format(slot_name)
    path = grant.get("path") or ""
    if not path:
        return False, "「{}」绑定的授权无效".format(slot_name)
    if os.path.islink(path.rstrip(os.sep)) or not (os.path.isdir(path) or os.path.isfile(path)):
        return False, "「{}」所在目录已不存在或不可读，可能已被移动或删除".format(slot_name)
    if not os.access(path, os.R_OK):
        return False, "「{}」不可读，请检查本地权限".format(slot_name)
    try:
        st = os.stat(path)
    except OSError:
        return False, "「{}」所在目录不可读".format(slot_name)
    if grant.get("is_git"):
        roots = git_root_commits(path)
        if not roots or ",".join(roots) != (grant.get("git_root_commit") or ""):
            return False, "「{}」所在目录已经不是同一个 Git 仓库".format(slot_name)
    else:
        if (st.st_dev, st.st_ino) != (grant.get("dev"), grant.get("ino")):
            return False, "「{}」所在目录已经改变，可能已被移动或替换".format(slot_name)
    return True, ""


def fingerprint(grant):
    """Capture the original directory's identity right before/after a run."""
    path = grant["path"]
    if grant.get("is_git"):
        head, _ = _git(path, "rev-parse", "HEAD")
        status, _ = _git(path, "status", "--porcelain=v1", "--branch")
        refs, _ = _git(path, "for-each-ref", "--format=%(refname) %(objectname)")
        stash, _ = _git(path, "stash", "list")
        worktrees, _ = _git(path, "worktree", "list", "--porcelain")
        return {"mode": "git", "head": head, "status": status, "refs": refs,
                "stash": stash, "worktrees": worktrees}
    if os.path.isfile(path):
        digest = hashlib.sha256()
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return {"mode": "file", "digest": digest.hexdigest()}
    entries = []
    for current, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames
                             if not os.path.islink(os.path.join(current, name)))
        for name in sorted(filenames):
            full = os.path.join(current, name)
            if os.path.islink(full):
                continue
            try:
                stat_result = os.stat(full)
            except OSError:
                continue
            entries.append([os.path.relpath(full, path).replace(os.sep, "/"),
                            stat_result.st_size, int(stat_result.st_mtime)])
            if len(entries) >= _FINGERPRINT_MAX_ENTRIES:
                break
        if len(entries) >= _FINGERPRINT_MAX_ENTRIES:
            break
    return {"mode": "snapshot", "entries": entries}


def diff_fingerprints(before, after):
    """Human-readable summary of what changed on the *original* directory."""
    if before == after:
        return []
    if before.get("mode") == "git":
        changes = []
        if before.get("head") != after.get("head"):
            changes.append("HEAD 从 {} 变为 {}".format(
                (before.get("head") or "")[:10] or "(空)", (after.get("head") or "")[:10] or "(空)"))
        if before.get("status") != after.get("status"):
            changes.append("工作区未提交改动发生了变化")
        if before.get("stash") != after.get("stash"):
            changes.append("stash 列表发生了变化")
        if before.get("refs") != after.get("refs"):
            changes.append("分支或标签发生了变化")
        if before.get("worktrees") != after.get("worktrees"):
            changes.append("worktree 列表发生了变化")
        return changes or ["检测到差异"]
    if before.get("mode") == "file":
        return ["原文件内容发生了变化"]
    before_map = {item[0]: (item[1], item[2]) for item in before.get("entries") or []}
    after_map = {item[0]: (item[1], item[2]) for item in after.get("entries") or []}
    added = sorted(set(after_map) - set(before_map))
    removed = sorted(set(before_map) - set(after_map))
    changed = sorted(path for path in set(before_map) & set(after_map)
                     if before_map[path] != after_map[path])
    changes = []
    if added:
        changes.append("新增 {} 个文件，如 {}".format(len(added), "、".join(added[:3])))
    if removed:
        changes.append("删除 {} 个文件，如 {}".format(len(removed), "、".join(removed[:3])))
    if changed:
        changes.append("修改 {} 个文件，如 {}".format(len(changed), "、".join(changed[:3])))
    return changes or ["检测到差异"]


def _split_patterns(patterns):
    dirs, files = [], []
    for raw in patterns or ():
        pattern = str(raw or "").strip()
        if not pattern:
            continue
        if pattern.endswith("/"):
            dirs.append(pattern[:-1])
        else:
            files.append(pattern)
    return dirs, files


def _git_worktree_estimate(path):
    """Estimate tracked working files before adding non-ignored changes.

    Gitignored build output, dependency directories and local backups
    sitting in the source working tree never make it into the copy.
    Walking the raw directory (as an earlier version of this
    function did) counts all of that too and rejects ordinary repositories
    whose working tree happens to hold multi-gigabyte untracked artifacts
    the clone would never touch — confirmed against a real ~7GB checkout
    with a 24MB, 451-file tracked footprint.
    """
    try:
        result = subprocess.run(["git", "-C", str(path), "ls-files", "-z"],
                                capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 0, 0
    if result.returncode != 0:
        return 0, 0
    total_bytes, total_files = 0, 0
    for name in result.stdout.split(b"\x00"):
        if not name:
            continue
        full = os.path.join(path, os.fsdecode(name))
        if os.path.islink(full):
            continue
        try:
            total_bytes += os.path.getsize(full)
        except OSError:
            continue
        total_files += 1
    return total_bytes, total_files


def _git_changed_paths(path):
    """Tracked changes against HEAD plus non-ignored untracked files."""
    changed = set()
    for args in (("diff", "--name-only", "-z", "HEAD", "--"),
                 ("ls-files", "--others", "--exclude-standard", "-z")):
        try:
            result = subprocess.run(["git", "-C", str(path), *args],
                                    capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise AssetError("无法读取 Git 工作区改动") from exc
        if result.returncode != 0:
            raise AssetError("无法读取 Git 工作区改动")
        changed.update(os.fsdecode(name) for name in result.stdout.split(b"\x00") if name)
    return sorted(changed)


def _excluded_git_path(relative, patterns):
    dirs, files = _split_patterns(patterns)
    parts = Path(relative).parts
    return (any(fnmatch.fnmatch(part, pattern) for part in parts[:-1] for pattern in dirs)
            or any(fnmatch.fnmatch(parts[-1], pattern) for pattern in files))


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def _overlay_git_worktree(source, destination, patterns, tracked_bytes, tracked_files):
    """Make the checkout reflect authorized live files, or fail the mount."""
    source, destination = Path(source), Path(destination)
    changed, included, excluded, untracked = _git_changed_paths(source), [], [], 0
    copied_hashes = {}
    total_bytes, total_files = tracked_bytes, tracked_files
    for relative in changed:
        parts = Path(relative).parts
        if (not parts or Path(relative).is_absolute() or ".." in parts
                or ".git" in parts or "\x00" in relative):
            raise AssetError("Git 工作区包含无效路径，无法完整挂载")
        if _excluded_git_path(relative, patterns):
            excluded.append(relative)
            continue
        original, target = source / relative, destination / relative
        if any((source / Path(*parts[:index])).is_symlink() for index in range(1, len(parts) + 1)):
            raise AssetError("Git 工作区包含符号链接，无法安全挂载：{}".format(relative))
        if any((destination / Path(*parts[:index])).is_symlink() for index in range(1, len(parts))):
            raise AssetError("Git 副本包含符号链接目录，无法安全挂载：{}".format(relative))
        if original.exists():
            if not original.is_file():
                raise AssetError("Git 工作区包含无法复制的目录：{}".format(relative))
            size = original.stat().st_size
            if size > SNAPSHOT_MAX_FILE_BYTES:
                raise AssetError("未提交文件超过单文件大小上限：{}".format(relative))
            if not target.exists():
                total_bytes += size
                total_files += 1
                untracked += 1
            if total_bytes > GIT_MAX_WORKTREE_BYTES or total_files > GIT_MAX_WORKTREE_FILES:
                raise AssetError("Git 工作区改动超过挂载大小上限")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                target.unlink()
            shutil.copy2(original, target)
            copied_hashes[relative] = _file_hash(target)
            if copied_hashes[relative] != _file_hash(original):
                raise AssetError("Git 工作区复制期间发生变化，请重试")
        elif target.is_file() or target.is_symlink():
            target.unlink()
        elif target.exists():
            raise AssetError("Git 副本包含无法删除的目录：{}".format(relative))
        included.append(relative)
    if changed != _git_changed_paths(source):
        raise AssetError("Git 工作区复制期间发生变化，请重试")
    for relative, digest in copied_hashes.items():
        if _file_hash(source / relative) != digest:
            raise AssetError("Git 工作区复制期间发生变化，请重试")
    return {"included": len(included), "untracked": untracked,
            "excluded": excluded, "paths": included[:100]}


def _content_digest(root):
    root = Path(root)
    value = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if os.path.islink(path) or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        body = path.read_bytes()
        value.update(len(relative).to_bytes(4, "big"))
        value.update(relative)
        value.update(len(body).to_bytes(8, "big"))
        value.update(body)
    return value.hexdigest()


def _snapshot_copy(source, destination, patterns):
    dir_patterns, file_patterns = _split_patterns(patterns)
    excluded, total_bytes, total_files = [], 0, 0
    source = Path(source)
    destination = Path(destination)
    for current_dir, dirnames, filenames in os.walk(source, followlinks=False):
        current = Path(current_dir)
        relative_dir = current.relative_to(source)
        pruned = []
        for name in list(dirnames):
            full = current / name
            if os.path.islink(full):
                excluded.append(((relative_dir / name).as_posix() if str(relative_dir) != "."
                                 else name) + "/")
                pruned.append(name)
                continue
            if any(fnmatch.fnmatch(name, pattern) for pattern in dir_patterns):
                excluded.append(((relative_dir / name).as_posix() if str(relative_dir) != "."
                                 else name) + "/")
                pruned.append(name)
        for name in pruned:
            dirnames.remove(name)
        dest_dir = destination / relative_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(filenames):
            source_file = current / name
            relative_name = ((relative_dir / name).as_posix() if str(relative_dir) != "."
                             else name)
            if os.path.islink(source_file):
                excluded.append(relative_name)
                continue
            if any(fnmatch.fnmatch(name, pattern) for pattern in file_patterns):
                excluded.append(relative_name)
                continue
            try:
                size = source_file.stat().st_size
            except OSError:
                continue
            if size > SNAPSHOT_MAX_FILE_BYTES:
                excluded.append(relative_name + "（超过单文件大小上限）")
                continue
            total_files += 1
            total_bytes += size
            if total_files > SNAPSHOT_MAX_FILES or total_bytes > SNAPSHOT_MAX_BYTES:
                raise AssetError("本地资产内容超过快照大小上限")
            shutil.copy2(source_file, dest_dir / name)
    return excluded, total_bytes, total_files


def _prune_excludes(root, patterns, skip_top=()):
    """Remove default-excluded paths from an already-materialized tree.

    ``git clone`` faithfully reproduces whatever was committed, including a
    secret a user accidentally checked in. Snapshot mode filters while
    copying; git mode filters the checked-out working tree afterwards so the
    same default excludes (credentials, dependency directories) never sit in
    the employee's workspace either way. This never rewrites git history —
    only the working-tree copy the employee actually reads.
    """
    dir_patterns, file_patterns = _split_patterns(patterns)
    root = Path(root)
    excluded = []
    for current_dir, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(current_dir)
        relative_dir = current.relative_to(root)
        if str(relative_dir) == "." and skip_top:
            dirnames[:] = [name for name in dirnames if name not in skip_top]
        pruned = []
        for name in list(dirnames):
            if any(fnmatch.fnmatch(name, pattern) for pattern in dir_patterns):
                relative_name = ((relative_dir / name).as_posix()
                                 if str(relative_dir) != "." else name)
                excluded.append(relative_name + "/")
                shutil.rmtree(current / name, ignore_errors=True)
                pruned.append(name)
        for name in pruned:
            dirnames.remove(name)
        for name in list(filenames):
            if any(fnmatch.fnmatch(name, pattern) for pattern in file_patterns):
                relative_name = ((relative_dir / name).as_posix()
                                 if str(relative_dir) != "." else name)
                excluded.append(relative_name)
                try:
                    (current / name).unlink()
                except OSError:
                    pass
    return excluded


def _git_clone(source, destination, commit):
    result = subprocess.run(
        ["git", "clone", "--local", "--quiet", str(source), str(destination)],
        capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise AssetError("克隆本地资产仓库失败：{}".format((result.stderr or "").strip()[:300]))
    checkout = subprocess.run(
        ["git", "-C", str(destination), "checkout", "--quiet", commit],
        capture_output=True, text=True, timeout=120)
    if checkout.returncode != 0:
        raise AssetError("检出固定提交失败：{}".format((checkout.stderr or "").strip()[:300]))
    # A local clone's origin still points at the original absolute path
    # (.git/config); the employee only ever sees the copy, never that path.
    subprocess.run(["git", "-C", str(destination), "remote", "remove", "origin"],
                    capture_output=True, text=True, timeout=30)


def mount(grant, destination):
    """Mount one bound grant into ``destination`` (a fresh, empty directory).

    Returns ``(record, fingerprint_before)`` where ``record`` is the public,
    path-free description injected into the work order.
    """
    path = grant["path"]
    if os.path.isfile(path) and os.path.getsize(path) > SNAPSHOT_MAX_FILE_BYTES:
        raise AssetError("本地文件超过单文件大小上限")
    before = fingerprint(grant)
    destination = Path(destination)
    if before.get("mode") == "file":
        size = os.path.getsize(path)
        if size > SNAPSHOT_MAX_FILE_BYTES:
            raise AssetError("本地文件超过单文件大小上限")
        _, patterns = _split_patterns(grant.get("excluded") or ())
        if any(fnmatch.fnmatch(os.path.basename(path), pattern) for pattern in patterns):
            raise AssetError("所选文件被授权的排除规则排除，请调整授权后重试")
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination / os.path.basename(path))
        record = {"mode": "snapshot", "digest": _content_digest(destination),
                  "excluded": [], "bytes": size, "files": 1}
    elif grant.get("is_git") and before.get("head"):
        worktree_bytes, worktree_files = _git_worktree_estimate(path)
        if worktree_bytes > GIT_MAX_WORKTREE_BYTES or worktree_files > GIT_MAX_WORKTREE_FILES:
            raise AssetError("Git 仓库超过挂载大小上限")
        _git_clone(path, destination, before["head"])
        excluded = _prune_excludes(destination, grant.get("excluded") or (), skip_top=(".git",))
        working_tree = _overlay_git_worktree(path, destination, grant.get("excluded") or (),
                                             worktree_bytes, worktree_files)
        if fingerprint(grant) != before:
            raise AssetError("Git 工作区复制期间发生变化，请重试")
        record = {"mode": "git", "commit": before["head"],
                  "excluded": sorted(set(excluded + working_tree["excluded"])),
                  "working_tree": working_tree}
    else:
        excluded, total_bytes, total_files = _snapshot_copy(
            path, destination, grant.get("excluded") or ())
        record = {"mode": "snapshot", "digest": _content_digest(destination),
                  "excluded": excluded, "bytes": total_bytes, "files": total_files}
    return record, before
