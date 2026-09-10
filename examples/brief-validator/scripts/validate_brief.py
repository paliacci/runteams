#!/usr/bin/env python3
"""Zero-dependency executable used by the first package vertical slice."""

import argparse
import json
import sys


def result(ok, message):
    return {
        "schema": "runteams.tool-result/v1",
        "tool_id": "validate-brief",
        "execution": {"status": "completed", "exit_code": 0 if ok else 1},
        "evaluation": {"status": "passed" if ok else "failed",
                       "owner": "none" if ok else "task",
                       "code": "passed" if ok else "invalid_brief",
                       "summary": message},
        "evidence": {"output": message, "artifacts": [], "truncated": False}
    }


def main(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?")
    args = parser.parse_args(arguments)
    if not args.path:
        print(json.dumps(result(False, "missing brief path")))
        return 1
    try:
        with open(args.path, encoding="utf-8") as handle:
            brief = json.load(handle)
        ok = bool(str(brief.get("objective") or "").strip() and
                  isinstance(brief.get("context"), dict))
        message = "brief is valid" if ok else "objective and context are required"
    except (OSError, ValueError, AttributeError) as exc:
        ok, message = False, str(exc)
    print(json.dumps(result(ok, message)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
