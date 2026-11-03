"""Project only declared user input from a stopped frozen pipeline handoff."""


def task_input_contract(frozen, position_key):
    """Only explicitly declared user fields of the current stopped handoff."""
    issue=frozen.get('pipeline_handoff') or {}
    if not issue.get('requires_user_input_or_authorization') or frozen.get('send_admitted'):
        return None
    from runteams_core.pipelines.source_pipeline_flow import declared
    asset=frozen['pipeline_work']['asset']
    position=next((p for p in asset['pipeline']['positions'] if p['key']==position_key),None)
    if not position or position['kind']!='employee':return None
    unit=declared(frozen['package'],position['skill_key'])
    schema=unit['input_schema'] if unit else {'type':'object'}
    keys={p['key'] for p in asset['pipeline'].get('parameters',[]) if p.get('source')=='user' and (not p.get('visible_to') or position_key in p['visible_to'])}
    properties={key:value for key,value in schema.get('properties',{}).items() if key in keys}
    if not properties:return None
    return {'input_schema':{'type':'object','properties':properties,'required':[key for key in schema.get('required',[]) if key in properties],'additionalProperties':False},
            'values':{key:value for key,value in frozen['pipeline_input'].get('parameters',{}).items() if key in properties}}
