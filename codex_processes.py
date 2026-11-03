"""Bounded per-chat App Server connections; no model work is replayed here."""
import atexit
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import queue
import threading
import time


class ProcessBusy(RuntimeError):
    pass


def configuration_stamp(executable, argv, env, cwd, profile, *, context_root=None):
    """Invalidate native configuration/auth changes without retaining their contents."""
    home = Path(env.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
    paths = {home / 'config.toml', home / 'auth.json', home / 'settings.json'}
    paths.update(home / name for name in ('AGENTS.md', 'AGENTS.override.md'))
    paths.update(home.glob('*.toml'))
    paths.update((home / 'plugins').glob('*.json'))
    # Public skill definitions may change independently of config.toml.
    paths.update((home / 'skills').rglob('SKILL.md'))
    if cwd:
        root = Path(cwd).resolve()
        for parent in (root, *root.parents):
            paths.add(parent / '.codex' / 'config.toml')
            paths.update(parent / name for name in ('AGENTS.md', 'AGENTS.override.md'))
            paths.update((parent / '.agents' / 'skills').glob('*/SKILL.md'))
            if context_root and parent == Path(context_root).resolve():
                break
    paths.add(Path(executable))
    stamps = []
    for path in sorted(paths, key=str):
        try:
            stat = path.stat()
            stamps.append((str(path.resolve()), stat.st_ino, stat.st_size, stat.st_mtime_ns))
        except OSError:
            stamps.append((str(path), None))
    value = [argv, sorted(env.items()), os.path.realpath(cwd) if cwd else '', profile, stamps]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Connection:
    def __init__(self, start, stop):
        self.process = start()
        self.stop = stop
        self.lines = queue.Queue()
        self.stderr = deque(maxlen=100)
        self.initialized = False
        self.next_id = 0
        self.thread_id = ''
        self.thread_signature = ''
        self.provider_selected = False
        self.model_provider = None
        self.finished_turns = deque(maxlen=64)
        self.last_used = time.monotonic()
        self.busy = True
        self.closed = False
        self.reader = threading.Thread(target=self._stdout, daemon=True)
        self.error_reader = threading.Thread(target=self._stderr, daemon=True)
        self.reader.start()
        self.error_reader.start()

    def _stdout(self):
        try:
            for line in self.process.stdout:
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self.lines.put(None)

    def _stderr(self):
        try:
            for line in self.process.stderr:
                self.stderr.append(line[-4000:])
        except (OSError, ValueError):
            pass

    def alive(self):
        return not self.closed and self.process.poll() is None

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop(self.process)
        for reader in (self.reader, self.error_reader):
            reader.join(timeout=.5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


class ProcessPool:
    """One exclusive connection per owner; parallel chats never share readers."""
    def __init__(self, idle_seconds=600, max_idle=8):
        self.idle_seconds, self.max_idle = idle_seconds, max_idle
        self.lock = threading.RLock()
        self.entries = {}
        self.sweeper = None

    def _expired(self, now):
        idle = sorted(((owner, row) for owner, row in self.entries.items() if not row[1].busy),
                      key=lambda item: item[1][1].last_used, reverse=True)
        dead = []
        for index, (owner, (signature, connection)) in enumerate(idle):
            if index >= self.max_idle or not connection.alive() or now - connection.last_used >= self.idle_seconds:
                self.entries.pop(owner, None)
                dead.append(connection)
        return dead

    def _sweep(self):
        while True:
            time.sleep(min(30, max(1, self.idle_seconds)))
            with self.lock:
                dead = self._expired(time.monotonic())
                if not self.entries:
                    self.sweeper = None
                    done = True
                else:
                    done = False
            for connection in dead:
                connection.close()
            if done:
                return

    def acquire(self, owner, signature, thread_id, start, stop):
        dead = []
        try:
            with self.lock:
                dead.extend(self._expired(time.monotonic()))
                row = self.entries.get(owner)
                if row and row[1].busy:
                    raise ProcessBusy('这段对话正在处理上一条消息')
                reused = bool(row and row[0] == signature and row[1].alive() and
                              row[1].thread_id == (thread_id or ''))
                if row and not reused:
                    self.entries.pop(owner)
                    dead.append(row[1])
                if reused:
                    connection = row[1]
                    connection.busy = True
                else:
                    connection = Connection(start, stop)
                    self.entries[owner] = (signature, connection)
                if self.sweeper is None:
                    self.sweeper = threading.Thread(target=self._sweep, daemon=True)
                    self.sweeper.start()
        finally:
            # A failed replacement/busy rejection must still reap entries that
            # were removed by this acquisition's expiry pass.
            for old in dead:
                old.close()
        return connection, reused

    def release(self, owner, connection, healthy):
        with self.lock:
            row = self.entries.get(owner)
            if row is None or row[1] is not connection or not healthy or not connection.alive():
                if row and row[1] is connection:
                    self.entries.pop(owner)
                dead = [connection]
            else:
                connection.busy = False
                connection.last_used = time.monotonic()
                dead = self._expired(connection.last_used)
        for old in dead:
            old.close()

    def close_all(self):
        with self.lock:
            connections = [row[1] for row in self.entries.values()]
            self.entries.clear()
        for connection in connections:
            connection.close()

    def close_thread(self, thread_id):
        with self.lock:
            owners = [owner for owner, row in self.entries.items() if row[1].thread_id == thread_id]
            connections = [self.entries.pop(owner)[1] for owner in owners]
        for connection in connections:
            connection.close()


POOL = ProcessPool()
atexit.register(POOL.close_all)
