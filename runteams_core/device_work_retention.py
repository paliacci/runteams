"""Confirmed personal-work trash policy and retryable managed-file cleanup."""
import datetime
import json
import shutil
from pathlib import Path

from .contracts import ContractError

RETENTION_DAYS=30
REQUESTED='device_work.cleanup_requested'
COMPLETED='device_work.cleanup_completed'


class CleanupIncomplete(ContractError):
    def __init__(self):
        super().__init__('本机文件清理尚未完成，请重试。')


def stream(identifier):return 'device-work-cleanup:'+str(int(identifier))


def job_stream(value):
    return ('device-document-cleanup:'+str(int(value['document_id']))
        if value.get('kind')=='document' else stream(value['workflow_id']))


def attachment_files(core,rows,*,strict=True):
    from .device_work import FILE_PREFIX
    refs=set()
    for row in rows:
        meta=json.loads(row['meta_json'] or '{}')
        for ref in meta.get('rich_asset_refs',[]):
            ref=core.repository.storage.canonical_data(ref)
            if not isinstance(ref,str) or not ref.startswith(FILE_PREFIX+'artifacts/rich-assets/'):
                if strict:raise ContractError('文档附件路径无效。')
                continue
            refs.add(core.repository.storage.file_path(ref))
    return refs


def referenced_files(core):
    with core.repository.connect() as connection:
        rows=connection.execute('SELECT ref,meta_json FROM artifacts').fetchall()
    return {row['ref'] for row in rows}|attachment_files(core,rows,strict=False)


def attachment_cleanup(core,connection,rows):
    return {'attachment_refs':sorted(attachment_files(core,rows))}


def request(core,connection,workflow_ids):
    jobs=[]
    for identifier in workflow_ids:
        row=connection.execute('SELECT task_id FROM workflow_runs WHERE id=?',(int(identifier),)).fetchone()
        if not row:continue
        runs=[int(r[0]) for r in connection.execute('SELECT id FROM employee_runs WHERE workflow_run_id=?',(int(identifier),))]
        rows=connection.execute('SELECT a.* FROM artifacts a JOIN employee_runs r ON r.id=a.employee_run_id WHERE r.workflow_run_id=?',(int(identifier),)).fetchall()
        refs=[r['ref'] for r in rows]
        jobs.append({'workflow_id':int(identifier),'task_id':int(row['task_id']),
            'run_ids':runs,'artifact_refs':refs,**attachment_cleanup(core,connection,rows)})
    return jobs


def job(core,identifier):
    with core.repository.connect() as connection:
        row=connection.execute('SELECT data_json FROM events WHERE stream=? AND type=? ORDER BY id DESC LIMIT 1',
            (stream(identifier),REQUESTED)).fetchone()
    return json.loads(row[0]) if row else None


def remove_owned(core,group,name,*,directory):
    """Never follow a managed parent or leaf link into the user's files."""
    core.repository.storage.check_scope()
    parent=Path(core.root)/group;target=parent/name
    if parent.is_symlink():raise CleanupIncomplete()
    if target.is_symlink():target.unlink()
    elif target.exists():
        if directory:shutil.rmtree(target)
        else:target.unlink()


def remove_inputs(core,task_ids):
    for identifier in task_ids or []:
        remove_owned(core,'task-inputs','task-'+str(int(identifier)),directory=True)


def finish(core,value):
    key='trash-document-delete' if value.get('kind')=='document' else 'trash-delete:'+str(int(value['workflow_id']))
    with core.repository.storage.confirmation_lock(key):
        return _finish(core,value)


def _finish(core,value):
    target=job_stream(value)
    with core.repository.connect() as connection:
        if connection.execute('SELECT 1 FROM events WHERE stream=? AND type=? LIMIT 1',
                (target,COMPLETED)).fetchone():return
    try:
        protected=referenced_files(core)
        refs=[core.repository.storage.file_path(ref) for ref in value['artifact_refs']+value.get('attachment_refs',[])]
        refs=[ref for ref in refs if ref not in protected]
        core._delete_artifact_files(refs)
        artifact_root=(Path(core.root)/'artifacts').resolve()
        for ref in refs:
            path=Path(ref).resolve()
            if artifact_root in path.parents and path.is_file():raise CleanupIncomplete()
        if value.get('kind')!='document':
            remove_inputs(core,[int(value['task_id'])])
            remove_owned(core,'workspaces','workflow-'+str(int(value['workflow_id'])),directory=True)
            for run_id in value['run_ids']:
                remove_owned(core,'reviews','quality-review-'+str(int(run_id))+'.jsonl',directory=False)
    except (OSError,ContractError):
        raise CleanupIncomplete() from None
    core.repository.event(target,COMPLETED,{'document_id':value['document_id']} if value.get('kind')=='document'
        else {'workflow_id':value['workflow_id']})


