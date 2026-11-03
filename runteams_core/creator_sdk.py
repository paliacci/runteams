"""Frozen SDK framing checks shared by the trusted host and cloud adapter."""
import math
from .creator_contracts import CreatorContractError, canonical, contract


def bounded_json(value, *, limit=16384):
    count = 0
    def walk(item, depth=0):
        nonlocal count
        count += 1
        if count > 4096 or depth > 32:
            raise CreatorContractError('sdk_frame_limit')
        if item is None or type(item) in (str, bool): return
        if type(item) in (int, float):
            if ((type(item) is int and abs(item) > 9007199254740991)
                    or (type(item) is float and (not math.isfinite(item)
                        or item.is_integer() and abs(item) > 9007199254740991))):
                raise CreatorContractError('sdk_invalid_json')
            return
        if isinstance(item, list):
            for child in item: walk(child, depth+1)
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or key in ('__proto__', 'prototype', 'constructor'):
                    raise CreatorContractError('sdk_invalid_json')
                walk(child, depth+1)
        else:
            raise CreatorContractError('sdk_invalid_json')
    walk(value)
    if len(canonical(value)) > limit:
        raise CreatorContractError('sdk_frame_limit')
    return value


def sdk_frame(value, *, reply=False):
    bounded_json(value)
    if not isinstance(value, dict) or type(value.get('id')) is not int:
        raise CreatorContractError('sdk_invalid_sequence')
    return contract('reply.schema.json' if reply else 'request.schema.json', value)
