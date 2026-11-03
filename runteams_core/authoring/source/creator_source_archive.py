"""Deterministic source transport. Inspection never extracts or executes files."""
import hashlib
import io
from pathlib import Path
import stat
import zipfile
import zlib

from runteams_core.authoring.creator_contracts import MAX_BYTES, MAX_FILES, CreatorContractError, canonical, relative, source_files, strict_json, tree, _source_tree

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
