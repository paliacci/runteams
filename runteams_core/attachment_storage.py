"""Local attachment persistence checks; parsing and layout stay in chat_attachments."""
from contextlib import contextmanager
import os


class LocalAttachmentStorage:
    @staticmethod
    def _require_device(chat_id):
        from runteams_core import product_store
        if not product_store.device_chat(chat_id):
            raise PermissionError('附件必须属于当前本机对话。')

    @contextmanager
    def scope(self, chat_id):
        self._require_device(chat_id)
        from . import device_data
        scope = device_data.identity()
        with device_data.connect():
            yield
            device_data.check(scope)

    def save(self, chat_id, items):
        self._require_device(chat_id)
        return items

    def restore(self, chat_id, item):
        self._require_device(chat_id)
        from runteams_core.chat_attachments import _contained_path
        folder=item.get('kind')=='folder'
        path = _contained_path(chat_id, item.get('stored_name') or '', require_file=not folder)
        if not (os.path.isdir(path) if folder else os.path.isfile(path)):
            raise ValueError('本机附件不存在，请从备份恢复或重新添加。')
