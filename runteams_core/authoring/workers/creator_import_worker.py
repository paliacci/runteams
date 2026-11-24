"""Isolated preflight worker. Reads a ZIP, emits metadata, executes no author code."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from runteams_core.authoring.workers.creator_worker_process import apply_limits
apply_limits('inspect')

from runteams_core.authoring.creator_contracts import MAX_BYTES, CreatorContractError, canonical
from runteams_core.authoring.source.creator_source_import import inspect_source

try:
    value = inspect_source(sys.stdin.buffer.read(MAX_BYTES + 1024 * 1024 + 1))
except CreatorContractError as error:
    value = {'error': '源码包未通过检查，请修正后重新选择。', 'code': error.code}
except Exception:
    # Keep unexpected packaging failures diagnosable in the private worker's
    # stderr; the public response remains bounded and never exposes internals.
    import traceback
    traceback.print_exc(file=sys.stderr)
    value = {'error': '源码包无法读取，请检查文件格式。', 'code': 'invalid_source_package'}
body = canonical(value)
if len(body) > MAX_BYTES:
    body = canonical({'error': '源码检查结果超过大小限制。', 'code': 'artifact_limit'})
sys.stdout.buffer.write(body)
