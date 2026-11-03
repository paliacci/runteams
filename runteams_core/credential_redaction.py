"""Canonical existing recursive credential redaction before persisted results/UI."""
def redact_text(value, credentials):
    text = str(value or "")
    for secret in sorted({str(item) for item in (credentials or {}).values() if str(item)},
                         key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def redact_value(value, credentials):
    if isinstance(value, dict):
        return {(redact_text(key, credentials) if isinstance(key, str) else key):
                redact_value(item, credentials) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item, credentials) for item in value]
    if isinstance(value, str):
        return redact_text(value, credentials)
    return value

