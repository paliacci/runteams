#!/usr/bin/env python3
"""Request a local product endpoint and record the evidence.

Only loopback HTTP(S) addresses (the product instance started inside the
workspace) and workspace files are allowed, so the tool can never be used to
reach outside services or the user's real running instance by accident.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _result import emit  # noqa: E402

TOOL = "http-probe"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def fetch(target, method, data, headers, timeout):
    if target.startswith("file:"):
        path = Path(target[len("file:"):]).resolve()
        if Path.cwd().resolve() not in path.parents:
            raise ValueError("file: 只能读取工作区内的文件")
        return 200, {}, path.read_bytes()
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("只允许访问本机地址（127.0.0.1 / localhost）")
    body = data.encode("utf-8") if data is not None else None
    request = urllib.request.Request(target, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(200000)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read(200000)


def main(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--method", default="GET")
    parser.add_argument("--data")
    parser.add_argument("--json", action="store_true", help="send --data as application/json")
    parser.add_argument("--expect-status", type=int)
    parser.add_argument("--contains", action="append", default=[])
    parser.add_argument("--out", help="save status, headers and body as evidence (workspace path)")
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args(arguments)
    headers = {"Content-Type": "application/json"} if args.json else {}
    try:
        status, response_headers, body = fetch(args.target, args.method.upper(), args.data,
                                               headers, args.timeout)
    except (ValueError, OSError, urllib.error.URLError) as exc:
        return emit(TOOL, False, "请求失败：{}".format(exc), code="request_failed")
    text = body.decode("utf-8", "replace")
    problems = []
    if args.expect_status is not None and status != args.expect_status:
        problems.append("状态码 {}，预期 {}".format(status, args.expect_status))
    elif args.expect_status is None and not 200 <= status < 300:
        problems.append("状态码 {}".format(status))
    problems += ["响应中没有「{}」".format(item) for item in args.contains if item not in text]
    artifacts = []
    if args.out:
        out = Path(args.out).resolve()
        if Path.cwd().resolve() not in out.parents:
            return emit(TOOL, False, "--out 必须位于工作区内", code="invalid_arguments")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"request": {"method": args.method.upper(), "target": args.target,
                                               "data": args.data},
                                   "status": status, "headers": response_headers,
                                   "body": text[:20000]}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        artifacts.append(os.path.relpath(out))
    summary = "{} {} → {}".format(args.method.upper(), args.target, status)
    if problems:
        return emit(TOOL, False, summary + "；" + "；".join(problems), output=text,
                    code="unexpected_response", artifacts=artifacts)
    return emit(TOOL, True, summary, output=text, artifacts=artifacts)


if __name__ == "__main__":
    raise SystemExit(main())
