"""Frozen communication language, separate from authored asset and output contracts."""
import json


def snapshot(value=None):
    if value is None:
        from runteams_core.storage import device_data
        with device_data.connect(readonly=True) as connection:
            row = connection.execute("SELECT value FROM device_settings WHERE key='language_policy'").fetchone()
        value = json.loads(row['value']) if row else {'communication_language': 'zh-CN'}
    if not isinstance(value, dict) or set(value) != {'communication_language'} or value['communication_language'] not in ('en', 'zh-CN'):
        raise ValueError('Invalid communication language.')
    return dict(value)


def save(value):
    policy = snapshot(value)
    from runteams_core.storage import device_data
    with device_data.connect() as connection:
        connection.execute("INSERT INTO device_settings(key,value) VALUES('language_policy',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(policy),))
    return policy


def guidance(policy):
    language = 'English' if snapshot(policy)['communication_language'] == 'en' else 'Simplified Chinese'
    return ('# Communication language policy\n'
        f'Unless the user explicitly requests another communication language for this turn, use {language} for conversation, progress, explanations, report summaries, approval questions and notifications. '
        'For deliverable content, follow an explicit task language requirement first, then an explicit asset language requirement, otherwise use the communication language. '
        'A prompt being written in a language is not itself an explicit output-language requirement. '
        'Preserve the original meaning and constraints of employee prompts and skills; never rewrite their source. '
        'Keep code, identifiers, schema keys, enum values, quoted source text and required verbatim content unchanged. '
        'This language policy does not change permissions, task scope, output schemas or approval requirements.')
