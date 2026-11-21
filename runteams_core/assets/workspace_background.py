"""A workspace background is a static image owned by its asset."""
import base64
from collections import OrderedDict
from pathlib import PurePosixPath
from threading import Lock

from runteams_core.authoring.creator_contracts import CreatorContractError, relative, strict_json


SOURCE_SCHEMA = {'type': 'string', 'minLength': 1, 'maxLength': 240,
                 'description': '工程根目录相对路径。支持随包保存的静态 PNG、JPEG 或 WebP。'}
_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
_MAX_BYTES = 5 * 1024 * 1024
_ERROR = '背景图必须是包内不超过 5 MB、最长边不超过 4096 像素的静态 PNG、JPEG 或 WebP。'
_colors = OrderedDict()
_color_lock = Lock()


def _path(value):
    path = relative(value)
    if PurePosixPath(path).suffix.lower() not in _SUFFIXES:
        raise CreatorContractError('invalid_workspace_background', _ERROR)
    return path


def source_fields(source, files):
    if 'workspace_background' not in source:
        return {}
    from runteams_core.employees.employee_avatars import attachment
    path = _path(source['workspace_background'])
    try:
        picture = attachment(path, files, max_bytes=_MAX_BYTES)
    except CreatorContractError as error:
        raise CreatorContractError('invalid_workspace_background', _ERROR) from error
    return {'workspace_background': {'path': path, **picture}}


def image_src(asset):
    if 'workspace_background' not in asset:
        return ''
    from runteams_core.employees.employee_avatars import verify_attachment
    picture = asset['workspace_background']
    if not isinstance(picture, dict) or set(picture) != {'path', 'sha256', 'content_base64'}:
        raise CreatorContractError('invalid_workspace_background', _ERROR)
    path = _path(picture['path'])
    try:
        return verify_attachment(path, {k: picture[k] for k in ('sha256', 'content_base64')}, max_bytes=_MAX_BYTES)
    except CreatorContractError as error:
        raise CreatorContractError('invalid_workspace_background', _ERROR) from error


def display_fields(asset, *, files=None):
    # A draft with a missing image can still open so its author can repair it.
    try:
        packed = asset if files is None else source_fields(asset, files)
        image = image_src(packed)
    except CreatorContractError:
        return {}
    if not image:
        return {}
    color = _background_color(packed['workspace_background'])
    return {'workspace_background_src': image, **({'workspace_background_color': color} if color else {})}


def _background_color(picture):
    key = picture['sha256']
    with _color_lock:
        if key in _colors:
            _colors.move_to_end(key)
            return _colors[key]
    from runteams_core.assets.workspace_color import representative_color
    kind = PurePosixPath(picture['path']).suffix.lower().lstrip('.')
    color = representative_color(base64.b64decode(picture['content_base64']), 'jpeg' if kind == 'jpg' else kind)
    result = ','.join(map(str, color)) if color else None
    with _color_lock:
        _colors[key] = result
        if len(_colors) > 128:
            _colors.popitem(last=False)
    return result


def validate_sources(files):
    project = strict_json(files['project.json'])
    entrypoints = project['entrypoints']
    pipelines = entrypoints.get('pipelines')
    for path in (*entrypoints['employees'], *(pipelines if isinstance(pipelines, list) else ())):
        if not isinstance(path, str) or path not in files:
            continue
        try:
            source = strict_json(files[path])
        except CreatorContractError:
            continue  # Incomplete pipeline drafts still use the normal build checks.
        if isinstance(source, dict):
            source_fields(source, files)
