from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from runteams_core.application.http.ui_asset_versions import static_cache_control, version_assets


class AssetVersionTests(unittest.TestCase):
    def test_version_is_bound_to_served_bytes_and_only_external_tags_change(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'example.js'
            path.write_bytes(b'first')
            literal = b'<script>const text=\'<link href="/example.js">\';</script>'
            raw = literal + b'<script src="/example.js?v=old"></script>'
            first = version_assets(raw, lambda url: path)
            url = '/example.js?v=' + sha256(b'first').hexdigest()
            self.assertEqual(first, literal + b'<script src="' + url.encode() + b'"></script>')
            self.assertIn('immutable', static_cache_control(url, 'text/javascript; charset=utf-8', b'first'))
            self.assertEqual(static_cache_control(url, 'text/html', b'first'), 'no-store')
            path.write_bytes(b'second')
            self.assertNotEqual(version_assets(raw, lambda url: path), first)
            self.assertEqual(static_cache_control(url, 'text/javascript', b'second'), 'no-store')
