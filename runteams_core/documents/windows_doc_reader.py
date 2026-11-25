"""Extract the body of a legacy Word document using the registered Windows Search filter."""
import ctypes
from ctypes import POINTER, byref, c_uint32, c_void_p
import sys
from uuid import UUID

TEXT_LIMIT_EXIT = 32


class PropertyValue(ctypes.Union):
    _fields_ = [('id', c_uint32), ('name', c_void_p)]


class PropertySpec(ctypes.Structure):
    _fields_ = [('kind', c_uint32), ('value', PropertyValue)]


class FullPropertySpec(ctypes.Structure):
    _fields_ = [('format', ctypes.c_ubyte * 16), ('property', PropertySpec)]


class Chunk(ctypes.Structure):
    _fields_ = [('id', c_uint32), ('break_type', c_uint32), ('flags', c_uint32), ('locale', c_uint32),
                ('attribute', FullPropertySpec), ('source', c_uint32), ('start', c_uint32), ('length', c_uint32)]


def guid(value):
    return (ctypes.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)


def method(pointer, index, *parameters):
    table = ctypes.cast(pointer, POINTER(POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(c_uint32, c_void_p, *parameters)(table[index])


def check(status):
    if status & 0x80000000:
        raise OSError(f'Windows document filter returned {status:#x}.')


def read_chunks(reader, limit):
    content = FullPropertySpec(guid('b725f130-47ef-101a-a5f1-02608c9eebac'), PropertySpec(1, PropertyValue(id=19)))
    initialize = method(reader, 3, c_uint32, c_uint32, POINTER(FullPropertySpec), POINTER(c_uint32))
    # Request only System.Search.Contents, preserve paragraph breaks and skip embedded objects.
    check(initialize(reader, 1 | 2 | 4 | 8 | 2048, 1, byref(content), byref(c_uint32())))
    next_chunk = method(reader, 4, POINTER(Chunk))
    get_text = method(reader, 5, POINTER(c_uint32), c_void_p)
    chunk = Chunk()
    buffer = ctypes.create_unicode_buffer(4096)
    output = bytearray()
    while True:
        status = next_chunk(reader, byref(chunk))
        if status == 0x80041700:  # FILTER_E_END_OF_CHUNKS
            break
        if status in (0x80041707, 0x80041708):  # Unavailable embedding or link
            continue
        check(status)
        if not chunk.flags & 1:
            continue
        separator = (' ' if chunk.break_type == 1 else '\n') if output and chunk.break_type else ''
        while True:
            count = c_uint32(len(buffer))
            status = get_text(reader, byref(count), buffer)
            if status in (0x80041701, 0x80041705):  # No more text in this chunk
                break
            check(status)
            if count.value > len(buffer):
                raise ValueError('Invalid filter text length.')
            if separator and count.value:
                output.extend(separator.encode('utf-16-le'))
                separator = ''
            output.extend(ctypes.string_at(buffer, count.value * 2))
            if len(output) > 2 * limit:
                raise OverflowError('Document text is too large.')
            if status == 0x41709 or not count.value:  # FILTER_S_LAST_TEXT
                break
    return output.decode('utf-16-le')


def main(path, limit):
    ole = ctypes.OleDLL('ole32')
    ole.CoInitializeEx(None, 2)
    unknown, reader = c_void_p(), c_void_p()
    try:
        load = ctypes.WinDLL('query').LoadIFilter
        load.argtypes = [ctypes.c_wchar_p, c_void_p, POINTER(c_void_p)]
        load.restype = c_uint32
        check(load(path, None, byref(unknown)))
        iid = guid('89bcb740-6119-101a-bcb7-00dd010655af')
        check(method(unknown, 0, c_void_p, POINTER(c_void_p))(unknown, iid, byref(reader)))
        return read_chunks(reader, limit)
    finally:
        for pointer in (reader, unknown):
            if pointer:
                method(pointer, 2)(pointer)
        ole.CoUninitialize()


if __name__ == '__main__':
    try:
        sys.stdout.buffer.write(main(sys.argv[1], int(sys.argv[2])).encode('utf-8'))
    except OverflowError:
        sys.exit(TEXT_LIMIT_EXIT)
    except (OSError, ValueError):
        sys.exit(1)
