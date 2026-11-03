"""Generate SDK inputs/types from exact frozen contracts. No npm lifecycle hooks."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import hashlib
import json
from pathlib import Path

ROOT = source_root()
SUPPORTED = {'type', 'properties', 'required', 'additionalProperties', 'anyOf',
    'const', 'enum', 'items', 'minItems', 'maxItems', 'uniqueItems', 'minLength',
    'maxLength', 'minimum', 'maximum', 'pattern', 'maxProperties'}


def type_of(schema):
    if 'anyOf' in schema:
        return ' | '.join(type_of(s) for s in schema['anyOf'])
    if 'const' in schema: return json.dumps(schema['const'])
    if 'enum' in schema: return ' | '.join(json.dumps(v) for v in schema['enum'])
    kinds = schema.get('type', [])
    if isinstance(kinds, list): return ' | '.join(type_of({**schema, 'type': k}) for k in kinds) or 'JsonValue'
    if kinds == 'array': return 'Array<' + type_of(schema['items']) + '>'
    if kinds == 'object':
        if 'properties' not in schema:
            extra = schema.get('additionalProperties')
            return '{[key: string]: ' + type_of(extra) + '}' if isinstance(extra, dict) else 'JsonObject'
        props = [json.dumps(k) + ('' if k in schema.get('required', []) else '?') + ': ' + type_of(v) for k, v in schema['properties'].items()]
        return '{ ' + '; '.join(props) + ' }' if props else 'Record<string, never>'
    return {'integer': 'number', 'number': 'number', 'string': 'string', 'boolean': 'boolean', 'null': 'null'}[kinds]


def verify_supported(schema):
    unknown = set(schema) - SUPPORTED
    if unknown: raise ValueError('Unsupported contract keyword(s): ' + ','.join(sorted(unknown)))
    for v in schema.get('properties', {}).values(): verify_supported(v)
    for v in schema.get('anyOf', []): verify_supported(v)
    for name in ('items', 'additionalProperties'):
        if isinstance(schema.get(name), dict): verify_supported(schema[name])


def generated():
    outputs = {}
    for profile, names, source in [
        ('runtime', ['system.negotiate', 'data.query', 'data.mutate', 'connection.http'], 'v1/methods.json'),
        ('view', ['context.read', 'context.select', 'context.update', 'draft.set', 'draft.discard', 'operation.invoke'], 'ui-v2/request.schema.json')]:
        raw = (ROOT / 'contracts/creator-system' / source).read_bytes()
        contract = json.loads(raw)
        schemas = contract['methods'] if profile == 'runtime' else {v['properties']['method']['const']: v['properties']['params'] for v in contract['oneOf']}
        schemas = {name: schemas[name] for name in names}
        for schema in schemas.values(): verify_supported(schema)
        directory = 'sdk/' + profile + '/'
        outputs[directory + 'internal/guards.js'] = (ROOT / 'sdk/shared/guards.js').read_text()
        outputs[directory + 'internal/requests.js'] = '// Generated. Run runteams_core/devtools/build_creator_sdk.py.\nexport const requests = ' + json.dumps(schemas, separators=(',', ':')) + ';\n'
        outputs[directory + 'internal/requests.d.ts'] = ('// Generated from the frozen ' + source + '.\n'
            'export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;\n'
            'export interface JsonObject { [key: string]: JsonValue; }\n'
            'export interface Parameters {\n' + ''.join('  ' + json.dumps(name) + ': ' + type_of(schema) + ';\n' for name, schema in schemas.items()) + '}\n')
        outputs[directory + 'contract-provenance.json'] = json.dumps({'schema': 'runteams.sdk-contract-input/1',
            'profile': profile, 'source': 'contracts/creator-system/' + source,
            'sha256': hashlib.sha256(raw).hexdigest(), 'methods': names,
            'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2) + '\n'
        outputs[directory + 'package.json'] = json.dumps({'name': 'runteams-' + profile, 'version': '0.1.0',
            'private': True, 'type': 'module', 'main': './index.js', 'types': './index.d.ts',
            'exports': {'.': {'types': './index.d.ts', 'import': './index.js'}},
            'sideEffects': False, 'license': 'Apache-2.0',
            'files': ['index.js', 'index.d.ts', 'internal', 'contract-provenance.json', 'README.md', 'LICENSE']}, indent=2) + '\n'
        outputs[directory + 'LICENSE'] = (ROOT / 'sdk/LICENSE-APACHE-2.0').read_text()
    return outputs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--check', action='store_true'); args = parser.parse_args()
    for relative, content in generated().items():
        target = ROOT / relative
        if args.check:
            if not target.is_file() or target.read_text() != content: raise SystemExit('Stale SDK generated file: ' + relative)
        else:
            target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content)
    print('Creator SDK contract generation checked' if args.check else 'Creator SDK contracts generated')
