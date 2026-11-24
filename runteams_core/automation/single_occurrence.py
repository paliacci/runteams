"""One-off calendar exceptions stored separately from the recurring schedule."""
from datetime import datetime, timedelta, timezone
import json
import uuid
from zoneinfo import ZoneInfo

from runteams_core.automation.device_employee_schedules import canonical
from runteams_core.foundation.contracts import ContractError

_NAMESPACE = uuid.UUID('0b05f7ae-b238-4c25-83c1-7749400d00cd')


def initialize(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS occurrence_moves (schedule_id INTEGER NOT NULL, '
                       'original_at TEXT NOT NULL, moved_to TEXT NOT NULL, PRIMARY KEY(schedule_id, original_at), '
                       'UNIQUE(schedule_id, moved_to))')
    connection.execute('CREATE TRIGGER IF NOT EXISTS clear_occurrence_moves '
                       'AFTER UPDATE OF enabled, deleted, schedule_kind, interval_sec, schedule ON schedules '
                       'BEGIN DELETE FROM occurrence_moves WHERE schedule_id=NEW.id; END')


def has_moves_table(connection):
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='occurrence_moves'").fetchone() is not None


def moves(connection, identifier):
    if not has_moves_table(connection):
        return []
    return connection.execute('SELECT original_at, moved_to FROM occurrence_moves WHERE schedule_id=? '
                              'ORDER BY moved_to', (identifier,)).fetchall()


def instant(value):
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None or moment.microsecond:
            raise ValueError
        return moment.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError('请提供含日期、时区偏移且精确到秒的执行时间。') from exc


def following(row, original, *, after=None):
    """Advance by the original cadence, including when a device wakes up late."""
    start = instant(original)
    floor = max(start, after or start)
    if row['schedule_kind'] == 'interval':
        step = timedelta(seconds=row['interval_sec'])
        return (start + step * ((floor - start) // step + 1)).isoformat(timespec='seconds')
    config = json.loads(row['schedule'])
    zone = ZoneInfo(config['timezone'])
    day = floor.astimezone(zone).date()
    hour, minute = map(int, config['time'].split(':'))
    for offset in range(9):
        date = day + timedelta(days=offset)
        if row['schedule_kind'] == 'weekly' and date.weekday() not in config['weekdays']:
            continue
        candidate = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone).astimezone(timezone.utc)
        if candidate > floor:
            return candidate.isoformat(timespec='seconds')
    raise ContractError('无法计算下一次正常触发时间。')


def first_slot(connection, row):
    pending = moves(connection, row['id'])
    regular = row['next_run_at']
    if regular and pending and pending[0]['moved_to'] < regular:
        return pending[0]['moved_to'], pending[0]['original_at']
    return regular, None


def _effective_time(connection):
    if not has_moves_table(connection):
        return 'next_run_at'
    return ("MIN(next_run_at, COALESCE((SELECT MIN(moved_to) FROM occurrence_moves "
            "WHERE schedule_id=schedules.id), next_run_at))")


def earliest_due(connection, selection, ids):
    return connection.execute(
        f"SELECT MIN({_effective_time(connection)}) FROM schedules "
        "WHERE enabled=1 AND deleted=0 AND next_run_at<>''" + selection, ids).fetchone()[0]


def due_query(connection, selection):
    effective = _effective_time(connection)
    return (f'SELECT *, {effective} AS due_at FROM schedules WHERE enabled=1 AND deleted=0 '
            f"AND next_run_at<>'' AND {effective}<=?" + selection + ' ORDER BY due_at,id LIMIT ?')


def consume(connection, row, now):
    if row['due_at'] != row['next_run_at']:
        connection.execute('DELETE FROM occurrence_moves WHERE schedule_id=? AND moved_to=?',
                           (row['id'], row['due_at']))
    else:
        connection.execute('UPDATE schedules SET next_run_at=? WHERE id=?',
                           (following(row, row['next_run_at'], after=now), row['id']))


def execute(host, *, kind, reference, turn_key, operation, arguments):
    required = {'id', 'expected_revision', 'expected_next_run_at'}
    if operation == 'move_next':
        required.add('move_to')
    if (operation not in ('skip_next', 'move_next') or set(arguments) != required
            or type(arguments['id']) is not int or arguments['id'] <= 0
            or type(arguments['expected_revision']) is not int or arguments['expected_revision'] < 0):
        raise ContractError('请先查看计划和下一次执行时间。')
    backend = host.backend(kind)
    command = str(uuid.uuid5(_NAMESPACE, canonical([turn_key, kind, reference, operation, arguments['id']])))
    request = canonical([operation, reference, arguments])
    with backend.connection(write=True) as connection:
        prior = connection.execute('SELECT request,result FROM commands WHERE id=?', (command,)).fetchone()
        if prior:
            if prior['request'] != request:
                raise ContractError('这次调整的内容已变化，请核对原操作。')
            return json.loads(prior['result'])
        row = connection.execute('SELECT * FROM schedules WHERE id=? AND reference=? AND deleted=0',
                                 (arguments['id'], canonical(reference))).fetchone()
        if row is None or row['revision'] != arguments['expected_revision'] or not row['enabled']:
            raise ContractError('计划已变化或暂停，请重新读取。')
        now = datetime.now(timezone.utc)
        previous, moved_from = first_slot(connection, row)
        if (not previous or instant(previous) <= now
                or instant(previous) != instant(arguments['expected_next_run_at'])):
            raise ContractError('原定这次已到点或已变化，请重新读取计划。')
        regular = row['next_run_at'] if moved_from else following(row, previous)
        original = moved_from or previous
        if moved_from:
            connection.execute('DELETE FROM occurrence_moves WHERE schedule_id=? AND original_at=?', (row['id'], original))
        else:
            connection.execute('UPDATE schedules SET next_run_at=? WHERE id=?', (regular, row['id']))
        replacement = None
        if operation == 'move_next':
            target = instant(arguments['move_to'])
            replacement = target.isoformat(timespec='seconds')
            if target <= now or replacement == previous:
                raise ContractError('请选择不同的未来执行时间。')
            is_regular = replacement == regular or (target > instant(regular) and
                following(row, regular, after=target - timedelta(seconds=1)) == replacement)
            existing = connection.execute(
                'SELECT 1 FROM occurrences WHERE schedule_id=? AND scheduled_for=?', (row['id'], replacement)
            ).fetchone()
            if (is_regular or existing
                    or any(item['moved_to'] == replacement for item in moves(connection, row['id']))):
                raise ContractError('该时间已有另一次触发，请选择不同的时间。')
            connection.execute('INSERT INTO occurrence_moves VALUES(?,?,?)', (row['id'], original, replacement))
        else:
            connection.execute("INSERT INTO occurrences(schedule_id,scheduled_for,operation_id,status,snapshot,reason) "
                               "VALUES(?,?,?,'skipped',?,?)", (row['id'], previous, command, canonical(dict(row)),
                                                               '用户已跳过这一次定时。'))
        connection.execute('UPDATE schedules SET revision=revision+1 WHERE id=?', (row['id'],))
        other = [item['moved_to'] for item in moves(connection, row['id']) if item['original_at'] != original]
        next_other = min([regular, *other])
        result = {'id': row['id'], 'name': row['name'], 'status': 'moved' if replacement else 'skipped',
                  'original_at': original, 'previous_at': previous, 'moved_to': replacement,
                  'following_regular_at': regular, 'next_other_at': next_other,
                  'next_run_at': min(next_other, replacement) if replacement else next_other,
                  'timezone': json.loads(row['schedule'])['timezone'], 'operation_id': command}
        connection.execute('INSERT INTO commands VALUES(?,?,?)', (command, request, canonical(result)))
    host.start(kind)
    return result
