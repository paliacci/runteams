"""Give bundled scripts and styles a URL tied to the bytes the browser receives."""
from functools import lru_cache
from hashlib import sha256
import re
import json
from urllib.parse import parse_qs, urlsplit


# Consume whole inline scripts and comments so examples inside them stay literal.
_TAG = re.compile(rb'<!--.*?-->|(<script\b[^>]*>)(.*?</script\s*>)|(<link\b[^>]*>)', re.S | re.I)
_URL = re.compile(rb' (?:src|href)="(/[-a-zA-Z0-9_./]+\.(?:js|css))(?:\?v=[^"&#\s]*)?"')


@lru_cache(maxsize=4)
def asset_versions(resource_root):
    try:
        return json.loads((resource_root / 'ui-asset-versions.json').read_bytes())
    except FileNotFoundError:
        # A source checkout serves editable, unversioned resources.
        return {}


def version_assets(html, versions):
    if not versions:
        return html
    def replace(match):
        tag = match[1] or match[3]
        asset = _URL.search(tag) if tag else None
        if not asset:
            return match[0]
        url = asset[1].decode('ascii')
        digest = versions.get(url)
        if digest is None:
            return match[0]
        return tag[:asset.end(1)] + b'?v=' + digest.encode('ascii') + tag[asset.end()-1:] + (match[2] or b'')
    return _TAG.sub(replace, html)


def static_cache_control(url, content_type, body):
    if content_type.split(';', 1)[0] in ('text/javascript', 'application/javascript', 'text/css'):
        version = parse_qs(urlsplit(url).query).get('v', [])
        if len(version) == 1 and re.fullmatch(r'[a-f0-9]{64}', version[0]):
            if version[0] == sha256(body).hexdigest():
                return 'private, max-age=31536000, immutable'
    return 'no-store'
