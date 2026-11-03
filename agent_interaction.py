"""One live turn's questions, including deferred official native requests.

This is a device interaction bridge, never a business approval or permission
grant. A stopped/replaced process cannot receive an answer from an old card.
"""
from copy import deepcopy
import secrets
import threading

from errors import Cancelled


def scope():
    from runteams_core.storage_context import current_provider
    return current_provider().interaction_scope()


def questions(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        raise ValueError('请提供 1～4 个问题')
    result, ids = [], set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError('问题格式无效')
        key = str(raw.get('id') or 'question-' + str(index + 1))
        title = str(raw.get('question') or raw.get('title') or '').strip()
        if not title or len(title) > 4000 or key in ids or len(key) > 180:
            raise ValueError('问题内容或编号无效')
        ids.add(key)
        options = raw.get('options') or []
        if not isinstance(options, list) or len(options) > 12:
            raise ValueError('问题选项无效')
        rows = []
        for item in options:
            if isinstance(item, str):
                item = {'label': item}
            if not isinstance(item, dict) or not str(item.get('label') or '').strip():
                raise ValueError('问题选项无效')
            rows.append({'label': str(item['label'])[:240],
                         'description': str(item.get('description') or '')[:1000]})
        result.append({'id': key, 'question': title,
                       'header': str(raw.get('header') or '')[:80],
                       'options': rows, 'multiSelect': bool(raw.get('multiSelect')),
                       'isSecret': bool(raw.get('isSecret'))})
    return result


class TurnQuestions:
    def __init__(self, cancel, owner):
        self.cancel, self.owner = cancel, owner
        self.lock = threading.RLock()
        self.requests = {}
        self.closed = False
        self.waiting = threading.Event()

    def _register(self, value, emit, blocking, submit=None):
        prompt = {'id': secrets.token_urlsafe(24), 'questions': questions(value),
                  'status': 'pending', 'isBlocking': blocking}
        request = {'prompt': prompt, 'ready': threading.Event(), 'answers': None,
                   'emit': emit, 'receipt': None, 'submit': submit, 'command': None, 'submitted': None}
        with self.lock:
            if self.closed or self.cancel.is_set():
                raise Cancelled('运行已停止')
            self.requests[prompt['id']] = request
            if blocking:
                self.waiting.set()
            emit({'kind': 'user_input', 'request': deepcopy(prompt)})
        return request

    def ask_async(self, value, emit, submit=None):
        """Register only. The native transport drains the original request later."""
        return self._register(value, emit, False, submit)['prompt']['id']

    def ask_deferred(self, value, emit):
        """Keep a blocking question without blocking the native protocol reader."""
        return self._register(value, emit, True)['prompt']['id']

    def response(self, request_id):
        with self.lock:
            request = self.requests.get(request_id)
            if self.closed or self.cancel.is_set() or not request or request['answers'] is None:
                return None
            return {'answers': deepcopy(request['answers'])}

    def expire(self, request_id):
        with self.lock:
            request = self.requests.get(request_id)
            if request and request['prompt']['status'] == 'pending':
                request['prompt']['status'] = 'expired'
                request['ready'].set()
                if not any(r['prompt']['status'] == 'pending' and r['prompt']['isBlocking'] for r in self.requests.values()):
                    self.waiting.clear()
                request['emit']({'kind': 'user_input_expired', 'id': request_id})

    def ask(self, value, emit):
        request = self._register(value, emit, True)
        try:
            while not request['ready'].wait(.1):
                if self.cancel.is_set() or self.closed:
                    raise Cancelled('运行已停止')
            with self.lock:
                if self.cancel.is_set() or self.closed or request['answers'] is None:
                    raise Cancelled('问题已结束')
                return {'answers': deepcopy(request['answers'])}
        finally:
            with self.lock:
                if self.closed or not any(r['answers'] is None and r['prompt']['isBlocking']
                                          for r in self.requests.values()):
                    self.waiting.clear()

    def answer(self, request_id, answers, owner, accept=None, receipt_replay=False):
        with self.lock:
            if owner != self.owner or self.closed or self.cancel.is_set():
                raise ValueError('这个问题已失效，请重新载入对话')
            request = self.requests.get(str(request_id))
            if request is None or request['prompt']['status'] == 'expired':
                raise ValueError('这个问题已失效，请重新载入对话')
            if not isinstance(answers, dict) or set(answers) != {q['id'] for q in request['prompt']['questions']}:
                raise ValueError('请回答每一个问题后再提交')
            cleaned = {}
            for question in request['prompt']['questions']:
                raw = answers[question['id']]
                values = raw.get('answers') if isinstance(raw, dict) else None
                if (not isinstance(values, list) or not values or
                        len(values) > (13 if question['multiSelect'] else 1) or
                        any(not isinstance(v, str) or not v.strip() or len(v) > 8000 for v in values)):
                    raise ValueError('请回答每一个问题后再提交')
                cleaned[question['id']] = {'answers': [v.strip() for v in values]}
            if request['answers'] is not None:
                if request['answers'] != cleaned:
                    raise ValueError('这个问题已经回答，不能重复修改')
                return deepcopy(request['receipt'])
            if request['submitted'] is not None and request['submitted'] != cleaned:
                raise ValueError('正在确认原回答，请保留原内容重试')
            submit = request['submit']
            if submit is not None:
                request['submitted'] = deepcopy(cleaned)
        if submit is not None:
            # Never hold the broker lock while acquiring native TurnControl's
            # lock: its acknowledgement commits back into this broker.
            command = submit(cleaned, lambda turn_id: self._commit(request, cleaned, accept))
            with self.lock:
                request['command'] = command
                if command['done'].is_set() and command['error']:
                    if receipt_replay and command.get('native_accepted'):
                        # The original native input was accepted and its device
                        # message exists. Reconcile that receipt, never submit again.
                        receipt = self._commit(request, cleaned, accept)
                        command['result'], command['error'] = receipt, ''
                        return receipt
                    raise ValueError(command['error'])
                return deepcopy(request['receipt']) if request['receipt'] else {'pending': True, 'id': request_id}
        return self._commit(request, cleaned, accept)

    def _commit(self, request, cleaned, accept):
        with self.lock:
            if self.closed or self.cancel.is_set() or request['prompt']['status'] == 'expired':
                raise ValueError('这个问题已结束，请重新载入对话')
            if request['receipt']:
                if request['answers'] != cleaned:
                    raise ValueError('这个问题已经回答，不能重复修改')
                return deepcopy(request['receipt'])
            public = {q['id']: {'answers': ['已填写'] if q['isSecret'] else cleaned[q['id']]['answers']}
                      for q in request['prompt']['questions']}
            receipt = accept(deepcopy(request['prompt']), public) if accept else {}
            request['receipt'] = {'accepted': True, 'id': request['prompt']['id'], **receipt}
            request['answers'] = deepcopy(cleaned)
            request['prompt']['status'] = 'answered'
            request['ready'].set()
            if not any(r['prompt']['status'] == 'pending' and r['prompt']['isBlocking'] for r in self.requests.values()):
                self.waiting.clear()
            request['emit']({'kind': 'user_input_resolved', 'id': request['prompt']['id'],
                             'answers': public, 'message': receipt.get('message'),
                             **({'prefix_message': receipt['prefix_message']} if receipt.get('prefix_message') else {})})
            return deepcopy(request['receipt'])

    def wait_receipt(self, request_id, timeout=5):
        with self.lock:
            request = self.requests.get(request_id)
            command = request['command'] if request else None
        if command:
            command['done'].wait(timeout)
            return deepcopy(command['result']) if command['done'].is_set() else None
        return None


    def pending(self, owner):
        with self.lock:
            if self.closed or owner != self.owner:
                return []
            return [deepcopy(r['prompt']) for r in self.requests.values()
                    if r['prompt']['status'] == 'pending']

    def receipts(self, owner):
        with self.lock:
            if owner != self.owner:
                return []
            return [deepcopy(r['receipt']) for r in self.requests.values() if r['receipt']]

    def close(self):
        with self.lock:
            for key in self.requests:
                self.expire(key)
            self.closed = True
            self.waiting.clear()
            for request in self.requests.values():
                request['ready'].set()
