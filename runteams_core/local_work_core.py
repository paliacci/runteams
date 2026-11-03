"""One genuine library work core, composed from the original shared mechanisms."""
import threading
from .local_documents import LocalDocuments
from .work_ledger import WorkLedger
from .source_work_service import SourceWorkService
from .contracts import ContractError

from .work_parameters import WorkParameters

class LocalWorkCore(SourceWorkService,WorkParameters,WorkLedger,LocalDocuments):
    def __init__(self,**options):
        super().__init__()
        self._cancel_events={};self._cancel_lock=threading.Lock()
        self.channel_resolver=options.get('channel_resolver')
        self.native_dependency_resolver=options.get('native_dependency_resolver')
        from .business_storage import bind_storage
        bind_storage(self.root/'runteams.db',self.repository.storage)

    def _workflow_claim_filter(self):
        from .source_pipeline_control import claim_filter
        return ("t.pipeline_id IS NULL AND json_extract(wr.snapshot_json,'$.schema')='runteams.employee-chat-work/v1' "
                "AND NOT EXISTS(SELECT 1 FROM device_work_restore_barriers b WHERE b.workflow_run_id=wr.id) AND "+claim_filter())

    def recover_interrupted_workflows(self):
        return self.recover_source_workflows()

    def runtime(self,**options):
        from .work_assets import WorkAssets
        import product_store
        return WorkAssets(self.root,product_store.get_local_asset_grant)
