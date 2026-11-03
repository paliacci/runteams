"""Durable chat directories and verified frozen skill trees for both editions."""
from pathlib import Path
import re
from runteams_core.storage import device_data
from runteams_core.foundation.contracts import ContractError
WORKSPACES="employee-workspaces"

def _directory(path):
    if path.is_symlink():
        raise ContractError('本机员工工作目录不能是符号链接。')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def workspace(chat_id):
    """A conversation keeps its work directory across downloaded asset updates."""
    if not device_data.personal() or not device_data.contains(chat_id):
        raise ContractError('本机员工对话不存在。')
    scope = device_data.identity()
    path = _directory(_directory(device_data.root() / WORKSPACES) / device_data.epoch(chat_id))
    _directory(_directory(path / '.runteams') / 'releases')
    device_data.check(scope)
    return path


def skill_root(path, release_digest):
    """Keep each release's managed source separate from mutable work output."""
    if not isinstance(release_digest, str) or not re.fullmatch('[0-9a-f]{64}', release_digest):
        raise ContractError('员工发布摘要无效。')
    base = _directory(_directory(Path(path) / '.runteams') / 'releases')
    return _directory(_directory(base / release_digest) / 'skills')

