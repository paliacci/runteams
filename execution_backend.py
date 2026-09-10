# -*- coding: utf-8 -*-
"""Unified process lifecycle for task capabilities.

The runtime contract chooses *what* to run.  Capabilities inherit the same
local authority as the user's Agent CLI; this module only adds operational
governance (resource limits, cancellation and process-tree cleanup).  RunTeams
must not impose a second filesystem/network/subprocess sandbox that can make a
working Agent automation fail after it enters a pipeline.
"""
import base64
import json
import os
import signal
import subprocess
import sys

import capability_runtime


def _encoded_limits(limits):
    payload = json.dumps(limits, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _resource_command(command, runtime):
    if runtime.get("version", 1) < 3:
        return list(command)
    encoded = _encoded_limits(runtime["limits"])
    if getattr(sys, "frozen", False):
        launcher = [sys.executable, "--runteams-capability-launcher", encoded, "--"]
    else:
        launcher = [sys.executable, os.path.join(os.path.dirname(__file__), "capability_launcher.py"),
                    encoded, "--"]
    return launcher + list(command)


def prepare_command(entry, command, workspace_path, private_tmp, label="capability"):
    runtime = capability_runtime.normalize((entry or {}).get("runtime"), (entry or {}).get("entry_path"))
    return _resource_command(list(command), runtime)


def process_tree_usage(root_pid):
    """Return process count and resident memory for a capability process tree."""
    if os.name != "posix":
        return {"processes": 0, "rss_kb": 0}
    try:
        output = subprocess.check_output(
            ["/bin/ps", "-axo", "pid=,ppid=,rss="], text=True,
            stderr=subprocess.DEVNULL, timeout=1)
    except (OSError, subprocess.SubprocessError):
        return {"processes": 0, "rss_kb": 0}
    children, memory = {}, {}
    for line in output.splitlines():
        try:
            pid, parent, rss = (int(value) for value in line.split()[:3])
        except (TypeError, ValueError):
            continue
        children.setdefault(parent, []).append(pid)
        memory[pid] = max(0, rss)
    seen, pending = set(), [int(root_pid)]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(children.get(current, []))
    return {"processes": len(seen), "rss_kb": sum(memory.get(pid, 0) for pid in seen)}


def stop_process_tree(process, grace_seconds=1):
    if process.poll() is not None:
        return
    if os.name != "posix":
        try:
            process.terminate()
            process.wait(timeout=grace_seconds)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace_seconds)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            pass


def process_limit_violation(pid, entry):
    runtime = capability_runtime.normalize((entry or {}).get("runtime"), (entry or {}).get("entry_path"))
    if runtime.get("version", 1) < 3:
        return ""
    usage = process_tree_usage(pid)
    count = usage["processes"]
    maximum = int(runtime["limits"]["processes"])
    if count and count > maximum:
        return "能力创建了 {} 个进程，超过声明上限 {}".format(count, maximum)
    memory_mb = usage["rss_kb"] / 1024
    memory_limit = int(runtime["limits"]["memory_mb"])
    if memory_mb > memory_limit:
        return "能力使用了 {:.0f} MB 内存，超过声明上限 {} MB".format(memory_mb, memory_limit)
    return ""
