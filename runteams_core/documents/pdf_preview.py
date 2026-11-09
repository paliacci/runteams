"""Render one authorized PDF page as inert pixels and accessible text."""
from base64 import b64encode
from contextlib import closing
from io import BytesIO
import math
from pathlib import Path
import re
from threading import RLock


PDF_LOCK = RLock()
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PAGE_SIDE = 1600


class PDFPreviewError(ValueError):
    pass


def render_pdf_page(source: bytes | str | Path, page: str):
    import pypdfium2 as pdfium

    if not re.fullmatch(r'[1-9][0-9]{0,8}', page):
        raise PDFPreviewError('unavailable')
    if isinstance(source, bytes):
        raw = source
    else:
        with Path(source).open('rb') as stream:
            raw = stream.read(MAX_PDF_BYTES + 1)
    if len(raw) > MAX_PDF_BYTES:
        raise PDFPreviewError('tooLarge')
    if not raw.lstrip().startswith(b'%PDF-'):
        raise PDFPreviewError('unavailable')

    number = int(page)
    with PDF_LOCK:
        try:
            with closing(pdfium.PdfDocument(raw)) as document:
                count = len(document)
                if number > count:
                    raise PDFPreviewError('unavailable')
                with closing(document[number - 1]) as pdf_page:
                    width, height = pdf_page.get_size()
                    if not all(math.isfinite(side) and side > 0 for side in (width, height)):
                        raise PDFPreviewError('unavailable')
                    scale = min(2, MAX_PAGE_SIDE / max(width, height))
                    if min(width, height) * scale < 1:
                        raise PDFPreviewError('unavailable')
                    with closing(pdf_page.render(scale=scale)) as bitmap, bitmap.to_pil() as image:
                        output = BytesIO()
                        image.save(output, 'PNG')
                    with closing(pdf_page.get_textpage()) as text_page:
                        original = text_page.get_text_bounded()[:24000]
        except pdfium.PdfiumError as error:
            reason = 'password' if error.err_code == pdfium.raw.FPDF_ERR_PASSWORD else 'unavailable'
            raise PDFPreviewError(reason) from None
    return {'page': number, 'count': count, 'png': b64encode(output.getvalue()).decode('ascii'), 'text': original}
