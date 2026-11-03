"""Direct launch of the self-contained community application, with no fallback."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def launch(data_directory, port=0, host=None):
    if sys.platform != 'darwin': raise ValueError('原生本机壳当前仅支持macOS。')
    app = Path(host or ROOT / '.build/community/RunTeams Local.app').expanduser().absolute()
    executable = app / 'Contents/MacOS/RunTeamsLocal'
    config = app / 'Contents/Resources/bootstrap.json'
    if app.suffix != '.app' or app.is_symlink() or executable.is_symlink() or not executable.is_file():
        raise ValueError('请先构建免费本机版安装包。')
    value = json.loads(config.read_text())
    if value.get('schema') != 'runteams.community-desktop/3':
        raise ValueError('该应用不是自包含的免费本机版，请重新构建。')
    return subprocess.call([str(executable), '--data-dir', str(Path(data_directory).expanduser().resolve()), '--port', str(port)])
