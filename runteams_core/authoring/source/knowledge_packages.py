"""Transfer complete asset versions without copying media through the source compiler."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import shutil
import tempfile

from runteams_core.assets import knowledge_archive as media
from runteams_core.authoring.creator_contracts import digest
from runteams_core.authoring.source import creator_source_archive
from runteams_core.authoring.source.creator_source_revisions import Revisions


def location(root, mapping):
    base = root / 'knowledge'
    dest = base / digest(mapping)
    if base.is_symlink() or dest.is_symlink():
        raise media.invalid('资产素材目录无效。')
    return dest


def require(root, files):
    mapping = media.index(files)
    if mapping and not location(root, mapping).is_dir():
        raise media.invalid('请导入含全部素材的完整资产包。')
    return mapping


def install_tree(staged, target):
    target.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        os.rename(staged, target)
    except OSError as error:
        if error.errno not in (errno.EEXIST, errno.ENOTEMPTY) or not target.is_dir() or target.is_symlink():
            raise


def copy_objects(mapping, sources, destination):
    """Collect only declared bytes, once, with the same check used at import."""
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    for sha, size in media.unique(mapping).items():
        with media.regular(sources[sha] / sha) as stream, (destination / sha).open('xb') as out:
            media.copy_checked(stream, out, size, sha)


def receive(store, archive, checker, *, edit=None):
    store.check_scope()
    with tempfile.TemporaryDirectory(prefix='.materials-import-', dir=store.root) as folder:
        stage = Path(folder) / 'objects'
        stage.mkdir(mode=0o700)
        raw, files = media.unpack(archive, stage)
        report = checker(raw)
        if report.get('error') or report.get('scope') != 'local-preflight' or not report.get('source'):
            raise media.invalid('资产内的工程未通过检查。')
        from runteams_core.authoring.creator_contracts import tree
        if report['source'] != tree(files):
            raise media.invalid('资产版本与工程不一致。')
        mapping = media.index(files)
        if edit:
            identity, revision, operation = edit
            revisions = Revisions(store, identity)
            store.check_scope()
            return revisions.commit(files, revision, operation, knowledge_stage=stage if mapping else None)
        return store._persist(raw, report['source']['sha256'], report, knowledge_stage=(stage, mapping) if mapping else None)


@contextmanager
def download(store, identity, revision, entry=None):
    raw = Revisions(store, identity).export(revision)
    files = creator_source_archive.inspect(raw)
    mapping = require(store._directory(identity), files)
    folder = location(store._directory(identity), mapping)
    if entry:
        from runteams_core.authoring.source.selected_asset import selected_source
        from runteams_core.authoring.creator_contracts import strict_json
        entries = strict_json(files['project.json'])['entrypoints']
        kind = 'employee' if entry in entries['employees'] else 'pipeline'
        files = selected_source(files, kind, entry)
        mapping = media.index(files)
        raw = creator_source_archive.pack(files)
    if not mapping:
        import io
        yield io.BytesIO(raw), len(raw)
        return
    with tempfile.TemporaryFile() as output:
        media.write_archive(output, files, lambda key: folder / key)
        size = output.tell()
        output.seek(0)
        store.check_scope()
        yield output, size


def receive_http(handler, store, checker, *, edit=None):
    values = handler.headers.get_all('Content-Length', [])
    if (handler.headers.get_all('Content-Type', []) != ['application/zip'] or
            handler.headers.get_all('Transfer-Encoding') or len(values) != 1 or
            not values[0].isascii() or not values[0].isdigit() or not 0 < int(values[0]) <= media.MAX_ARCHIVE):
        raise media.invalid('请选择完整的资产 ZIP 文件。')
    remaining = int(values[0])
    with tempfile.NamedTemporaryFile(dir=store.root, prefix='.upload-') as out:
        while remaining:
            chunk = handler.rfile.read(min(media.CHUNK, remaining))
            if not chunk:
                raise media.invalid('上传中断，请重新选择资产文件。')
            out.write(chunk)
            remaining -= len(chunk)
        out.flush()
        return receive(store, out.name, checker, edit=edit)


def send_http(handler, store, identity, revision, entry=None):
    with download(store, identity, revision, entry) as (stream, size):
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/zip')
        handler.send_header('Content-Length', str(size))
        handler.send_header('Content-Disposition', 'attachment; filename="runteams-source-' + identity[:12] + '.zip"')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Content-Security-Policy', "sandbox; default-src 'none'")
        handler.send_header('X-RunTeams-Source-Revision', revision)
        handler.end_headers()
        shutil.copyfileobj(stream, handler.wfile, media.CHUNK)


def attach(store, identity, request):
    """Snapshot the folder the author actually selects in the native picker."""
    from runteams_core.conversations.chat_attachments import choose_location
    from runteams_core.authoring.creator_contracts import canonical
    if not isinstance(request, dict) or set(request) != {'owner', 'base_revision', 'operation_key'}:
        raise ValueError('请选择要添加素材的员工或智能体团队。')
    revisions = Revisions(store, identity)
    files = revisions.files_at(request['base_revision'])
    owner = request['owner']
    if owner not in media.owners(files):
        raise ValueError('只能为本工程中的员工或智能体团队添加素材。')
    selected = choose_location('folder', '选择要加入资产知识库的文件夹')
    if not selected:
        return {'cancelled': True}
    prior = require(revisions.root, files)
    updated, sources = media.inventory(files, {owner: selected})
    new = media.index(updated)[owner]
    combined = {r['path']: r for r in prior.get(owner, [])}
    combined.update({r['path']: r for r in new})
    mapping = {**prior, owner: [combined[k] for k in sorted(combined)]}
    updated[media.INDEX] = canonical(mapping)
    media.index(updated)
    previous = location(revisions.root, prior)
    with tempfile.TemporaryDirectory(prefix='.attach-', dir=store.root) as folder:
        stage = Path(folder) / 'objects'
        stage.mkdir()
        for sha, size in media.unique(mapping).items():
            with media.regular(sources.get(sha, previous / sha)) as src, (stage / sha).open('xb') as dst:
                media.copy_checked(src, dst, size, sha)
        store.check_scope()
        return revisions.commit(updated, request['base_revision'], request['operation_key'], knowledge_stage=stage)


def backup_knowledge(root, destination, files):
    mapping = require(root, files)
    if not mapping:
        return
    source = location(root, mapping)
    target = location(destination, mapping) if destination else None
    if target and target.exists():
        return
    if target:
        target.mkdir(mode=0o700, parents=True)
    expected = media.unique(mapping)
    if {f.name for f in source.iterdir()} != set(expected):
        raise media.invalid('备份素材清单与文件不一致。')
    for sha, size in expected.items():
        with media.regular(source / sha) as src:
            if target:
                with (target / sha).open('xb') as dst:
                    media.copy_checked(src, dst, size, sha)
            else:
                media.copy_checked(src, None, size, sha)
