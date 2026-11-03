"""Check the PDF attachment implementation against a fixed standards fixture."""
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from runteams_core.conversations import chat_attachments


class PDFAttachments(unittest.TestCase):
    def test_two_page_text_and_images(self):
        raw = (Path(__file__).parent / 'fixtures/two-pages.pdf').read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            result = chat_attachments._normalize_pdf(raw, 'brief.pdf', directory, 'pdf')
            self.assertEqual([x['kind'] for x in result], ['text', 'image', 'image'])
            self.assertEqual([x['stored_name'] for x in result], ['pdf/content.txt', 'pdf/page-001.png', 'pdf/page-002.png'])
            self.assertIn('Page 2 content', (Path(directory) / 'content.txt').read_text())
            for name in ('page-001.png', 'page-002.png'):
                with Image.open(Path(directory) / name) as image:
                    self.assertEqual(image.size, (480, 360))

    def test_invalid_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                chat_attachments._normalize_pdf(b'%PDF-broken', 'broken.pdf', directory, 'pdf')


if __name__ == '__main__':
    unittest.main()
