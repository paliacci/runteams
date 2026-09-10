# -*- coding: utf-8 -*-
"""Small child-process launcher that applies v3 resource limits before exec.

It runs after the parent has forked, so RunTeams never uses ``preexec_fn`` from
its threaded server.  The launcher contains no policy decisions; it only
applies the immutable values already validated by ``capability_runtime``.
"""
import base64
import json
import os
import sys


def _decode(value):
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8"))


def _set_limit(resource, kind, value):
    current_soft, current_hard = resource.getrlimit(kind)
    if current_hard not in (-1, resource.RLIM_INFINITY):
        value = min(value, current_hard)
    # Darwin rejects lowering the hard limit below the current soft limit in a
    # single setrlimit call.  Lower the soft side first, then seal both sides.
    if current_soft in (-1, resource.RLIM_INFINITY) or current_soft > value:
        resource.setrlimit(kind, (value, current_hard))
    resource.setrlimit(kind, (value, value))


def apply_limits(limits):
    if os.name != "posix":
        return
    import resource
    _set_limit(resource, resource.RLIMIT_CORE, 0)
    _set_limit(resource, resource.RLIMIT_CPU, int(limits["cpu_seconds"]))
    _set_limit(resource, resource.RLIMIT_FSIZE, int(limits["file_size_mb"]) * 1024 * 1024)
    _set_limit(resource, resource.RLIMIT_NOFILE, int(limits["open_files"]))
    if hasattr(resource, "RLIMIT_AS"):
        try:
            _set_limit(resource, resource.RLIMIT_AS, int(limits["memory_mb"]) * 1024 * 1024)
        except (OSError, ValueError):
            # A Python-hosted launcher can already have a larger virtual address
            # space on Darwin.  Keep the other hard limits and apply the native
            # resident-set limit where the platform exposes it.
            if hasattr(resource, "RLIMIT_RSS"):
                try:
                    _set_limit(resource, resource.RLIMIT_RSS,
                               int(limits["memory_mb"]) * 1024 * 1024)
                except (OSError, ValueError):
                    pass


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(arguments) < 3 or arguments[1] != "--":
        raise SystemExit("能力资源启动参数无效")
    limits = _decode(arguments[0])
    command = arguments[2:]
    if not command or not os.path.isabs(command[0]):
        raise SystemExit("能力启动文件必须是绝对路径")
    try:
        apply_limits(limits)
        os.execvpe(command[0], command, os.environ)
    except Exception as exc:
        sys.stderr.write("RUNTEAMS_RESOURCE_LAUNCH_FAILED: {}\n".format(str(exc)[:300]))
        raise SystemExit(70)


if __name__ == "__main__":
    main()
