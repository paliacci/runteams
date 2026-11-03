"""Local-only composer references backed by the existing asset grants.

Selection records contain identity, never staged content. Chat carries grant
references; only an accepted work order mounts a bounded read-only copy.
"""
import os
import secrets
import threading
import time

import product_store as store
from runteams_core import local_assets

_picks = {}
_lock = threading.Lock()
_ttl = 15 * 60


def reference(grant_id):
    grant = store.get_local_asset_grant(int(grant_id))
    ok, reason = local_assets.preflight(grant, "本地引用")
    if not ok:
        raise ValueError(reason + "，请重新选择或授权")
    return {"id": "asset-{}".format(grant['id']), "kind": "local_asset",
            "grant_id": grant['id'], "name": grant['name'],
            "local_kind": "file" if os.path.isfile(grant['path']) else "folder"}


def references(ids):
    if not isinstance(ids, list) or len(ids) > 10:
        raise ValueError("一次最多添加 10 个本地引用")
    if any(type(value) is not int or value <= 0 for value in ids):
        raise ValueError('本地引用编号无效')
    return [reference(value) for value in dict.fromkeys(ids)]


def with_input_bindings(refs, bindings=None):
    """Only label references selected with this message; never grant access."""
    if bindings is None:
        return refs
    if not isinstance(bindings, dict) or len(bindings) > 10:
        raise ValueError("资料对应关系无效")
    copied = [dict(r) for r in refs]
    available = {r['grant_id']: r for r in copied if r.get('kind') == 'local_asset'}
    for ref in available.values():
        ref.pop('input_names', None)
    for name, grant_id in bindings.items():
        if (not isinstance(name, str) or not name.strip() or len(name) > 200
                or any(ord(char) < 32 for char in name)
                or type(grant_id) is not int or grant_id not in available):
            raise ValueError("只能使用本次选择的资料")
        available[grant_id].setdefault('input_names', []).append(name)
    return copied


def prepare(paths):
    if not isinstance(paths, list) or not paths or len(paths) > 10:
        raise ValueError("请选择 1–10 个文件或文件夹")
    if any(not isinstance(path, str) or not os.path.isabs(path) or '\x00' in path for path in paths):
        raise ValueError('本地引用必须来自所选文件或文件夹的完整路径')
    # Validate the whole selection before retaining any tokens.
    infos = [store.inspect_local_asset_source(store.validate_local_asset_path(path))
             for path in dict.fromkeys(paths)]
    grants = store.list_local_asset_grants(include_revoked=False)
    ready, pending = [], []
    with _lock:
        cutoff = time.time() - _ttl
        for key in list(_picks):
            if _picks[key]['created_at'] < cutoff:
                del _picks[key]
        for info in infos:
            existing = next((g for g in grants if g['path'] == info['path'] and
                             (g['dev'], g['ino']) == (info['dev'], info['ino'])), None)
            if existing:
                ready.append(dict(reference(existing['id']), path=info['path']))
                continue
            token = secrets.token_hex(16)
            _picks[token] = dict(info, created_at=time.time())
            pending.append(dict(info, token=token))
    return {'references': ready, 'pending': pending}


def confirm(tokens):
    if not isinstance(tokens, list) or not tokens or len(tokens) > 10:
        raise ValueError("本地引用选择无效")
    if any(not isinstance(token, str) for token in tokens):
        raise ValueError('本地引用选择无效')
    with _lock:
        infos = [_picks.get(token) for token in dict.fromkeys(tokens)]
        if any(not info or info['created_at'] < time.time() - _ttl for info in infos):
            raise ValueError("本地引用选择已过期，请重新选择")
        for info in infos:
            path = store.validate_local_asset_path(info['path'])
            current = store.inspect_local_asset_source(path)
            if (current['dev'], current['ino']) != (info['dev'], info['ino']):
                raise ValueError("所选内容已被替换，请重新选择")
        # Tokens stay valid on failure, allowing retry without choosing again.
        result = [reference(store.create_local_asset_grant(info['path'])['id'])
                  for info in infos]
        for token in tokens:
            _picks.pop(token, None)
    return result


def bind_task(action, slots, source):
    """Bind only references frozen with this proposal, never model-supplied paths."""
    current = source.get('local_references') or []
    available = {r['grant_id']: r for r in source.get('available_local_references', current)}
    mapping = action.get('asset_bindings') or {}
    if not isinstance(mapping, dict):
        raise ValueError("本地引用绑定无效")
    names = {slot['name'] for slot in slots}
    if set(mapping) - names:
        raise ValueError("本地引用绑定了不存在的输入")
    for ref in current:
        for name in ref.get('input_names') or []:
            if name in names:
                if name in mapping and mapping[name] != ref['grant_id']:
                    raise ValueError('资料对应关系与交办方案不一致')
                mapping[name] = ref['grant_id']
    if not mapping and len(slots) == 1 and len(current) == 1:
        mapping = {slots[0]['name']: current[0]['grant_id']}
    if current and slots and not mapping:
        raise ValueError("有多个本地引用或输入，请先在对话中明确各输入使用哪个引用")
    if current and any(slot.get('required', True) and slot['name'] not in mapping for slot in slots):
        raise ValueError('请明确每项必填输入使用哪个本地引用')
    for name, grant_id in mapping.items():
        if type(grant_id) is not int or grant_id not in available:
            raise ValueError("只能绑定这项交办方案中用户提供的本地引用")
        ref = reference(grant_id)
        slot = next(s for s in slots if s['name'] == name)
        if (slot.get('type') == 'file' or name in (available[grant_id].get('input_names') or [])) and slot.get('type', 'folder') != ref['local_kind']:
            raise ValueError('「{}」请选择{}'.format(name, '文件夹' if slot['type'] == 'folder' else '文件'))
    used = set(mapping.values())
    # Additional file/folder inputs remain task-scoped and share the existing
    # mount/fingerprint/cleanup machinery, without changing employee releases.
    extra = [r for r in current if r['grant_id'] not in used]
    for r in extra:
        reference(r['grant_id'])
    inputs = []
    for r in extra:
        name = '本次资料：' + r['name'].replace('/', '_').replace('\\', '_')[:80]
        if name in names or any(i['name'] == name for i in inputs):
            name += ' ({})'.format(r['grant_id'])
        inputs.append({'name': name, 'grant_id': r['grant_id']})
    return mapping, inputs


def conversation_source(attachments, history=()):
    current = [r for r in attachments or [] if r.get('kind') == 'local_asset']
    available = {r['grant_id']: r for m in list(history)[-8:] for r in m.get('attachments') or []
                 if r.get('kind') == 'local_asset'}
    available.update({r['grant_id']: r for r in current})
    return {'local_references': current, 'available_local_references': list(available.values())}

