import sqlite3
import unittest
from unittest.mock import patch

from runteams_core.automation import composio_realtime, fireflies_recaps


class ConnectedEmployeeAutomationsTest(unittest.TestCase):
    def test_gmail_event_accepts_only_the_pinned_inbox(self):
        metadata = {'connected_account_id': 'ca_a', 'user_id': 'user', 'trigger_id': 'ti_a',
                    'trigger_slug': composio_realtime.GMAIL_TRIGGER}
        binding = dict(account='ca_a', user='user', trigger='ti_a')
        payload = {'id': 'abc000012345', 'label_ids': ['INBOX']}
        event = {'type': 'composio.trigger.message', 'metadata': metadata, 'data': payload}
        operation = composio_realtime.gmail_operation(event, **binding)
        self.assertIsNotNone(operation)
        self.assertEqual(operation, composio_realtime.gmail_operation(
            {**event, 'data': {**payload, 'message_text': 'private body'}}, **binding))
        self.assertIsNone(composio_realtime.gmail_operation(event, **{**binding, 'account': 'ca_other'}))
        payload['label_ids'].append('SENT')
        self.assertIsNone(composio_realtime.gmail_operation(event, **binding))

    def test_review_and_delivery_use_same_meeting_and_never_repeat_an_ambiguous_send(self):
        cfg = {'recipient': 'owner@example.com', 'eva_public': 'local-test', 'eva_employee_id': 4}
        meeting = {'id': '01M7EK000TEST', 'title': '【Eva纪要】测试', 'privacy': 'owner', 'is_live': False,
                   'organizer_email': cfg['recipient'], 'meeting_link': 'https://meet.google.com/abc-defg-hij',
                   'sentences': [{'index': 0, 'speaker_name': 'Riley', 'text': 'Check the transcript.'}]}
        identifier = meeting['id']
        marker = 'EVA-FIREFLIES-' + identifier
        self.assertFalse(fireflies_recaps.opted_in({**meeting, 'privacy': 'link'}, cfg))
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE recaps(id TEXT PRIMARY KEY,state TEXT,mail_id TEXT,changed_at TEXT)')
        messages, calls = [], []

        def turn(key, prompt):
            self.assertEqual(key, marker)
            messages.append({'role': 'user', 'text': prompt})
            messages.append({'role': 'bot', 'text': f'<eva-recap id="{marker}">Riley 检查逐字稿。</eva-recap>'})

        def gmail(tool, args):
            calls.append(tool)
            if tool == 'GMAIL_SEND_EMAIL':
                self.assertEqual(args['recipient_email'], cfg['recipient'])
                self.assertNotIn('cc', args)
                return {'id': 'expected-mail'}
            return {'messages': [{'id': 'expected-mail'}]}

        with patch.object(fireflies_recaps, 'fireflies', return_value={'transcript': meeting}):
            for _ in range(3):
                fireflies_recaps.process(db, identifier, 'placeholder', cfg,
                    history=lambda: {'public_id': cfg['eva_public'], 'subject_type': 'employee',
                                     'employee_id': cfg['eva_employee_id'], 'messages': messages},
                    turn=turn, gmail_for_recipient=lambda: gmail, stopped=lambda: False)
            self.assertEqual(calls, ['GMAIL_SEND_EMAIL', 'GMAIL_FETCH_EMAILS'])
            self.assertEqual(db.execute('SELECT state FROM recaps').fetchone()[0], 'delivered')
            db.execute("UPDATE recaps SET state='sending',mail_id=NULL")
            fireflies_recaps.process(db, identifier, 'placeholder', cfg, history=None, turn=None,
                                    gmail_for_recipient=lambda: lambda *args: {'messages': []}, stopped=lambda: False)
            self.assertEqual(calls, ['GMAIL_SEND_EMAIL', 'GMAIL_FETCH_EMAILS'])
