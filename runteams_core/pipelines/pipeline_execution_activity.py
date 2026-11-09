"""Bounded, read-only observations for the currently executing pipeline visit."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Condition, Lock


_LIMIT = 8
_TEXT_LIMIT = 600
_active = {}
_lock = Lock()
_turn = ContextVar('pipeline_execution_activity', default=None)


def _remember(rows, key, value):
    rows[key] = value
    rows.move_to_end(key)
    if len(rows) > _LIMIT:
        rows.popitem(last=False)


class _Activity:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.changed = Condition()
        self.revision = 0
        self.closed = False
        self.notes = OrderedDict()
        self.steps = OrderedDict()
        self.questions = OrderedDict()
        self.check_approval = None

    def record(self, event, check_approval=None):
        if not isinstance(event, dict):
            return
        kind = event.get('kind')
        with self.changed:
            if kind == 'work_delta':
                delta = event.get('delta')
                if not isinstance(delta, str) or not delta:
                    return
                key = str(event.get('id') or '')[:256]
                note = self.notes.get(key, '') + delta[-_TEXT_LIMIT:]
                _remember(self.notes, key, note[-_TEXT_LIMIT:])
            elif kind == 'step' and event.get('status') in ('running', 'completed', 'failed'):
                step = event.get('step_kind')
                _remember(self.steps, str(event.get('id') or '')[:256], {
                    'kind': step if step in ('command', 'file', 'search') else 'tool',
                    'status': event['status'],
                })
            elif kind == 'user_input':
                request = event['request']
                question = next((q['question'][:_TEXT_LIMIT] for q in request['questions']
                                 if not q.get('isSecret')), '')
                _remember(self.questions, request['id'], question)
            elif kind in ('user_input_resolved', 'user_input_expired'):
                self.questions.pop(event.get('id'), None)
            elif kind == 'employee_mcp_approval':
                self.check_approval = check_approval
            else:
                return
            self.revision += 1
            self.changed.notify_all()

    def close(self):
        with self.changed:
            self.closed = True
            self.changed.notify_all()

    def snapshot(self):
        with self.changed:
            result = {
                'notes': [note.strip() for note in self.notes.values() if note.strip()],
                'steps': list(self.steps.values()),
                'questions': list(self.questions.values()),
            }
            check_approval = self.check_approval
        # The program host owns consent and can clear it without a model event.
        try:
            result['approval_pending'] = bool(check_approval and check_approval())
        except PermissionError:
            result['approval_pending'] = False
        return result if any(result.values()) else None


@contextmanager
def capture(core, workflow_id, frozen):
    if not frozen.get('pipeline_work'):
        yield
        return
    key = (core.repository.path, workflow_id, frozen['employee_run_id'], frozen['work_chat_id'])
    activity = _Activity(frozen['work_chat_id'])
    token = _turn.set(activity)
    with _lock:
        _active[key] = activity
    try:
        yield
    finally:
        activity.close()
        _turn.reset(token)
        with _lock:
            if _active.get(key) is activity:
                del _active[key]


def current_turn(chat_id):
    activity = _turn.get()
    return activity if activity and activity.chat_id == chat_id else None


def _find(core, workflow_id, run_id, chat_id):
    with _lock:
        return _active.get((core.repository.path, workflow_id, run_id, chat_id))


def read(core, workflow_id, run_id, chat_id):
    activity = _find(core, workflow_id, run_id, chat_id)
    return activity.snapshot() if activity else None


class ActivityStream:
    def __init__(self, activity=None):
        self.activity = activity

    def events(self):
        activity = self.activity
        if activity is None:
            return
        revision = -1
        previous = object()
        while True:
            with activity.changed:
                activity.changed.wait_for(lambda: activity.closed or activity.revision != revision, timeout=2)
                if activity.closed:
                    return
                revision = activity.revision
            snapshot = activity.snapshot()
            if snapshot != previous:
                yield {'type': 'work_activity', 'activity': snapshot}
                previous = snapshot
            else:
                # Detect disconnected clients and approvals resolved outside the turn.
                yield {'type': 'heartbeat'}


def observe(core, workflow_id, run_id, chat_id):
    return ActivityStream(_find(core, workflow_id, run_id, chat_id))

