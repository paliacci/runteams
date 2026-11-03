#!/usr/bin/env python3
"""Run the upstream CLI through the existing audited capability host.

The agent's macOS shell sandbox cannot launch Chromium. No browser action
semantics live here: arguments and results belong to Microsoft's CLI.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from prepare_runtime import owned, runtime_environment
from _result import emit


def main():
    arguments = sys.argv[1:]
    try:
        registry = json.loads(owned('.runteams/project-runner.json').read_text())
        record = (registry.get('runtimes') or {}).get('browser')
        if not isinstance(record, dict):
            raise ValueError('先调用 prepare-runtime browser')
        cli = owned(record['entry'])
        config = owned(record['config'])
        if not cli.is_file() or not config.is_file():
            raise ValueError('本任务官方浏览器运行环境已清理或不完整')
        if 'kill-all' in arguments:
            raise ValueError('kill-all 会扫描主机进程；本任务使用 close-all')
        # Keep upstream syntax while always using this task's configuration.
        filtered = []
        index = 0
        while index < len(arguments):
            arg = arguments[index]
            if arg == '--config' or arg.startswith('--config='):
                if arg == '--config':
                    index += 1
                    if index >= len(arguments):
                        raise ValueError('--config 缺少路径')
                    supplied = arguments[index]
                else:
                    supplied = arg.split('=', 1)[1]
                if owned(supplied) != config:
                    raise ValueError('只使用本任务浏览器配置')
            else:
                filtered.append(arg)
            index += 1
        if 'open' in filtered:
            filtered.append('--config=' + str(config))
        env = runtime_environment()
        env['PATH'] = str(cli.parent) + os.pathsep + env.get('PATH', '')
        result = subprocess.run([str(cli)] + filtered, cwd=Path.cwd(), env=env,
                                capture_output=True, text=True, timeout=210)
        evidence = owned('evidence/browser/cli-calls')
        evidence.mkdir(parents=True, exist_ok=True)
        path = evidence / (uuid.uuid4().hex + '.json')
        path.write_text(json.dumps({'arguments': filtered, 'exit_code': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr},
                                  ensure_ascii=False, indent=2), encoding='utf-8')
        return emit('browser-cli', result.returncode == 0,
                    '官方 CLI 完整调用记录：' + str(path.relative_to(Path.cwd())),
                    result.stdout + result.stderr)
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        return emit('browser-cli', False, str(exc), code='environment_unavailable')


if __name__ == '__main__':
    raise SystemExit(main())
