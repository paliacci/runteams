"""Versioned, explicitly owned data files accompanying a creator source archive."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import struct
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from runteams_core.authoring.creator_contracts import (
    MAX_BYTES, CreatorContractError, canonical, digest, relative, strict_json,
)
from runteams_core.authoring.source import creator_source_archive as source_archive

INDEX = 'asset-materials.json'
SOURCE = 'runteams-source.zip'
MAX_ARCHIVE = 2 * 1024**3 - 1
MAX_DATA = MAX_ARCHIVE - MAX_BYTES - 4 * 1024**2
MAX_FILES = 8000
CHUNK = 1024**2
TYPES = frozenset('.markdown .png .jpg .jpeg .webp .gif .mp4 .mov .wav .mp3 .m4a .ogg .flac .txt .md .csv .json .srt .vtt .pdf .doc .docx .xls .xlsx'.split())


def invalid(detail):
    return CreatorContractError('invalid_asset_knowledge', detail)


def file_name(name):
    name = relative(name)
    if any(p.startswith('.') or p.casefold() in {'auth.json', 'token.json', 'credentials.json', 'node_modules'}
           or p.endswith((' ', '.')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?', p)
           for p in name.split('/')) or Path(name).suffix.lower() not in TYPES:
        raise invalid('素材须为图片、影音、字幕或资料文件。')
    return name


def owners(files):
    entries = strict_json(files['project.json'])['entrypoints']
    return set(entries['employees'] + entries.get('pipelines', []))


def index(files):
    if INDEX not in files:
        return {}
    value = strict_json(files[INDEX])
    if not isinstance(value, dict) or not value or not value.keys() <= owners(files):
        raise invalid('素材须归属本工程中的员工或智能体团队。')
    count = total = 0
    for records in value.values():
        if not isinstance(records, list) or not records:
            raise invalid('缺少资产素材。')
        names = set()
        for record in records:
            if not isinstance(record, dict) or record.keys() != {'path', 'size', 'sha256'}:
                raise invalid('素材清单无效。')
            name = file_name(record['path']).casefold()
            if name in names or type(record['size']) is not int or record['size'] < 0 or not re.fullmatch('[a-f0-9]{64}', str(record['sha256'])):
                raise invalid('素材路径、大小或校验值无效。')
            names.add(name)
            count += 1
            total += record['size']
        if any(str(p) in names for n in names for p in Path(n).parents):
            raise invalid('素材目录与文件重名。')
    if count > MAX_FILES or total > MAX_DATA:
        raise invalid('素材数量或大小超过上限。')
    return value


@contextmanager
def regular(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise invalid('素材必须是普通文件。')
        yield stream


def copy_checked(source, output, size, expected=None):
    h = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = source.read(min(CHUNK, remaining))
        if not chunk:
            raise invalid('素材内容不完整。')
        remaining -= len(chunk)
        h.update(chunk)
        if output is not None:
            output.write(chunk)
    if source.read(1) or expected is not None and h.hexdigest() != expected:
        raise invalid('素材内容与保存的版本不符。')
    return h.hexdigest()


def inventory(files, folders):
    """Each folder is explicitly chosen by the author for one entry point."""
    result, blobs = {}, {}
    count = total = 0
    for owner, raw in folders.items():
        root = Path(raw)
        if owner not in owners(files) or root.is_symlink() or not root.is_dir():
            raise invalid('请选择资产和对应的素材文件夹。')
        records = []
        for path in sorted(root.rglob('*')):
            if path.name == '.DS_Store':
                continue
            if path.is_symlink():
                raise invalid('素材文件夹中含有链接，请选择实际文件。')
            if path.is_dir():
                continue
            name = file_name(path.relative_to(root).as_posix())
            with regular(path) as stream:
                size = os.fstat(stream.fileno()).st_size
                count += 1
                total += size
                if total > MAX_DATA or count > MAX_FILES:
                    raise invalid('素材超过数量或大小上限。')
                sha = copy_checked(stream, None, size)
            blobs[sha] = path
            records.append({'path': name, 'sha256': sha, 'size': size})
        result[owner] = records
    compiled = {**files, INDEX: canonical(result)}
    index(compiled)
    return compiled, blobs


def unique(mapping):
    result = {}
    for records in mapping.values():
        for row in records:
            sha = row['sha256']
            if result.setdefault(sha, row['size']) != row['size']:
                raise invalid('同一素材的大小不一致。')
    return result


def write_archive(target, files, blob_path):
    with ZipFile(target, 'w', compression=ZIP_STORED) as archive:
        archive.writestr(ZipInfo(SOURCE), source_archive.pack(files))
        for sha, size in sorted(unique(index(files)).items()):
            with regular(blob_path(sha)) as src, archive.open('knowledge/' + sha, 'w') as dst:
                copy_checked(src, dst, size, sha)


def open_archive(stream):
    # Product archives are single-disk, comment-free ZIPs below the ZIP64 threshold.
    size = stream.seek(0, 2)
    if not 22 <= size <= MAX_ARCHIVE:
        raise invalid('资产包大小无效。')
    stream.seek(-22, 2)
    signature, disk, directory_disk, on_disk, count, length, offset, comment = struct.unpack(
        '<4s4H2IH', stream.read(22))
    if (signature != b'PK\x05\x06' or disk or directory_disk or comment or on_disk != count
            or count > MAX_FILES + 1 or length > 4 * 1024**2 or offset + length != size - 22):
        raise invalid('资产包目录无效。')
    stream.seek(0)
    return ZipFile(stream)


def unpack(archive_path, staging):
    """Verify every byte into a caller-owned empty staging folder before adoption."""
    try:
        with regular(archive_path) as stream, open_archive(stream) as archive:
            if os.fstat(stream.fileno()).st_size > MAX_ARCHIVE:
                raise invalid('资产包超过大小上限。')
            if SOURCE not in archive.namelist():
                if os.fstat(stream.fileno()).st_size > MAX_BYTES + 1024**2:
                    raise invalid('资产包缺少工程。')
                stream.seek(0)
                raw = stream.read(MAX_BYTES + 1024**2 + 1)
                files = source_archive.inspect(raw)
                if index(files):
                    raise invalid('资产包缺少素材。')
                return raw, files
            info = archive.getinfo(SOURCE)
            entries = archive.infolist()
            if len(entries) > MAX_FILES + 1 or info.file_size > MAX_BYTES + 1024**2:
                raise invalid('资产包超过大小上限。')
            if any(i.compress_type != ZIP_STORED or i.flag_bits & 1 or i.filename != i.orig_filename or
                   stat.S_IFMT(i.external_attr >> 16) not in (0, stat.S_IFREG) for i in entries):
                raise invalid('资产包格式无效。')
            raw = archive.read(info)
            files = source_archive.inspect(raw)
            expected = unique(index(files))
            names = {SOURCE, *('knowledge/' + sha for sha in expected)}
            if len(entries) != len(names) or set(archive.namelist()) != names or not expected:
                raise invalid('资产包缺少素材或包含未声明文件。')
            for sha, size in expected.items():
                member = archive.getinfo('knowledge/' + sha)
                if member.file_size != size:
                    raise invalid('素材大小与清单不符。')
                with archive.open(member) as src, (staging / sha).open('xb') as dst:
                    copy_checked(src, dst, size, sha)
            return raw, files
    except (BadZipFile, KeyError, EOFError) as error:
        raise invalid('无法读取完整的员工或智能体团队资产包。') from error

