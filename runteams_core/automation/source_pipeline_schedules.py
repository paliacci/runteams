"""Local pipeline plans reuse employee schedule storage/protocol and R03 admission.

An occurrence durably owns the exact request before admission. Recovery retries
that request only; it never sends an employee turn or creates another occurrence.
"""
from runteams_core.pipelines import pipeline_references
from runteams_core.work import workflow_policy
import json
import threading
import uuid
from runteams_core.storage import device_data
from runteams_core.automation.automation_time import checked_device_schedule
from runteams_core.pipelines import source_pipeline_work as work, source_pipeline_control as control
from runteams_core.foundation.contracts import ContractError
from runteams_core.automation.device_employee_schedules import EmployeeSchedules, canonical, next_run, operation_id

DIRECTORY='pipeline-schedules'
_gate=threading.RLock()


class PipelineSchedules(EmployeeSchedules):
    directory=DIRECTORY
    api_path='/api/device/pipeline-schedules'

    def __init__(self,controller_factory):
        super().__init__(controller_factory)
        self._executing=set()

    def core(self):
        device_data.check(self.scope)
        return self.controller_factory().core

    def dispatch_ids(self):
        from runteams_core.automation.automation_dispatch import selected_schedule_ids
        device_data.check(self.scope)
        return selected_schedule_ids(self.directory, self.binding())

    def scoped_dispatch_enabled(self):
        return bool(self.dispatch_ids())

    def dispatch_selection(self, column):
        ids = self.dispatch_ids()
        if ids is None:
            return '', ()
        if not ids:
            return ' AND 0', ()
        return ' AND ' + column + ' IN (' + ','.join('?' for _ in ids) + ')', ids

    @staticmethod
    def workflow_outcome(core, identifier, state):
        if state in ('completed','failed','canceled','blocked'):
            return state,''
        try:
            core.repository.storage.assert_executable(identifier)
        except ContractError as error:
            return 'interrupted',str(error)
        # An admitted task awaiting a review must be opened in its own card.
        # The schedule's interrupted state also permits abandoning an occurrence.
        if state=='interrupted':
            return 'blocked',''
        return 'waiting',''

    def changed_workflow_outcomes(self, rows):
        # Only linked, recoverable records follow their original workflow.
        linked = [row for row in rows if row['status'] in ('failed','waiting','blocked') and row['workflow_id']]
        if not linked:
            return
        core = self.core()
        for start in range(0,len(linked),500):
            batch = linked[start:start+500]
            identifiers = [row['workflow_id'] for row in batch]
            placeholders = ','.join('?' for _ in identifiers)
            with core.repository.read_snapshot() as connection:
                states = dict(connection.execute(
                    f'SELECT id,state FROM workflow_runs WHERE id IN ({placeholders})',identifiers))
            for row in batch:
                identifier = row['workflow_id']
                if identifier in states and states[identifier]!=row['status']:
                    status,reason = self.workflow_outcome(core,identifier,states[identifier])
                    if status!=row['status']:
                        yield row,status,reason

    def record(self, connection, row):
        value = super().record(connection,row)
        for run,status,reason in self.changed_workflow_outcomes(value['runs']):
            run.update(status=status,reason=reason)
        return value

    def list_reference(self,reference):
        reference=pipeline_references.checked_reference(reference)
        core=self.core();saved=control.read(core,reference)
        unavailable=''
        try:
            if saved['bundle']:asset=saved['bundle']['asset']
            else:
                from runteams_core.pipelines.source_pipeline_settings import read
                asset=read(core,reference)['asset']
            positions=[{'key':p['key'],'name':p['name']} for p in asset['pipeline']['positions']]
        except (ValueError,ContractError,PermissionError):
            positions=[];unavailable='智能体团队资产暂不可用，请核对版本；已有计划和记录仍保留。'
        with self.connection() as c:
            rows=[] if c is None else [self.record(c,r) for r in c.execute(
                'SELECT * FROM schedules WHERE reference=? AND deleted=0 ORDER BY id DESC',(canonical(reference),))]
        return {'items':rows,'reference':reference,'skills':[], 'positions':positions,
            'start_column_key':workflow_policy.start_position(asset['pipeline']) if positions else None,'pipeline_status':saved['status'],'storage_scope':'device','unavailable':unavailable}

    def contract(self,reference,position):
        return control.dispatch_contract(self.core(),pipeline_references.checked_reference(reference),position)

    def validate_start_parameters(self, reference, position, parameters):
        from jsonschema import Draft202012Validator
        contract = self.contract(reference, position)
        error = next(Draft202012Validator(contract['input_schema']).iter_errors(parameters), None)
        if error:
            raise ContractError('工作输入不符合技能声明：' + error.message)

    def target_row(self, connection, data, reference):
        identifier = data['id']
        if identifier is None:
            if data['action'] != 'save' or data['expected_revision'] is not None:
                raise ContractError('请选择原自动化。')
            return None
        if type(identifier) is not int or identifier < 1:
            raise ContractError('请选择有效的自动化。')
        row = None if connection is None else connection.execute(
            'SELECT * FROM schedules WHERE id=? AND deleted=0', (identifier,)).fetchone()
        if (row is None or type(data['expected_revision']) is not int
                or row['revision'] != data['expected_revision'] or row['reference'] != canonical(reference)):
            raise ContractError('自动化已变化，请重新读取。')
        return row

    def prepare_edit(self, row, value, reference, operation):
        name, stored = self.patched_payload(row, value, 'start_column_key')
        payload = dict(stored)
        position = payload.pop('start_column_key')
        self.validate_start_parameters(reference, position, payload['parameters'])
        work._request({'operation_id': operation, 'reference': reference, 'title': name,
                       'payload': payload, 'start_column_key': position})
        return name, stored

    def command(self,data):
        if not isinstance(data,dict) or set(data)!={'operation_id','action','reference','id','expected_revision','value'}:
            raise ContractError('自动化操作内容无效。')
        operation_id(data['operation_id']);ref=pipeline_references.checked_reference(data['reference'])
        request=canonical(data);action=data['action']
        if action not in ('save','edit','reschedule','pause','resume','delete','run','resolve'):raise ContractError('自动化操作无效。')
        # This gate fences this domain's plan edits against its own admission;
        # no employee scheduling lock is held across building/admitting work.
        with _gate:
            with self.connection() as c:
                prior=None if c is None else c.execute('SELECT * FROM commands WHERE id=?',(data['operation_id'],)).fetchone()
                if prior is None and action == 'edit':
                    original = self.target_row(c, data, ref)
            if prior:
                if prior['request']!=request or json.loads(prior['result']).get('abandoned'):raise ContractError('原操作内容已变化或取消。')
                return json.loads(prior['result'])
            value=data['value'];payload=None;following=''
            if action=='save':
                keys={'name','objective','enabled','schedule_kind','interval_sec','schedule','start_column_key','parameters'}
                if (not isinstance(value,dict) or set(value)!=keys or type(value['enabled']) is not bool
                    or not isinstance(value['name'],str) or not value['name'].strip() or len(value['name'])>120
                    or not isinstance(value['objective'],str) or not value['objective'].strip() or len(value['objective'])>20000):raise ContractError('请填写名称和要完成的工作。')
                kind,interval,schedule=checked_device_schedule(value)
                self.validate_start_parameters(ref, value['start_column_key'], value['parameters'])
                payload={'schema':'runteams.task-input/v2','objective':value['objective'],
                    'parameters':value['parameters'],'context':{},'inputs':[],'module_bindings':{},'asset_bindings':{}}
                work._request({'operation_id':data['operation_id'],'reference':ref,'title':value['name'],'payload':payload,'start_column_key':value['start_column_key']})
                following=next_run(kind,interval,schedule) if value['enabled'] else ''
            elif action == 'edit':
                # Read the referenced source/schema outside the device write transaction.
                edited = self.prepare_edit(original, value, ref, data['operation_id'])
            elif action != 'reschedule' and value is not None:raise ContractError('请选择原自动化。')
            core=self.core()
            with self.connection(write=True) as c:
                # Abandon can commit while contract validation runs.
                prior=c.execute('SELECT * FROM commands WHERE id=?',(data['operation_id'],)).fetchone()
                if prior:
                    if prior['request']!=request or json.loads(prior['result']).get('abandoned'):raise ContractError('原操作内容已变化或取消。')
                    return json.loads(prior['result'])
                identifier=data['id']
                row = self.target_row(c, data, ref)
                if action=='save':
                    stored={**payload,'start_column_key':value['start_column_key']}
                    values=(0,canonical(ref),'',value['name'].strip(),canonical(stored),int(value['enabled']),kind,interval,canonical(schedule),following)
                    if row is None:identifier=c.execute('INSERT INTO schedules(revision,employee_id,reference,release_digest,name,payload,enabled,schedule_kind,interval_sec,schedule,next_run_at) VALUES(0,?,?,?,?,?,?,?,?,?,?)',values).lastrowid
                    else:
                        c.execute('UPDATE schedules SET revision=revision+1,employee_id=?,reference=?,release_digest=?,name=?,payload=?,enabled=?,schedule_kind=?,interval_sec=?,schedule=?,next_run_at=? WHERE id=?',(*values,identifier))
                        self.cancel_rows(c,identifier)
                elif action=='edit':
                    self.save_payload_edit(c, identifier, *edited)
                elif action=='reschedule':
                    self.reschedule(c,row,value)
                elif action=='run':
                    if control.read(core,ref)['status']!='running':raise ContractError('智能体团队已暂停，不能开始新工作。')
                    self.fire(c,row,'manual:'+data['operation_id'])
                elif action=='resolve':
                    c.execute("UPDATE occurrences SET status='cancelled',reason='用户核对后结束本次记录，原工作未重做。' WHERE schedule_id=? AND status='interrupted'",(identifier,))
                else:
                    enabled=action=='resume'
                    following=next_run(row['schedule_kind'],row['interval_sec'],json.loads(row['schedule'])) if enabled else ''
                    c.execute('UPDATE schedules SET revision=revision+1,enabled=?,deleted=?,next_run_at=? WHERE id=?',(int(enabled),int(action=='delete'),following,identifier))
                    if not enabled:self.cancel_rows(c,identifier)
                result={'id':identifier,'operation_id':data['operation_id']}
                c.execute('INSERT INTO commands VALUES(?,?,?)',(data['operation_id'],request,canonical(result)))
                return result

    def cancel_rows(self,c,identifier):
        for row in c.execute("SELECT * FROM occurrences WHERE schedule_id=? AND status IN ('queued','running','blocked')",(identifier,)).fetchall():
            admitted=self._receipt(self.core(),json.loads(row['snapshot']))
            if admitted:c.execute("UPDATE occurrences SET status='waiting',workflow_id=? WHERE id=?",(admitted,row['id']))
            else:c.execute("UPDATE occurrences SET status='cancelled',reason='计划已暂停或更新，原触发未受理。' WHERE id=?",(row['id'],))

    def fire(self,c,row,scheduled):
        open_run=c.execute("SELECT 1 FROM occurrences WHERE schedule_id=? AND status IN ('queued','running','waiting','blocked','interrupted')",(row['id'],)).fetchone()
        failures=c.execute("SELECT status,workflow_id FROM occurrences WHERE schedule_id=? AND status='failed' AND workflow_id IS NOT NULL",(row['id'],))
        if open_run or any(status in ('waiting','blocked','interrupted') for _,status,_ in self.changed_workflow_outcomes(failures)):
            raise ContractError('这项自动化还有未完成或需要核对的运行。')
        op=str(uuid.uuid5(uuid.NAMESPACE_URL,canonical([self.binding(),row['id'],scheduled])))
        payload=json.loads(row['payload']);position=payload.pop('start_column_key')
        request={'operation_id':op,'reference':json.loads(row['reference']),'title':row['name'],'payload':payload,'start_column_key':position}
        c.execute("INSERT OR IGNORE INTO occurrences(schedule_id,scheduled_for,operation_id,status,snapshot) VALUES(?,?,?,'queued',?)",(row['id'],scheduled,op,canonical(request)))

    def materialize_due_automations(self,limit=20,has_open_work=None):
        from runteams_core.automation import automation_time, single_occurrence
        with _gate:
            selection,ids=self.dispatch_selection('id')
            params = (automation_time.now(), *ids, min(20,limit))
            with self.connection() as c:
                if c is None:return
                statement = single_occurrence.due_query(c, selection)
                if c.execute(statement,params).fetchone() is None:return
            core=self.core()
            with self.connection(write=True) as c:
                statement = single_occurrence.due_query(c, selection)
                for row in c.execute(statement,params).fetchall():
                    if not self.dispatch_allowed(row['id']):
                        continue
                    try:
                        if control.read(core,json.loads(row['reference']))['status']!='running':raise ContractError('智能体团队已暂停，本次未创建工作。')
                        self.fire(c,row,row['due_at'])
                    except ContractError as exc:
                        c.execute("INSERT OR IGNORE INTO occurrences(schedule_id,scheduled_for,operation_id,status,snapshot,reason) VALUES(?,?,?,'skipped',?,?)",(row['id'],row['due_at'],str(uuid.uuid4()),canonical(dict(row)),str(exc)))
                    single_occurrence.consume(c, row, single_occurrence.instant(params[0]))

    def claim_next_automation_run(self):
        with _gate:
            selection,ids=self.dispatch_selection('schedule_id')
            with self.connection() as c:
                rows=[] if c is None else c.execute(
                    "SELECT * FROM occurrences WHERE status='queued'"+selection+" ORDER BY id",ids).fetchall()
            if not rows:return
            core=self.core()
            for row in rows:
                ref=json.loads(row['snapshot'])['reference']
                if control.read(core,ref)['status']!='running':continue
                allowed = self.dispatch_ids()
                if allowed is not None and row['schedule_id'] not in allowed:continue
                with self.connection(write=True) as c:
                    if c.execute("UPDATE occurrences SET status='running' WHERE id=? AND status='queued'",(row['id'],)).rowcount:
                        return {**dict(row),'automation_id':row['schedule_id']}

    def _receipt(self,core,request):
        key,body=work._request(request)
        return work._receipt(core,key,body)

    def execute(self,job,cancel_event=None):
        with _gate:
            ids=self.dispatch_ids()
            if ids is not None and job['schedule_id'] not in ids:return
            core=self.core();request=json.loads(job['snapshot'])
            self._executing.add(job['id'])
            try:
                identifier=self._receipt(core,request)
                with self.connection() as c:row=c.execute('SELECT status FROM occurrences WHERE id=?',(job['id'],)).fetchone()
                if row is None or row['status'] not in ('queued','running','waiting'):return
                if identifier is None:
                    if cancel_event is not None and cancel_event.is_set():
                        self.finish_automation_run(job['id'],'cancelled','本次触发已停止。');return
                    if control.read(core,request['reference'])['status']!='running':
                        self.finish_automation_run(job['id'],'queued','智能体团队已暂停，等待启动。');return
                    try:
                        result = work.create(core, request, schedule_origin={
                            'schedule_id': job['schedule_id'], 'operation_id': job['operation_id'],
                        })
                        identifier = result['workflow']['id']
                    except work.WorkAdmissionUnknown:
                        identifier=self._receipt(core,request)
                        if identifier is None:
                            self.finish_automation_run(job['id'],'queued','沿原编号核对受理。');return
                with self.connection(write=True) as c:c.execute("UPDATE occurrences SET status='waiting',workflow_id=?,reason='' WHERE id=?",(identifier,job['id']))
                self.controller_factory().wake()
            except (ContractError,PermissionError) as exc:
                state='queued' if control.read(core,request['reference'])['status']!='running' else 'blocked'
                self.finish_automation_run(job['id'],state,str(exc))
            finally:self._executing.discard(job['id'])

    def reconcile(self):
        with _gate:
            if self.dispatch_ids() == ():return
            selection,ids=self.dispatch_selection('schedule_id')
            with self.connection() as c:
                if c is None:return False
                rows=[dict(r) for r in c.execute("SELECT * FROM occurrences WHERE status IN ('running','waiting','blocked','interrupted')"+selection,ids)]
                failures=c.execute("SELECT id,status,workflow_id,reason,chat_id FROM occurrences WHERE status='failed' AND workflow_id IS NOT NULL"+selection,ids).fetchall()
            tracking=False
            for row,status,reason in self.changed_workflow_outcomes(failures):
                self.record_outcome(row,status,row['workflow_id'],reason)
                tracking |= status in ('waiting','blocked','interrupted')
            if not rows:return tracking
            core=self.core()
            for row in rows:
                if row['id'] in self._executing:continue
                request=json.loads(row['snapshot']);identifier=row['workflow_id'] or self._receipt(core,request)
                current=core.workflow(identifier) if identifier else None
                if current:
                    status,reason=self.workflow_outcome(core,identifier,current['state'])
                else:
                    status='interrupted' if identifier else row['status'] if row['status'] in ('blocked','interrupted') else 'queued'
                    reason='原工作已不可读取，请核对工作记录。' if identifier else row['reason'] if status in ('blocked','interrupted') else '沿原编号等待受理。'
                self.record_outcome(row,status,identifier,reason)
                tracking |= identifier is not None and status in ('waiting','blocked','interrupted')
            return tracking

    def finish_automation_run(self,identifier,status,reason=''):
        with self.connection() as c:row=None if c is None else c.execute('SELECT * FROM occurrences WHERE id=?',(identifier,)).fetchone()
        if row is None:return
        request=json.loads(row['snapshot']);core=self.core();admitted=row['workflow_id'] or self._receipt(core,request)
        if admitted:status,reason='waiting',''
        elif status=='failed' and control.read(core,request['reference'])['status']!='running':status,reason='queued','智能体团队已暂停，等待启动。'
        with self.connection(write=True) as c:c.execute("UPDATE occurrences SET status=?,workflow_id=?,reason=? WHERE id=? AND status NOT IN ('cancelled','canceled')",(status,admitted,str(reason)[:1000],identifier))


def verify(directory,scope):
    from runteams_core.automation.device_employee_schedules import verify as shared
    shared(directory,scope,schedule_directory=DIRECTORY,pipeline=True)

def snapshot(source,destination,scope,check):
    from runteams_core.automation.device_employee_schedules import snapshot as shared
    shared(source,destination,scope,check,schedule_directory=DIRECTORY,pipeline=True)

def quarantine_restored(directory):
    from runteams_core.automation.device_employee_schedules import quarantine_restored as shared
    shared(directory,schedule_directory=DIRECTORY)
