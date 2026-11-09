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


_SYSTEM_TEXT = {
    'save_unknown': ('回复的保存状态需要核对，请勿重复发送。', 'The reply save status needs checking. Do not send it again.'),
    'stop_save_unknown': ('停止后的保存状态需要核对，请勿重复发送。', 'Check the saved reply after stopping. Do not send it again.'),
    'processing_unknown': ('处理状态需要核对，请勿重复发送。', 'The processing status needs checking. Do not send it again.'),
    'stopped': ('运行已停止', 'Execution stopped'),
    'reply_stopped': ('回复已停止。', 'Reply stopped.'),
    'interrupted': ('消息已保存，上次处理已中断。', 'Message saved. The previous execution was interrupted.'),
    'failed': ('模型未能完成回复，请检查渠道后重试。', 'The model could not finish the reply. Check the channel and try again.'),
    'save_failed': ('回复保存失败，请重新打开对话确认。', 'The reply could not be saved. Reopen the conversation to check.'),
    'unconfirmed': ('工作回复尚未确认，请查看原对话。', 'The work reply has not been confirmed. Check the original conversation.'),
    'check_work': ('请查看原工作对话。', 'Check the original work conversation.'),
    'stall': ('员工已约 {minutes} 分钟无新动作', 'No new employee activity for about {minutes} minutes'),
    'still_running': ('仍在运行，可手动停止。', 'Still running. You can stop it manually.'),
    'timeout': ('Agent 超时 {seconds}s', 'Agent timed out after {seconds}s'),
    'authorization_required': ('本次工作尚未获得运行授权。', 'This work requires execution approval.'),
    'approval_stopped': ('工作已停止。', 'Work stopped.'),
    'approval_expired': ('本次确认已失效。', 'This approval request has expired.'),
    'authorization_revoked': ('本次工作未获授权或授权已撤销。', 'This work was not approved or its approval was revoked.'),
}


def system_text(key, policy=None, **values):
    """Only application-owned text; never translate tool output or diagnostics."""
    return _SYSTEM_TEXT[key][snapshot(policy)['communication_language'] == 'en'].format(**values)
