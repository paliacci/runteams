import json
import sqlite3
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import scheduled_followup as f
from runteams_core.pipelines.portable_pipeline import validate_pipeline_bindings


class FollowupTests(unittest.TestCase):
    def test_independent_member_does_not_need_a_board_position(self):
        g={'name':'Team','positions':[{'key':'send','kind':'employee','name':'Send','employee_ref':'p','skill_key':'send'}],
           'states':[{'key':'published','kind':'done','name':'Published'}],'edges':[{'from':'send','to':'published'}]}
        validate_pipeline_bindings(g,{'p':['send'],'analyst':['review']})
        with self.assertRaises(ContractError):
            validate_pipeline_bindings(g,{'analyst':['review']})

    def test_preserves_state_and_versions_original_card(self):
        conn=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(conn.close)
        conn.row_factory=sqlite3.Row
        conn.executescript('CREATE TABLE events(id INTEGER PRIMARY KEY,stream TEXT,type TEXT,data_json TEXT);'
                           'CREATE TABLE workflow_runs(id INTEGER, task_id INTEGER,cursor_key TEXT,snapshot_json TEXT);'
                           'CREATE TABLE tasks(id INTEGER, title TEXT,trashed_at TEXT);')
        ref={'source_id':'a','pipeline_source':'team'}
        for wid,state in ((1,'published'),(2,'abandoned')):
            conn.execute('INSERT INTO tasks VALUES(?,?,NULL)',(wid,str(wid)))
            conn.execute('INSERT INTO workflow_runs VALUES(?,?,?,?)',(wid,wid,state,json.dumps({'pipeline_work':{'reference':ref}})))
        core=SimpleNamespace(repository=SimpleNamespace(connect=lambda:conn,event=lambda stream,kind,data,connection:
                 conn.execute('INSERT INTO events(stream,type,data_json) VALUES(?,?,?)',(stream,kind,json.dumps(data)))))
        asset={'employees':[{'source':'analyst'}],'pipeline':{'states':[{'key':'published'}]}}
        scope=(ref,'published','one')
        with patch.object(f.source_pipeline_control,'read',return_value={'status':'running','bundle':{'asset':asset}}), \
             patch.object(f,'member_reference',return_value='analyst'), \
             patch.object(f.pipeline_work_access,'_row',side_effect=lambda c,r,i:(c.execute('SELECT * FROM workflow_runs WHERE id=?',(i,)).fetchone(),{})):
            self.assertEqual([r['workflow_id'] for r in f.operate(core,'analyst',scope,{'operation':'followup_list'})['items']],[1])
            data=dict(operation='followup_append',workflow_id=1,observed_at='2026-11-20T12:00:00Z',metrics={'views':0,'likes':None},source_url='https://example.org/post',content='Checked',base_revision=0)
            first=f.operate(core,'analyst',scope,data)
            self.assertEqual(first,f.operate(core,'analyst',scope,data))
            with self.assertRaises(PermissionError):f.operate(core,'other',scope,data)
            with self.assertRaises(PermissionError):f.operate(core,'analyst',scope,{**data,'workflow_id':2})
            with self.assertRaises(ContractError):f.operate(core,'analyst',(*scope[:2],'two'),data)
            second=f.operate(core,'analyst',(*scope[:2],'two'),{**data,'base_revision':1,'observed_at':'2026-11-21T12:00:00Z'})
            self.assertEqual(second['revision'],2)
            self.assertEqual(conn.execute('SELECT cursor_key FROM workflow_runs WHERE id=1').fetchone()[0],'published')
