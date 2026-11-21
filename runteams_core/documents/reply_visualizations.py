"""Convert an agent's bounded json-render selection to editable document blocks."""

from decimal import Decimal
import hashlib
import json
import math
import re

from runteams_core.foundation.contracts import ContractError

INPUT = {
    'type': 'object',
    'description': (
        'runteams-view v2 object {version:2,title,data,spec:{root,elements}}, '
        'using the same Table, Chart, Messages, Detail and Stack selection as a chat reply. '
        'The chosen views are saved as editable document blocks.'
    ),
}
BLOCK_PREFIX = 'reply-visual-'
FORBIDDEN = {'__proto__', 'constructor', 'prototype'}
MAX_BYTES = 95_000


def _require(condition):
    if not condition:
        raise ContractError('可视化的组件、字段或数据绑定无效，请核对 runteams-view v2 格式。')


def _shape(value, required, optional=()):
    _require(isinstance(value, dict) and set(required) <= value.keys() <= set(required) | set(optional))


def _text(value, maximum):
    _require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum)


def _check_data(value, budget, depth=0):
    budget[0] -= 1
    _require(depth <= 16 and budget[0] >= 0)
    if isinstance(value, dict):
        _require(not FORBIDDEN.intersection(value))
        for child in value.values():
            _check_data(child, budget, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_data(child, budget, depth + 1)
    elif isinstance(value, str):
        _require(len(value) <= 20_000)


def _json_size(value):
    """Measure compact UTF-8 JSON using the browser's number representation."""
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('JSON keys must be strings')
        return 2 + max(0, len(value) - 1) + sum(
            _json_size(key) + 1 + _json_size(child) for key, child in value.items()
        )
    if isinstance(value, list):
        return 2 + max(0, len(value) - 1) + sum(map(_json_size, value))
    if type(value) in (float, int):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('JSON numbers must be finite')
        if number == 0:
            return 1
        shortest = repr(number)
        if 1e-6 <= abs(number) < 1e21:
            decimal = format(Decimal(shortest), 'f')
            return len(decimal.rstrip('0').rstrip('.') if '.' in decimal else decimal)
        mantissa, exponent = shortest.split('e')
        return len(f'{mantissa.removesuffix(".0")}e{int(exponent):+d}')
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))


def is_generated(block):
    return re.fullmatch(r'reply-visual-\d+(?:-\d+)*', block['id']) is not None


def _path(value):
    _require(isinstance(value, str) and len(value) <= 500 and
             (value == '' or value.startswith('/')) and not re.search(r'~(?![01])', value))
    parts = [part.replace('~1', '/').replace('~0', '~') for part in value.split('/')[1:]]
    _require(not FORBIDDEN.intersection(parts))
    return parts


def _get(value, path):
    for part in path:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part) and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _bind(snapshot, binding):
    _shape(binding, ('$state',))
    path = _path(binding['$state'])
    _require(path and path[0] == 'data')
    # A bound null is allowed for Detail. A missing path is a different value.
    wrapped = {'data': snapshot}
    parent = _get(wrapped, path[:-1])
    leaf = path[-1]
    _require(isinstance(parent, dict) and leaf in parent or
             isinstance(parent, list) and re.fullmatch(r'0|[1-9][0-9]*', leaf) and int(leaf) < len(parent))
    return _get(wrapped, path)


def _model(columns, rows):
    _require(isinstance(columns, list) and 1 <= len(columns) <= 12)
    fields = {}
    for column in columns:
        _shape(column, ('key', 'label', 'path'), ('format',))
        key = column['key']
        _require(isinstance(key, str) and re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,49}', key) and
                 key not in FORBIDDEN and key not in fields)
        _text(column['label'], 80)
        kind = column.get('format', 'text')
        _require(kind in ('text', 'number'))
        fields[key] = ({'id': key, 'name': column['label'], 'type': kind}, _path(column['path']))

    result = []
    for row in rows:
        projected = {}
        for key, (column, path) in fields.items():
            value = _get(row, path)
            _require(value is None or type(value) in (str, int, float, bool))
            if isinstance(value, str):
                _require(len(value) <= 2000)
            if column['type'] == 'number':
                _require(value is None or type(value) in (int, float))
            projected[key] = value
        result.append(projected)
    return {'columns': [column for column, _ in fields.values()], 'rows': result}


