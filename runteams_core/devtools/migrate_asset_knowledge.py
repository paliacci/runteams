"""One-time offline relocation of installed knowledge originals without rewriting signed versions."""
import argparse
import hashlib
from pathlib import Path
import re

from runteams_core.assets.knowledge_archive import regular


def migrate(root, *, apply=False):
    root = Path(root).resolve(strict=True)
    moves = []
    for library in root.iterdir():
        if library.is_symlink() or not library.is_dir():
            continue
        for old in library.glob('creator-sources/*/materials'):
            moves.append((old, old.with_name('knowledge')))
        market = library / 'market-materials'
        if market.exists():
            moves.append((market / 'materials', library / 'market-knowledge' / 'knowledge'))
    count = size = 0
    for old, new in moves:
        if (old.resolve() != old or new.resolve() != new or new.exists() or not old.is_dir()):
            raise ValueError('知识库迁移路径冲突。')
        for version in old.iterdir():
            if not re.fullmatch('[0-9a-f]{64}', version.name) or version.is_symlink() or not version.is_dir():
                raise ValueError('素材版本目录无效。')
            for file in version.iterdir():
                with regular(file) as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != file.name:
                        raise ValueError('资料文件校验失败。')
                count += 1
                size += file.stat().st_size
    if apply:
        for old, new in moves:
            new.parent.mkdir(mode=0o700, exist_ok=True)
            old.rename(new)
            if old.parent.name == 'market-materials' and not any(old.parent.iterdir()):
                old.parent.rmdir()
    return {'directories':len(moves),'originals':count,'bytes':size}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device_data', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(migrate(args.device_data, apply=args.apply))
