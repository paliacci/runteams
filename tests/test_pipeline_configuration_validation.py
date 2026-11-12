"""Task configuration hints must agree with validation and save revisions."""
import copy
import unittest
from unittest.mock import patch
from runteams_core.foundation.contracts import ContractError, normalize_pipeline_parameters
from runteams_core.pipelines.pipeline_task_configuration import (
    ConfigurationInvalid, configuration_fields, project, validate_values,
)


class TaskConfigurationValidationTests(unittest.TestCase):
    def test_conditional_requirement_allows_staged_configuration(self):
        fields = [{'key':'app_id','type':'text','required_when':'Store inspection',
                   'constraints':{'pattern':'^[0-9]+$','max_length':12}}]
        self.assertEqual(validate_values(fields, {}), {})
        self.assertEqual(validate_values(fields, {'app_id':'123'}), {'app_id':'123'})
        for value in ('wrong-id', '1'*13):
            with self.assertRaises(ConfigurationInvalid) as raised:
                validate_values(fields, {'app_id':value})
            self.assertIn('app_id', raised.exception.fields)
            self.assertNotIn(value, str(raised.exception))

    def test_unconditional_required_and_numeric_limits(self):
        required = [{'key':'project','type':'text','required':True}]
        for value in ({}, {'project':''}, {'project':'  '}):
            with self.assertRaises(ConfigurationInvalid):validate_values(required, value)
        numeric = [{'key':'amount','type':'number','constraints':{'min':1,'max':3,'step':.5}}]
        self.assertEqual(validate_values(numeric, {'amount':1.5}), {'amount':1.5})
        for value in (0, 4, 1.2):
            with self.assertRaises(ConfigurationInvalid):validate_values(numeric, {'amount':value})

    def test_metadata_is_typed_scoped_and_part_of_save_revision(self):
        base = {'key':'id','label':'ID','source':'user','display':'setup','type':'text'}
        frozen = {'pipeline_work':{'reference':{},'asset':{'pipeline':{'parameters':[base]}}},
                  'pipeline_input':{'parameters':{}}}
        original = copy.deepcopy(frozen)
        latest = {'pipeline':{'parameters':[{**base,'note':'数字 ID','constraints':{'pattern':'^[0-9]+$'}},
                    {**base,'key':'other','required':True}]}}
        with patch('runteams_core.pipelines.source_pipeline_workspace._definition', return_value=('r',latest,{})):
            inherited = configuration_fields(frozen)
        self.assertEqual([p['key'] for p in inherited], ['id'])
        self.assertEqual(frozen, original)
        row = {'id':1,'state':'needs_approval'}
        a = project(row, frozen, declarations=[base])
        b = project(row, frozen, declarations=inherited)
        self.assertNotEqual(a['revision'], b['revision'])
        frozen['pipeline_work']['asset']['pipeline']['parameters'][0]['constraints'] = {'max_length':8}
        with patch('runteams_core.pipelines.source_pipeline_workspace._definition', return_value=('r',latest,{})):
            self.assertEqual(configuration_fields(frozen)[0]['constraints'], {'max_length':8})

    def test_invalid_declaration_limits_are_rejected(self):
        base = {'key':'id','label':'ID','source':'user','display':'setup','type':'text'}
        for limits in ({'min':0}, {'min_length':10,'max_length':2}, {'pattern':'['}):
            with self.assertRaises(ContractError):normalize_pipeline_parameters([{**base,'constraints':limits}],set())
        valid = {**base,'required':False,'required_when':'Store inspection', 'constraints':{'max_length':12}}
        self.assertEqual(normalize_pipeline_parameters([valid],set())[0], valid)


