"""Personal documents composed from the shared document service and work ledger."""
import json
from .document_service import Documents
from .repository import Repository
from .device_work import DeviceWorkStorage, database_path
from . import device_data


class LocalDocuments(Documents):
    def __init__(self):
        self.scope = device_data.identity()
        if self.scope.get('storage_kind') != 'local':
            raise PermissionError('请从本机资料库打开文档。')
        self.root = database_path().parent
        self.repository = Repository(database_path(), storage=DeviceWorkStorage())
        self.repository.initialize()

    def _actor(self):
        self.repository.storage.check_scope()
        actor = self.repository.current_audit_context().get('actor_id')
        if actor and actor != self.scope['library_id']:
            raise PermissionError('本机资料库已变化。')
        return self.scope['library_id']

    def _document_owner_names(self, connection, owner_ids):
        if any(owner_ids):
            raise ValueError('此入口只处理个人文档。')
        return {}

    def page_ids(self):
        with self.repository.connect() as c:
            rows = c.execute('SELECT id,name,meta_json FROM artifacts').fetchall()
        return [{'resource': resource, 'id': str(row['id']),
                 'public_id': self.repository.storage.public_id('artifacts', int(row['id']))}
                for row in rows if self.is_document_artifact(json.loads(row['meta_json']), row['name'])
                for resource in ('artifacts','documents')]

    def delete_trashed_document(self, artifact_id):
        from .device_work_retention import delete_document
        return delete_document(self, artifact_id)

    def purge_expired_documents(self, retention_days=30):
        from .device_work_retention import purge_documents
        if retention_days != 30:raise ValueError('本机垃圾箱保留30天。')
        return purge_documents(self)
