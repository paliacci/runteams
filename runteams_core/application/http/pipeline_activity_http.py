"""HTTP delivery for a read-only pipeline activity subscription."""
import json


PATH = '/api/device/work/source-pipelines/work-activity'


def send(handler, stream, check):
    # The caller has released the host request lease. A quiet observer must
    # never block a work operation or a library switch.
    check()
    handler.close_connection = True
    try:
        handler.connection.settimeout(3)
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Connection', 'close')
        handler.end_headers()
        for event in stream.events():
            check()
            handler.wfile.write(json.dumps(event, ensure_ascii=False).encode() + b'\n')
            handler.wfile.flush()
    except (OSError, PermissionError):
        pass  # The observer has no ownership of the execution.
