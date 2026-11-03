"""Process-local maintenance dispatch: explicit plans, scope and expiry only.

The ordinary global switch retains its meaning. A maintenance exception never
enables another backend, account, queued occurrence or saved plan implicitly.
"""
import hashlib
import json
import math
import os
import time


def selected_schedule_ids(backend, binding):
    if os.environ.get('RUNTEAMS_AUTOMATION_DISPATCH', '1') != '0':
        return None
    try:
        value = json.loads(os.environ.get('RUNTEAMS_AUTOMATION_SCOPE', ''))
        digest = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False,
            separators=(',', ':')).encode()).hexdigest()
        if (not isinstance(value, dict) or set(value) !=
                {'schema', 'backend', 'binding_sha256', 'schedule_ids', 'expires_at'} or
                value['schema'] != 'runteams.automation-dispatch-scope/1' or
                value['backend'] != backend or value['binding_sha256'] != digest):
            return ()
        ids, expiry = value['schedule_ids'], value['expires_at']
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 20 or
                any(type(i) is not int or i < 1 for i in ids) or len(set(ids)) != len(ids) or
                type(expiry) not in (int, float) or not math.isfinite(expiry) or
                not time.time() < expiry <= time.time() + 3600):
            return ()
        return tuple(ids)
    except (ValueError, TypeError, KeyError):
        return ()


def dispatch_enabled():
    """Process maintenance hold; does not change any saved plan or due time."""
    return os.environ.get('RUNTEAMS_AUTOMATION_DISPATCH','1')!='0'
