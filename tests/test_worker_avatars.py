import base64
import io
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest import mock

from PIL import Image

import app
import worker_avatars


class WorkerAvatarTests(unittest.TestCase):
    def _image_data(self, size=(96, 64), color=(80, 120, 160)):
        output = io.BytesIO()
        Image.new("RGB", size, color).save(output, "PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")

    def test_presets_have_stable_local_references(self):
        items = worker_avatars.preset_items()
        self.assertEqual(len(items), 16)
        self.assertEqual(len({item["avatar"] for item in items}), 16)
        self.assertTrue(all(item["avatar"].startswith("preset:bottts:") for item in items))
        self.assertTrue(all(item["src"].startswith("/worker-avatars/bottts/") for item in items))

    def test_upload_is_cropped_and_saved_as_managed_webp(self):
        with tempfile.TemporaryDirectory() as data_dir:
            saved = worker_avatars.save_upload({"data": self._image_data()}, data_dir)
            self.assertRegex(saved["avatar"], r"^upload:[a-f0-9]{24}\.webp$")
            path = worker_avatars.upload_path(saved["avatar"], data_dir)
            with Image.open(path) as image:
                self.assertEqual(image.size, (512, 512))
                self.assertEqual(image.format, "WEBP")
            self.assertEqual(worker_avatars.normalize_reference(saved["avatar"], data_dir), saved["avatar"])

    def test_exported_upload_is_restored_with_new_managed_reference(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            saved = worker_avatars.save_upload({"data": self._image_data()}, source_dir)
            bundle = {"workers": [{"key": "w0", "avatar": saved["avatar"]}]}
            exported = worker_avatars.include_export_assets(bundle, source_dir)
            restored = worker_avatars.materialize_import_assets(exported, target_dir)
            new_reference = restored["workers"][0]["avatar"]
            self.assertNotEqual(new_reference, saved["avatar"])
            self.assertTrue(worker_avatars.upload_path(new_reference, target_dir))
            self.assertNotIn("worker_avatar_assets", restored)

    def test_invalid_reference_and_oversized_data_are_rejected(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with self.assertRaisesRegex(ValueError, "头像无效"):
                worker_avatars.normalize_reference("https://example.com/avatar.png", data_dir)
            with self.assertRaisesRegex(ValueError, "5 MB"):
                worker_avatars.save_upload({"data": "a" * (7 * 1024 * 1024)}, data_dir)

    def test_formal_ui_serves_bundled_presets(self):
        with tempfile.TemporaryDirectory() as data_dir, mock.patch.object(
                app.store, "data_dir", return_value=data_dir):
            server = app.Server(("127.0.0.1", 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
            try:
                connection.request("GET", "/api/worker-avatars")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                presets = json.loads(response.read().decode("utf-8"))["presets"]
                self.assertEqual(len(presets), 16)

                connection.request("GET", "/worker-avatars/bottts/ada.svg")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "image/svg+xml")
                self.assertGreater(len(response.read()), 100)

                body = json.dumps({"data": self._image_data()}).encode("utf-8")
                connection.request(
                    "POST", "/api/worker-avatar/upload", body=body,
                    headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                uploaded = json.loads(response.read().decode("utf-8"))
                connection.request("GET", uploaded["src"])
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "image/webp")
                self.assertGreater(len(response.read()), 100)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
