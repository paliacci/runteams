import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from runteams_core.agents.tools.agent_tool_registry import AgentToolError
from runteams_core.assets.skills.skill_bundles import extension
from runteams_core.authoring.creator_contracts import canonical, compile_source, digest, tree
from runteams_core.authoring.creator_definitions import author_schema, compile_definitions
from runteams_core.authoring.source import creator_source_tool
from runteams_core.authoring.source.creator_source_archive import pack
from runteams_core.authoring.source.creator_source_import import inspect_source
from runteams_core.authoring.source.creator_local_source import LocalSources
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.authoring.source.employee_starters import validate_edit
from runteams_core.employees.employee_directory import source_entries
from runteams_core.storage import product_store


STARTERS = [
    {'title': '整理项目进度', 'prompt': '请整理本周的项目进度。', 'icon': 'doc',
     'translations': {'en': {'title': 'Summarize progress', 'prompt': 'Summarize project progress this week.'}}},
    {'title': 'Flag blockers', 'prompt': 'Flag open blockers in the project.'},
]


def project(examples):
    return {
        'project.json': canonical({'schema': 'runteams.creator-project/2', 'key': 'starter-test',
            'name': 'Starter test', 'version': '1.0.0', 'sdk': 'mcp-apps/1-dev',
            'entrypoints': {'employees': ['employee.json']}, 'dependency_lock': 'dependencies.lock.json',
            'source_access': {'default': 'author', 'public_files': []}}),
        'dependencies.lock.json': canonical({'schema': 'runteams.dependencies/2', 'root': 'starter-test',
            'runtime': {'protocol': 'mcp', 'managed_node': '24'}, 'dependencies': []}),
        'employee.json': canonical({'schema': 'runteams.employee-source/3', 'key': 'employee',
            'name': 'Project assistant', 'avatar': '👤', 'soul_file': 'soul.md', 'skill_dirs': ['skills/project']}),
        'soul.md': b'Summarize project progress.',
        'skills/project/SKILL.md': b'---\nname: project\ndescription: Summarize project progress\n---\n',
        'skills/project/runteams.json': canonical({'schema': 'runteams.package-extension/v3',
            'display_name': 'Project reporting', 'tools': [], 'execution': {},
            'work': {'name': 'Project reporting', 'summary': 'Summarize project progress.',
                'objective': 'Produce a status report.', 'input_schema': {'type': 'object'},
                'output_schema': {'type': 'object'}, 'steps': [{'id': 'read', 'instruction': 'Read the project notes.'}],
                'acceptance': [{'id': 'summary', 'label': 'Summary', 'criterion': 'Summarize the current status.'}],
                'deliverables': [], 'assets': [], 'result_actions': [], 'examples': examples}}),
    }


def source(*counts, translated=True):
    def encode(obj):
        return json.dumps(obj).encode()
    files = {'project.json': encode({'entrypoints': {'employees': ['employee.json']}}),
             'employee.json': encode({'skill_dirs': [str(i) for i in range(len(counts))]})}
    for i, count in enumerate(counts):
        examples = [{'title': f'T{i}{j}', 'prompt': f'P{i}{j}'} for j in range(count)]
        if translated:
            for example in examples:
                example['translations'] = {'zh-CN': {'title': '标题' + example['title'], 'prompt': '提问' + example['prompt']}}
        files[f'{i}/runteams.json'] = encode({'work': {'examples': examples}})
    return files


