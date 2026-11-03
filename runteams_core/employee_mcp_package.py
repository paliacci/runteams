"""Read-only MCPB admission and immutable local execution resources.

These resources are part of an already authorized employee release, not a new
employee marketplace or a substitute for asset/installation authority. No code,
dependency manager or package lifecycle script runs during inspection/materialization.
"""
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from types import MappingProxyType
import zipfile

from .creator_contracts import canonical, strict_json

MAX_PACKAGE = 256 * 1024 * 1024
MAX_FILES = 10000
_VERSION = re.compile(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?')


class MCPPackageError(ValueError):
    pass


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def safe_path(name):
    if (not isinstance(name, str) or not name or len(name) > 512 or
            '\\' in name or ':' in name or '\0' in name or
            any(p in ('', '.', '..') for p in name.split('/')) or name.startswith('/') or
            any(ord(c) < 32 for c in name)):
        raise MCPPackageError('invalid_package_path')
    return name


def credential_key(key):
    reserved={'PATH','HOME','USERPROFILE','TMPDIR','TEMP','TMP','LANG','NODE_OPTIONS','NODE_PATH','SHELL','BASH_ENV','ENV',
        'OPENAI_API_KEY','ANTHROPIC_API_KEY','CODEX_ACCESS_TOKEN','OPENAI_ACCESS_TOKEN','CLAUDE_CODE_OAUTH_TOKEN','AZURE_OPENAI_API_KEY'}
    return (isinstance(key,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,119}',key) is not None
            and key.upper() not in reserved and not key.upper().startswith(('RUNTEAMS_','LD_','DYLD_','PYTHON')))


def credential_names(manifest):
    """Bound host subset only; no author values/defaults or generic interpolation."""
    declared=manifest.get('user_config',{})
    env=manifest['server'].get('mcp_config',{}).get('env',{})
    if not isinstance(declared,dict) or not isinstance(env,dict) or len(declared)>32 or set(env)!=set(declared):
        raise MCPPackageError('mcp_configuration_requires_host_binding')
    for key,value in declared.items():
        if (not credential_key(key)
                or not isinstance(value,dict) or set(value)-{'type','title','description','sensitive','required'}
                or value.get('type')!='string' or value.get('sensitive') is not True or value.get('required') is not True
                or not isinstance(value.get('title'),str) or not 1<=len(value['title'])<=160
                or 'description' in value and (not isinstance(value['description'],str) or len(value['description'])>500)
                or env[key]!='${user_config.'+key+'}'):
            raise MCPPackageError('mcp_configuration_requires_host_binding')
    return tuple(sorted(declared))


@dataclass(frozen=True)
class MCPBundle:
    digest: str
    _manifest: bytes
    files: dict
    executables: frozenset

    def __post_init__(self):
        object.__setattr__(self, 'files', MappingProxyType(dict(self.files)))

    @property
    def manifest(self):
        return strict_json(self._manifest)

    @classmethod
    def inspect(cls, raw):
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_PACKAGE:
            raise MCPPackageError('package_budget')
        files, folded, total, executables = {}, set(), 0, set()
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if not 1 <= len(entries) <= MAX_FILES:
                    raise MCPPackageError('package_budget')
                for item in entries:
                    # Directory records are not executable resources.
                    name = safe_path(item.filename.rstrip('/') if item.is_dir() else item.filename)
                    mode = item.external_attr >> 16
                    if (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1 or
                            item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or
                            name.casefold() in folded):
                        raise MCPPackageError('invalid_package_entry')
                    folded.add(name.casefold())
                    if item.is_dir():
                        continue
                    total += item.file_size
                    if total > MAX_PACKAGE or item.file_size > 32 * 1024 * 1024:
                        raise MCPPackageError('package_budget')
                    body = archive.read(item)
                    if len(body) != item.file_size:
                        raise MCPPackageError('invalid_package_entry')
                    files[name] = body
                    if mode & 0o111:
                        executables.add(name)
        except (zipfile.BadZipFile, RuntimeError, OSError) as error:
            raise MCPPackageError('invalid_mcp_bundle') from error
        file_names = {n.casefold() for n in files}
        for name in files:
            if any('/'.join(name.split('/')[:i]).casefold() in file_names
                   for i in range(1, len(name.split('/')))):
                raise MCPPackageError('package_path_collision')
        try:
            manifest = strict_json(files['manifest.json'])
            if (not isinstance(manifest, dict) or manifest.get('manifest_version') != '0.3' or
                    not all(isinstance(manifest.get(k), str) and manifest[k].strip()
                            for k in ('name', 'version', 'description')) or
                    not _VERSION.fullmatch(manifest['version']) or
                    not isinstance(manifest.get('author'), dict) or
                    not isinstance(manifest['author'].get('name'), str) or not manifest['author']['name'].strip()):
                raise MCPPackageError('invalid_mcp_manifest')
            server = manifest['server']
            entry = safe_path(server['entry_point'])
            if server['type'] not in ('node', 'binary') or entry not in files:
                raise MCPPackageError('unsupported_mcp_entry')
            config = server.get('mcp_config', {})
            # No shell, floating interpreter, external path or arbitrary env.
            # Exact secret declarations still require a live trusted host lease.
            credential_names(manifest)
            expected = 'node' if server['type'] == 'node' else '${__dirname}/' + entry
            if (config.get('command', expected) != expected or
                    config.get('args', ['${__dirname}/' + entry] if server['type'] == 'node' else []) !=
                    (['${__dirname}/' + entry] if server['type'] == 'node' else [])):
                raise MCPPackageError('mcp_configuration_requires_host_binding')
            compatibility = manifest.get('compatibility', {})
            platforms = compatibility.get('platforms', ['darwin', 'linux', 'win32'])
            architectures=compatibility.get('architectures',['arm64','x86_64'])
            if not isinstance(architectures,list) or not architectures or any(v not in ('arm64','x86_64') for v in architectures):
                raise MCPPackageError('unsupported_mcp_architecture')
            if (not isinstance(platforms, list) or not platforms or
                    any(p not in ('darwin', 'linux', 'win32') for p in platforms) or
                    compatibility.get('runtimes')):
                raise MCPPackageError('unsupported_mcp_compatibility')
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, MCPPackageError):
                raise
            raise MCPPackageError('invalid_mcp_manifest') from error
        if server['type'] == 'binary':
            executables.add(entry)
        return cls(sha256(raw), canonical(manifest), files, frozenset(executables))

    def credential_names(self):
        return credential_names(self.manifest)

    def verify_credential_configuration(self, definition):
        """Every program requirement must be a mandatory native field of its owner.

        This validates declaration alignment only, never current access/ready.
        """
        from .configuration_schema import fields
        declared={field['binding']['key'] for field in fields(definition) if field.get('type')=='secret'
            and field.get('binding',{}).get('provider')=='native_credential' and field.get('required') is True}
        if set(self.credential_names())-declared:raise MCPPackageError('mcp_credential_configuration_missing')

    def materialize(self, root):
        """Content-addressed cache only. Does not install/enable an employee."""
        root = Path(root).absolute()
        if any(p.is_symlink() for p in (root, *root.parents)):
            raise MCPPackageError('invalid_package_root')
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        destination = root / self.digest
        if destination.exists():
            self.verify(destination)
            return destination
        staging = Path(tempfile.mkdtemp(prefix='.mcp-', dir=root))
        try:
            for name, body in self.files.items():
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with target.open('xb') as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                executable = name in self.executables
                target.chmod(0o500 if executable else 0o400)
            try:
                os.rename(staging, destination)
            except OSError:
                if not destination.is_dir():
                    raise
            self.verify(destination)
            return destination
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def verify(self, root):
        root = Path(root)
        if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
            raise MCPPackageError('package_integrity')
        actual = {}
        for path in root.rglob('*'):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise MCPPackageError('package_integrity')
            if stat.S_ISREG(info.st_mode):
                name = path.relative_to(root).as_posix()
                if name not in self.files or info.st_nlink != 1 or info.st_size != len(self.files[name]):
                    raise MCPPackageError('package_integrity')
                if os.name != 'nt' and bool(info.st_mode & 0o111) != (name in self.executables):
                    raise MCPPackageError('package_integrity')
                actual[name] = sha256(path.read_bytes())
        if actual != {name: sha256(body) for name, body in self.files.items()}:
            raise MCPPackageError('package_integrity')

    def summary(self):
        return {'sha256': self.digest, 'name': self.manifest['name'], 'version': self.manifest['version'],
                'author': self.manifest['author']['name'], 'files': len(self.files),
                'code_executed': False, 'enabled': False, 'business_installation_confirmed': False,
                'required_credentials': list(self.credential_names())}
