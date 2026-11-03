"""Shared runteams.tool-result/v1 envelope for the project-runner tools."""

import json


def emit(tool_id, ok, summary, output="", code=None, artifacts=()):
    print(json.dumps({
        "schema": "runteams.tool-result/v1",
        "tool_id": tool_id,
        "execution": {"status": "completed", "exit_code": 0 if ok else 1},
        "evaluation": {"status": "passed" if ok else "failed",
                       "owner": "none" if ok else "task",
                       "code": code or ("passed" if ok else "failed"),
                       "summary": summary},
        "evidence": {"output": output[:4000], "artifacts": list(artifacts),
                     "truncated": len(output) > 4000},
    }, ensure_ascii=False))
    return 0 if ok else 1
