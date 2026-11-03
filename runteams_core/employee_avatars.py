from runteams_core.resources import root as resource_root
"""Portable employee pictures. Shared source/build code, without account services.

Source paths are relative to the project root. Runtime attachments contain the
exact validated bytes; presentation data URLs are derived, never saved identity.
"""
import base64
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import sys
import xml.etree.ElementTree as ET

from .creator_contracts import CreatorContractError, relative, strict_json

MAX_BYTES = 512 * 1024
MEDIA = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
         '.webp': 'image/webp', '.svg': 'image/svg+xml'}
PRESETS = ('ada', 'alan', 'aso-specialist', 'atlas', 'commercial-manager', 'cora',
           'echo', 'grace', 'juno', 'localization-specialist', 'market-analyst',
           'nova', 'product-manager', 'qa-engineer', 'software-architect', 'user-operations')


def bundled(reference):
    return (isinstance(reference, str) and bool(reference) and not reference.startswith(('preset:', 'upload:'))
            and ('/' in reference or '\\' in reference or ':' in reference or reference.startswith(('.', '~'))
                 or PurePosixPath(reference).suffix.lower() in MEDIA))


def validate_image(path, body):
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in MEDIA or not isinstance(body, bytes) or not 0 < len(body) <= MAX_BYTES:
        raise CreatorContractError('invalid_employee_avatar', '头像须为不超过512 KB的 PNG、JPEG、WebP 或静态 SVG。')
    image_errors = (ValueError, OSError, SyntaxError, ET.ParseError)
    if suffix != '.svg':
        from PIL import Image
        image_errors += (Image.DecompressionBombError,)
    try:
        if suffix == '.svg':
            if re.search(br'<!\s*(?:DOCTYPE|ENTITY)', body, re.I):
                raise ValueError()
            root = ET.fromstring(body)
            if root.tag != '{http://www.w3.org/2000/svg}svg':
                raise ValueError()
            tags = {'svg', 'g', 'defs', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline',
                    'polygon', 'linearGradient', 'radialGradient', 'stop', 'clipPath', 'mask',
                    'title', 'desc', 'metadata', 'use', 'filter', 'feBlend', 'feColorMatrix',
                    'feComposite', 'feFlood', 'feGaussianBlur', 'feOffset'}
            nodes = list(root.iter())
            if len(nodes) > 4096:
                raise ValueError()
            metadata = {id(n) for m in nodes if m.tag == '{http://www.w3.org/2000/svg}metadata' for n in m.iter()}
            svg_tags = {'{http://www.w3.org/2000/svg}' + t for t in tags}
            metadata_namespaces = ('{http://purl.org/dc/elements/1.1/}', '{http://purl.org/dc/terms/}',
                                   '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}')
            for node in nodes:
                if node.tag not in svg_tags and not (id(node) in metadata and node.tag.startswith(metadata_namespaces)):
                    raise ValueError()
                for key, value in node.attrib.items():
                    name = key.rsplit('}', 1)[-1].lower()
                    if (name.startswith('on') or name == 'base'
                            or name == 'href' and not re.fullmatch(r'#[A-Za-z0-9_-]+', value)
                            or name == 'style' and value != 'mask-type:luminance'):
                        raise ValueError()
                    if re.search(r'url\s*\(', value, re.I) and not re.fullmatch(r'url\(#[A-Za-z0-9_-]+\)', value):
                        raise ValueError()
        else:
            from PIL import Image
            with Image.open(io.BytesIO(body)) as image:
                expected = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}[suffix]
                if image.format != expected or not 1 <= image.width <= 4096 or not 1 <= image.height <= 4096 or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError()
                image.verify()
    except image_errors as error:
        raise CreatorContractError('invalid_employee_avatar', '头像图片无效，或包含不支持的动态／外部内容。') from error
    return MEDIA[suffix]


def attachment(reference, files):
    if not bundled(reference):
        if reference.startswith('preset:') and reference not in {'preset:bottts:' + key for key in PRESETS}:
            raise CreatorContractError('invalid_employee_avatar', '预设头像不存在。')
        if reference.startswith('upload:') and not re.fullmatch(r'upload:[a-f0-9]{64}\.webp', reference):
            raise CreatorContractError('invalid_employee_avatar', '上传头像引用无效。')
        return None
    path = relative(reference)
    body = files.get(path)
    validate_image(path, body)
    return {'sha256': hashlib.sha256(body).hexdigest(), 'content_base64': base64.b64encode(body).decode('ascii')}


