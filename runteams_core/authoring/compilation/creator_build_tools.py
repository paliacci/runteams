"""Platform-owned build tools. Source packages cannot select tools or scripts."""
import os
from pathlib import Path
import sys
from runteams_core.foundation.resources import root as resource_root

from runteams_core.foundation.content_hashes import sha256 as sha
from runteams_core.authoring.creator_contracts import CreatorContractError, digest, strict_json


def directory():
    # A development host may provision this explicitly. Packaged applications
    # always use their signed resource closure, never an environment override.
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'creator-builder'
    return Path(os.environ.get('RUNTEAMS_CREATOR_BUILDER_DIR',
        str(resource_root() / 'runtime-dependencies/creator-builder'))).resolve()


def load(root=None, *, cancelled=lambda: False, profile='mcp'):
    if profile!='mcp':raise CreatorContractError('platform_builder_unavailable')
    from runteams_core.authoring.compilation.creator_mcp_build import MCPSourceBuilder, identity
    root=Path(root) if root is not None else directory()
    try:
        if any(p.is_symlink() for p in (root,*root.parents)):raise ValueError()
        config=strict_json((root/'toolchain.json').read_bytes())
        if set(config)!={'schema','platform','esbuild'} or config['schema']!='runteams.platform-builder/2':raise ValueError()
        parser=root/'esbuild';pin=config['esbuild']['sha256']
        if parser.is_symlink() or sha(parser.read_bytes())!=pin:raise ValueError()
    except Exception:raise CreatorContractError('platform_builder_unavailable') from None
    return MCPSourceBuilder(esbuild=parser,esbuild_sha256=pin,cancelled=cancelled),digest({'mcp_builder':identity(),'parser':pin})


def load_worker(requested, *, cancelled=lambda: False, profile='mcp'):
    root = Path(requested)
    if getattr(sys, 'frozen', False) and root != directory():
        raise CreatorContractError('builder_integrity')
    return load(root, cancelled=cancelled,profile=profile)
