from runteams_core import automation_time
# -*- coding: utf-8 -*-
"""Prompt-first automation schedules, durable runs, and derived attention.

This module owns the automation domain.  It shares the application's cloud
transaction boundary while remaining independent of unrelated
employee execution behavior.
"""

import datetime
import json
import re
import sqlite3

from runteams_core import local_database


conn = local_database.conn
_lock = local_database.lock
now = local_database.now
_after = local_database.after


def _load(connection, sql, args=()):
    return [dict(row) for row in connection.execute(sql, args).fetchall()]


def _automation_record(row):
    if not row:
        return None
    item = dict(row)
    for source, target, fallback in (("schedule_config", "schedule", {}),):
        try:
            value = json.loads(item.get(source) or json.dumps(fallback))
        except (TypeError, ValueError) as exc:
            raise ValueError('云端自动化计划无效，请重新读取或修复。') from exc
        if not isinstance(value, type(fallback)):
            raise ValueError('云端自动化计划无效，请重新读取或修复。')
        item[target] = value
        item.pop(source, None)
    return item








def _automation_next_run(kind, interval, config):
    if kind == "interval":
        return _after(interval)
    current = datetime.datetime.now()
    hour, minute, _ = automation_time._automation_time(config)
    if kind == "daily":
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += datetime.timedelta(days=1)
    else:
        weekdays = set(config.get("weekdays") or [])
        candidate = None
        for offset in range(0, 8):
            day = current + datetime.timedelta(days=offset)
            option = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if option.weekday() in weekdays and option > current:
                candidate = option
                break
        if candidate is None:
            candidate = current + datetime.timedelta(days=7)
    return candidate.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def _render_automation_value(value, row, scheduled_for):
    moment = local_database.timestamp(scheduled_for).astimezone()
    variables = {
        "date": moment.strftime("%Y-%m-%d"),
        "time": moment.strftime("%H:%M"),
        "datetime": moment.strftime("%Y-%m-%d %H:%M"),
        "scheduled_at": moment.isoformat(timespec="minutes"),
        "automation_name": str(row["name"] or ""),
    }
    if isinstance(value, str):
        return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}",
                      lambda match: variables.get(match.group(1), match.group(0)), value)
    if isinstance(value, list):
        return [_render_automation_value(item, row, scheduled_for) for item in value]
    if isinstance(value, dict):
        return {key: _render_automation_value(item, row, scheduled_for) for key, item in value.items()}
    return value


def list_automations():
    """List scheduled Agent tasks and the most recent standalone run."""
    with conn() as c:
        rows = c.execute("""SELECT a.*,
               ar.id AS last_run_id,ar.status AS last_status,ar.reason AS last_reason,ar.chat_id AS last_chat_id,
               ar.triggered_at AS last_triggered_at,ar.completed_at AS last_completed_at
            FROM automations a
            LEFT JOIN automation_runs ar ON ar.id=(
              SELECT id FROM automation_runs WHERE automation_id=a.id ORDER BY id DESC LIMIT 1)
            WHERE a.trashed_at=''
            ORDER BY a.enabled DESC,a.next_run_at,a.id""").fetchall()
        return [_automation_record(row) for row in rows]


def get_automation(automation_id):
    with conn() as c:
        row = c.execute("SELECT * FROM automations WHERE id=? AND trashed_at=''",
                        (int(automation_id),)).fetchone()
        if not row:
            return None
        item = _automation_record(row)
        item["runs"] = _load(c, """SELECT ar.*,ch.title AS chat_title,
                   (SELECT COUNT(*) FROM automation_run_events ev
                    WHERE ev.automation_run_id=ar.id) AS event_count
            FROM automation_runs ar LEFT JOIN chats ch ON ch.id=ar.chat_id
            WHERE ar.automation_id=? ORDER BY ar.id DESC LIMIT 30""", (int(automation_id),))
        return item


