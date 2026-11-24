"""Give bundled scripts and styles a URL tied to the bytes the browser receives."""
from functools import lru_cache
from hashlib import sha256
import re
import stat
from urllib.parse import parse_qs, urlsplit


# Consume whole inline scripts and comments so examples inside them stay literal.
_TAG = re.compile(rb'<!--.*?-->|(<script\b[^>]*>)(.*?</script\s*>)|(<link\b[^>]*>)', re.S | re.I)
_URL = re.compile(rb' (?:src|href)="(/[-a-zA-Z0-9_./]+\.(?:js|css))(?:\?v=[^"&#\s]*)?"')


@lru_cache(maxsize=512)
def _file_digest(path, stamp):
    return sha256(path.read_bytes()).hexdigest().encode('ascii')


def version_assets(html, locate):
    def replace(match):
        tag = match[1] or match[3]
        asset = _URL.search(tag) if tag else None
        if not asset:
            return match[0]
        url = asset[1].decode('ascii')
        if '..' in url.split('/'):
            return match[0]
        path = locate(url)
        if path is None or path.suffix not in ('.js', '.css'):
            return match[0]
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                return match[0]
            digest = _file_digest(path, (info.st_dev, info.st_ino, info.st_size,
                                         info.st_mtime_ns, info.st_ctime_ns))
        except OSError:
            return match[0]
        return tag[:asset.end(1)] + b'?v=' + digest + tag[asset.end()-1:] + (match[2] or b'')
    return _TAG.sub(replace, html)


def static_cache_control(url, content_type, body):
    if content_type.split(';', 1)[0] in ('text/javascript', 'application/javascript', 'text/css'):
        version = parse_qs(urlsplit(url).query).get('v', [])
        if len(version) == 1 and re.fullmatch(r'[a-f0-9]{64}', version[0]):
            if version[0] == sha256(body).hexdigest():
                return 'private, max-age=31536000, immutable'
    return 'no-store'
