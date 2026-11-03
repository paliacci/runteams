"""Original pipeline-owned conversation binding, without constructing an MCP host."""
from . import device_data,pipeline_references

def reference(chat):
    import product_store
    session = product_store.get_chat(chat, include_messages=False)
    if (not device_data.personal() or not product_store.device_chat(chat) or not session or
            session['kind'] != 'general' or session['subject_type'] != 'workspace' or
            'source_pipeline_workspace' not in session['context']):
        raise PermissionError('请打开这条流水线自己的会话。')
    return pipeline_references.checked_reference(session['context']['source_pipeline_workspace'])

