"""Deterministic source transport. Inspection never extracts or executes files."""
from contextlib import contextmanager
import hashlib
import io
import os
from pathlib import Path
import stat
import zipfile
import zlib

from runteams_core.authoring.creator_contracts import MAX_BYTES, MAX_FILES, CreatorContractError, canonical, digest, relative, source_files, strict_json, tree, _source_tree

MANIFEST = 'runteams-source.json'
FORMAT = 'runteams.source-archive/1-dev'


def pack(files):
    files = source_files(files)
    manifest = {'schema': FORMAT, 'source': tree(files)}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, body in [(MANIFEST, canonical(manifest)), *[('source/' + p, b) for p, b in files.items()]]:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, body)
    return output.getvalue()


def inspect(raw):
    return inspect_with_tree(raw)[0]


def inspect_with_tree(raw):
    """Return the verified source and its index without re-scanning all bytes."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES + 1024 * 1024:
        raise CreatorContractError('archive_limit')
    return _inspect_stream(io.BytesIO(raw))


def inspect_file_with_tree(path, *, hash_bytes=None):
    """Same checks over an owned seekable input, avoiding a full archive copy."""
    with Path(path).open('rb') as stream:
        if stream.seek(0, 2) > MAX_BYTES + 1024 * 1024:
            raise CreatorContractError('archive_limit')
        stream.seek(0)
        return _inspect_stream(stream, hash_bytes=hash_bytes)


def _inspect_stream(stream, *, hash_bytes=None):
    try:
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if not 2 <= len(entries) <= MAX_FILES + 1:
                raise CreatorContractError('archive_limit')
            files, manifest, seen, total = {}, None, set(), 0
            for info in entries:
                if info.orig_filename != info.filename:
                    raise CreatorContractError('invalid_archive_entry')
                name = relative(info.filename)
                if name.casefold() in seen:
                    raise CreatorContractError('path_collision')
                seen.add(name.casefold())
                mode = info.external_attr >> 16
                if (info.flag_bits & 1 or info.is_dir() or
                        stat.S_IFMT(mode) not in (0, stat.S_IFREG) or
                        info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise CreatorContractError('invalid_archive_entry')
                total += info.file_size
                if total > MAX_BYTES + 256 * 1024 or info.file_size > MAX_BYTES:
                    raise CreatorContractError('archive_limit')
                with archive.open(info) as stream:
                    body = stream.read(info.file_size + 1)
                if len(body) != info.file_size:
                    raise CreatorContractError('archive_integrity')
                if name == MANIFEST:
                    manifest = strict_json(body)
                elif name.startswith('source/'):
                    files[name[7:]] = body
                else:
                    raise CreatorContractError('invalid_archive_entry')
            files = source_files(files)
            folded = {p.casefold() for p in files}
            for name in files:
                parts = name.split('/')
                if any('/'.join(parts[:i]).casefold() in folded for i in range(1, len(parts))):
                    raise CreatorContractError('path_collision')
            source = _source_tree(files, hash_bytes=hash_bytes)
            if manifest != {'schema': FORMAT, 'source': source}:
                raise CreatorContractError('archive_integrity')
            return files, source
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error):
        raise CreatorContractError('invalid_archive') from None


def inspect_file(path):
    with Path(path).open('rb') as stream:
        return inspect(stream.read(MAX_BYTES + 1024 * 1024 + 1))


@contextmanager
def display_files(path, source):
    """Read and verify individual display files without loading unrelated assets."""
    entries = source.get('files')
    if (not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES
            or any(not isinstance(item, dict) or not isinstance(item.get('path'), str)
                   or not isinstance(item.get('sha256'), str) for item in entries)
            or digest(entries) != source.get('sha256')):
        raise CreatorContractError('archive_integrity')
    expected = {item['path']: item for item in entries}
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES + 1024 * 1024:
                raise CreatorContractError('invalid_archive')
            with zipfile.ZipFile(stream) as archive:
                names = archive.namelist()
                if len(names) != len(expected) + 1 or set(names) != {MANIFEST, *('source/' + key for key in expected)}:
                    raise CreatorContractError('archive_integrity')

                class Files:
                    def __contains__(self, name):
                        return name in expected

                    def get(self, name, default=None):
                        entry = expected.get(name)
                        if entry is None:
                            return default
                        relative(name)
                        member = archive.getinfo('source/' + name)
                        if (member.orig_filename != member.filename or member.flag_bits & 1
                                or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG)
                                or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                                or member.file_size != entry.get('size') or member.file_size > MAX_BYTES):
                            raise CreatorContractError('invalid_archive_entry')
                        body = archive.read(member)
                        if hashlib.sha256(body).hexdigest() != entry['sha256']:
                            raise CreatorContractError('archive_integrity')
                        return body

                yield Files()
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error):
        raise CreatorContractError('invalid_archive') from None
