"""Shared local interaction settings validation, independent of accounts."""
import json


def validate(value):
    if len(json.dumps(value).encode()) > 65536:
        raise ValueError('设置格式无效。')
    decoded = value
    allowed = {"send_mode", "allow_supplement", "notification_timing", "confirmation",
               "information", "failure", "completion", "sound", "default_model", "default_effort"}
    if not isinstance(decoded, dict) or set(decoded) - allowed:
        raise ValueError('设置格式无效。')
    if decoded.get("send_mode", "enter") not in ("enter", "meta-enter") or decoded.get("notification_timing", "background") not in ("always", "background", "never"):
        raise ValueError('设置选项无效。')
    for field in ("allow_supplement", "confirmation", "information", "failure", "completion", "sound"):
        if field in decoded and not isinstance(decoded[field], bool):
            raise ValueError('设置选项无效。')
    for field in ("default_model", "default_effort"):
        if field in decoded and (not isinstance(decoded[field], str) or len(decoded[field]) > 256):
            raise ValueError('设置选项无效。')