def verify_attachment(reference, value):
    if not isinstance(value, dict) or set(value) != {'sha256', 'content_base64'} or not isinstance(value['content_base64'], str) or len(value['content_base64']) > (MAX_BYTES + 2) // 3 * 4:
        raise CreatorContractError('invalid_employee_avatar', '头像附件无效。')
    try:
        body = base64.b64decode(value['content_base64'], validate=True)
    except (ValueError, TypeError) as error:
        raise CreatorContractError('invalid_employee_avatar') from error
    relative(reference)
    media = validate_image(reference, body)
    if hashlib.sha256(body).hexdigest() != value['sha256']:
        raise CreatorContractError('invalid_employee_avatar', '头像附件摘要不一致。')
    return 'data:' + media + ';base64,' + value['content_base64']


def identity(employee, *, files=None, avatar_file=None):
    result = {key: employee[key] for key in ('name', 'avatar')}
    if bundled(result['avatar']):
        value = attachment(result['avatar'], files) if files is not None else avatar_file
        result['avatar_src'] = verify_attachment(result['avatar'], value)
    return result


def validate_sources(files):
    """Validate identities only; ordinary source editing need not build programs."""
    project = strict_json(files['project.json'])
    for path in project['entrypoints']['employees']:
        employee = strict_json(files[path])
        if not isinstance(employee.get('name'), str) or not employee['name'].strip() or len(employee['name']) > 160 or not isinstance(employee.get('avatar'), str) or not employee['avatar'] or len(employee['avatar']) > 180:
            raise CreatorContractError('invalid_employee_identity', '员工名字或头像无效。')
        attachment(employee['avatar'], files)


def preset_items():
    return [{'id': key, 'avatar': 'preset:bottts:' + key,
             'asset_avatar': prepare_picture('preset:bottts:' + key)[0],
             'src': '/worker-avatars/bottts/' + key + '.svg'} for key in PRESETS]


def prepare_picture(value):
    """UI selection is converted to portable bytes before the atomic revision."""
    if isinstance(value, str) and value.startswith('preset:bottts:'):
        key = value.removeprefix('preset:bottts:')
        if key not in PRESETS:
            raise ValueError('预设头像不存在。')
        root = resource_root()
        body = (root / 'web/worker-avatars/bottts' / (key + '.svg')).read_bytes()
        suffix = '.svg'
    elif isinstance(value, dict) and set(value) == {'content_base64'}:
        encoded = value['content_base64']
        if not isinstance(encoded, str) or len(encoded) > 6990508:
            raise ValueError('请选择不超过5 MB的图片。')
        from PIL import Image, ImageOps
        try:
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > 5 * 1024 * 1024:
                raise ValueError()
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP') or max(source.size) > 12000 or source.width * source.height > 16 * 1024 * 1024 or min(source.size) < 32 or getattr(source, 'n_frames', 1) != 1:
                    raise ValueError()
                image = ImageOps.exif_transpose(source).convert('RGBA')
                image = ImageOps.fit(image, (512, 512), method=Image.Resampling.LANCZOS)
                output = io.BytesIO(); image.save(output, 'WEBP', quality=88, method=6)
                body = output.getvalue(); suffix = '.webp'
        except (ValueError, OSError, Image.DecompressionBombError) as error:
            raise ValueError('头像图片无效或尺寸过大。') from error
    else:
        raise ValueError('头像选择无效。')
    path = 'assets/avatars/' + hashlib.sha256(body).hexdigest() + suffix
    validate_image(path, body)
    return path, body


def edit(store, source_id, body):
    """Same revision/receipt ledger as the Agent and source editor."""
    from .creator_source_revisions import Revisions
    from .creator_contracts import canonical
    if not isinstance(body, dict) or set(body) != {'base_revision', 'operation_key', 'employee_source', 'name', 'avatar'}:
        raise ValueError('员工资料保存参数无效。')
    revisions = Revisions(store, source_id)
    files = revisions.files_at(body['base_revision'])
    project = strict_json(files['project.json']); path = body['employee_source']
    if path not in project['entrypoints']['employees']:
        raise PermissionError('这份员工不属于当前工程。')
    employee = strict_json(files[path]); avatar = body['avatar']
    if avatar != employee.get('avatar'):
        if isinstance(avatar, dict) or isinstance(avatar, str) and avatar.startswith('preset:bottts:'):
            avatar, picture = prepare_picture(avatar); files[avatar] = picture
        elif not bundled(avatar):
            raise ValueError('请选择图片或使用包内头像。')
    employee = {**employee, 'name': body['name'], 'avatar': avatar}
    files[path] = canonical(employee) + b'\n'
    validate_sources(files)
    result = revisions.commit(files, body['base_revision'], body['operation_key'])
    return {**result, 'identity': identity(employee, files=files)}
