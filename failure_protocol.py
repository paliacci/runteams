# -*- coding: utf-8 -*-
"""Stable failure envelopes shared by capability execution paths.

Agent runtimes should receive raw evidence, while RunTeams needs one small,
provider-neutral contract to decide whether a failure belongs to a user, the
host environment, or an immutable worker capability.  Keeping this contract in
one place prevents tools, checks and preflight from silently diverging.
"""
import capability_runtime


OWNERS = ("user", "system", "capability", "provider", "product", "task", "unknown")
CAPABILITY_KINDS = ("tool", "check")
CAPABILITY_PROOFS = ("preflight", "selfcheck", "minimal_sample", "runtime_launch",
                     "repeated_unrelated_tasks")


def normalize(value=None, *, source="", capability_kind="", capability_slug="",
              message="", output="", exit_code=1, remediation=""):
    value = dict(value) if isinstance(value, dict) else {}
    raw_output = str(output or value.get("output") or message or value.get("message") or "")
    classified = capability_runtime.classify_failure(raw_output, exit_code) or {}
    owner = str(value.get("owner") or classified.get("owner") or "unknown")
    if owner not in OWNERS:
        owner = "unknown"
    kind = str(capability_kind or value.get("capability_kind") or "").lower()
    if kind not in CAPABILITY_KINDS:
        kind = ""
    slug = str(capability_slug or value.get("capability_slug") or
               value.get("capability") or "")[:240]
    proof = str(value.get("proof") or "")[:80]
    return {
        "schema": "runteams.failure/v1",
        "source": str(source or value.get("source") or "")[:80],
        "owner": owner,
        "code": str(value.get("code") or classified.get("code") or
                    "execution_failed")[:120],
        "message": str(value.get("message") or classified.get("message") or
                       message or "执行未通过")[:4000],
        "remediation": str(value.get("remediation") or classified.get("remediation") or
                           remediation or "")[:2000],
        "capability_kind": kind,
        "capability_slug": slug,
        "exit_code": int(exit_code or 0),
        "output": raw_output[-30000:],
        "proof": proof,
        "repairable": bool(kind and owner == "capability" and proof in CAPABILITY_PROOFS),
    }


def from_exception(exc, *, source, capability_kind, capability_slug, output=""):
    existing = getattr(exc, "failure", None)
    return normalize(existing, source=source, capability_kind=capability_kind,
                     capability_slug=capability_slug, message=str(exc),
                     output=output or str(exc), exit_code=1)


def result(*, tool_id="", exit_code=0, output="", truncated=False, failure=None,
           artifacts=None, execution_status="completed"):
    """Build the provider-neutral task-tool result envelope.

    ``execution`` answers whether the control plane managed to run the command.
    ``evaluation`` answers whether the command's evidence passed.  These are
    deliberately independent: a verifier that exits non-zero was executed
    successfully and is ordinary evidence for the worker Agent, not an MCP
    transport error.

    The flat keys remain during the compatibility window because persisted
    sessions and older desktop builds may still read them.
    """
    status = str(execution_status or "completed")
    if status not in ("completed", "failed"):
        status = "failed"
    normalized_failure = None
    if isinstance(failure, dict):
        normalized_failure = normalize(
            failure,
            source=failure.get("source") or "task_tool_result",
            capability_kind=failure.get("capability_kind") or "tool",
            capability_slug=failure.get("capability_slug") or failure.get("capability") or tool_id,
            output=failure.get("output") or output,
            exit_code=exit_code,
        )
        # Preserve additional diagnostic metadata without weakening the stable
        # fields produced by normalize().
        for key in ("runtime", "proof", "failure_fingerprint", "capability"):
            if key in failure:
                normalized_failure[key] = failure[key]
    evaluation_status = "failed" if normalized_failure or int(exit_code or 0) != 0 else "passed"
    evaluation = {
        "status": evaluation_status,
        "owner": (normalized_failure or {}).get("owner") or "task" if evaluation_status == "failed" else "none",
        "code": (normalized_failure or {}).get("code") or ("nonzero_exit" if evaluation_status == "failed" else "passed"),
        "summary": (normalized_failure or {}).get("message") or ("执行未通过" if evaluation_status == "failed" else "执行通过"),
    }
    evidence = {
        "output": str(output or ""),
        "artifacts": list(artifacts or []),
        "truncated": bool(truncated),
    }
    return {
        "schema": "runteams.tool-result/v1",
        "tool_id": str(tool_id or ""),
        "execution": {"status": status, "exit_code": int(exit_code or 0)},
        "evaluation": evaluation,
        "evidence": evidence,
        # Backward-compatible projection.
        "exit_code": int(exit_code or 0),
        "output": evidence["output"],
        "truncated": evidence["truncated"],
        "failure": normalized_failure,
    }


def execution_status(value):
    if not isinstance(value, dict):
        return "failed"
    execution = value.get("execution") if isinstance(value.get("execution"), dict) else {}
    return str(execution.get("status") or ("completed" if "exit_code" in value else "failed"))


def exit_code(value):
    if not isinstance(value, dict):
        return 1
    execution = value.get("execution") if isinstance(value.get("execution"), dict) else {}
    try:
        return int(execution.get("exit_code", value.get("exit_code", 0)) or 0)
    except (TypeError, ValueError):
        return 1


def failure_from_result(value):
    if not isinstance(value, dict):
        return None
    failure = value.get("failure")
    if isinstance(failure, dict):
        return failure
    evaluation = value.get("evaluation") if isinstance(value.get("evaluation"), dict) else {}
    if evaluation.get("status") != "failed" and exit_code(value) == 0:
        return None
    evidence = value.get("evidence") if isinstance(value.get("evidence"), dict) else {}
    return normalize(
        evaluation,
        source="tool_result",
        capability_kind="tool",
        capability_slug=value.get("tool_id") or "",
        message=evaluation.get("summary") or "执行未通过",
        output=evidence.get("output") or value.get("output") or "",
        exit_code=exit_code(value),
    )


def passed(value):
    if not isinstance(value, dict) or execution_status(value) != "completed":
        return False
    evaluation = value.get("evaluation") if isinstance(value.get("evaluation"), dict) else {}
    if evaluation:
        return evaluation.get("status") == "passed" and exit_code(value) == 0
    return failure_from_result(value) is None and exit_code(value) == 0


def fingerprint(value, capability_slug=""):
    if isinstance(value, dict) and (value.get("owner") or value.get("code")):
        failure = normalize(value, capability_slug=capability_slug,
                            output=value.get("output") or value.get("message") or "",
                            exit_code=value.get("exit_code", 1))
    else:
        failure = failure_from_result(value) if isinstance(value, dict) else normalize(value)
    failure = failure or {}
    stable = {
        "capability": str(capability_slug or failure.get("capability_slug") or
                          failure.get("capability") or ""),
        "owner": str(failure.get("owner") or "unknown"),
        "code": str(failure.get("code") or "execution_failed"),
        "message": " ".join(str(failure.get("message") or "").split())[:1200],
    }
    import hashlib
    import json
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
