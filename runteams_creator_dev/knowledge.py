"""Author tooling for the same complete package accepted by the desktop."""
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runteams_core.assets import knowledge_archive as media
from runteams_core.authoring.source.creator_source_archive import inspect_file, pack


def inspect_package(path, staging):
    with media.regular(path) as stream, media.open_archive(stream) as source:
        if media.SOURCE not in source.namelist():
            files = inspect_file(path)
            if media.index(files):
                raise media.invalid('资产包缺少素材。')
            return files
    return media.unpack(path, staging)[1]


def folders_for(files, project, assignments):
    result = {owner: Path(project).parent / 'knowledge' / Path(owner).with_suffix('')
              for owner in media.index(files)}
    for option in assignments:
        owner, sep, folder = option.partition('=')
        if not sep:
            raise ValueError('--knowledge requires entry.json=folder')
        result[owner] = Path(folder)
    return result


def save_package(target, files, blobs):
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent) as directory:
        temp = Path(directory) / 'output.zip'
        if blobs:
            media.write_archive(temp, files, blobs.__getitem__)
        else:
            temp.write_bytes(pack(files))
        with temp.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        os.link(temp, target)
    return sha
