"""Pure schema rules, called only inside resource-limited validation workers."""
import json
from jsonschema import Draft202012Validator


def check_references(root):
    count = [0]
    def walk(node, ancestors=(), depth=0):
        count[0] += 1
        if depth > 24 or count[0] > 4096 or id(node) in ancestors:
            raise ValueError('schema budget')
        if not isinstance(node, dict):
            return
        ancestors = (*ancestors, id(node))
        if set(node) & {'$id', '$dynamicRef', '$dynamicAnchor', '$recursiveRef', '$recursiveAnchor'}:
            raise ValueError('schema relocation')
        if '$ref' in node:
            ref = node['$ref']
            if not isinstance(ref, str) or ref != '#' and not ref.startswith('#/'):
                raise ValueError('external reference')
            target = root
            for part in ref[2:].split('/') if ref != '#' else []:
                target = target[part.replace('~1', '/').replace('~0', '~')]
            walk(target, ancestors, depth + 1)
        # Traverse schema positions, not arbitrary property names or examples.
        for keyword in ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'):
            for child in node.get(keyword, {}).values():
                walk(child, ancestors, depth + 1)
        for keyword in ('items', 'additionalProperties', 'contains', 'not', 'if', 'then', 'else',
                        'propertyNames', 'unevaluatedProperties', 'unevaluatedItems', 'additionalItems', 'contentSchema'):
            if keyword in node:
                walk(node[keyword], ancestors, depth + 1)
        for keyword in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
            for child in node.get(keyword, []):
                walk(child, ancestors, depth + 1)
    walk(root)


def validate_payload(value):
    # Keep the existing combined author-schema input budget in every runtime.
    if len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')) > 128 * 1024:
        raise ValueError('schema budget')
    for schema in value['schemas']:
        check_references(schema)
        Draft202012Validator.check_schema(schema)
    valid = ('value' not in value or not any(
        Draft202012Validator(value['schemas'][0]).iter_errors(value['value'])))
    if 'values' in value:
        validator = Draft202012Validator(value['schemas'][0])
        valid = valid and all(not any(validator.iter_errors(item)) for item in value['values'])
    if 'instances' in value:
        valid = valid and len(value['instances']) == len(value['schemas']) and all(
            not any(Draft202012Validator(schema).iter_errors(item))
            for schema, item in zip(value['schemas'], value['instances']))
    return valid

