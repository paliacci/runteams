"""Read local Office documents for the knowledge viewer and for source citations."""
from contextlib import closing
from datetime import datetime
import io
import subprocess
import sys
from zipfile import ZipFile

WORD = {'.doc', '.docx'}
EXCEL = {'.xls', '.xlsx'}
FORMATS = WORD | EXCEL
# Bound decoded content, including sparse sheets. Originals remain available to export.
MAX_XML = 64 * 1024**2
MAX_TEXT = 2_000_000
MAX_CELLS = 250_000


def _docx(archive):
    from defusedxml.ElementTree import iterparse
    paragraphs = []
    with archive.open('word/document.xml') as part:
        for _, node in iterparse(part, events=('end',)):
            if node.tag.rsplit('}', 1)[-1] != 'p':
                continue
            parts = []
            for child in node.iter():
                tag = child.tag.rsplit('}', 1)[-1]
                if tag == 't':
                    parts.append(child.text or '')
                elif tag in ('tab', 'br', 'cr'):
                    parts.append('\t' if tag == 'tab' else '\n')
            paragraphs.append(''.join(parts))
            node.clear()
    return '\n'.join(paragraphs)


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.isoformat(sep=' ')
    return str(value)


def _xls_cell(cell, datemode):
    import xlrd
    if cell.ctype == xlrd.XL_CELL_DATE:
        return _cell(xlrd.xldate_as_datetime(cell.value, datemode))
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return str(bool(cell.value))
    if cell.ctype == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(cell.value, '#ERROR!')
    if cell.ctype == xlrd.XL_CELL_NUMBER and cell.value.is_integer():
        return str(int(cell.value))
    return _cell(cell.value)


def _sheets(named_rows):
    sheets = []
    cells = chars = 0
    for name, rows in named_rows:
        sheet = {'name': name, 'rows': []}
        for number, row in enumerate(rows, 1):
            cells += max(1, len(row))
            if cells > MAX_CELLS:
                raise ValueError('工作簿超过可预览的单元格数量。')
            values = [_cell(v) for v in row]
            while values and values[-1] == '':
                values.pop()
            if not values:
                continue
            chars += sum(map(len, values))
            if chars > MAX_TEXT:
                raise ValueError('工作簿正文过长。')
            sheet['rows'].append((number, values))
        sheets.append(sheet)
    return {'kind': 'workbook', 'sheets': sheets}


def preview(suffix, raw):
    from defusedxml.common import DefusedXmlException
    from zipfile import BadZipFile
    from xml.etree.ElementTree import ParseError
    from xlrd import XLRDError
    if isinstance(raw, bytes):
        raw = io.BytesIO(raw)
    try:
        if suffix in ('.docx', '.xlsx'):
            with ZipFile(raw) as archive:
                if sum(i.file_size for i in archive.infolist()) > MAX_XML:
                    raise ValueError('文件解压后过大。')
                if suffix == '.docx':
                    text = _docx(archive)
            if suffix == '.xlsx':
                from openpyxl import load_workbook
                with closing(load_workbook(raw, read_only=True, data_only=True, keep_links=False)) as book:
                    def worksheets():
                        for sheet in book.worksheets:
                            sheet.reset_dimensions()  # Ignore inaccurate dimensions written by some producers.
                            yield sheet.title, sheet.values
                    return _sheets(worksheets())
        elif suffix == '.xls':
            import xlrd
            data = raw.read(MAX_XML + 1)
            if len(data) > MAX_XML:
                raise ValueError('工作簿过大。')
            with xlrd.open_workbook(file_contents=data, on_demand=True, ragged_rows=True) as book:
                def worksheets():
                    for sheet in book.sheets():
                        yield sheet.name, ([_xls_cell(cell, book.datemode) for cell in row] for row in sheet.get_rows())
                return _sheets(worksheets())
        elif suffix == '.doc':
            if sys.platform != 'darwin':
                raise ValueError('此系统暂不支持旧版 Word 正文预览。')
            data = raw.read(MAX_XML + 1)
            if len(data) > MAX_XML:
                raise ValueError('Word 文件过大。')
            converted = subprocess.run(['/usr/bin/textutil', '-convert', 'txt', '-format', 'doc',
                '-encoding', 'UTF-8', '-noload', '-nostore', '-stdin', '-stdout'],
                input=data, capture_output=True, timeout=30, check=True)
            text = converted.stdout.decode('utf-8-sig')
        else:
            raise ValueError('不支持的 Office 文件类型。')
    except (BadZipFile, DefusedXmlException, ParseError, XLRDError, KeyError, IndexError,
            TypeError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise ValueError('无法读取此 Office 文件。请检查原件是否损坏或受密码保护。') from exc
    if len(text) > MAX_TEXT:
        raise ValueError('Word 正文过长。')
    return {'kind': 'text', 'text': text}


def pages(suffix, raw):
    result = preview(suffix, raw)
    if result['kind'] == 'text':
        return [result['text']]
    return ['\n'.join([f'工作表「{sheet["name"]}」',
            *(f'第{number}行\t' + '\t'.join(values) for number, values in sheet['rows'])])
            for sheet in result['sheets']]
