"""Run each recovery case in a process bound to its own temporary library."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

import runteams_core


CORE_ROOT = Path(runteams_core.__file__).resolve().parent.parent
HTTP_CLIENT = Path(__file__).resolve().parent / 'community' / 'work_state_http.mjs'

SETUP = """
import json, os, sys, threading, uuid
from pathlib import Path
from runteams_core.application.local_application import LocalApplication

http_client = sys.argv[1]
app = LocalApplication(Path(os.environ['RUNTEAMS_DATA']))
r = app.runtime
BASE = '/api/device/work/source-pipelines/ui-state-'

def read():
    return app.dispatch('POST', BASE + 'read', {})

def write(key, value, revision=0):
    data = {'key': key, 'value': json.dumps(value) if value is not None else None,
            'expected_revision': revision, 'operation_id': str(uuid.uuid4())}
    return data, app.dispatch('POST', BASE + 'save', data)
"""


class WorkUIStateTests(unittest.TestCase):
    def child(self, scenario):
        with tempfile.TemporaryDirectory(prefix='work-ui-state-') as directory:
            # Use the same source checkout or installed package as the parent.
            code = f'import sys; sys.path.insert(0, {str(CORE_ROOT)!r})\n' + SETUP + textwrap.dedent(scenario)
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, HTTP_CLIENT],
                                    cwd=directory, env={**os.environ, 'RUNTEAMS_DATA': directory,
                                                        'RUNTEAMS_AUTOMATION_DISPATCH': '0'},
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_original_operation_is_durable_and_same_UI_save_receipt_is_idempotent(self):
        self.child('''
            original=str(uuid.uuid4());value={'operation_id':original,'reference':{'storage_kind':'local','library_id':app.binding.library_id}}
            data,result=write('pipeline-admission:own',value)
            assert app.dispatch('POST',BASE+'save',data)==result and result['revision']==1
            try:app.dispatch('POST',BASE+'save',{**data,'value':'{}'})
            except ValueError:pass
            else:raise AssertionError('same persistence operation changed')
            location=app.data_directory;library=app.binding.library_id;app.close()
            app=LocalApplication(location);r=app.runtime;state=read();assert state['owner']['library_id']==library
            assert json.loads(state['items']['pipeline-admission:own']['value'])==value
            assert not any(n=='account_auth' or n.startswith(('runteams_official','supabase')) for n in sys.modules)
            app.close()
        ''')

    def test_stale_clear_cannot_erase_newer_work_state_and_original_tombstone_can_be_replayed(self):
        self.child('''
            first,a=write('pipeline-control:own',{'operation_id':str(uuid.uuid4())})
            clear,b=write('pipeline-control:own',None,1)
            third,c=write('pipeline-control:own',{'operation_id':str(uuid.uuid4())},2)
            assert app.dispatch('POST',BASE+'save',clear)==b
            out=app.dispatch('POST',BASE+'save',{**clear,'operation_id':str(uuid.uuid4())});assert out.status==409
            assert read()['items']['pipeline-control:own']['value']==third['value']
            assert read()['items']['pipeline-control:own']['revision']==3;app.close()
        ''')

    def test_original_state_follows_whole_backup_restore_and_does_not_dispatch_work(self):
        self.child('''
            request,receipt=write('employee-schedule-operation:own',{'operation_id':str(uuid.uuid4())})
            prior=read();backup=app.dispatch('POST','/api/backups',{'operation_id':str(uuid.uuid4())});assert backup['state']=='completed'
            import io
            raw=app.backups.download(backup['backup_id']).read_bytes();upload=app.backups.upload(io.BytesIO(raw),len(raw),str(uuid.uuid4()))
            write('employee-schedule-operation:own',None,1)
            app.dispatch('POST','/api/backups/restore',{'operation_id':str(uuid.uuid4()),'import_id':upload['import_id']})
            assert read()==prior and not r.employee_jobs and not r.active
            assert app.dispatch('POST',BASE+'save',request)==receipt;app.close()
        ''')

    def test_invalid_keys_and_corrupt_owner_are_not_valid_recovery_data(self):
        self.child('''
            for key in ('../../outside','arbitrary-state','pipeline-unknown:x'):
             try:write(key,{'auth_token':'must not be a new storage feature'})
             except ValueError:pass
             else:raise AssertionError('unsupported key accepted')
            write('pipeline-settings:own',{'draft':{'name':'original'}})
            from runteams_core.storage import device_data; from runteams_core.work import work_ui_state
            with r.scope(),device_data.connect() as c:
             name,raw=c.execute("SELECT key,value FROM device_settings WHERE key LIKE 'work-ui-state:%'").fetchone();value=json.loads(raw);value['owner']['library_id']=str(uuid.uuid4());c.execute('UPDATE device_settings SET value=? WHERE key=?',(json.dumps(value),name))
            try:read()
            except ValueError:pass
            else:raise AssertionError('foreign owner accepted')
            try:app.dispatch('POST','/api/backups',{'operation_id':str(uuid.uuid4())})
            except ValueError:pass
            else:raise AssertionError('corrupt recovery state backed up as success')
            app.close()
        ''')

    def test_cleared_pipeline_card_receipt_does_not_block_employee_schedule_recovery(self):
        self.child('''
            _,stored=write('pipeline-card:fixture',{'operation_id':str(uuid.uuid4())})
            cleared,receipt=write('pipeline-card:fixture',None,stored['revision'])
            schedule,_=write('employee-schedule-operation:fixture',{'operation_id':str(uuid.uuid4())})
            items=read()['items']
            assert items['pipeline-card:fixture']=={'revision':2,'value':None}
            assert items['employee-schedule-operation:fixture']['value']==schedule['value']
            assert app.dispatch('POST',BASE+'save',cleared)==receipt
            app.close()
        ''')

    def test_actual_JS_store_and_LocalClient_survive_two_processes_and_dropped_HTTP_ack(self):
        self.child('''
            from runteams_core.application.http.local_http import LocalServer
            import subprocess
            server=LocalServer(app,0);thread=threading.Thread(target=server.serve_forever);thread.start();original=str(uuid.uuid4())
            try:
             for mode in ('seed','cold'):
              data={'origin':server.origin,'token':server.session_token,'mode':mode,'original':original}
              child=subprocess.run(['node',http_client],input=json.dumps(data),capture_output=True,text=True,timeout=30)
              assert child.returncode==0,child.stdout+child.stderr
              result=json.loads(child.stdout);assert result['original']==original and not result['pending']
              assert result['writes']==(2 if mode=='seed' else 1)
             assert read()['items']['pipeline-control:HTTP-fixture']['value'] is None
             with r.scope():
              with r.work_core().repository.connect() as c:assert c.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
            finally:server.shutdown();server.server_close();thread.join(5);app.close()
        ''')
