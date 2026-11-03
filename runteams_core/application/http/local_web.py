from runteams_core.foundation.resources import root as resource_root
"""Explicit static inputs for the single shared business UI; no asset-manager page."""
import json
from pathlib import Path
import re
import sys
import uuid

ROOT=resource_root()
ASSETS={key:tuple(value) for key,value in json.loads((Path(__file__).with_name('community_web_assets.json')).read_text()).items()}
# The canonical renderer uses inline event attributes and layout declarations.
# Its executable scripts require a per-response nonce; network remains same-origin.
CSP=("default-src 'none'; script-src 'self' 'nonce-{nonce}'; script-src-attr 'unsafe-inline'; "
     "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' blob: data:; "
     "font-src 'self'; frame-src 'self'; worker-src 'self' blob:; base-uri 'none'; "
     "form-action 'none'; frame-ancestors 'none'; object-src 'none'")


def document(raw,nonce,library_id=None):
    text=raw.decode()
    # Presentation namespace only; API identity still comes from /api/library.
    if library_id is not None:
        display='<meta name="runteams-library-id" content="'+str(uuid.UUID(library_id))+'">'
        text=text.replace('<!-- runteams-device-display-scope -->',display,1)
    text=text.replace('<!-- runteams-host-prelude -->','<script src="/community/application.js"></script><script src="/ui/local-backups.js"></script>',1)
    def tag(match):
        value=match.group(0)
        source=re.search(r'(?:src|href)="([^"?]+)',value.split('>',1)[0])
        if value.startswith('<script'):value=value.replace('<script','<script nonce="'+nonce+'"',1)
        return value
    # Resource composition only: every business function/template stays in the
    # canonical source, without rewriting its implementation or keeping a fork.
    text=re.sub(r'<script\b[^>]*>.*?</script>|<link\b[^>]*>',tag,text,flags=re.S)
    return text.encode()


def read_asset(path,nonce='',library_id=None):
    relative,content_type=ASSETS[path]
    source=ROOT/relative
    if source.is_symlink() or not source.resolve().is_relative_to(ROOT.resolve()):raise OSError('Invalid UI input')
    raw=source.read_bytes()
    if relative=='contracts/page-routes.json':raw=b'window.RunTeamsPageRouteContract='+raw+b';'
    return (document(raw,nonce,library_id) if relative=='web/index.html' else raw),content_type
