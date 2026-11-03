"""Private isolated validator entry. No platform services or credential imports."""
import json
from pathlib import Path
import resource
import sys

resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))
# The trusted module lives next to this worker in source and frozen builds.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from runteams_core.creator_schema_validation import validate_payload
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
    print(json.dumps({'error': {'code': 'invalid_author_schema', 'detail': detail}}, ensure_ascii=False))
    raise SystemExit(1)
print(json.dumps({'valid': valid}))
