"""Pipeline asset icons use the same validated picture format as employees."""
from runteams_core.authoring.creator_contracts import CreatorContractError
from runteams_core.employees import employee_avatars


def source_attachment(reference, files):
    picture = employee_avatars.attachment(reference, files)
    if picture is None and not employee_avatars.preset_src(reference):
        raise CreatorContractError('invalid_pipeline_avatar', '请选择预设图标或使用随源码保存的图片。')
    return picture


def source_fields(asset, files):
    if 'avatar' not in asset:
        return {}
    reference = asset['avatar']
    picture = source_attachment(reference, files)
    return {'avatar': reference, **({'avatar_file': picture} if picture else {})}


def image_src(asset):
    reference = asset.get('avatar')
    if employee_avatars.bundled(reference):
        return employee_avatars.verify_attachment(reference, asset.get('avatar_file'))
    if 'avatar_file' in asset:
        raise CreatorContractError('invalid_pipeline_avatar', '智能体团队图标附件与引用不匹配。')
    if reference is None:
        return ''
    url = employee_avatars.preset_src(reference)
    if not url:
        raise CreatorContractError('invalid_pipeline_avatar', '预设图标不存在。')
    return url
