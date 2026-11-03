"""Locate explicit build source when tools are used across the two projects."""
import hashlib
import json
import os
from pathlib import Path
import tomllib


def root():
    configured = os.environ.get('RUNTEAMS_CORE_SOURCE')
    if configured and not Path(configured).is_absolute():
        raise ValueError('RUNTEAMS_CORE_SOURCE must be absolute.')
    source = Path(configured) if configured else Path(__file__).resolve().parents[2]
    project = source / 'pyproject.toml'
    if not project.is_file() or tomllib.loads(project.read_text()).get('project', {}).get('name') != 'runteams-core':
        raise ValueError('Run this build tool from the core checkout, or set RUNTEAMS_CORE_SOURCE explicitly.')
    identity = Path(__file__).resolve().parents[1] / 'package_identity.json'
    if identity.is_file():
        for name, expected in json.loads(identity.read_text())['inputs'].items():
            path = source / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Installed build tool/source mismatch: ' + name)
    return source
