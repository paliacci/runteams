"""Read public pages using only the host's collector and managed Node binary."""
import json
import subprocess

from runteams_core.employees.mcp.employee_mcp import platform_runtime
from runteams_core.foundation.resources import root


def audit(arguments):
    website = arguments.get('website')
    limit = arguments.get('maxPages', 5)
    if (arguments.keys() - {'website', 'maxPages'} or not isinstance(website, str)
            or not 1 <= len(website.strip()) <= 2048 or '\x00' in website
            or type(limit) is not int or not 1 <= limit <= 10):
        raise ValueError('请提供公开网址，采样页数范围为 1 至 10。')
    script = root() / 'agent_skills/runteams-work-execution/public-site-audit/check.cjs'
    node, _ = platform_runtime().verify()
    try:
        result = subprocess.run([str(node), str(script), website.strip(), str(limit)],
                                stdin=subprocess.DEVNULL, capture_output=True, env={},
                                cwd=script.parent, timeout=38, check=False, text=True)
    except subprocess.TimeoutExpired as error:
        raise ValueError('公开网页采样超时。') from error
    if result.returncode:
        raise ValueError(result.stderr.strip()[:300] or '公开网页采样未能启动。')
    return json.loads(result.stdout)