class StarterLimits(unittest.TestCase):
    def test_limits_across_skills_and_legacy_edit(self):
        for after in (source(1, 1), source(2, 1)):
            validate_edit(source(1), after)
        for after in (source(0), source(1), source(2, 2)):
            with self.assertRaisesRegex(ValueError, '2–3'):
                validate_edit(source(2), after)
        legacy = source(5, translated=False)
        validate_edit(legacy, {**legacy, 'soul.md': b'updated'})
        validate_edit(legacy, source(5))
        with self.assertRaisesRegex(ValueError, '快捷问题的译文无效'):
            validate_edit(source(1, translated=False), source(2, translated=False))
        validate_edit(source(1, translated=False), source(1, 1, translated=True) |
                      {'0/runteams.json': source(1, translated=False)['0/runteams.json']})

    def test_sdk_contract_import_edit_directory_and_portable_package(self):
        from jsonschema import Draft202012Validator

        files = project(STARTERS)
        skill = json.loads(files['skills/project/runteams.json'])
        Draft202012Validator(author_schema('skill')).validate(skill)
        with TemporaryDirectory() as directory:
            store = LocalSources(Path(directory).resolve())
            identity = tree(files)['sha256']
            store.save(pack(files), identity, inspect_source)
            self.assertEqual(source_entries(store, identity)[0]['source']['capabilities'][0]['examples'], STARTERS)

            both = {'en': {'title': 'Flag blockers', 'prompt': 'Flag open blockers in the project.'},
                    'zh-CN': {'title': '发现阻碍', 'prompt': '请指出项目里尚未解决的阻碍。'}}
            updated = [STARTERS[0], {**STARTERS[1], 'translations': both}]
            Revisions(store, identity).commit(project(updated), identity, 'starter-translation')
            self.assertEqual(source_entries(store, identity)[0]['source']['capabilities'][0]['examples'], updated)

        asset = compile_definitions(files, compile_source(files))['employees']['employee.json']
        self.assertEqual(extension(asset['skill_bundles'][0])['work']['examples'], STARTERS)

    def test_incomplete_translations_rejected_on_import_and_edit(self):
        before = project(STARTERS)
        for translations in ({}, None, {'fr': {'title': 'Rapport', 'prompt': 'Rédigez un rapport.'}},
                             {'en': {'title': 'Report'}}, {'zh-CN': {'title': ' ', 'prompt': '整理。'}}):
            after = project([{**STARTERS[0], 'translations': translations}, STARTERS[1]])
            with self.subTest(translations=translations):
                with self.assertRaisesRegex(ValueError, 'translations'):
                    inspect_source(pack(after))
                with self.assertRaisesRegex(ValueError, '快捷问题的译文无效'):
                    validate_edit(before, after)

    def test_rejects_a_copy_of_the_original_as_the_only_translation(self):
        original = {'title': 'Flag blockers', 'prompt': 'Flag open blockers in the project.'}
        copied = {**original, 'translations': {'zh-CN': original}}
        with self.assertRaisesRegex(ValueError, '译文与原文相同'):
            validate_edit(project(STARTERS), project([STARTERS[0], copied]))

    def test_submission_requires_translations_but_legacy_import_and_retry_are_supported(self):
        files = project(STARTERS)
        request = {'action': 'submit', 'files': {path: base64.b64encode(body).decode() for path, body in files.items()}}
        localized = project([STARTERS[0], {**STARTERS[1], 'translations': {
            'zh-CN': {'title': '发现阻碍', 'prompt': '请指出项目里尚未解决的阻碍。'}}}])
        localized_request = {'action': 'submit',
            'files': {path: base64.b64encode(body).decode() for path, body in localized.items()}}
        context = {'chat_id': 1, 'library_id': 'local'}
        scope = {'storage_kind': 'local', 'library_id': 'local', 'cache_scope': 'local'}
        session = {'id': 1, 'context': {}}
        tool = creator_source_tool
        with (patch.object(product_store, 'get_chat', return_value=session),
              patch.object(tool.device_data, 'identity', return_value=scope),
              patch.object(tool.device_data, 'check'), patch.object(tool, '_workspace'),
              patch.object(tool, 'attachment_source', return_value=files),
              patch.object(tool, 'bind', return_value=session),
              patch.object(tool, 'current_store') as store,
              patch('runteams_core.authoring.creator_local_authoring.source')):
            store.return_value.save.return_value = {'id': 'source-id'}
            with self.assertRaisesRegex(AgentToolError, 'invalid_employee_starters'):
                tool.tool(request, context)
            store.assert_not_called()
            tool.tool(localized_request, context)
            tool.tool({'action': 'import', 'attachment_id': 'a' * 24}, context)
            session['context'] = {'creator_local_source_id': 'source-id', 'creator_submission_sha256': digest(request)}
            tool.tool(request, context)
            self.assertEqual(store.return_value.save.call_count, 3)
