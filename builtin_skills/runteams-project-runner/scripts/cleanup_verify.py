#!/usr/bin/env python3
"""Prove the isolated environment was torn down before the employee submits.

Passes only when .scratch/ is gone, no process still references it, and every
port handed out by isolated-env is free again. The employee's own word is never
the proof.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _result import emit  # noqa: E402

TOOL = "cleanup-verify"


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.settimeout(0.5)
        return handle.connect_ex(("127.0.0.1", int(port))) == 0


def processes_referencing(path):
    try:
        listing = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                                 text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    own = {os.getpid(), os.getppid()}
    found = []
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and int(pid) not in own and path in command:
            found.append("{} {}".format(pid, command[:160]))
    return found


def main(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".")
    args = parser.parse_args(arguments)
    workspace = Path(args.workspace).resolve()
    registry_path = workspace / ".runteams" / "project-runner.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registry = {}
    scratch = Path(registry.get("scratch") or workspace / ".scratch")
    problems = []
    if scratch.exists():
        problems.append("隔离目录仍然存在：{}".format(os.path.relpath(scratch, workspace)))
    for line in processes_referencing(str(scratch)):
        problems.append("仍有进程引用隔离目录：{}".format(line))
    for port in registry.get("ports") or []:
        if port_in_use(port):
            problems.append("端口 {} 仍被占用".format(port))
    if problems:
        return emit(TOOL, False, "清理未完成：" + "；".join(problems[:5]),
                    output="\n".join(problems), code="cleanup_incomplete")
    return emit(TOOL, True, "清理已完成：隔离目录已删除，没有残留进程，登记的端口已释放")


if __name__ == "__main__":
    raise SystemExit(main())
