"""Strict Developer ID signing primitives; local ad-hoc signing is explicit."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess

MAGICS = {b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xfe\xed\xfa\xce',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca',b'\xca\xfe\xba\xbf',b'\xbf\xba\xfe\xca'}


def macho(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():return False
    with path.open('rb') as stream:return stream.read(4) in MAGICS


def executable_macho(path):
    with Path(path).open('rb') as stream:
        raw=stream.read(32);magic=raw[:4]
        if magic in (b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca',b'\xca\xfe\xba\xbf',b'\xbf\xba\xfe\xca'):
            order='big' if magic[:1]==b'\xca' else 'little'
            offset=int.from_bytes(raw[16:24] if magic in (b'\xca\xfe\xba\xbf',b'\xbf\xba\xfe\xca') else raw[16:20],order)
            stream.seek(offset);raw=stream.read(16);magic=raw[:4]
        return int.from_bytes(raw[12:16],'little' if magic in (b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe') else 'big')==2


def signature(path):
    value=subprocess.run(['/usr/bin/codesign','-d','--verbose=4',str(path)],check=True,capture_output=True,text=True).stderr
    fields={}
    for line in value.splitlines():
        if '=' in line:
            key,data=line.split('=',1)
            fields.setdefault(key,[]).append(data)
    return value,fields


@dataclass(frozen=True)
class Signer:
    local: bool
    identity: str
    team: str = ''
    keychain: str | None = None

    @classmethod
    def resolve(cls, *, local=False, identity=None, keychain=None):
        if local:
            if identity or keychain:raise ValueError('--local cannot use a signing identity or signing keychain')
            return cls(True,'-')
        command=['/usr/bin/security','find-identity','-v','-p','codesigning']
        if keychain:command.append(str(Path(keychain).expanduser().absolute()))
        result=subprocess.run(command,check=True,capture_output=True,text=True)
        choices=[]
        for line in result.stdout.splitlines():
            match=re.match(r'\s*\d+\)\s+([A-Fa-f0-9]{40})\s+"(Developer ID Application: [^"]+ \(([A-Z0-9]{10})\))"\s*$',line)
            if match and (not identity or identity in (match[1],match[2])):choices.append(match)
        if len(choices)!=1:
            raise ValueError('正式发行需要唯一可用的 Developer ID Application 证书及私钥；请用 --sign-identity 指定。不会回退到 Apple Distribution、开发证书或临时签名。')
        value=choices[0]
        return cls(False,value[1],value[3],str(Path(keychain).expanduser().absolute()) if keychain else None)

    def sign(self,path,*,executable=False):
        command=['/usr/bin/codesign','--force','--sign',self.identity]
        if self.keychain:command+=['--keychain',self.keychain]
        if not self.local:
            command+=['--timestamp']
            if executable:command+=['--options','runtime']
        subprocess.run([*command,str(path)],check=True,capture_output=True)
        self.verify(path,executable=executable)

    def verify(self,path,*,executable=False):
        subprocess.run(['/usr/bin/codesign','--verify','--strict',str(path)],check=True,capture_output=True)
        if self.local:return
        text,fields=signature(path)
        if (fields.get('TeamIdentifier')!=[self.team] or
            not any(x.startswith('Developer ID Application: ') and x.endswith('('+self.team+')') for x in fields.get('Authority',[])) or
            not fields.get('Timestamp') or 'Signature=adhoc' in text or
            executable and not re.search(r'flags=0x[0-9a-fA-F]+\([^)]*\bruntime\b',text)):
            raise ValueError('Developer ID / secure timestamp / hardened runtime validation failed: '+str(path))
        if Path(path).suffix=='.dmg':return
        entitlements=subprocess.run(['/usr/bin/codesign','-d','--entitlements',':-',str(path)],check=True,capture_output=True).stdout.strip()
        if entitlements and plistlib.loads(entitlements).get('com.apple.security.get-task-allow') is True:
            raise ValueError('Debug entitlement is forbidden in a release')


def seal_runtime(root):
    """Reseal our verified staging copy after signing; upstream lock is unchanged."""
    from runteams_core.agent_environment import payload_files, verify_runtime
    root=Path(root);manifest=json.loads((root/'runtime.json').read_bytes())
    manifest['files']=payload_files(root)
    raw=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
    (root/'runtime.json').write_bytes(raw)
    (root/'runtime.sha256').write_text(hashlib.sha256(raw).hexdigest()+'\n')
    verify_runtime(root)


def sign_runtime(root,signer):
    from runteams_core.agent_environment import verify_runtime
    verify_runtime(root)
    for path in sorted(Path(root).rglob('*')):
        if macho(path):signer.sign(path,executable=executable_macho(path))
    seal_runtime(root)


def verify_release_app(app,signer):
    if signer.local:raise ValueError('Local acceptance apps cannot be notarized for distribution')
    app=Path(app)
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    if (info.get('CFBundleIdentifier')!='ai.runteams.community' or info.get('CFBundleExecutable')!='RunTeamsLocal'
        or info.get('RunTeamsLocalBuild') is not False or {'SUFeedURL','SUPublicEDKey'} & set(info)
        or (app/'Contents/Frameworks/Sparkle.framework').exists()):
        raise ValueError('Expected an explicit community release without automatic updates')
    config=json.loads((app/'Contents/Resources/bootstrap.json').read_bytes())
    forbidden={'core/app_update.py','core/sparkle_bridge.py','core/desktop/macos_signing.py','core/desktop/community/notarization.py'}
    if any(row.get('path') in forbidden for row in config.get('inputs',[])):
        raise ValueError('Update or signing infrastructure must not be bundled in community runtime')
    if config.get('schema')!='runteams.community-desktop/3' or config.get('data_directory') is not None:
        raise ValueError('Release must use the canonical library directory')
    if (app/'Contents/Resources/core/VERSION').read_text().strip()!=config['version'] or info['CFBundleShortVersionString']!=config['version'] or info['CFBundleVersion']!=config['version']:
        raise ValueError('Application version fields differ')
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,capture_output=True)
    signer.verify(app,executable=True)
    for path in sorted(app.rglob('*')):
        if macho(path):signer.verify(path,executable=executable_macho(path))
    subprocess.run([str(app/'Contents/MacOS/RunTeamsLocal'),'--check-bootstrap'],check=True,capture_output=True,timeout=30)
    return info['CFBundleShortVersionString']