def resume(core):
    with core.repository.connect() as connection:
        rows=connection.execute('SELECT e.data_json FROM events e WHERE e.type=? AND NOT EXISTS '
            '(SELECT 1 FROM events done WHERE done.stream=e.stream AND done.type=?) ORDER BY e.id',
            (REQUESTED,COMPLETED)).fetchall()
    for row in rows:finish(core,json.loads(row[0]))


def purge_tasks(core,*,now=None):
    """Fixed 30-day policy; no client-selected age or cloud fallback."""
    core._actor();resume(core)
    now=now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:raise ValueError('清理时间需要包含时区。')
    cutoff=(now-datetime.timedelta(days=RETENTION_DAYS)).isoformat()
    with core.repository.connect() as connection:
        ids=[int(row[0]) for row in connection.execute('SELECT w.id FROM workflow_runs w JOIN tasks t ON t.id=w.task_id '
            'WHERE t.trashed_at IS NOT NULL AND julianday(t.trashed_at)<=julianday(?) '
            'AND NOT EXISTS(SELECT 1 FROM artifacts a JOIN employee_runs r ON r.id=a.employee_run_id WHERE r.workflow_run_id=w.id)',(cutoff,))]
    count=0
    for identifier in ids:
        try:core.delete_trashed_workflow(identifier,acknowledged_documents=0);count+=1
        except CleanupIncomplete:raise
        except ContractError:continue  # restored or changed after the read
    return count


def delete_document(core,identifier,*,cutoff=None):
    """Reuse the saved full revision lineage; atomically journal byte cleanup."""
    core._actor();identifier=int(identifier)
    with core.repository.storage.confirmation_lock('trash-document-delete'):
        with core.repository.connect() as connection:
            previous=connection.execute('SELECT data_json FROM events e WHERE type=? AND '
                "json_extract(data_json,'$.kind')='document' AND EXISTS "
                "(SELECT 1 FROM json_each(e.data_json,'$.artifact_ids') WHERE value=?) ORDER BY id DESC LIMIT 1",
                (REQUESTED,identifier)).fetchone()
            if previous:
                value=json.loads(previous[0])
            else:
                value=None
        if value is None:
            value=request_document(core,identifier,cutoff=cutoff)
            finish(core,value)
            return True
        finish(core,value)
    return True


def request_document(core,identifier,*,cutoff=None):
    with core.repository.connect() as connection:
        row=connection.execute('SELECT * FROM artifacts WHERE id=? AND trashed_at IS NOT NULL',(identifier,)).fetchone()
        if not row:raise ContractError('垃圾箱中没有这份文档')
        root=core._document_root_id(row)
        rows=[candidate for candidate in core._document_rows(connection,include_trashed=True)
            if core._document_root_id(candidate)==root]
        if any(candidate['trashed_at'] is None for candidate in rows):raise ContractError('请先将整份文档移入垃圾箱')
        if cutoff and any(not connection.execute('SELECT julianday(?)<=julianday(?)',
                (candidate['trashed_at'],cutoff)).fetchone()[0] for candidate in rows):raise ContractError('文档还在保留期内')
        value={'kind':'document','document_id':int(root),'artifact_ids':[int(row['id']) for row in rows],
            'artifact_refs':[row['ref'] for row in rows],**attachment_cleanup(core,connection,rows)}
        for candidate in rows:connection.execute('DELETE FROM artifacts WHERE id=?',(candidate['id'],))
        core.repository.event(job_stream(value),REQUESTED,value,connection=connection)
    return value


def purge_documents(core,*,now=None):
    core._actor();resume(core)
    now=now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:raise ValueError('清理时间需要包含时区。')
    cutoff=(now-datetime.timedelta(days=RETENTION_DAYS)).isoformat()
    with core.repository.connect() as connection:
        ids=[int(row[0]) for row in connection.execute('SELECT min(id) FROM artifacts '
            "GROUP BY coalesce(nullif(json_extract(meta_json,'$.revision_of'),0),id) "
            'HAVING sum(CASE WHEN trashed_at IS NULL OR julianday(trashed_at) IS NULL '
            'OR julianday(trashed_at)>julianday(?) THEN 1 ELSE 0 END)=0',(cutoff,))]
    count=0
    for identifier in ids:
        try:core.delete_trashed_document(identifier,_cutoff=cutoff);count+=1
        except CleanupIncomplete:raise
        except ContractError:continue
    return count


def expire(core):
    # Documents have their own 30-day lifetime. Only afterwards can an old
    # work item without any remaining delivery become eligible for expiry.
    return {'purged_documents':core.purge_expired_documents(),'purged_tasks':core.purge_expired_tasks()}
