"""Original pipeline-owned conversation binding, without constructing an MCP host."""
from runteams_core.storage import device_data
from runteams_core.pipelines import pipeline_references

def reference(chat):
    from runteams_core.storage import product_store
    session = product_store.get_chat(chat, include_messages=False)
    if (not device_data.personal() or not product_store.device_chat(chat) or not session or
            session['kind'] != 'general' or session['subject_type'] != 'workspace' or
            'source_pipeline_workspace' not in session['context']):
        raise PermissionError('请打开这个智能体团队自己的会话。')
    return pipeline_references.checked_reference(session['context']['source_pipeline_workspace'])


def directory_rows(rows):
    """Include standalone discussions under their owner and leave dock chats on the board."""
    from runteams_core.conversations.page_paths import chat_owner_paths
    from runteams_core.pipelines.source_pipeline_trash import hidden_source_references

    visible, discussions = [], []
    hidden = None
    for row in rows:
        context = row['context']
        if context.get('source_pipeline_workspace'):
            if not context.get('source_pipeline_discussion') or row['kind'] != 'general' or row['subject_type'] != 'workspace':
                continue
            try:
                owner = pipeline_references.checked_reference(context['source_pipeline_workspace'])
            except (ValueError, PermissionError):
                continue
            if hidden is None:
                hidden = hidden_source_references()
            if owner in hidden:
                continue
            discussions.append(row)
        visible.append(row)
    if discussions:
        paths = chat_owner_paths(row['context'] for row in discussions)
        for row, path in zip(discussions, paths, strict=True):
            row['owner_path'] = path
    return visible

