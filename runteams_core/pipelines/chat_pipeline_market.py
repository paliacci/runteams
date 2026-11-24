"""Pin a marketplace query to the user turn that produced it."""
import json
import re

from runteams_core.authoring.creator_contracts import digest
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import chat_pipeline_flow as chat
from runteams_core.storage import device_data, product_store

_VERSION = r'[A-Za-z0-9][A-Za-z0-9._+\-]{0,79}'
_CHINESE_LEAD = r'^\s*(?:(?:那就|那么|然后|再|就|请(?:你)?|麻烦(?:你)?|帮我|给我|我要|我想|现在|直接|确认)\s*)*'
_COMMAND = (
    '(?:' + _CHINESE_LEAD +
    r'(?:下载|取得|获取)\s*(?:(?:本|这支|当前|这个)团队(?:的)?\s*)?'
    r'|^\s*(?:(?:please|then|now|go ahead and|i want you to)\s+)*(?:download|get)\s+'
    r'(?:(?:this|the|my) team(?:\x27s)?\s+)?(?:version\s+)?'
    r')'
)
_RELATIVE = (
    r'(?:(?:你|我们)?(?:刚(?:刚|才)?|先前|上(?:一)?轮|之前|上次|上一条(?:回复|消息)?(?:中|里)?)'
    r'(?:你|我们)?(?:刚(?:刚|才)?)?(?:查(?:到|过|出|询到)?|核对(?:到|过)?|'
    r'确[认定](?:过|的)?|找到|看到)的?(?:那(?:个|一)?|这(?:个|一)?)?(?:市场)?(?:版(?:本)?|发布版)|'
    r'(?:the|that) (?:version|release) (?:you |we )?(?:just |previously )?(?:checked|verified|found|looked up)|'
    r'(?:the|that) (?:just |previously )?(?:checked|verified) (?:version|release))'
)
_NEGATIVE = (
    r'(?:不要|不用|无需|别|请勿|暂不|先不|不必)\s*(?:现在|自动|直接|先|实际|进行|再)*\s*(?:下载|取得|获取)|'
    r'\b(?:do not|never|don\x27t|don’t|without)\s+(?:(?:automatically|actually|directly|yet)\s+)*(?:download|get)\b|'
    r'\b(?:hold off (?:on )?downloading|no downloads?)\b|'
    r'(?:只|仅)(?:查|看|核对|告诉我)|\b(?:only check|check only|just check|ask me first)\b|'
    r'(?:确认后|等我).{0,15}(?:下载|取得|获取)'
)


def _key(turn):
    return 'market-team-chat-query:' + turn.epoch


def _market_message(turn):
    message = chat._current_message(turn)
    if any((message.get('metadata') or {}).get(flag) for flag in (
            'background_work_operation', 'background_chat_turn', 'question_request_id')):
        raise PermissionError('请在团队主对话中发送原始指令。')
    return message


def _queries(connection, turn):
    row = connection.execute('SELECT value FROM device_settings WHERE key=?', (_key(turn),)).fetchone()
    return json.loads(row['value']) if row else {}


def _previous(turn):
    with device_data.connect(readonly=True) as connection:
        row = connection.execute(
            "SELECT id,text FROM chat_messages WHERE chat_id=? AND role='user' AND id<? ORDER BY id DESC LIMIT 1",
            (turn.chat_id, turn.message_id)).fetchone()
        if row:
            saved = _queries(connection, turn).get(str(row['id']))
            if (saved and saved['reference'] == turn.reference and saved['message_sha256'] == digest(row['text'])
                    and len(saved['candidates']) == 1):
                return saved['candidates'][0]
    return None