def save_automation(data, automation_id=None):
    """Create or update a prompt-first scheduled Agent task."""
    raw = data if isinstance(data, dict) else {}
    name = str(raw.get("name") or "新自动化").strip()[:120] or "新自动化"
    prompt = str(raw.get("prompt") or "").strip()[:200000]
    if not prompt:
        raise ValueError("请写下希望 Agent 完成的工作")
    schedule_kind, interval, schedule = automation_time._normalize_automation_schedule(raw)
    enabled = 1 if raw.get("enabled", True) else 0
    try:
        channel_id = int(raw.get("channel_id")) if raw.get("channel_id") else None
    except (TypeError, ValueError):
        channel_id = None
    model = str(raw.get("model") or "").strip()[:160]
    effort = str(raw.get("reasoning_effort") or "").strip()[:40]
    ts = now()
    with _lock, conn() as c:
        if channel_id is not None and not c.execute(
                "SELECT 1 FROM model_channels WHERE id=? AND enabled=1", (channel_id,)).fetchone():
            raise ValueError("请选择可用的模型")
        if automation_id is None:
            next_run = _automation_next_run(schedule_kind, interval, schedule) if enabled else ""
            automation_id = c.execute(
                """INSERT INTO automations(name,prompt,enabled,schedule_kind,interval_sec,schedule_config,
                   channel_id,model,reasoning_effort,next_run_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, prompt, enabled, schedule_kind, interval, json.dumps(schedule, ensure_ascii=False),
                 channel_id, model, effort, next_run, ts, ts)).lastrowid
        else:
            current = c.execute("SELECT * FROM automations WHERE id=? AND trashed_at=''",
                                (int(automation_id),)).fetchone()
            if not current:
                raise ValueError("自动化不存在")
            next_run = current["next_run_at"]
            schedule_changed = (schedule_kind != current["schedule_kind"] or interval != current["interval_sec"]
                                or schedule != automation_time._automation_json(current["schedule_config"], {}))
            if enabled and (not current["enabled"] or not next_run or schedule_changed):
                next_run = _automation_next_run(schedule_kind, interval, schedule)
            elif not enabled:
                next_run = ""
            c.execute(
                """UPDATE automations SET name=?,prompt=?,enabled=?,schedule_kind=?,interval_sec=?,
                   schedule_config=?,channel_id=?,model=?,reasoning_effort=?,next_run_at=?,updated_at=?
                   WHERE id=?""",
                (name, prompt, enabled, schedule_kind, interval, json.dumps(schedule, ensure_ascii=False),
                 channel_id, model, effort, next_run, ts, int(automation_id)))
    return get_automation(int(automation_id))


def delete_automation(automation_id):
    with _lock, conn() as c:
        automation_id = int(automation_id)
        chat_ids = [row["chat_id"] for row in c.execute(
            "SELECT chat_id FROM automation_runs WHERE automation_id=? AND chat_id IS NOT NULL",
            (automation_id,)).fetchall()]
        if chat_ids:
            placeholders = ",".join("?" for _ in chat_ids)
            c.execute("DELETE FROM chat_messages WHERE chat_id IN ({})".format(placeholders), chat_ids)
            c.execute("DELETE FROM chats WHERE id IN ({})".format(placeholders), chat_ids)
        run_ids = [row["id"] for row in c.execute(
            "SELECT id FROM automation_runs WHERE automation_id=?", (automation_id,)).fetchall()]
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            c.execute("DELETE FROM automation_run_events WHERE automation_run_id IN ({})".format(
                placeholders), run_ids)
        c.execute("DELETE FROM automation_runs WHERE automation_id=?", (automation_id,))
        cur = c.execute("DELETE FROM automations WHERE id=?", (automation_id,))
        return cur.rowcount == 1


def list_trashed_automations(retention_days=30):
    """Return the automation domain's trash without reading other domains."""
    with conn() as c:
        rows = c.execute(
            """SELECT a.*,(SELECT COUNT(*) FROM automation_runs ar
               WHERE ar.automation_id=a.id) AS run_count
               FROM automations a WHERE a.trashed_at<>'' ORDER BY a.trashed_at DESC"""
        ).fetchall()
    items = []
    for row in rows:
        item = _automation_record(row)
        item.update({"type": "automation", "kind": "automation",
                     "title": item.get("name") or "未命名自动化",
                     "location": "自动化", "count": int(row["run_count"] or 0)})
        try:
            deleted = local_database.timestamp(item["trashed_at"])
            item["expires_at"] = (deleted + datetime.timedelta(
                days=max(1, int(retention_days)))).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            item["expires_at"] = ""
        item.pop("trash_meta", None)
        items.append(item)
    return items


def delete_trashed_automation(automation_id):
    """Permanently delete only an automation that is currently in trash."""
    with conn() as c:
        exists = c.execute(
            "SELECT 1 FROM automations WHERE id=? AND trashed_at<>''",
            (int(automation_id),),
        ).fetchone()
    return delete_automation(automation_id) if exists else False


def purge_expired_automations(retention_days=30):
    """Permanently remove expired automation trash and return the count."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=max(1, int(retention_days)))).isoformat(timespec="seconds")
    with conn() as c:
        ids = [row["id"] for row in c.execute(
            "SELECT id FROM automations WHERE trashed_at<>'' AND trashed_at<=?", (cutoff,)
        ).fetchall()]
    return sum(1 for automation_id in ids if delete_trashed_automation(automation_id))


def trash_automation(automation_id):
    """Soft-delete one stopped schedule while retaining its runs and work log."""
    with _lock, conn() as c:
        automation_id = int(automation_id)
        row = c.execute(
            "SELECT enabled,next_run_at FROM automations WHERE id=? AND trashed_at=''",
            (automation_id,),
        ).fetchone()
        if not row:
            return False
        if _automation_has_open_run_tx(c, automation_id):
            raise ValueError("自动化仍在停止，请稍后再移到垃圾箱")
        ts = now()
        meta = {"enabled": int(row["enabled"] or 0), "next_run_at": row["next_run_at"] or ""}
        c.execute(
            "UPDATE automations SET enabled=0,next_run_at='',trashed_at=?,trash_meta=?,updated_at=? WHERE id=?",
            (ts, json.dumps(meta, ensure_ascii=False), ts, automation_id),
        )
        return True


def restore_automation(automation_id):
    """Restore one trashed schedule without involving other trash domains."""
    with _lock, conn() as c:
        row = c.execute(
            "SELECT schedule_kind,interval_sec,schedule_config,trash_meta FROM automations "
            "WHERE id=? AND trashed_at<>''", (int(automation_id),),
        ).fetchone()
        if not row:
            return False
        meta = automation_time._automation_json(row["trash_meta"], {})
        enabled = 1 if meta.get("enabled") else 0
        next_run = (_automation_next_run(
            row["schedule_kind"], row["interval_sec"],
            automation_time._automation_json(row["schedule_config"], {})) if enabled else "")
        c.execute(
            "UPDATE automations SET trashed_at='',trash_meta='{}',enabled=?,next_run_at=?,updated_at=? "
            "WHERE id=?", (enabled, next_run, now(), int(automation_id)),
        )
        return True


def pause_automation(automation_id, resolution="自动化已暂停"):
    with _lock, conn() as c:
        ts = now()
        cur = c.execute(
            "UPDATE automations SET enabled=0,next_run_at='',updated_at=? "
            "WHERE id=? AND trashed_at=''", (ts, int(automation_id)),
        )
        return cur.rowcount == 1


def automation_is_enabled(automation_id):
    with conn() as c:
        row = c.execute("SELECT enabled FROM automations WHERE id=? AND trashed_at=''",
                        (int(automation_id),)).fetchone()
        return bool(row and row["enabled"])


def _automation_has_open_run_tx(c, automation_id):
    return bool(c.execute(
        "SELECT 1 FROM automation_runs WHERE automation_id=? AND status IN ('queued','running') LIMIT 1",
        (int(automation_id),)).fetchone())


def _skip_automation_tx(c, row, scheduled_for, reason, advance_schedule):
    ts = now()
    run_id = c.execute(
        """INSERT INTO automation_runs(automation_id,scheduled_for,status,reason,snapshot_json,
           created_at,completed_at) VALUES(?,?,'skipped',?,'{}',?,?)""",
        (row["id"], scheduled_for, str(reason or "")[:4000], ts, ts)).lastrowid
    if advance_schedule:
        c.execute("UPDATE automations SET last_run_at=?,next_run_at=?,updated_at=? WHERE id=?",
                  (ts, _automation_next_run(row["schedule_kind"], row["interval_sec"],
                   automation_time._automation_json(row["schedule_config"], {})), ts, row["id"]))
    return {"id": int(run_id), "status": "skipped", "chat_id": None,
            "reason": str(reason or "")}


def _fire_automation_tx(c, row, scheduled_for, advance_schedule):
    ts = now()
    prompt = _render_automation_value(row["prompt"], row, scheduled_for)
    snapshot = {"automation_id": int(row["id"]), "name": row["name"], "prompt": prompt,
                "channel_id": row["channel_id"], "model": row["model"],
                "reasoning_effort": row["reasoning_effort"]}
    run_id = c.execute(
        """INSERT INTO automation_runs(automation_id,scheduled_for,status,snapshot_json,created_at,trigger_kind)
           VALUES(?,?,'queued',?,?,?)""",
        (row["id"], scheduled_for, json.dumps(snapshot, ensure_ascii=False), ts, "scheduled" if advance_schedule else "manual")).lastrowid
    if advance_schedule:
        c.execute("UPDATE automations SET last_run_at=?,next_run_at=?,updated_at=? WHERE id=?",
                  (ts, _automation_next_run(row["schedule_kind"], row["interval_sec"],
                   automation_time._automation_json(row["schedule_config"], {})), ts, row["id"]))
    return {"id": int(run_id), "status": "queued", "chat_id": None}


def materialize_due_automations(limit=20, has_open_work=None):
    """Persist one standalone Agent occurrence for every due automation."""
    ts = now()
    with _lock, conn() as c:
        rows = c.execute("""SELECT * FROM automations WHERE enabled=1
            AND trashed_at=''
            AND schedule_kind IN ('interval','daily','weekly') AND next_run_at!='' AND datetime(next_run_at)<=datetime(?)
            ORDER BY next_run_at,id LIMIT ?""", (ts, max(1, min(100, int(limit or 20))))).fetchall()
        occurrences = []
        for row in rows:
            open_work = bool(has_open_work and has_open_work(int(row["id"])))
            if _automation_has_open_run_tx(c, row["id"]) or open_work:
                occurrences.append(_skip_automation_tx(
                    c, row, row["next_run_at"] or ts, "上一项自动化工作尚未结束", True))
            else:
                occurrences.append(_fire_automation_tx(c, row, row["next_run_at"] or ts, True))
        return occurrences


def run_automation_now(automation_id, has_open_work=None):
    with _lock, conn() as c:
        row = c.execute("SELECT * FROM automations WHERE id=? AND trashed_at=''",
                        (int(automation_id),)).fetchone()
        if not row:
            raise ValueError("自动化不存在")
        if (_automation_has_open_run_tx(c, automation_id) or
                bool(has_open_work and has_open_work(int(automation_id)))):
            raise ValueError("上一项自动化工作尚未结束")
        return _fire_automation_tx(c, row, now(), False)


def recover_automation_runs():
    """Only replay occurrences that stopped before an Agent conversation began.

    Once a chat exists, product actions may already have been applied.  Replaying
    the prompt automatically could duplicate cards or other side effects, so the
    interrupted occurrence becomes failed.  The formal attention inbox derives
    its item directly from that durable run state, so recovery never mirrors a
    second intervention record.
    """
    from runteams_core.business_storage import storage_for
    storage = storage_for(local_database.DB_PATH)
    owned = storage.recovery_ids('automation_runs') if hasattr(storage,'recovery_ids') else None
    with _lock, conn() as c:
        rows = c.execute(
            "SELECT id,automation_id,chat_id FROM automation_runs WHERE status='running'"
        ).fetchall()
        recovered = 0
        for row in rows:
            if owned is not None and row['id'] not in owned:
                continue
            if row["chat_id"] is None:
                c.execute(
                    "UPDATE automation_runs SET status='queued',triggered_at='',reason='' WHERE id=?",
                    (row["id"],),
                )
            else:
                reason = "应用退出时自动化被中断；为避免重复执行，已停止自动重放"
                c.execute(
                    "UPDATE automation_runs SET status='failed',reason=?,completed_at=? WHERE id=?",
                    (reason, now(), row["id"]),
                )
            recovered += 1
        return recovered


def claim_next_automation_run():
    with _lock, conn() as c:
        row = c.execute("SELECT * FROM automation_runs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        ts = now()
        cur = c.execute("UPDATE automation_runs SET status='running',triggered_at=? "
                        "WHERE id=? AND status='queued'", (ts, row["id"]))
        if cur.rowcount != 1:
            return None
        item = dict(row)
        item["status"], item["triggered_at"] = "running", ts
        item.update(automation_time._automation_json(item.pop("snapshot_json", "{}"), {}))
        return item


def add_automation_run_event(run_id, kind, content):
    event_kind = str(kind or "agent_event")[:40]
    payload = content if isinstance(content, dict) else {"message": str(content or "")}
    with _lock, conn() as c:
        exists = c.execute("SELECT 1 FROM automation_runs WHERE id=?", (int(run_id),)).fetchone()
        if not exists:
            return None
        serialized = json.dumps(payload, ensure_ascii=False)
        return c.execute(
            "INSERT INTO automation_run_events(automation_run_id,ts,kind,content_json) VALUES(?,?,?,?)",
            (int(run_id), now(), event_kind, serialized),
        ).lastrowid


def automation_run_activity(run_id):
    """Publish one location receipt, then keep every native event on this host."""
    from runteams_core import device_data, device_activity
    if not device_data.personal():
        return lambda event: add_automation_run_event(run_id, 'agent_event', event)
    stream = device_activity.open_stream('automation', run_id)
    with _lock, conn() as c:
        if not c.execute('SELECT 1 FROM automation_runs WHERE id=?', (int(run_id),)).fetchone():
            raise ValueError('自动化运行不存在。')
        markers = c.execute("SELECT content_json FROM automation_run_events WHERE automation_run_id=? AND kind='device_trace'", (int(run_id),)).fetchall()
        if not any(json.loads(row[0]).get('ref') == stream['ref'] for row in markers):
            c.execute('INSERT INTO automation_run_events(automation_run_id,ts,kind,content_json) VALUES(?,?,?,?)',
                (int(run_id), now(), 'device_trace', json.dumps({'schema': 'runteams.device-trace/v1', 'ref': stream['ref']})))
    # No business/cloud calls on the high frequency native event path.
    return lambda event: device_activity.append(stream, event)


def get_automation_run(run_id):
    with conn() as c:
        row = c.execute(
            """SELECT ar.*,a.name AS automation_name,a.trashed_at,ch.title AS chat_title
               FROM automation_runs ar JOIN automations a ON a.id=ar.automation_id
               LEFT JOIN chats ch ON ch.id=ar.chat_id WHERE ar.id=?""",
            (int(run_id),),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item.pop("snapshot_json", None)
        events = []
        for event in c.execute(
                "SELECT id,ts,kind,content_json FROM automation_run_events "
                "WHERE automation_run_id=? ORDER BY id", (int(run_id),)).fetchall():
            value = dict(event)
            try:
                value["content"] = json.loads(value.pop("content_json") or "{}")
            except (TypeError, ValueError):
                value["content"] = {}
            if value['kind'] == 'device_trace':
                from runteams_core import device_activity
                try:
                    local = device_activity.events(value['content'].get('ref'), 'automation', run_id)
                    note = '完整过程记录仅保存在执行本次运行的电脑上。' if local is None else '完整过程记录仅保存在本机。'
                except (ValueError, OSError, sqlite3.Error):
                    local, note = None, '本机过程记录暂时无法读取，运行结果仍以此处显示为准。'
                events.append(dict(value, kind='system', content={'message': note}))
                events.extend(local or [])
            else:
                events.append(value)
        item["events"] = events
        return item


def failure_reasons(limit=2000):
    """Read failed-run reasons without persisting a statistics projection."""
    limit = max(1, min(10000, int(limit)))
    with conn() as c:
        rows = c.execute(
            "SELECT reason FROM automation_runs "
            "WHERE status='failed' AND TRIM(reason)<>'' "
            "ORDER BY COALESCE(completed_at,created_at) DESC,id DESC LIMIT ?",
            (limit,),).fetchall()
    return [str(row["reason"]) for row in rows]


def _automation_attention(row):
    run_id = int(row["id"])
    automation_id = int(row["automation_id"])
    name = str(row["automation_name"] or "自动化")
    reason = str(row["reason"] or "自动化未能完成")
    event_count = int(row["event_count"] or 0) if "event_count" in row.keys() else 0
    attempted = [
        "本次运行记录了 {} 条工作事件，最终未完成。".format(event_count)
        if event_count else "本次自动化已启动，但没有完成交付。"
    ]
    return {
        "id": "automation-intervention:{}".format(run_id),
        "card_id": 0,
        "node_id": None,
        "automation_id": automation_id,
        "workflow_id": None,
        "pipeline_id": None,
        "target_type": "automation",
        "kind": "automation",
        "source_type": "automation_run",
        "source_id": run_id,
        "title": "自动化运行失败",
        "reason": reason,
        "context": "",
        "recovery": "检查本次工作记录；修正配置后可立即重试，或先暂停自动化。",
        "attempted": attempted,
        "resume_from": "立即重试会创建一次新运行；本次失败记录会保留。",
        "status": "open",
        "created_at": row["completed_at"] or row["created_at"] or now(),
        "resolved_at": None,
        "resolution": "",
        "card_title": name,
        "card_status": "failed",
        "card_facts": "",
        "pipeline_name": "自动化",
        "node_name": "计划任务",
        "node_kind": "automation",
        "chain_status": "failed",
        "attempt_count": None,
        "retry_count": None,
        "chain_error": reason,
        "artifact_count": 0,
        "details": {"automation_name": name, "run_id": run_id},
        "actions": [
            {"id": "retry", "label": "立即重试", "style": "primary"},
            {"id": "pause_automation", "label": "暂停自动化", "style": "danger"},
        ],
    }


def automation_attention_catalog(limit=100):
    """Derive one current attention item from each enabled schedule's latest run."""
    limit = max(1, min(500, int(limit)))
    with conn() as c:
        rows = c.execute(
            """SELECT ar.*,a.name AS automation_name,
                      (SELECT COUNT(*) FROM automation_run_events event
                       WHERE event.automation_run_id=ar.id) AS event_count
               FROM automations a JOIN automation_runs ar ON ar.id=(
                 SELECT latest.id FROM automation_runs latest
                 WHERE latest.automation_id=a.id ORDER BY latest.id DESC LIMIT 1)
               WHERE a.enabled=1 AND a.trashed_at='' AND ar.status='failed'
               ORDER BY COALESCE(ar.completed_at,ar.created_at) DESC,ar.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [_automation_attention(row) for row in rows]


def get_automation_attention(run_id):
    """Revalidate an opaque automation attention target against current facts."""
    with conn() as c:
        row = c.execute(
            """SELECT ar.*,a.name AS automation_name,
                      (SELECT COUNT(*) FROM automation_run_events event
                       WHERE event.automation_run_id=ar.id) AS event_count
               FROM automation_runs ar JOIN automations a ON a.id=ar.automation_id
               WHERE ar.id=? AND ar.status='failed' AND a.enabled=1 AND a.trashed_at=''
                 AND ar.id=(SELECT latest.id FROM automation_runs latest
                            WHERE latest.automation_id=a.id ORDER BY latest.id DESC LIMIT 1)""",
            (int(run_id),),
        ).fetchone()
    return _automation_attention(row) if row else None


def set_automation_run_chat(run_id, chat_id):
    with _lock, conn() as c:
        c.execute("UPDATE automation_runs SET chat_id=? WHERE id=?", (int(chat_id), int(run_id)))
        c.execute("UPDATE chats SET kind='automation' WHERE id=?", (int(chat_id),))


def finish_automation_run(run_id, status, reason=""):
    final = status if status in ("completed", "failed", "cancelled", "skipped") else "failed"
    with _lock, conn() as c:
        previous=c.execute('SELECT status FROM automation_runs WHERE id=?',(int(run_id),)).fetchone()
        c.execute("UPDATE automation_runs SET status=?,reason=?,completed_at=? WHERE id=?",
                  (final, str(reason or "")[:4000], now(), int(run_id)))

        if previous and previous[0] != final:
            c.execute("INSERT INTO automation_run_events(automation_run_id,ts,kind,content_json) VALUES(?,?,?,?)", (int(run_id),now(),"status",json.dumps({"status":final},ensure_ascii=False)))


def cancel_queued_automation_runs(automation_id, reason="自动化已暂停"):
    with _lock, conn() as c:
        cur = c.execute(
            """UPDATE automation_runs SET status='cancelled',reason=?,completed_at=?
               WHERE automation_id=? AND status='queued'""",
            (str(reason or "")[:4000], now(), int(automation_id)))
        return cur.rowcount
