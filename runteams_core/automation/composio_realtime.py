"""Receive Composio trigger events over its authenticated private Pusher channel."""

from contextlib import closing
import http.client
import json
import re
import time
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

GMAIL_TRIGGER = 'GMAIL_NEW_GMAIL_MESSAGE'
MAX_FRAME = 4 * 1024 * 1024


def gmail_operation(event, *, account, user, trigger):
    meta = event.get('metadata')
    if not isinstance(meta, dict):
        return None
    if event.get('type') == 'composio.trigger.message':
        actual = (meta.get('connected_account_id'), meta.get('user_id'), meta.get('trigger_id'), meta.get('trigger_slug'))
        payload = event.get('data')
    else:
        connection = meta.get('connection')
        if not isinstance(connection, dict):
            return None
        actual = (connection.get('connectedAccountNanoId'), connection.get('clientUniqueUserId'),
                  meta.get('nanoId'), meta.get('triggerName'))
        payload = event.get('payload')
    if actual != (account, user, trigger, GMAIL_TRIGGER) or not isinstance(payload, dict):
        return None
    message = payload.get('message_id') or payload.get('id')
    if not isinstance(message, str) or not re.fullmatch(r'[0-9a-fA-F]{8,64}', message):
        return None
    labels = payload.get('label_ids', payload.get('labelIds'))
    if labels is not None and (not isinstance(labels, list) or 'INBOX' not in labels
                               or any(label in labels for label in ('SENT', 'SPAM', 'TRASH', 'DRAFT'))):
        return None
    return str(uuid5(NAMESPACE_URL, f'runteams:eva:gmail:{account}:{message.lower()}'))


def _request(key, endpoint, arguments=None):
    # The SDK realtime endpoints are still served under v3.
    headers = {'x-api-key': key, 'Accept': 'application/json'}
    if arguments:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    with closing(http.client.HTTPSConnection('backend.composio.dev', timeout=12)) as connection:
        connection.request('POST' if arguments else 'GET', '/api/v3/internal/sdk/realtime/' + endpoint,
                           urlencode(arguments) if arguments else None, headers)
        response = connection.getresponse()
        raw = response.read(65537)
        if response.status != 200 or len(raw) > 65536:
            raise RuntimeError(f'Composio realtime HTTP {response.status}')
        return json.loads(raw)


def _payload(value):
    if isinstance(value, str):
        if len(value) > MAX_FRAME:
            raise ValueError('Composio frame exceeds the size limit')
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('Invalid Composio frame')
    return value


def subscribe(key, stop, on_event, on_ready, connection_changed):
    """Run one private subscription. The caller owns reconnect policy."""
    import websocket

    info = _request(key, 'credentials')
    cluster, app, project = (info[field] for field in ('pusher_cluster', 'pusher_key', 'project_id'))
    if not re.fullmatch(r'[a-z0-9]{1,15}', cluster) or any(
            not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', item) for item in (app, project)):
        raise ValueError('Invalid Composio realtime endpoint')
    channel = f'private-{project}_triggers'
    url = f'wss://ws-{cluster}.pusher.com/app/{app}?protocol=7&client=python-runteams&version=1.0'
    socket = websocket.create_connection(url, timeout=8, redirect_limit=0, suppress_origin=True)
    connection_changed(socket)
    chunks = {}
    last, pending_ping = time.monotonic(), None
    ready_deadline = last + 20
    ready = False
    try:
        while not stop.is_set():
            try:
                raw = socket.recv()
            except websocket.WebSocketTimeoutException:
                now = time.monotonic()
                if not ready and now >= ready_deadline:
                    raise TimeoutError('Composio subscription did not become ready')
                if pending_ping is not None and now - pending_ping > 20:
                    raise TimeoutError('Composio heartbeat did not answer')
                if pending_ping is None and now - last > 25:
                    socket.send(json.dumps({'event': 'pusher:ping', 'data': {}}))
                    pending_ping = now
                continue
            if not raw:
                return
            last, pending_ping = time.monotonic(), None
            frame = _payload(raw)
            event = frame.get('event')
            if event == 'pusher:connection_established':
                socket_id = _payload(frame['data'])['socket_id']
                if not re.fullmatch(r'\d+\.\d+', socket_id):
                    raise ValueError('Invalid Composio socket identifier')
                auth = _request(key, 'auth?source=python', {'socket_id': socket_id, 'channel_name': channel})['auth']
                socket.send(json.dumps({'event': 'pusher:subscribe', 'data': {'channel': channel, 'auth': auth}}))
            elif event == 'pusher:ping':
                socket.send(json.dumps({'event': 'pusher:pong', 'data': {}}))
            elif event in ('pusher:error', 'pusher:subscription_error', 'pusher_internal:subscription_error'):
                raise RuntimeError('Composio realtime subscription was rejected')
            elif frame.get('channel') == channel and event == 'pusher_internal:subscription_succeeded':
                ready = True
                on_ready()
            elif ready and frame.get('channel') == channel:
                try:
                    if event == 'trigger_to_client':
                        on_event(_payload(frame['data']))
                    elif event == 'chunked-trigger_to_client':
                        part = _payload(frame['data'])
                        if (len(chunks) > 64 or type(part.get('index')) is not int or
                                not 0 <= part['index'] < 512 or not isinstance(part.get('chunk'), str)):
                            chunks.clear()
                            continue
                        current = chunks.setdefault(part['id'], {})
                        current[part['index']] = part['chunk']
                        if sum(len(piece) for piece in current.values()) > MAX_FRAME:
                            chunks.pop(part['id'], None)
                        elif part.get('final') is True:
                            parts = chunks.pop(part['id'])
                            if sorted(parts) == list(range(part['index'] + 1)):
                                on_event(_payload(''.join(parts[index] for index in sorted(parts))))
                except (KeyError, TypeError, ValueError):
                    continue  # A malformed frame cannot terminate the subscription.
    finally:
        connection_changed(None)
        socket.shutdown()
