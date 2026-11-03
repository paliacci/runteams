"""Original source-employee task reference grant selection."""
import local_references
def source_task_references(action, source, *, core=None):
    if 'local_reference_ids' in action:
        selected = action['local_reference_ids']
        if not isinstance(selected, list) or any(type(i) is not int or i < 1 for i in selected):
            raise ValueError('任务资料选择必须是引用标识数组')
        available = {r['grant_id']: r for r in
                     source.get('available_local_references', source.get('local_references') or [])}
        if any(i not in available for i in selected):
            raise ValueError('只能选择本次对话中用户提供的资料')
        chosen = [available[i] for i in dict.fromkeys(selected)]
        source = {**source, 'local_references': chosen, 'available_local_references': chosen}
    if not source.get('local_references') and not action.get('asset_bindings'):
        return {}, []
    from runteams_core.employee_binding import for_context
    bound=for_context(source)
    if action.get('op')=='create_employee_task' and bound and bound['package']:
        from runteams_core.source_employee_runtime import package_asset
        from runteams_core.creator_conversation_assets import extension
        units=[extension(bundle).get('work') for bundle in package_asset(bound['package'])['skill_bundles']]
        works=[unit for unit in units if unit]
        selected=next((unit for unit in works if unit.get('key')==action.get('skill_key')),None)
        if action.get('skill_key') and selected is None:
            # The package's stable skill key is the bundle package_key.
            bundles=package_asset(bound['package'])['skill_bundles']
            selected=next((extension(b).get('work') for b in bundles if b['package_key']==action['skill_key']),None)
            if selected is None:raise ValueError('所选工作不属于当前员工运行包。')
        slots=(selected or {}).get('assets') or []
        bindings,inputs=local_references.bind_task(action,slots,source)
        action['asset_bindings']=bindings
        return bindings,inputs
    raise ValueError('请在已绑定的源码员工对话中选择工作资料。')
