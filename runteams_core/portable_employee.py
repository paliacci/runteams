"""Verify immutable portable employee bytes; no install, entitlement or IDs allocated."""
import base64
import hashlib
import re
from .contracts import ContractError
from .definition_contracts import validate_definition
from . import skill_bundles


def verify(value):
    asset = validate_definition("marketplace_employee_asset", value)
    if 'configuration' in asset['employee']:
        from .configuration_schema import validate_declaration
        try:
            validate_declaration(asset['employee']['configuration'])
        except ValueError as error:
            raise ContractError(str(error)) from error
    avatar = asset["employee"]["avatar"]
    if avatar.startswith(("/", "~", "file:", "./", "../")) or re.match(r"^[A-Za-z]:[\\/]", avatar):
        raise ContractError("市场头像不能引用本机目录")
    from .employee_avatars import bundled, verify_attachment
    if bundled(avatar):
        verify_attachment(avatar, asset.get('avatar_file'))
    uploaded=re.fullmatch(r'upload:([a-f0-9]{64})\.webp',avatar)
    attachment=asset.get('avatar_file')
    if not bundled(avatar) and bool(uploaded)!=bool(attachment):raise ContractError('市场上传头像缺少可校验资源')
    if attachment and uploaded:
        try:body=base64.b64decode(attachment['content_base64'],validate=True)
        except (ValueError,TypeError):raise ContractError('市场头像资源无效') from None
        if len(body)>5*1024*1024 or len(body)<12 or body[:4]!=b'RIFF' or body[8:12]!=b'WEBP' or hashlib.sha256(body).hexdigest()!=uploaded.group(1) or attachment['sha256']!=uploaded.group(1):
            raise ContractError('市场头像资源摘要无效')
    for bundle in asset["skill_bundles"]:
        skill_bundles.extension(bundle)
    return asset

