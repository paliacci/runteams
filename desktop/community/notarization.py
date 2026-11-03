"""Resumable App/DMG notarization. No credentials, updater or publisher is bundled."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import shutil
import uuid

from desktop.macos_signing import signature,verify_release_app
from runteams_core.devtools.package_desktop_dmg import package


class PendingNotarization(ValueError):
    pass


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    from runteams_core.storage.backups.backup_files import replace_json
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    replace_json(path,value)


class Workflow:
    def __init__(self,app,dmg,signer,profile,state,*,keychain=None,resume=False):
        if signer.local:raise ValueError('Local builds cannot request notarization')
        if not profile or profile.startswith('-') or len(profile)>128 or any(ord(c)<32 for c in profile):
            raise ValueError('Provide a saved notarytool --notary-profile; never pass passwords in build arguments')
        self.app=Path(app).expanduser().absolute();self.dmg=Path(dmg).expanduser().absolute()
        self.signer=signer;self.path=Path(state).expanduser().absolute()
        if self.path.is_symlink() or self.app.is_symlink() or self.dmg.is_symlink():raise ValueError('Release paths cannot be symbolic links')
        self.credentials=['--keychain-profile',profile]
        if keychain:self.credentials+=['--keychain',str(Path(keychain).expanduser().absolute())]
        version=verify_release_app(self.app,signer)
        _,metadata=signature(self.app)
        binding={'app':str(self.app),'dmg':str(self.dmg),'identity':signer.identity,'team':signer.team,
                 'profile':profile,'keychain':str(Path(keychain).expanduser().absolute()) if keychain else None,
                 'version':version,'cdhash':metadata['CDHash'][0],
                 'bootstrap_sha256':sha(self.app/'Contents/Resources/bootstrap.json')}
        if self.dmg.suffix!='.dmg' or self.app.suffix!='.app' or self.app in self.path.parents or self.path==self.dmg:
            raise ValueError('Notary state must be outside the App and separate from the DMG')
        import fcntl
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock_fd=os.open(str(self.path)+'.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:fcntl.flock(self.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:os.close(self.lock_fd);self.lock_fd=None;raise
        try:self.initialize(binding,resume)
        except BaseException:self.close();raise

    def initialize(self,binding,resume):
        if resume:
            self.value=json.loads(self.path.read_bytes())
            if self.value.get('schema')!='runteams.community-notarization/1' or self.value.get('binding')!=binding:
                raise ValueError('Resume requires the exact original signed App, destinations and credential profile')
            work=Path(self.value['work'])
            if work.parent!=self.path.parent or not work.name.startswith('.community-notary-') or work.is_symlink():
                raise ValueError('Invalid notarization workspace')
        else:
            if self.path.exists() or self.dmg.exists():raise ValueError('Choose new release outputs, or explicitly --resume the original receipt')
            self.path.parent.mkdir(parents=True,exist_ok=True)
            work=Path(tempfile.mkdtemp(prefix='.community-notary-',dir=self.path.parent))
            self.value={'schema':'runteams.community-notarization/1','binding':binding,'work':str(work),'stages':{},'complete':False}
            save(self.path,self.value)
        self.work=work

    def persist(self):save(self.path,self.value)

    def command(self,*arguments,timeout=60):
        return subprocess.run(['/usr/bin/xcrun','notarytool',*arguments,*self.credentials],capture_output=True,text=True,timeout=timeout)

    def notarize(self,name,path):
        path=Path(path);stages=self.value['stages'];digest=sha(path)
        if name not in stages:
            stages[name]={'archive':str(path),'sha256':digest,'status':'new'};self.persist()
        stage=stages[name]
        if stage['archive']!=str(path) or stage['sha256']!=digest:raise ValueError('Submitted artifact changed; do not resubmit or replace it')
        if stage['status']=='submission_unknown':
            raise ValueError('Previous submission result is unknown. Inspect the original Apple history; no automatic resubmission is allowed.')
        if stage['status']=='new':
            authentication=self.command('history','--output-format','json',timeout=30)
            if authentication.returncode:raise ValueError('无法验证已保存的公证 profile；尚未上传安装包。')
            # Persist before uploading. A lost upload receipt must never cause another submit.
            stage['status']='submission_unknown';self.persist()
            result=self.command('submit',str(path),'--output-format','json',timeout=300)
            try:
                received=json.loads(result.stdout);identifier=str(uuid.UUID(received['id']))
            except (ValueError,KeyError,TypeError):
                raise ValueError('Notarization upload result is unknown; original state retained for investigation') from None
            stage.update(submission_id=identifier,status=received.get('status','In Progress'));self.persist()
            if sha(path)!=digest:raise ValueError('Artifact changed during upload')
        identifier=stage.get('submission_id')
        if not identifier:raise ValueError('Missing original Apple submission ID')
        if stage['status'] not in ('Accepted','Invalid','Rejected'):
            result=self.command('wait',identifier,'--timeout','45s','--output-format','json',timeout=60)
            try:received=json.loads(result.stdout)
            except ValueError:raise PendingNotarization('尚未取得 Apple 公证结果；请用相同参数加 --resume 查询原提交。') from None
            if received.get('id')!=identifier:raise ValueError('Apple response does not match the original submission')
            stage['status']=received.get('status','In Progress');self.persist()
        if stage['status'] not in ('Accepted','Invalid','Rejected'):
            raise PendingNotarization('Apple 仍在处理；请用相同参数加 --resume 继续原提交，不要重新构建或上传。')
        log=self.work/(name+'-notary-log.json')
        if not stage.get('log_verified'):
            result=self.command('log',identifier,str(log),timeout=60)
            if result.returncode:raise ValueError('Could not retrieve the original Apple notarization log; receipt retained')
            data=json.loads(log.read_bytes())
            if data.get('jobId',identifier)!=identifier or data.get('sha256',digest)!=digest:
                raise ValueError('Apple log does not match the submitted bytes')
            stage['log']=str(log);stage['warnings']=[x for x in data.get('issues') or [] if x.get('severity')=='warning']
            if stage['status']!='Accepted' or any(x.get('severity')=='error' for x in data.get('issues') or []):
                self.persist();raise ValueError('Apple rejected the submitted artifact; see original notarization log: '+str(log))
            stage['log_verified']=True;self.persist()
        if stage['status']!='Accepted':raise ValueError('Apple did not accept the artifact')
        return stage

    def staple(self,name,path):
        stage=self.value['stages'][name]
        if not stage.get('stapled'):
            subprocess.run(['/usr/bin/xcrun','stapler','staple',str(path)],check=True,capture_output=True,timeout=60)
        subprocess.run(['/usr/bin/xcrun','stapler','validate',str(path)],check=True,capture_output=True,timeout=60)
        if Path(path).suffix=='.dmg':stage['stapled_sha256']=sha(path)
        stage['stapled']=True;self.persist()

    def close(self):
        if getattr(self,'lock_fd',None) is not None:
            os.close(self.lock_fd);self.lock_fd=None

    def finish(self):
        try:return self._finish()
        finally:self.close()

    def _finish(self):
        if self.value.get('complete'):
            if sha(self.dmg)!=self.value['dmg_sha256']:raise ValueError('Completed DMG bytes changed')
            self.assess();return self.report()
        archive=self.work/'application.zip'
        if not archive.exists():
            if 'app' in self.value['stages']:raise ValueError('Original submission ZIP missing; do not rebuild it')
            subprocess.run(['/usr/bin/ditto','-c','-k','--sequesterRsrc','--keepParent',str(self.app),str(archive)],check=True)
        self.notarize('app',archive);self.staple('app',self.app)
        verify_release_app(self.app,self.signer)
        image=self.work/'installer.dmg'
        if not image.exists():
            if 'dmg' in self.value['stages']:raise ValueError('Original submission DMG missing; do not repackage it')
            package(self.app,image,signer=self.signer)
        stage=self.notarize('dmg',image)
        stapled=self.work/'installer-stapled.dmg'
        # Keep submitted transport bytes immutable. Only a disposable copy is stapled.
        if stage.get('stapled'):
            if not stapled.exists() and self.dmg.exists() and sha(self.dmg)==stage['stapled_sha256']:
                self.value['dmg_sha256']=stage['stapled_sha256'];self.assess()
                self.value['complete']=True;self.persist();return self.report()
            if sha(stapled)!=stage['stapled_sha256']:raise ValueError('Stapled DMG changed')
            subprocess.run(['/usr/bin/xcrun','stapler','validate',str(stapled)],check=True,capture_output=True,timeout=60)
        else:
            shutil.copyfile(image,stapled)
            self.staple('dmg',stapled)
        self.signer.verify(stapled)
        subprocess.run(['/usr/bin/hdiutil','verify',str(stapled)],check=True,capture_output=True,timeout=60)
        self.gatekeeper(stapled)
        self.value['dmg_sha256']=sha(stapled);self.persist()
        self.publish(stapled);self.value['complete']=True;self.persist()
        return self.report()

    def publish(self,stapled):
        from runteams_core.storage.backups.backup_files import sync_directory
        expected=self.value['dmg_sha256']
        if self.dmg.exists():
            if sha(self.dmg)!=expected:raise ValueError('Final DMG destination contains different bytes; no overwrite')
            self.assess();return
        self.dmg.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.community-release-',suffix='.dmg',dir=self.dmg.parent)
        try:
            with os.fdopen(fd,'wb') as output,Path(stapled).open('rb') as source:
                shutil.copyfileobj(source,output);os.fchmod(output.fileno(),0o644);output.flush();os.fsync(output.fileno())
            if sha(name)!=expected:raise ValueError('Final DMG copy differs from the accepted image')
            os.link(name,self.dmg)  # No-clobber publication, including across filesystems.
            sync_directory(self.dmg.parent)
        finally:Path(name).unlink(missing_ok=True)

    def assess(self):
        verify_release_app(self.app,self.signer);self.signer.verify(self.dmg)
        for path in [self.app,self.dmg]:subprocess.run(['/usr/bin/xcrun','stapler','validate',str(path)],check=True,capture_output=True,timeout=60)
        self.gatekeeper(self.dmg)

    def gatekeeper(self,image):
        status=subprocess.run(['/usr/sbin/spctl','--status'],check=True,capture_output=True,text=True,timeout=10)
        if status.stdout.strip()!='assessments enabled':
            raise ValueError('Gatekeeper assessments must be enabled; no policy change or bypass is performed')
        subprocess.run(['/usr/sbin/spctl','--assess','--type','execute',str(self.app)],check=True,capture_output=True,timeout=60)
        subprocess.run(['/usr/sbin/spctl','--assess','--type','open','--context','context:primary-signature',str(image)],check=True,capture_output=True,timeout=60)

    def report(self):
        return {'app':str(self.app),'dmg':str(self.dmg),'bytes':self.dmg.stat().st_size,'sha256':self.value['dmg_sha256'],
                'notarized':True,'stapled':True,'gatekeeper_assessed':True,'state':str(self.path),
                'app_submission_id':self.value['stages']['app']['submission_id'],'dmg_submission_id':self.value['stages']['dmg']['submission_id']}