class TaskCredentialIsolationTests(unittest.TestCase):
    def setUp(self):
        import tempfile, sqlite3
        from pathlib import Path
        from contextlib import contextmanager, ExitStack
        from runteams_core.configuration.credentials.app_secrets import vault_scope
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.vault = Path(directory)/'vault.json'
        self.stack.enter_context(vault_scope(str(self.vault)))
        scope = {'storage_kind':'local','library_id':'test-library','storage_namespace':'test-library'}
        for name, value in [('identity',scope),('personal',True),('check',None)]:
            self.stack.enter_context(patch('runteams_core.storage.device_data.'+name, return_value=value))
        self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE device_settings(key TEXT PRIMARY KEY,value TEXT)')
        @contextmanager
        def connect(**kwargs):
            with self.db:yield self.db
        self.stack.enter_context(patch('runteams_core.storage.device_data.connect',connect))
        self.declarations = [
            {'key':'rc_project_id','label':'项目 ID','type':'text','source':'user','display':'setup'},
            {'key':'APP_RC_SECRET_KEY','label':'Secret API Key','type':'secret','source':'user','display':'setup',
             'scope_parameter':'rc_project_id','visible_to':['billing']}]
        self.frozen = {'pipeline_work':{'reference':{'source_id':'fixture'},'position_key':'billing',
                        'asset':{'pipeline':{'parameters':self.declarations}}},
                       'pipeline_input':{'parameters':{'rc_project_id':'project-a'}}}
        self.row = {'id':1,'state':'needs_approval'}
        from runteams_core.pipelines import pipeline_task_configuration as task
        self.task = task
    def save_secret(self, value='test-secret-only'):
        store, _ = self.task.credential_store(self.row,self.frozen,self.declarations)
        return store.credential(field=self.task.credential_field_key('APP_RC_SECRET_KEY'),
                                definition_sha256=store.definition_sha256,value=value)
    def lease(self):
        self.stack.enter_context(patch.object(self.task,'chat_credentials',side_effect=lambda _:(self.row,self.frozen,self.declarations)))
        return self.task.credential_lease(1,['APP_RC_SECRET_KEY'],lambda:None,
                                        lambda:self.fail('Task credentials must not fall back to a shared key'))
    def test_plaintext_stays_in_vault_and_tasks_and_projects_are_isolated(self):
        import json
        original=copy.deepcopy(self.frozen)
        self.save_secret()
        a=self.task.project(self.row,self.frozen,declarations=self.declarations)
        self.assertEqual(a['credential_fields']['APP_RC_SECRET_KEY']['state'],'configured')
        self.assertNotIn('APP_RC_SECRET_KEY',a['values'])
        self.assertNotIn('test-secret-only',json.dumps(a))
        self.assertNotIn('test-secret-only',str(list(self.db.execute('SELECT value FROM device_settings'))))
        self.assertEqual(self.frozen,original)
        self.assertIn('test-secret-only',self.vault.read_text())
        self.assertEqual(self.vault.stat().st_mode & 0o777,0o600)
        self.row['id']=2
        b=self.task.project(self.row,self.frozen,declarations=self.declarations)
        self.assertFalse(b['credential_fields']['APP_RC_SECRET_KEY']['selected'])
    def test_other_task_has_no_fallback(self):
        self.save_secret();self.row['id']=2
        with self.assertRaises(PermissionError):
            with self.lease():pass
    def test_project_change_invalidates_selection_and_lease(self):
        self.save_secret()
        with self.lease() as bound:
            self.assertEqual(bound.values['APP_RC_SECRET_KEY'],'test-secret-only');bound.verify()
            self.frozen['pipeline_input']['parameters']['rc_project_id']='project-b'
            with self.assertRaises(PermissionError):bound.verify()
        view=self.task.project(self.row,self.frozen,declarations=self.declarations)
        self.assertFalse(view['credential_fields']['APP_RC_SECRET_KEY']['selected'])
        with self.assertRaises(PermissionError):
            with self.lease():pass
    def test_replacement_and_clear_revoke_lease_and_other_positions_are_denied(self):
        self.save_secret()
        with self.lease() as bound:
            self.save_secret('test-replacement')
            with self.assertRaises(PermissionError):bound.verify()
        with self.lease() as bound:
            self.save_secret('')
            with self.assertRaises(PermissionError):bound.verify()
        self.save_secret();self.frozen['pipeline_work']['position_key']='engineering'
        with self.assertRaises(PermissionError):
            with self.lease():pass
    def test_secret_rejected_from_ordinary_input_and_scope_must_be_declared(self):
        with self.assertRaises(ConfigurationInvalid):
            validate_values(self.declarations,{'rc_project_id':'a','APP_RC_SECRET_KEY':'must-not-save'})
        with self.assertRaises(ContractError):normalize_pipeline_parameters(self.declarations[1:],{'billing'})
        normalized=normalize_pipeline_parameters(self.declarations,{'billing'})
        self.assertEqual(normalized[1]['scope_parameter'],'rc_project_id')
    def test_existing_tasks_can_explicitly_configure_new_project_secret_without_rewriting_history(self):
        self.frozen['pipeline_work']['asset']['pipeline']['parameters']=self.declarations[:1]
        original=copy.deepcopy(self.frozen)
        with patch('runteams_core.pipelines.source_pipeline_workspace._definition',return_value=('r',{'pipeline':{'parameters':self.declarations}}, {})):
            self.assertEqual(len(configuration_fields(self.frozen)),2)
        self.assertEqual(self.frozen,original)
    def test_credential_endpoint_cas_owner_and_running_guard(self):
        import sqlite3,json
        from types import SimpleNamespace
        from contextlib import contextmanager
        connection=sqlite3.connect(':memory:');self.addCleanup(connection.close)
        @contextmanager
        def connect():
            try:yield connection
            finally:connection.rollback()
        core=SimpleNamespace(_actor=lambda:None,repository=SimpleNamespace(connect=connect,
             storage=SimpleNamespace(assert_executable=lambda _id:None)))
        row={**self.row,'snapshot_json':json.dumps(self.frozen)}
        self.stack.enter_context(patch('runteams_core.pipelines.source_pipeline_flow._row',return_value=row))
        self.stack.enter_context(patch('runteams_core.pipelines.pipeline_references.checked_reference',side_effect=lambda r:r))
        self.stack.enter_context(patch.object(self.task,'configuration_fields',return_value=self.declarations))
        data={'reference':self.frozen['pipeline_work']['reference'],'workflow_id':1,'action':'credential',
              'field':'APP_RC_SECRET_KEY','value':'endpoint-test-secret',
              'expected_revision':self.task.project(row,self.frozen,declarations=self.declarations)['revision']}
        reply=self.task.request(core,data)
        self.assertEqual(reply['configuration']['credential_fields']['APP_RC_SECRET_KEY']['state'],'configured')
        self.assertEqual(reply['configuration']['credential_fields']['APP_RC_SECRET_KEY']['mask_length'],len(data['value']))
        self.assertNotIn('endpoint-test-secret',json.dumps(reply))
        reveal={k:v for k,v in data.items() if k!='value'}
        reveal['action']='reveal-credential'
        self.assertEqual(self.task.request(core,reveal)[1],409)
        reveal['expected_revision']=reply['configuration']['revision']
        self.assertEqual(self.task.request(core,reveal),{'value':'endpoint-test-secret'})
        self.assertEqual(self.task.request(core,{'reference':data['reference'],'workflow_id':1,'action':'read'})['configuration'],reply['configuration'])
        self.assertEqual(self.task.request(core,data)[1],409)
        data['expected_revision']=reply['configuration']['revision']
        for state in ['running','completed','canceled','failed']:
            row['state']=state
            with self.assertRaises(ContractError):self.task.request(core,data)
        row['state']='needs_approval'
        with self.assertRaises(ContractError):self.task.request(core,data,active_ids=[1])
        with self.assertRaises(PermissionError):self.task.request(core,{**data,'reference':{'source_id':'another'}})
        with self.assertRaises(PermissionError):self.task.request(core,{**reveal,'reference':{'source_id':'another'}})
        with self.assertRaises(ContractError):self.task.request(core,{**data,'field':'UNDECLARED'})
