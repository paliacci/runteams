"""Canonical read-only assets in source, wheel and native application builds."""
from pathlib import Path
import sys


def root():
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    package = Path(__file__).resolve().parent
    bundled = package / '_resources'
    if bundled.is_dir():
        return bundled
    source = package.parent
    if (source / 'contracts/product-model-v2.json').is_file() and (source / 'VERSION').is_file():
        return source
    raise RuntimeError('RunTeams core resource payload is missing; rebuild the package.')
