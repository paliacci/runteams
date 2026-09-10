"""Capability handshake for the two supported Agent CLI protocols."""

import subprocess


_PROFILES = {
    "codex": {
        "label": "Codex",
        "protocol": "codex-jsonl",
        "help_args": ("exec", "--help"),
        "required_options": (
            "--json", "--ephemeral", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules", "--enable", "--disable",
            "--sandbox", "--dangerously-bypass-approvals-and-sandbox",
            "--config", "--image",
        ),
    },
    "claude-code": {
        "label": "Claude Code",
        "protocol": "claude-stream-json",
        "help_args": ("--help",),
        "required_options": (
            "--print", "--output-format", "--verbose", "--include-partial-messages",
            "--no-session-persistence", "--safe-mode", "--setting-sources",
            "--disable-slash-commands", "--permission-mode", "--effort",
            "--mcp-config", "--strict-mcp-config",
        ),
    },
}


def _run(argv, env, timeout=8):
    return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, env=env, timeout=timeout)


def required_options(provider):
    profile = _PROFILES.get(provider) or {}
    return tuple(profile.get("required_options") or ())


def check(provider, executable, env, run=None):
    """Verify behavior used by RunTeams instead of guessing from a semver range."""
    profile = _PROFILES.get(provider)
    if profile is None:
        return {"compatible": True, "protocol": "", "missing_options": [], "detail": ""}
    invoke = run or _run
    argv = [str(executable)] + list(profile["help_args"])
    try:
        completed = invoke(argv, env, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"compatible": False, "protocol": profile["protocol"],
                "missing_options": list(profile["required_options"]),
                "detail": "{} CLI 兼容性检测失败：{}".format(profile["label"], exc)}
    help_text = "\n".join((completed.stdout or "", completed.stderr or ""))
    missing = [option for option in profile["required_options"] if option not in help_text]
    compatible = completed.returncode == 0 and not missing
    if compatible:
        detail = ""
    elif completed.returncode != 0:
        detail = "{} CLI 无法提供兼容性信息（退出码 {}）".format(
            profile["label"], completed.returncode)
    else:
        detail = "{} CLI 与 RunTeams 不兼容：缺少 {}；请更新官方 CLI".format(
            profile["label"], "、".join(missing))
    return {"compatible": compatible, "protocol": profile["protocol"],
            "missing_options": missing, "detail": detail}
