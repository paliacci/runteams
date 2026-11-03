"""Bounded keyset cursors for read-only lists, never access or payment tokens."""
import base64
import hashlib
import json


class CursorError(ValueError):
    pass


def scope_key(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def cursor_for(scope, after):
    return base64.urlsafe_b64encode(json.dumps({'v':1,'scope':scope,'after':after}, separators=(',', ':')).encode()).decode().rstrip('=')


def cursor_after(token, scope):
    if not token:
        return None
    try:
        if not isinstance(token, str) or len(token) > 2048:
            raise ValueError()
        value = json.loads(base64.b64decode(token + '='*(-len(token)%4), altchars=b'-_', validate=True))
        if value['v'] != 1 or value['scope'] != scope or not isinstance(value['after'], list):
            raise ValueError()
        return value['after']
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise CursorError('分页已失效，请从第一页重新载入。') from None


def page_size(value, maximum=100):
    if isinstance(value, bool):
        raise ValueError('分页数量无效。')
    number = int(value)
    if not 1 <= number <= maximum:
        raise ValueError('分页数量无效。')
    return number
