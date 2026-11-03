"""One document action contract for conversations in either edition."""
from .contracts import ContractError


def apply_document_action(core, action):
    with core.repository.definition_lock():
        op = action['op']
        if op not in ('create_document','update_document'):
            raise ContractError('不支持的文档动作。')
        identifier = action.get('document_id')
        current = None
        if op == 'update_document':
            if identifier not in (None, ''):
                current = core.document_detail(int(identifier))
            else:
                needle = str(action.get('document_key') or action.get('name') or '').strip()
                current = next((item for item in core.document_catalog(limit=500, query=needle)
                                if needle and needle in (item.get('document_key'),item.get('name'))), None)
            if not current:
                raise ContractError('找不到要更新的文档。')
            identifier = current['id']
            if 'base_revision' in action and action['base_revision'] != current['revision']:
                raise ContractError('文档已被更新，请重新读取后再修改。')
        if action.get('document') is not None:
            from . import rich_documents
            item = rich_documents.write(core, name=action.get('name') or (current or {}).get('name'),
                document=action['document'], document_id=identifier if current else None,
                document_key=action.get('document_key'), base_revision=action.get('base_revision',0),
                author='agent', note=action.get('note',''))
            if item.get('conflict'):
                raise ContractError(item['error'])
        elif current:
            item = core.update_agent_document(identifier, name=action.get('name'), content=action.get('content'),
                data_view=action.get('data_view'), note=action.get('note',''))
        else:
            item = core.create_agent_document(action.get('name'),action.get('content'),
                document_key=action.get('document_key'),data_view=action.get('data_view'),note=action.get('note',''))
        return ('创建' if op == 'create_document' else '更新')+'文档「'+item['name']+'」', {'document_id':item['id']}