def _save_query(turn, ensure_current, message, candidate):
    with device_data.connect() as connection:
        ensure_current()
        records = _queries(connection, turn)
        key = str(turn.message_id)
        identity = {'reference': turn.reference, 'message_sha256': digest(message['text'])}
        saved = records.get(key)
        candidates = list(saved['candidates']) if saved and all(saved[k] == v for k, v in identity.items()) else []
        if not any(item == candidate or item and candidate
                   and all(item[key] == candidate[key] for key in ('listing_id', 'version', 'selected_revision'))
                   for item in candidates):
            candidates.append(candidate)
        records[key] = {**identity, 'candidates': candidates[:2]}
        newest = sorted(records, key=int, reverse=True)[:2]
        connection.execute(
            'INSERT INTO device_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (_key(turn), json.dumps({key: records[key] for key in newest})))


def _selection(arguments, message, prior):
    text, intent = message['text'], arguments['intent']
    supplied = arguments.get('version')
    if not intent.strip() or intent not in text or re.search(_NEGATIVE, text, re.IGNORECASE):
        raise PermissionError('请在本轮明确要求下载一个团队版本。')
    choices = set()
    authorized = False
    clauses = re.findall(r'[^。！？；!?;\n，,]+[。！？；!?;]?', text)
    for clause in (part for item in clauses for part in re.split(r'\.(?=\s|$)', item)):
        if re.search(r'有没有|什么版本|能否|吗[？?！!。\s]*$|[？?]\s*$', clause):
            continue
        relative = re.match(_COMMAND + _RELATIVE, clause, re.IGNORECASE) or re.match(
            _CHINESE_LEAD + r'(?:把|将)\s*' + _RELATIVE + r'\s*(?:下载|取得|获取)', clause)
        version_match = rf'(?P<version>{_VERSION})(?![A-Za-z0-9_+\-]|\.[A-Za-z0-9])'
        named = re.match(_COMMAND + version_match, clause, re.IGNORECASE) or re.match(
            _CHINESE_LEAD + r'(?:把|将)\s*' + version_match + r'\s*(?:下载|取得|获取)', clause)
        target = relative or named
        if target and re.search(r'^\s*(?:或|和|或者|以及|、|and|or|都|均)', clause[target.end():], re.IGNORECASE):
            raise PermissionError('请只选择一个要下载的团队版本。')
        if relative:
            choices.add(('prior', None))
        elif named and supplied and (named['version'].rstrip('.') == supplied
                                     or supplied[0].isdigit() and named['version'].rstrip('.') in ('v' + supplied, 'V' + supplied)):
            choices.add(('named', supplied))
        elif named:
            choices.add(('named', named['version'].rstrip('.')))
        else:
            if choices and re.fullmatch(r'\s*[vV]?\d[0-9A-Za-z._+\-]*\s*', clause):
                raise PermissionError('请只选择一个要下载的团队版本。')
            continue
        authorized = authorized or clause.strip().rstrip('。！!；;') in intent
    if len(choices) != 1 or not authorized:
        raise PermissionError('请写明唯一要下载的版本号，或选择上一轮查到的版本。')
    kind, version = choices.pop()
    if kind == 'named' and supplied == version:
        return version, None
    if kind == 'prior':
        if not prior:
            raise ContractError('上一轮没有查到唯一可下载的市场版本，请先查询或写明版本号。')
        if supplied is None or supplied == prior['version']:
            return prior['version'], prior
    raise PermissionError('请求的版本与本轮指令所选的版本不一致。')


def execute(core, runtime, arguments, message):
    turn = runtime.turn

    def ensure_current():
        session = product_store.get_chat(turn.chat_id, include_messages=False)
        if (not device_data.personal() or not session
                or session['context'].get('source_pipeline_discussion')):
            raise PermissionError('请在已领取团队的主对话中操作。')
        if _market_message(turn) != message:
            raise PermissionError('本轮用户指令已变化，请重新发送。')

    with turn.lock:
        ensure_current()
        if not runtime.market_prior_loaded:
            runtime.market_prior = _previous(turn)
            runtime.market_prior_loaded = True
        operation = arguments['operation']
        if operation == 'market_versions':
            result = runtime.market(core, turn.reference, operation, arguments.get('version'), ensure_current)
            if 'query_candidate' in result:
                _save_query(turn, ensure_current, message, result['query_candidate'])
                return {**result, 'prior_candidate_version': (runtime.market_prior or {}).get('version')}
            return result

        version, prior = _selection(arguments, message, runtime.market_prior)
        if runtime.market_receipt:
            if runtime.market_receipt['downloaded_version'] != version:
                raise ContractError('本轮已下载一个版本，请先核对下载结果。')
            return runtime.market_receipt
        result = runtime.market(core, turn.reference, operation, version, ensure_current,
                                **({'expected_query': prior} if prior else {}))
        if result.get('status') in ('downloaded', 'already_downloaded') and result.get('downloaded_version') == version:
            runtime.market_receipt = result
        return result
