"""Device-owned SDK employee schedules. Never part of an employee asset.

Commands and occurrences have durable identities. Admission uses the existing
work transaction/event ledger; recovery only looks up that original admission.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from errors import Cancelled

from . import device_data
from .contracts import ContractError
from .definition_contracts import validate_definition, select_work_unit, validate_work_parameters

DIRECTORY = 'employee-schedules'
DATABASE = 'schedules.sqlite3'
_lock = threading.RLock()


class PreparationUnknown(ContractError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def next_run(kind, interval, schedule):
    now = datetime.now(timezone.utc)
    if kind == 'interval':
        return (now + timedelta(seconds=interval)).isoformat(timespec='seconds')
    zone = ZoneInfo(schedule['timezone'])
    local = now.astimezone(zone)
    hour, minute = map(int, schedule['time'].split(':'))
    for offset in range(9):
        date = local.date() + timedelta(days=offset)
        if kind == 'weekly' and date.weekday() not in schedule['weekdays']:
            continue
        candidate = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone).astimezone(timezone.utc)
        if candidate > now:
            return candidate.isoformat(timespec='seconds')
    raise ContractError('执行时间无效。')


def operation_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ContractError('操作编号无效。')
    return value


def employee(identifier, reference=None):
    if identifier == 0 and isinstance(reference,dict) and reference.get('schema') == 'runteams.local-employee-reference/1':
        from .source_employee_runtime import describe
        item = describe(reference)
        return {'runtime_source':item,'native_asset':{'employee_reference':reference},
                'active_release':{'digest':hashlib.sha256(canonical(item['asset']).encode()).hexdigest()}}
    from .employee_context import current
    return current().scheduled_employee(identifier,reference)


def record_id(reference):
    from .employee_references import checked_reference
    reference=checked_reference(reference)
    if reference['schema']=='runteams.local-employee-reference/1':return 0
    from .employee_context import current
    return current().schedule_record_id(reference)


class EmployeeSchedules:
    device_owned = True
    directory = DIRECTORY
    api_path = '/api/device/employee-schedules'

    def __init__(self, controller_factory, *, chat_execute=None, polisher=None):
        if not device_data.personal():
            raise PermissionError('请在个人工作区设置员工自动化。')
        self.scope = device_data.identity()
        self.path = device_data.root() / self.directory / DATABASE
        self.controller_factory = controller_factory
        self.chat_execute = chat_execute
        self.polisher = polisher
        self.recovering = True

    @contextmanager
    def connection(self, write=False):
        device_data.check(self.scope)
        if not device_data.personal():
            raise PermissionError('工作区已变化。')
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise ContractError('自动化数据路径无效。')
        with _lock, device_data.connect(readonly=not write):
            if not self.path.exists() and not write:
                yield None
                return
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            c = sqlite3.connect(self.path, timeout=10)
            c.row_factory = sqlite3.Row
            try:
                if not c.execute("SELECT 1 FROM sqlite_master WHERE name='binding'").fetchone():
                    if not write:
                        raise ContractError('自动化数据结构无效。')
                    c.executescript('''
                        CREATE TABLE binding(version INTEGER NOT NULL,scope TEXT NOT NULL);
                        CREATE TABLE schedules(id INTEGER PRIMARY KEY AUTOINCREMENT,revision INTEGER NOT NULL,
                          employee_id INTEGER NOT NULL,reference TEXT NOT NULL,release_digest TEXT NOT NULL,
                          name TEXT NOT NULL,payload TEXT NOT NULL,enabled INTEGER NOT NULL,
                          schedule_kind TEXT NOT NULL,interval_sec INTEGER NOT NULL,schedule TEXT NOT NULL,
                          next_run_at TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
                        CREATE TABLE occurrences(id INTEGER PRIMARY KEY AUTOINCREMENT,schedule_id INTEGER NOT NULL,
                          scheduled_for TEXT NOT NULL,operation_id TEXT NOT NULL UNIQUE,status TEXT NOT NULL,
                          snapshot TEXT NOT NULL,workflow_id INTEGER,chat_id INTEGER,reason TEXT NOT NULL DEFAULT '',
                          UNIQUE(schedule_id,scheduled_for));
                        CREATE TABLE commands(id TEXT PRIMARY KEY,request TEXT NOT NULL,result TEXT NOT NULL);
                        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id INTEGER,kind TEXT,content TEXT);
                    ''')
                    c.execute('INSERT INTO binding VALUES(1,?)', (canonical(self.binding()),))
                    c.commit()
                    self.path.chmod(0o600)
                row = c.execute('SELECT * FROM binding').fetchone()
                if row is None or row['version'] != 1 or json.loads(row['scope']) != self.binding():
                    raise PermissionError('自动化不属于当前账户或部署。')
                if write:
                    c.execute('BEGIN IMMEDIATE')
                    c.execute('CREATE TABLE IF NOT EXISTS preparations(id TEXT PRIMARY KEY,request TEXT NOT NULL,state TEXT NOT NULL,result TEXT NOT NULL)')
                yield c
                device_data.check(self.scope)
                if write:
                    c.commit()
            except BaseException:
                c.rollback()
                raise
            finally:
                c.close()

    def binding(self):
        from .work_identity import schedule_binding
        return schedule_binding(self.scope)

    def record(self, c, row):
        value = dict(row)
        for key in ('reference', 'payload', 'schedule'):
            value[key] = json.loads(value[key])
        value['enabled'] = bool(value['enabled'])
        value.pop('deleted', None)
        value.pop('employee_id',None)
        value['runs'] = [dict(r) for r in c.execute(
            'SELECT id,status,scheduled_for,workflow_id,chat_id,reason FROM occurrences WHERE schedule_id=? ORDER BY id DESC LIMIT 30', (value['id'],))]
        return value

    def list(self, identifier, reference=None):
        value = employee(identifier, reference)
        with self.connection() as c:
            rows = [] if c is None else [self.record(c, r) for r in c.execute(
                'SELECT * FROM schedules WHERE employee_id=? AND reference=? AND deleted=0 ORDER BY id DESC',
                (identifier, canonical(value['native_asset']['employee_reference'])))]
        skills = value['runtime_source']['skills'] if 'runtime_source' in value else [
            {'key': u['skill_key'], 'name': u['work']['name'], 'input_schema': u['work']['input_schema']}
            for u in value['active_release']['snapshot_json']['work_units']]
        return {'items': rows, 'reference': value['native_asset']['employee_reference'],
                'skills': skills,
                'storage_scope': 'device', 'unavailable':value.get('runtime_source',{}).get('unavailable','')}

    def list_reference(self, reference):
        return self.list(record_id(reference), reference)

    def receipt(self, identifier):
        operation_id(identifier)
        with self.connection() as c:
            row = None if c is None else c.execute('SELECT result FROM commands WHERE id=?', (identifier,)).fetchone()
            if not row:
                if c is not None and c.execute("SELECT 1 FROM sqlite_master WHERE name='preparations'").fetchone():
                    phase = c.execute('SELECT state FROM preparations WHERE id=?', (identifier,)).fetchone()
                    if phase and phase['state'] == 'failed':
                        return {'state': 'failed', 'error': '润色失败，尚未创建。请重试或勾选原文。'}
                return {'state': 'unknown'}
            result = json.loads(row[0])
            return {'state': 'abandoned' if result.get('abandoned') else 'committed', 'result': result}

    def abandon(self, identifier):
        operation_id(identifier)
        with self.connection(write=True) as c:
            row = c.execute('SELECT result FROM commands WHERE id=?', (identifier,)).fetchone()
            if row is None:
                c.execute('INSERT INTO commands VALUES(?,?,?)', (identifier, 'null', canonical({'abandoned': True})))
        return self.receipt(identifier)

    def prepared_instruction(self, data, request):
        value = data['value']
        if data['action'] != 'save' or not isinstance(value, dict) or 'use_original' not in value:
            return None  # Existing programmatic/skill commands retain their contract.
        expected = {'name', 'objective', 'enabled', 'schedule_kind', 'interval_sec', 'schedule', 'use_original'}
        if (set(value) != expected or type(value['use_original']) is not bool
                or not isinstance(value['objective'], str) or not value['objective'].strip()
                or len(value['objective']) > 20000 or not isinstance(value['name'], str)
                or not value['name'].strip() or len(value['name']) > 120 or type(value['enabled']) is not bool):
            raise ContractError('自动化设置无效。')
        schedule = value['schedule']
        if (not isinstance(schedule, dict) or set(schedule) - {'time', 'weekdays', 'timezone'}
                or not isinstance(schedule.get('timezone'), str) or type(value['interval_sec']) is not int
                or not 60 <= value['interval_sec'] <= 2592000):
            raise ContractError('时间安排无效。')
        try:
            ZoneInfo(schedule['timezone'])
        except (ValueError, KeyError) as exc:
            raise ContractError('请选择有效时区。') from exc
        if value['schedule_kind'] == 'weekly' and (not isinstance(schedule.get('weekdays'), list)
                or not schedule['weekdays'] or any(type(d) is not int or not 0 <= d <= 6 for d in schedule['weekdays'])):
            raise ContractError('请选择至少一天。')
        from . import automation_time
        automation_time._normalize_automation_schedule(value)
        with self.connection(write=True) as c:
            prior = c.execute('SELECT request,result FROM commands WHERE id=?', (data['operation_id'],)).fetchone()
            if prior:
                if prior['request'] != request or json.loads(prior['result']).get('abandoned'):
                    raise ContractError('这次操作已变化或取消。')
                return None
            employee_id = record_id(data['reference'])
            asset = employee(employee_id, data['reference'])
            row = None if data['id'] is None else c.execute('SELECT * FROM schedules WHERE id=? AND deleted=0', (data['id'],)).fetchone()
            if data['id'] is None and data['expected_revision'] is not None:
                raise ContractError('新自动化没有先前版本。')
            if data['id'] is not None and (row is None or type(data['expected_revision']) is not int
                    or row['revision'] != data['expected_revision'] or row['employee_id'] != employee_id
                    or row['reference'] != canonical(data['reference'])):
                raise ContractError('自动化已变化，请重新读取。')
            if value['use_original']:
                return value['objective']
            if row:
                saved = json.loads(row['payload'])
                if saved.get('use_original') is False and saved.get('original_objective') == value['objective']:
                    return saved['objective']  # Timing/name-only edits do not rewrite the task again.
            preparation = c.execute('SELECT * FROM preparations WHERE id=?', (data['operation_id'],)).fetchone()
            if preparation:
                if preparation['request'] != request:
                    raise ContractError('同一操作编号不能用于不同内容。')
                if preparation['state'] == 'ready':
                    return json.loads(preparation['result'])
                if preparation['state'] == 'preparing':
                    raise PreparationUnknown('创建结果待核对，请勿重复提交。')
                raise ContractError('润色失败，尚未创建。请重试或勾选原文。')
            c.execute('INSERT INTO preparations VALUES(?,?,?,?)', (data['operation_id'], request, 'preparing', 'null'))
        # No SQLite/global scheduling lock is held while the official runtime is working.
        try:
            from .employee_instruction_polish import polish
            objective = (self.polisher or polish)(asset, value['objective'])
            if not isinstance(objective, str) or not objective.strip() or len(objective) > 20000:
                raise ContractError('润色结果无效。')
        except Exception as exc:
            with self.connection(write=True) as c:
                c.execute("UPDATE preparations SET state='failed' WHERE id=?", (data['operation_id'],))
            raise ContractError('润色失败，尚未创建。请重试或勾选原文。') from exc
        with self.connection(write=True) as c:
            if c.execute('SELECT 1 FROM commands WHERE id=?', (data['operation_id'],)).fetchone():
                raise ContractError('这次操作已取消，请重新设置。')
            c.execute("UPDATE preparations SET state='ready',result=? WHERE id=?", (canonical(objective), data['operation_id']))
        return objective

    def command(self, data):
        if not isinstance(data, dict) or set(data) != {'operation_id', 'action', 'reference', 'id', 'expected_revision', 'value'}:
            raise ContractError('自动化操作内容无效。')
        operation_id(data['operation_id'])
        action = data['action']
        if action not in ('save', 'pause', 'resume', 'delete', 'run', 'resolve'):
            raise ContractError('自动化操作无效。')
        # Receipt recovery never revalidates changed assets or replays a command.
        request = canonical(data)
        prepared = self.prepared_instruction(data, request)
        with self.connection(write=True) as c:
            prior = c.execute('SELECT * FROM commands WHERE id=?', (data['operation_id'],)).fetchone()
            if prior:
                if json.loads(prior['result']).get('abandoned'):
                    raise ContractError('这次操作已取消，请重新设置。')
                if prior['request'] != request:
                    raise ContractError('同一操作编号不能用于不同内容。')
                return json.loads(prior['result'])
            employee_id=record_id(data['reference'])
            asset = employee(employee_id, data['reference'])
            identifier = data['id']
            row = None if identifier is None else c.execute('SELECT * FROM schedules WHERE id=? AND deleted=0', (identifier,)).fetchone()
            if identifier is not None and (row is None or type(data['expected_revision']) is not int
                    or row['revision'] != data['expected_revision'] or row['employee_id'] != employee_id
                    or row['reference'] != canonical(data['reference'])):
                raise ContractError('自动化已变化，请重新读取。')
            if action == 'save':
                value = data['value']
                common = {'name','objective','enabled','schedule_kind','interval_sec','schedule'}
                if not isinstance(value,dict) or set(value) not in (common, common|{'use_original'}, common|{'skill_key','parameters'}):
                    raise ContractError('自动化设置无效。')
                instruction = 'skill_key' not in value
                if (not isinstance(value['name'], str) or not value['name'].strip() or len(value['name']) > 120
                        or not isinstance(value['objective'], str) or not value['objective'].strip() or len(value['objective']) > 20000
                        or type(value['enabled']) is not bool):
                    raise ContractError('请填写名称和要完成的工作。')
                if instruction:
                    payload = {'schema':'runteams.employee-instruction/1','objective':value['objective'],
                               'skill_key':None,'parameters':{}}
                    if 'use_original' in value:
                        payload.update(objective=prepared, original_objective=value['objective'], use_original=value['use_original'])
                else:
                    payload = validate_definition('task_payload', {'schema': 'runteams.task-input/v2',
                        'objective': value['objective'], 'skill_key': value['skill_key'], 'parameters': value['parameters'],
                        'context': {}, 'inputs': [], 'module_bindings': {}, 'asset_bindings': {}})
                if instruction:
                    pass
                elif 'runtime_source' in asset:
                    from .skill_bundles import extension as _extension
                    bundle = next((b for b in asset['runtime_source']['asset']['skill_bundles'] if b['package_key']==value['skill_key']),None)
                    if bundle is None:raise ContractError('员工已不提供这项工作，请重新选择。')
                    from .source_employee_runtime import validate_parameters
                    validate_parameters(asset['runtime_source']['asset'],value['skill_key'],value['parameters'])
                else:
                    unit = select_work_unit(asset['active_release']['snapshot_json'], value['skill_key'])
                    validate_work_parameters(unit, value['parameters'])
                from . import automation_time as time_rules
                raw_schedule = value['schedule']
                if (not isinstance(raw_schedule, dict) or set(raw_schedule) - {'time', 'weekdays', 'timezone'}
                        or not isinstance(raw_schedule.get('timezone'), str)
                        or type(value['interval_sec']) is not int or not 60 <= value['interval_sec'] <= 2592000):
                    raise ContractError('时间安排无效。')
                try:
                    ZoneInfo(raw_schedule['timezone'])
                except (KeyError, ValueError) as exc:
                    raise ContractError('请选择有效时区。') from exc
                if value['schedule_kind'] == 'weekly' and (not isinstance(raw_schedule.get('weekdays'), list)
                        or any(type(day) is not int or not 0 <= day <= 6 for day in raw_schedule['weekdays'])):
                    raise ContractError('星期选择无效。')
                kind, interval, schedule = time_rules._normalize_automation_schedule(value)
                following = next_run(kind, interval, schedule) if value['enabled'] else ''
                values = (employee_id, canonical(data['reference']), asset['active_release']['digest'],
                    value['name'].strip(), canonical(payload), int(value['enabled']), kind, interval, canonical(schedule), following)
                if identifier is None:
                    if data['expected_revision'] is not None:
                        raise ContractError('新自动化没有先前版本。')
                    identifier = c.execute('INSERT INTO schedules(revision,employee_id,reference,release_digest,name,payload,enabled,schedule_kind,interval_sec,schedule,next_run_at) VALUES(0,?,?,?,?,?,?,?,?,?,?)', values).lastrowid
                else:
                    c.execute('UPDATE schedules SET revision=revision+1,employee_id=?,reference=?,release_digest=?,name=?,payload=?,enabled=?,schedule_kind=?,interval_sec=?,schedule=?,next_run_at=? WHERE id=?', (*values, identifier))
                    self.cancel_rows(c,identifier)
            else:
                if row is None or data['value'] is not None:
                    raise ContractError('请选择原自动化。')
                if action == 'run':
                    self.fire(c, row, 'manual:' + data['operation_id'])
                elif action == 'resolve':
                    c.execute("UPDATE occurrences SET status='cancelled',reason='用户核对后结束本次记录，原工作未重做。' WHERE schedule_id=? AND status='interrupted'", (identifier,))
                else:
                    from . import automation_time as time_rules
                    enabled = action == 'resume'
                    following = next_run(row['schedule_kind'], row['interval_sec'], json.loads(row['schedule'])) if enabled else ''
                    c.execute('UPDATE schedules SET revision=revision+1,enabled=?,deleted=?,next_run_at=? WHERE id=?',
                        (int(enabled), int(action == 'delete'), following, identifier))
                    if not enabled:
                        self.cancel_rows(c,identifier)
            result = {'id': identifier, 'operation_id': data['operation_id']}
            c.execute('INSERT INTO commands VALUES(?,?,?)', (data['operation_id'], request, canonical(result)))
            return result

    def cancel_rows(self,c,identifier):
        # A scheduler claim is not work admission. Fence it with the same
        # transaction used by native-chat creation and ordinary work admission.
        for row in c.execute("SELECT * FROM occurrences WHERE schedule_id=? AND status IN ('queued','running')",(identifier,)).fetchall():
            if row['chat_id'] or row['workflow_id']:continue
            receipt=self.admitted(self.controller_factory().core,row['operation_id'])
            if receipt:
                c.execute("UPDATE occurrences SET status='waiting',workflow_id=? WHERE id=?",(receipt['workflow_id'],row['id']))
            else:
                c.execute("UPDATE occurrences SET status='cancelled',reason='计划已暂停或更新，原触发未受理。' WHERE id=?",(row['id'],))

    def fire(self, c, row, scheduled):
        if c.execute("SELECT 1 FROM occurrences WHERE schedule_id=? AND status IN ('queued','running','waiting','blocked','interrupted')", (row['id'],)).fetchone():
            raise ContractError('这项自动化还有未完成或需要核对的运行。')
        c.execute("INSERT INTO occurrences(schedule_id,scheduled_for,operation_id,status,snapshot) VALUES(?,?,?,'queued',?)",
            (row['id'], scheduled, str(uuid.uuid4()), canonical(dict(row))))

    def materialize_due_automations(self, limit=20, has_open_work=None):
        self.reconcile()
        from . import automation_time as time_rules
        with self.connection(write=True) as c:
            for row in c.execute("SELECT * FROM schedules WHERE enabled=1 AND deleted=0 AND next_run_at<>'' AND next_run_at<=? ORDER BY next_run_at LIMIT ?", (time_rules.now(), min(20, limit))).fetchall():
                try:
                    from .managed_employee_data import writer_busy
                    if writer_busy(json.loads(row['reference'])):
                        raise ContractError('员工已有工作正在执行，本次未重复启动。')
                    self.fire(c, row, row['next_run_at'])
                except ContractError as exc:
                    c.execute("INSERT OR IGNORE INTO occurrences(schedule_id,scheduled_for,operation_id,status,snapshot,reason) VALUES(?,?,?,'skipped',?,?)",
                        (row['id'], row['next_run_at'], str(uuid.uuid4()), canonical(dict(row)), str(exc)))
                c.execute('UPDATE schedules SET next_run_at=? WHERE id=?',
                    (next_run(row['schedule_kind'], row['interval_sec'], json.loads(row['schedule'])), row['id']))

    def claim_next_automation_run(self):
        with self.connection(write=True) as c:
            row = c.execute("SELECT * FROM occurrences WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return None
            c.execute("UPDATE occurrences SET status='running' WHERE id=?", (row['id'],))
            return {**dict(row), 'automation_id': row['schedule_id']}

    def admitted(self, core, operation):
        events = core.repository.events('employee-schedule:' + operation)
        return next((e['data_json'] for e in events if e['type'] == 'employee_schedule.admitted'), None)

    def execute(self, job, cancel_event=None):
        device_data.check(self.scope)
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled('本次运行已取消。')
        with self.connection() as c:
            row=c.execute('SELECT status FROM occurrences WHERE id=?',(job['id'],)).fetchone()
            if row is None or row['status'] not in ('queued','running'):return
        snap = json.loads(job['snapshot'])
        asset = employee(snap['employee_id'], json.loads(snap['reference']))
        if 'runtime_source' in asset:
            from .source_employee_runtime import prepare,employee as source_employee
            package = prepare(json.loads(snap['reference']), job['operation_id'], cancel=cancel_event)
            asset = source_employee(package)
            payload = json.loads(snap['payload'])
            if payload.get('schema') != 'runteams.employee-instruction/1':
                from .source_employee_runtime import validate_parameters,package_asset
                validate_parameters(package_asset(package),payload['skill_key'],payload['parameters'])
            if self.chat_execute is None:raise ContractError('员工的原生工作宿主尚未就绪。')
            return self.chat_execute(self,job,asset,cancel_event)
        if asset['active_release']['digest'] != snap['release_digest']:
            raise ContractError('员工版本已变化，请编辑此自动化后再运行。')
        from .device_employee_mcp import bundles
        if json.loads(snap['payload']).get('schema') == 'runteams.employee-instruction/1' or bundles(asset):
            if self.chat_execute is None:
                raise ContractError('员工的原生工作宿主尚未就绪。')
            return self.chat_execute(self, job, asset, cancel_event)
        controller = self.controller_factory()
        core = controller.core
        # Existing repository nesting joins this transaction. Admission and its
        # recovery receipt therefore commit with the one ordinary work item.
        with self.connection(write=True) as schedules,core.repository.connect() as c:
            row=schedules.execute('SELECT status FROM occurrences WHERE id=?',(job['id'],)).fetchone()
            if row is None or row['status'] not in ('queued','running'):return
            c.execute('BEGIN IMMEDIATE')
            result = self.admitted(core, job['operation_id'])
            if result is None:
                result = core.dispatch_task(snap['name'], json.loads(snap['payload']), employee_id=snap['employee_id'],
                    source={'kind': 'sdk_employee_schedule', 'schedule_id': job['schedule_id'], 'operation_id': job['operation_id']})
                core.repository.event('employee-schedule:' + job['operation_id'], 'employee_schedule.admitted', result, connection=c)
        with self.connection(write=True) as c:
            c.execute("UPDATE occurrences SET status='waiting',workflow_id=? WHERE id=?", (result['workflow_id'], job['id']))
        controller.wake()

    def reconcile(self):
        with self.connection() as c:
            rows = [] if c is None else [dict(r) for r in c.execute("SELECT * FROM occurrences WHERE status IN ('waiting','running','blocked','interrupted')")]
        if not rows:
            self.recovering = False
            return
        core = None
        for row in rows:
            if row['status'] == 'running' and not self.recovering:
                continue
            if row['chat_id']:
                from .scheduled_employee_chat import outcome
                status, reason = outcome(row['chat_id'])
                with self.connection(write=True) as c:
                    c.execute('UPDATE occurrences SET status=?,reason=? WHERE id=?', (status, reason, row['id']))
                continue
            is_source = json.loads(json.loads(row['snapshot'])['reference']).get('schema') == 'runteams.local-employee-reference/1'
            if is_source:
                with self.connection(write=True) as c:
                    c.execute("UPDATE occurrences SET status='interrupted',reason='原工作结果需要核对，不会自动重做。' WHERE id=?",(row['id'],))
                continue
            core = core or self.controller_factory().core
            receipt = self.admitted(core, row['operation_id']) if not row['workflow_id'] else None
            workflow_id = row['workflow_id'] or (receipt or {}).get('workflow_id')
            work = core.workflow(workflow_id) if workflow_id else None
            status = work['state'] if work and work['state'] in ('completed', 'failed', 'canceled', 'blocked') else 'waiting' if work else 'interrupted'
            with self.connection(write=True) as c:
                c.execute('UPDATE occurrences SET status=?,workflow_id=?,reason=? WHERE id=?',
                    (status, workflow_id, '' if work else '原运行结果需要核对，不会自动重做。', row['id']))
        self.recovering = False

    def add_automation_run_event(self, identifier, kind, content):
        with self.connection(write=True) as c:
            c.execute('INSERT INTO events(run_id,kind,content) VALUES(?,?,?)', (identifier, kind, canonical(content)))

    def finish_automation_run(self, identifier, status, reason=''):
        with self.connection() as c:
            row=c.execute('SELECT status,chat_id,workflow_id FROM occurrences WHERE id=?',(identifier,)).fetchone()
        if row and row['status']=='cancelled' and not row['chat_id'] and not row['workflow_id']:return
        if status == 'failed':
            with self.connection() as c:
                row = c.execute('SELECT operation_id,workflow_id,status,snapshot,chat_id FROM occurrences WHERE id=?', (identifier,)).fetchone()
            if row and row['status'] == 'waiting':
                return  # Ordinary work owns the outcome after admission.
            if row and not row['chat_id'] and json.loads(json.loads(row['snapshot'])['reference']).get('schema') != 'runteams.local-employee-reference/1':
                receipt = self.admitted(self.controller_factory().core, row['operation_id'])
                if receipt:
                    with self.connection(write=True) as c:
                        c.execute("UPDATE occurrences SET status='waiting',workflow_id=? WHERE id=?", (receipt['workflow_id'], identifier))
                    return
        with self.connection(write=True) as c:
            c.execute("UPDATE occurrences SET status=?,reason=? WHERE id=? AND (status<>'cancelled' OR chat_id IS NOT NULL OR workflow_id IS NOT NULL)",
                (status, str(reason)[:1000], identifier))

    def cancel_queued_automation_runs(self, identifier, reason='计划已暂停'):
        with self.connection(write=True) as c:
            c.execute("UPDATE occurrences SET status='cancelled',reason=? WHERE schedule_id=? AND status='queued'", (reason, identifier))


def handle(handler, method, backend, data=None, *, on_mutation=None):
    from urllib.parse import urlparse, parse_qs
    path = urlparse(handler.path).path
    try:
        host = handler.headers.get('Host')
        allowed = {'127.0.0.1:' + str(handler.server.server_port), 'localhost:' + str(handler.server.server_port)}
        if (host not in allowed or handler.headers.get('X-RunTeams-Device-Scope') != backend.scope['cache_scope']
                or handler.headers.get('Sec-Fetch-Site') == 'cross-site'
                or (method == 'POST' and handler.headers.get('Origin') != 'http://' + host)):
            raise PermissionError('请在当前账户的应用页面中设置自动化。')
        from .schedule_operations import dispatch
        query=parse_qs(urlparse(handler.path).query)
        try:value=dispatch(backend,method,path,query,data,on_mutation)
        except KeyError:return handler._json({'error':'自动化接口不存在。'},404)
        return handler._json(value)
    except PreparationUnknown as exc:
        return handler._json({'error': str(exc), 'state': 'unknown'}, 409)
    except (ValueError, ContractError, PermissionError) as exc:
        return handler._json({'error': str(exc), 'code': 'employee_schedule_unavailable'}, 403 if isinstance(exc, PermissionError) else 400)
    except (OSError, sqlite3.Error):
        return handler._json({'error': '本机自动化暂时无法读取或保存，请核对原操作。', 'state': 'unknown'}, 503)


def verify(directory, scope, *, schedule_directory=DIRECTORY, pipeline=False):
    path = Path(directory) / schedule_directory / DATABASE
    if not path.exists():
        if path.parent.exists():
            raise ContractError('自动化备份不完整。')
        return
    if path.is_symlink() or path.parent.is_symlink():
        raise ContractError('自动化备份路径无效。')
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ContractError('自动化备份损坏。')
        row = c.execute('SELECT version,scope FROM binding').fetchone()
        from .work_identity import schedule_binding
        expected = schedule_binding(scope)
        if row is None or row[0] != 1 or json.loads(row[1]) != expected:
            raise PermissionError('自动化备份账户或部署不一致。')
        def check_reference(reference):
            ref=json.loads(reference) if isinstance(reference,str) else reference
            if pipeline:
                from .pipeline_references import checked_reference
                checked_reference(ref,scope)
            elif ref.get('schema') in ('runteams.local-employee-reference/1','runteams.acquired-employee-reference/1'):
                from .employee_references import checked_source_reference
                checked_source_reference(ref,scope)
            else:
                if scope.get('storage_kind')=='local' or ref.get('workspace_id')!=scope.get('account_id') or ref.get('deployment_id')!=scope.get('deployment_id'):
                    raise PermissionError('自动化员工来源不一致。')
        for (reference,) in c.execute('SELECT reference FROM schedules'):check_reference(reference)
        for (raw,) in c.execute('SELECT snapshot FROM occurrences'):
            value=json.loads(raw)
            check_reference(value['reference'])



def snapshot(source, destination, scope, check, *, schedule_directory=DIRECTORY, pipeline=False):
    path = Path(source) / schedule_directory / DATABASE
    if not path.exists():
        return
    verify(source, scope, schedule_directory=schedule_directory, pipeline=pipeline)
    target = Path(destination) / schedule_directory / DATABASE
    target.parent.mkdir(mode=0o700)
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as original, sqlite3.connect(target) as copy:
        original.backup(copy)
    target.chmod(0o600)
    check()
    verify(destination, scope, schedule_directory=schedule_directory, pipeline=pipeline)


def quarantine_restored(directory, *, schedule_directory=DIRECTORY):
    path = Path(directory) / schedule_directory / DATABASE
    if not path.exists():
        return
    with sqlite3.connect(path) as c:
        c.execute("UPDATE schedules SET enabled=0,next_run_at='',revision=revision+1")
        c.execute("UPDATE occurrences SET status='interrupted',reason='从备份恢复，请核对原工作，不会自动重做。' WHERE status IN ('queued','running','waiting')")
