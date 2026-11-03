"""Canonical immutable-content digest shared by source and runtime verification."""
import hashlib


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

