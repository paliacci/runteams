import json
import unittest

from runteams_core.documents import reply_visualizations, rich_documents
from runteams_core.foundation.contracts import ContractError


def visualization(kind='Chart', **props):
    return {
        'version': 2, 'title': 'Traffic', 'data': {
            'rows': [{'name': 'Mail', 'traffic/total': 120}, {'name': 'Video'}],
        },
        'spec': {'root': 'view', 'elements': {'view': {
            'type': kind, 'children': [], 'props': {'title': 'Traffic', **props},
        }}},
    }


class ReplyVisualizationTests(unittest.TestCase):
    def test_capacity_counts_compact_utf8_bytes(self):
        value = visualization('Detail', value={'$state': '/data/rows/0/name'})
        value['data']['context'] = ['汉' * 10_000] * 3 + ['🙂', 1, 1e-7, 10**20, 0, '']
        compact = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        # The browser spells 1e-07 as 1e-7.
        value['data']['context'][-1] = 'a' * (95_000 - len(compact) + 1)
        value['data']['context'][4:8] = [1.0, 1e-7, 1e20, -0.0]
        reply_visualizations.compile_blocks(value)
        value['data']['context'][-1] += 'a'
        with self.assertRaisesRegex(ContractError, '超过容量'):
            reply_visualizations.compile_blocks(value)

    def test_capacity_bounds_nodes_depth_and_unicode(self):
        value = visualization('Detail', value={'$state': '/data/rows/0/name'})
        deep = None
        for _ in range(16):
            deep = [deep]
        for context in ([None] * 15_000, deep, '\ud800'):
            with self.subTest(context_type=type(context)), self.assertRaises(ContractError):
                value['data']['context'] = context
                reply_visualizations.compile_blocks(value)

    def test_projection_preserves_number_labels_and_missing_cells(self):
        value = visualization(
            items={'$state': '/data/rows'}, x='name', metrics=['visits'],
            columns=[
                {'key': 'name', 'label': 'Channel', 'path': '/name'},
                {'key': 'visits', 'label': 'Visits', 'path': '/traffic~1total', 'format': 'number'},
            ],
        )
        document = rich_documents.from_markdown('Summary')
        for _ in range(2):
            reply_visualizations.apply(document, value)
        blocks = rich_documents.validate(document)['blocks']
        self.assertEqual([block['type'] for block in blocks], ['markdown', 'barChart'])
        self.assertEqual(json.loads(blocks[1]['props']['data']), {
            'columns': [
                {'id': 'name', 'name': 'Channel', 'type': 'text'},
                {'id': 'visits', 'name': 'Visits', 'type': 'number'},
            ],
            'rows': [{'name': 'Mail', 'visits': 120}, {'name': 'Video', 'visits': None}],
        })

    def test_reject_unsafe_actions_and_missing_bindings(self):
        value = visualization('Detail', value={'$state': '/data/rows'})
        value['spec']['elements']['view']['on'] = {'press': {'action': 'send'}}
        with self.assertRaises(ContractError):
            reply_visualizations.compile_blocks(value)
        del value['spec']['elements']['view']['on']
        value['spec']['elements']['view']['props']['value']['$state'] = '/data/missing'
        with self.assertRaises(ContractError):
            reply_visualizations.compile_blocks(value)
