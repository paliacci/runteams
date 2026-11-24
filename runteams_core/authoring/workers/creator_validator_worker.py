"""Private isolated validator entry. No platform services or credential imports."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from runteams_core.authoring.workers.creator_worker_process import apply_limits
apply_limits('schema')

try:
    from runteams_core.authoring.creator_schema_validation import validate_payload
    from jsonschema.exceptions import SchemaError
except ImportError:
    print(json.dumps({'error': {'code': 'validator_unavailable'}}))
    raise SystemExit(70)

try:
    value = json.loads(sys.stdin.buffer.read(128 * 1024 + 1))
    valid = validate_payload(value)
except (SchemaError, ValueError, KeyError, TypeError, RecursionError) as error:
    path = '/'.join(str(p) for p in getattr(error, 'absolute_path', ()))
    reason = getattr(error, 'message', None) or str(error)
    detail = ((path + ': ' if path else '') + reason).encode('utf-8')[:600].decode('utf-8', errors='ignore')
    sys.stdout.buffer.write(json.dumps({'error': {'code': 'invalid_author_schema', 'detail': detail}}, ensure_ascii=False).encode('utf-8'))
    raise SystemExit(1)
print(json.dumps({'valid': valid}))
