"""Original native connection metadata/vault mechanics, shared by explicit hosts.

Concrete hosts own scope checks and authorization. No stored record or bearer
alone creates a connection grant, cloud claim, execution or network client.
"""
import hashlib,hmac,time
from pathlib import Path
from runteams_core import app_secrets; from runteams_core import local_database
from .creator_contracts import CreatorContractError,canonical,digest
from .device_files import _read,_publish


class ConnectionCredentialRecords:
    def _record_path(self, binding): return self.directory/(digest(binding)+'.json')


    def _record(self, binding):
        self.check(); path = self._record_path(binding)
        if not path.exists() and not path.is_symlink(): return None
        row = _read(path)
        if (not isinstance(row, dict) or set(row) != {'data','sha256'} or row['sha256'] != digest(row['data'])
                or row['data'].get('binding') != binding or row['data'].get('state') not in ('pending','authorized','revoking','revoked','rejected')):
            raise CreatorContractError('credential_scope')
        return row['data']


    def _save(self, row):
        self.check()
        # Follow the existing local vault boundary; never write references into
        # the selected work directory or into the cloud business contract.
        directory = self.directory
        for path in (directory.parent.parent, directory.parent, directory):
            if path.is_symlink(): raise CreatorContractError('credential_scope')
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        _publish(directory, directory, self._record_path(row['binding']), canonical({'data':row,'sha256':digest(row)}))


    def _fingerprint(self, token):
        from .execution_host import identity
        native = identity(Path(local_database.DB_PATH).parent)
        return hmac.new(native['secret'].encode(), (digest(self.scope)+'\n'+token).encode(), hashlib.sha256).hexdigest()


    def _credential(self, binding, row):
        from .creator_connection import NativeCredential
        if row is None or row['state'] != 'authorized' or row['expires_at'] <= time.time():
            raise CreatorContractError('credential_scope')
        with app_secrets.vault_scope(self.vault): token = app_secrets.resolve([row['credential_name']]).get(row['credential_name'], '')
        if not token or not hmac.compare_digest(row['fingerprint'], self._fingerprint(token)):
            raise CreatorContractError('credential_scope')
        return NativeCredential(token, row['origin'], frozenset(row['scopes']), row['expires_at'], digest(binding))


