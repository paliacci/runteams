"""Trusted, offline source builder and signed immutable artifact verification."""
import base64
import hashlib
from . import content_hashes
import threading

from .creator_contracts import CreatorContractError, canonical, contract, digest, relative


class ReleaseSigner:
    def __init__(self, private_key):
        self.key = private_key

    @property
    def public_key(self):
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        return base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()

    def sign(self, manifest):
        return {'manifest': manifest, 'sha256': digest(manifest),
            'signature': base64.b64encode(self.key.sign(canonical(manifest))).decode(),
            'key_id': content_hashes.sha256(base64.b64decode(self.public_key))}


def verify_manifest(signed, trusted_keys):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    if not isinstance(signed, dict) or set(signed) != {'manifest', 'sha256', 'signature', 'key_id'}:
        raise CreatorContractError('release_signature')
    manifest = contract('release.schema.json', signed['manifest'])
    if signed['sha256'] != digest(manifest) or signed['key_id'] not in trusted_keys:
        raise CreatorContractError('release_signature')
    try:
        key = base64.b64decode(trusted_keys[signed['key_id']], validate=True)
        if content_hashes.sha256(key) != signed['key_id']:
            raise ValueError()
        Ed25519PublicKey.from_public_bytes(key).verify(base64.b64decode(signed['signature'], validate=True), canonical(manifest))
    except (ValueError, InvalidSignature):
        raise CreatorContractError('release_signature') from None
    return manifest


def verify_release(signed, artifacts, trusted_keys):
    manifest = verify_manifest(signed, trusted_keys)
    expected = {row['path']: row for row in manifest['artifacts']}
    if len(expected) != len(manifest['artifacts']) or set(expected) != set(artifacts):
        raise CreatorContractError('artifact_integrity')
    total = 0
    for path, body in artifacts.items():
        relative(path); total += len(body)
        if len(body) != expected[path]['size'] or content_hashes.sha256(body) != expected[path]['sha256']:
            raise CreatorContractError('artifact_integrity')
    if total > 32 * 1024 * 1024:
        raise CreatorContractError('artifact_limit')
    return manifest


class SignedCreatorBuilder:
    """Backend-owned provider; source callers cannot supply its tools or key."""
    def __init__(self, builder, signer):
        self.builder, self.signer = builder, signer
        self.slots = threading.BoundedSemaphore(2)

    def build(self, files):
        if not self.slots.acquire(blocking=False):
            raise CreatorContractError('builder_busy')
        try:
            # Publication deliberately freezes portable release assets. Local
            # development builds use conversation packages by default.
            built = self.builder.build(files, require_work=True)
            return {'signed': self.signer.sign(built['manifest']), 'artifacts': built['artifacts']}
        finally:
            self.slots.release()
