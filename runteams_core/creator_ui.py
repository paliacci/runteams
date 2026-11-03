"""Generic frozen UI framing; references identify records, never grant access."""
import hashlib
from .creator_contracts import CreatorContractError, contract
from .creator_sdk import bounded_json

METHODS = frozenset(('context.read','context.update','context.select','draft.set','draft.discard'))


def execution_key(context_id, original_key):
    from .resource_ids import resource_id
    return 'ui:'+resource_id(context_id)+':'+original_key


def ui_json(value, limit=20000):
    bounded_json(value, limit=limit)
    def walk(v, depth=0):
        if depth > 16: raise CreatorContractError('ui_message_budget')
        if isinstance(v,dict):
            for child in v.values(): walk(child,depth+1)
        elif isinstance(v,list):
            for child in v: walk(child,depth+1)
    walk(value)
    return value


def ui_request(frame):
    ui_json(frame)
    return contract('request.schema.json',frame,'ui-v2')


def object_ref(type_name, object_id, revision):
    if type(revision) is not int or not 1 <= revision <= 9007199254740991:
        raise CreatorContractError('ui_revision_unrepresentable')
    return {'type':type_name,'id':'o'+hashlib.sha256(object_id.encode()).hexdigest()[:62],'revision':revision}
