"""Original canonical-byte JSON publication for source records."""
import os
import tempfile
from runteams_core.authoring.creator_contracts import canonical
from runteams_core.foundation import durable_files


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())
        durable_files.move(name, path, replace=True)
    finally:
        if os.path.exists(name):os.unlink(name)

