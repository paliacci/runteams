"""Transfer complete asset versions without copying media through the source compiler."""
from contextlib import contextmanager, nullcontext
import errno
import os
from pathlib import Path
import re
import shutil
import tempfile

from runteams_core.assets import knowledge_archive as media
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, digest, strict_json
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



def source_asset_reference(store, identity, files, owner):
    from runteams_core.employees.employee_references import source_reference
    from runteams_core.pipelines.pipeline_references import reference

    store.check_scope()
    entries = strict_json(files['project.json'])['entrypoints']
    if owner in entries['employees']:
        return source_reference(identity, owner)
    if owner in entries.get('pipelines', []):
        return reference(identity, owner)
    raise PermissionError('请选择当前工程中的员工或智能体团队。')


def _personal_bank(store, identity, files, owner):
    from runteams_core.conversations.asset_memory import bank_for
    from runteams_core.storage import device_data

    if not device_data.personal():
        raise PermissionError('请在个人工作区选择知识库资料。')
    return bank_for(source_asset_reference(store, identity, files, owner))


def _selectable_name(name):
    try:
        return '/' not in media.file_name(name)
    except CreatorContractError:
        return False


def personal_choices(store, identity, owner, revision, offset=0):
    from runteams_core.conversations.asset_sources import CATALOG_SIZE
    from runteams_core.storage import device_data

    if type(offset) is not int or offset < 0:
        raise ValueError('资料列表位置无效。')
    files = Revisions(store, identity).files_at(revision)
    bank = _personal_bank(store, identity, files, owner)
    with device_data.connect(readonly=True) as connection:
        rows = connection.execute(
            'SELECT id,name,length(original) FROM asset_sources WHERE bank=? '
            'AND length(original) <= ? ORDER BY name,id', (bank, media.MAX_DATA))
        eligible = [(sid, name, size) for sid, name, size in rows if _selectable_name(name)]
        items = []
        for sid, name, size in eligible[offset:offset + CATALOG_SIZE]:
            with connection.blobopen('asset_sources', 'original', sid, readonly=True) as blob:
                sha = media.copy_checked(blob, None, size)
            items.append({'id': sid, 'name': name, 'size': size, 'sha256': sha})
    store.check_scope()
    end = offset + len(items)
    return {'sources': items, 'total': len(eligible), 'next_offset': end if end < len(eligible) else None}


@contextmanager
def personal_snapshot(store, identity, files, owner, sources, *, on_selected=None):
    """Stage checked originals for the caller's source revision commit."""
    from runteams_core.storage import device_data

    bank = _personal_bank(store, identity, files, owner)
    if not isinstance(sources, list) or len(sources) > media.MAX_FILES:
        raise media.invalid('请选择有效的知识库资料。')
    selected = {}
    for row in sources:
        if (not isinstance(row, dict) or set(row) != {'id', 'sha256'}
                or type(row['id']) is not int or not 0 < row['id'] < 2**53
                or row['id'] in selected or not isinstance(row['sha256'], str)
                or not re.fullmatch('[a-f0-9]{64}', row['sha256'])):
            raise media.invalid('请选择有效的知识库资料。')
        selected[row['id']] = row['sha256']
    if not selected:
        yield files, None
        return

    root = store._directory(identity)
    prior = require(root, files)
    prior_objects = media.unique(prior)
    previous = location(root, prior)
    with tempfile.TemporaryDirectory(prefix='.personal-materials-', dir=store.root) as folder:
        stage = Path(folder) / 'objects'
        stage.mkdir(mode=0o700)
        with device_data.connect(readonly=True) as connection:
            combined = {r['path'].casefold(): r for r in prior.get(owner, [])}
            additions = []
            names = []
            for sid, sha in selected.items():
                row = connection.execute(
                    'SELECT name,length(original) FROM asset_sources WHERE bank=? AND id=?',
                    (bank, sid)).fetchone()
                if row is None or not _selectable_name(row[0]):
                    raise media.invalid('资料已不存在，请刷新后重新选择。')
                name, size = row
                record = {'path': name, 'size': size, 'sha256': sha}
                existing = combined.get(name.casefold())
                if existing and existing != record:
                    raise media.invalid(f'发布包中已有同名资料“{name}”，请重命名后再添加。')
                combined[name.casefold()] = record
                additions.append((sid, sha, size))
                names.append(name)

            mapping = {**prior, owner: sorted(combined.values(), key=lambda r: r['path'])}
            updated = {**files, media.INDEX: canonical(mapping)}
            media.index(updated)
            media.unique(mapping)
            for sid, sha, size in additions:
                target = stage / sha
                with connection.blobopen('asset_sources', 'original', sid, readonly=True) as blob:
                    output = nullcontext() if sha in prior_objects or target.exists() else target.open('xb')
                    with output as out:
                        if media.copy_checked(blob, out, size) != sha:
                            raise media.invalid('所选资料已更新，请刷新后重新选择。')

        copy_objects(prior, {sha: previous for sha in prior_objects}, stage)
        store.check_scope()
        if on_selected is not None:
            on_selected(names)
        yield updated, stage

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
