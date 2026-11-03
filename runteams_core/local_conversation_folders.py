"""Library-host composition of the shared working-folder authorization flow."""
import os


def dispatch(runtime, method, path, data):
    from . import conversation_folders as folders, device_data
    from .local_runtime import RuntimeBusy
    scope = device_data.identity()
    if scope.get('library_id') != runtime.app.binding.library_id:
        raise PermissionError('本机资料库已变化，请重新打开。')
    if not isinstance(data, dict) or data.keys() - {'chat_id', 'selection_id'}:
        raise ValueError('工作文件夹请求无效。')
    chat_id = data.get('chat_id')
    if chat_id not in (None, '', 'new'):
        if not str(chat_id).isdigit():
            raise ValueError('对话编号无效。')
        chat_id = int(chat_id)
        runtime.chat(chat_id, include_live=False)
    if method == 'GET' and path == '/api/work-folders':
        if 'selection_id' in data:
            raise ValueError('工作文件夹读取参数无效。')
        return {'folder': folders.read(chat_id, expected=scope)}
    if method != 'POST':
        raise KeyError('工作文件夹入口不存在。')
    if path == '/api/work-folders/pick':
        if 'selection_id' in data:
            raise ValueError('文件夹选择请求无效。')
        if not os.environ.get('RUNTEAMS_ATTACHMENT_PICKER'):
            raise ValueError('请在本机桌面版选择工作文件夹。')
        with runtime.lock:
            if runtime.closing or chat_id in runtime.active:
                raise RuntimeBusy('请先结束当前回复或文件夹选择。')
            if not runtime.picker_lock.acquire(blocking=False):
                raise RuntimeBusy('已有资料选择窗口。')
        try:
            return folders.pick(chat_id, expected=scope, cancel_event=runtime.picker_cancel)
        finally:
            runtime.picker_lock.release()
    with runtime.lock:
        if runtime.closing or chat_id in runtime.active:
            raise RuntimeBusy('请先结束当前回复。')
        selection_id = data.get('selection_id')
        if not isinstance(selection_id, str) or not selection_id:
            raise ValueError('工作文件夹授权无效。')
        if path == '/api/work-folders/bind':
            return {'folder': folders.bind(chat_id, selection_id, expected=scope)}
        if path == '/api/work-folders/clear':
            return folders.clear(chat_id, selection_id, expected=scope)
        if path == '/api/work-folders/open':
            return folders.open_folder(chat_id, selection_id, expected=scope)
    raise KeyError('工作文件夹入口不存在。')