def compile_blocks(value):
    """Return document display blocks and their document-owned data snapshots."""
    _shape(value, ('version', 'title', 'data', 'spec'))
    _require(value['version'] == 2)
    _text(value['title'], 120)
    _check_data(value, [15_000])
    try:
        size = _json_size(value)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ContractError('可视化数据必须是有效的 JSON。') from exc
    if size > MAX_BYTES:
        raise ContractError('展示数据超过容量，请缩小范围。')
    snapshot = value['data']
    _shape(value['spec'], ('root', 'elements'))
    elements = value['spec']['elements']
    _require(isinstance(elements, dict) and 1 <= len(elements) <= 24)
    seen, blocks, sources = set(), [], {}

    def block(identifier, kind, props, **extra):
        blocks.append({'id': identifier, 'type': kind, 'props': props, 'children': [], **extra})

    def inline(text):
        return [{'type': 'text', 'text': text, 'styles': {}}]

    def visit(key, depth):
        _require(isinstance(key, str) and key not in FORBIDDEN and key in elements and key not in seen and depth <= 6)
        seen.add(key)
        identifier = BLOCK_PREFIX + str(len(seen))
        element = elements[key]
        _shape(element, ('type', 'props', 'children'))
        kind, props, children = element['type'], element['props'], element['children']
        _require(isinstance(kind, str))
        _require(isinstance(children, list) and len(children) <= 12)
        if kind == 'Stack':
            _shape(props, ())
            for child in children:
                visit(child, depth + 1)
            return

        _require(not children and kind in ('Table', 'Chart', 'Messages', 'Detail'))
        fields = {
            'Table': ('items', 'columns'), 'Chart': ('items', 'columns', 'x', 'metrics'),
            'Messages': ('items', 'headline', 'body', 'meta'), 'Detail': ('value',),
        }
        _shape(props, ('title', *fields[kind]))
        title = props['title']
        _text(title, 120)
        if kind == 'Detail':
            source = {'label': title, 'data': _bind(snapshot, props['value'])}
            fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()[:24]
            source_key = BLOCK_PREFIX + fingerprint
            sources[source_key] = source
            block(identifier, 'jsonData', {'title': title, 'source': source_key})
            return

        rows = _bind(snapshot, props['items'])
        _require(isinstance(rows, list) and len(rows) <= 500 and all(isinstance(row, dict) for row in rows))
        if kind == 'Messages':
            _require(isinstance(props['meta'], list) and len(props['meta']) <= 3)
            paths = [_path(path) for path in [props['headline'], *props['meta'], props['body']]]
            block(identifier, 'heading', {'level': 3}, content=inline(title))
            for index, row in enumerate(rows):
                fields = [_get(row, path) for path in paths]
                _require(all(field is None or type(field) in (str, int, float, bool) for field in fields))
                lines = [json.dumps(field) if type(field) is bool else str(field)
                         for field in fields if field is not None and field != '']
                block(f'{identifier}-{index}', 'bulletListItem', {}, content=inline('\n'.join(lines) or '—'))
            return

        model = _model(props['columns'], rows)
        data = json.dumps(model, ensure_ascii=False, separators=(',', ':'))
        if kind == 'Table':
            block(identifier, 'dataTable', {'title': title, 'data': data})
            return
        column_names = {column['id']: column for column in model['columns']}
        x, metrics = props['x'], props['metrics']
        _require(isinstance(x, str) and x in column_names and isinstance(metrics, list) and 1 <= len(metrics) <= 4)
        _require(all(isinstance(metric, str) and column_names.get(metric, {}).get('type') == 'number'
                     for metric in metrics) and len(set(metrics)) == len(metrics))
        for index, metric in enumerate(metrics):
            heading = title if len(metrics) == 1 else f"{title} · {column_names[metric]['name']}"
            block(f'{identifier}-{index}', 'barChart',
                  {'title': heading, 'data': data, 'dataKey': identifier, 'x': x, 'y': metric})

    visit(value['spec']['root'], 0)
    _require(len(seen) == len(elements) and bool(blocks))
    return blocks, sources


def apply(document, value):
    blocks, sources = compile_blocks(value)
    def walk(items):
        for block in items:
            yield block
            yield from walk(block.get('children', []))

    def used_sources(items):
        return {block.get('props', {}).get('source', '') for block in walk(items)}

    generated = [block for block in document['blocks'] if is_generated(block)]
    retained = [block for block in document['blocks'] if not is_generated(block)]
    occupied = {block['id'] for block in walk(retained)}
    # A user may have moved a generated block into a column by hand.
    for block in blocks:
        while block['id'] in occupied:
            block['id'] += '-0'
        occupied.add(block['id'])
    rendered = retained + blocks
    for key in used_sources(generated) - used_sources(rendered):
        if key.startswith(BLOCK_PREFIX):
            document['sources'].pop(key, None)
    document['blocks'] = rendered
    document['sources'].update(sources)
    return document
