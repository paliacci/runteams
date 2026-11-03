"""Original SDK work dispatch/projections shared by account and library hosts."""
import json
from runteams_core.foundation.contracts import ContractError

class SourceWorkService:
    def page_ids(self):
        """Public work identities grant no asset or platform access."""
        with self.repository.connect() as c:
            workflows = [row[0] for row in c.execute('SELECT id FROM workflow_runs')]
            artifacts = [row[0] for row in c.execute('SELECT id FROM artifacts')]
            items = [{'resource': public, 'id': str(identifier),
                      'public_id': self.repository.storage.public_id(table, identifier)}
                for public, table, values in [('workflows', 'workflow_runs', workflows), ('artifacts', 'artifacts', artifacts)]
                for identifier in values]
            # Document links use the same durable artifact identity, including
            # historical revisions. Registration is never an access grant.
            items.extend({'resource': 'documents', 'id': str(row['id']),
                          'public_id': self.repository.storage.public_id('artifacts', row['id'])}
                         for row in c.execute('SELECT id,name,meta_json FROM artifacts').fetchall()
                         if self.is_document_artifact(self._decode_meta(row['meta_json']), row['name']))
        return items


    def execute_claimed_workflow(self, workflow_run_id, runtime, max_attempts=3, retry_delay_sec=5):
        from runteams_core.employees.employee_chat_work import snapshot, execute
        frozen=snapshot(self,workflow_run_id)
        if frozen is not None:return execute(self,workflow_run_id,frozen,runtime)
        return super().execute_claimed_workflow(workflow_run_id,runtime,max_attempts,retry_delay_sec)


    def recover_interrupted_workflow(self, workflow_run_id):
        from runteams_core.employees.employee_chat_work import snapshot, finish
        frozen=snapshot(self,workflow_run_id)
        if frozen is not None:
            if frozen.get('pipeline_work'):
                from runteams_core.pipelines.source_pipeline_flow import recover
                return recover(self,workflow_run_id)
            else:finish(self,workflow_run_id,'interrupted','原工作结果需要核对，不会自动重发。')
            return True
        return super().recover_interrupted_workflow(workflow_run_id)


    def workflow(self,workflow_run_id):
        from runteams_core.employees.employee_chat_work import snapshot, detail
        if snapshot(self,workflow_run_id) is not None:return detail(self,workflow_run_id)
        return super().workflow(workflow_run_id)


    def retry_workflow(self,workflow_run_id):
        from runteams_core.employees.employee_chat_work import snapshot
        frozen = snapshot(self,workflow_run_id)
        if frozen is not None:
            if frozen.get('pipeline_work'):
                from runteams_core.pipelines.source_pipeline_work import retry_before_send
                return retry_before_send(self,workflow_run_id)
            raise ContractError('请在原员工工作对话中核对结果后继续，不会重复发送原任务。')
        return super().retry_workflow(workflow_run_id)


    def respond_to_human(self,workflow_run_id,response,choice=None):
        from runteams_core.employees.employee_chat_work import snapshot
        if snapshot(self,workflow_run_id) is not None:
            raise ContractError('请在原员工工作对话中回答问题。')
        return super().respond_to_human(workflow_run_id,response,choice)


    def _document_employee_owner(self):
        from runteams_core.documents.document_ownership import current_document_owner
        return current_document_owner()


    def _document_owner_names(self,connection,owner_ids):
        # Frozen work identity is display metadata, never a current asset grant.
        if not owner_ids:return {}
        placeholders=','.join('?' for _ in owner_ids)
        names={}
        for row in connection.execute('SELECT employee_id,snapshot_json FROM employee_releases '
                f'WHERE employee_id IN ({placeholders}) ORDER BY id DESC',list(owner_ids)):
            names.setdefault(int(row['employee_id']),json.loads(row['snapshot_json'])['employee']['name'])
        return names


    def _document_position_employee(self,position):
        frozen=position.get('employee') or {}
        return frozen.get('employee') if isinstance(frozen.get('employee'),dict) else frozen


    def _revision_was_handed_off(self,connection,artifact):
        # Inputs store portable device refs; rows expose resolved file paths.
        # Compare the same identity so an already consumed human revision is
        # never overwritten or unlinked by the next autosave.
        if not artifact['employee_run_id']:return False
        refs={str(artifact['ref']),self.repository.storage.canonical_data(artifact['ref'])}
        for row in connection.execute('SELECT input_json FROM employee_runs WHERE workflow_run_id=('
                'SELECT workflow_run_id FROM employee_runs WHERE id=?)',(int(artifact['employee_run_id']),)):
            values=[json.loads(row['input_json'] or '{}')]
            while values:
                value=values.pop()
                if isinstance(value,dict):values.extend(value.values())
                elif isinstance(value,list):values.extend(value)
                elif isinstance(value,str) and any(ref in value for ref in refs):return True
        return False


    def recover_source_workflows(self):
        from runteams_core.employees.employee_chat_work import finish
        from runteams_core.employees.employee_work_contracts import SCHEMA
        with self.repository.connect() as connection:
            ids=[row['id'] for row in connection.execute("SELECT id FROM workflow_runs WHERE (state='running' OR json_extract(snapshot_json,'$.pipeline_execution.active')=1 OR json_extract(snapshot_json,'$.pipeline_recovery_pending')=1) AND json_extract(snapshot_json,'$.schema')=? AND (json_type(snapshot_json,'$.pipeline_work') IS NULL OR NOT EXISTS(SELECT 1 FROM device_work_restore_barriers b WHERE b.workflow_run_id=workflow_runs.id))",(SCHEMA,))]
        from runteams_core.pipelines.source_pipeline_flow import RecoveryPending
        for identifier in ids:
            try:self.recover_interrupted_workflow(identifier)
            except RecoveryPending:self.__dict__.setdefault('_pending_pipeline_recoveries',set()).add(identifier)
            except (ContractError,RuntimeError) as error:
                from runteams_core.employees.employee_chat_work import snapshot
                current=snapshot(self,identifier)
                if not current or not current.get('pipeline_submission'):raise
                from runteams_core.pipelines.source_pipeline_flow import defer_settlement
                defer_settlement(self,identifier,current['pipeline_visit'],error)
        return ids


    def claim_workflow(self,workflow_run_id=None):
        # Only known pending pipeline settlements use this retry. An ordinary
        # employee queue has no extra scan, program call, or model retry.
        self._actor()
        pending=self.__dict__.get('_pending_pipeline_recoveries',set())
        if pending:
            import time
            from runteams_core.pipelines.source_pipeline_flow import recover, RecoveryPending
            if time.monotonic()>=getattr(self,'_next_pipeline_recovery_at',0):
                self._next_pipeline_recovery_at=time.monotonic()+5
                ordered=sorted(pending)
                if not ordered:return super().claim_workflow(workflow_run_id)
                offset=getattr(self,'_pipeline_recovery_cursor',0)%len(ordered)
                self._pipeline_recovery_cursor=offset+1
                for identifier in ordered[offset:offset+1]:
                    with self.repository.connect() as connection:
                        row=connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?',(identifier,)).fetchone()
                    frozen=json.loads(row[0]) if row else {}
                    if not frozen.get('pipeline_recovery_pending'):pending.discard(identifier);continue
                    if (frozen.get('pipeline_execution') or {}).get('active'):continue
                    try:recover(self,identifier)
                    except (ContractError,RuntimeError):continue
        return super().claim_workflow(workflow_run_id)

