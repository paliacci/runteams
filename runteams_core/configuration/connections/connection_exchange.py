"""Original native prepare/HTTPS/settle algorithm with explicit host authority."""
from runteams_core.storage.storage_contracts import BusinessCloudUnknown
from runteams_core.authoring.creator_connection import ConnectionNotSent
from runteams_core.authoring.creator_contracts import CreatorContractError
from runteams_core.authoring.creator_sdk import sdk_frame


def exchange(frame,claim,expected,credential_scope,transport,settle):
    if not claim['send']:return sdk_frame(claim['reply'],reply=True)
    binding=claim['binding'];payload={'sequence':frame['id']}
    try:
        if binding!=expected or claim['params']!=frame['params']:raise CreatorContractError('credential_scope')
        with credential_scope(binding) as credential:
            response=transport.request_http(claim['descriptor'],claim['params'],credential,binding=binding)
        payload.update(state='confirmed',response=response)
    except (ConnectionNotSent,CreatorContractError):payload['state']='failed'
    except Exception:payload['state']='unknown'
    try:return sdk_frame(settle(payload),reply=True)
    except Exception as error:raise BusinessCloudUnknown(frame['params'].get('operation_key','connection')) from error
