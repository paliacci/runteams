"""Original schedule normalization, without a cloud database dependency."""
import json,re
from local_database import now

def _automation_json(value, fallback):
    if isinstance(value, type(fallback)):
        return value
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError) as exc:
        raise ValueError('自动化记录无效，请重新读取或修复。') from exc
    if not isinstance(parsed,type(fallback)):
        raise ValueError('自动化记录无效，请重新读取或修复。')
    return parsed


def _automation_time(config):
    value = str((config or {}).get("time") or "09:00")
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value)
    if not match:
        raise ValueError("请选择有效的执行时间")
    return int(match.group(1)), int(match.group(2)), "{:02d}:{:02d}".format(
        int(match.group(1)), int(match.group(2)))


def _normalize_automation_schedule(raw):
    kind = str(raw.get("schedule_kind") or "interval").strip().lower()
    if kind not in ("interval", "daily", "weekly"):
        raise ValueError("请选择有效的运行计划")
    try:
        interval = max(60, min(30 * 86400, int(raw.get("interval_sec") or 3600)))
    except (TypeError, ValueError):
        raise ValueError("请选择有效的运行周期")
    # An omitted input creates the documented default schedule. Stored invalid
    # JSON still fails explicitly when an existing record is read.
    supplied = raw.get("schedule") if "schedule" in raw else raw.get("schedule_config", {})
    config = _automation_json({} if supplied is None else supplied, {})
    if kind in ("daily", "weekly"):
        _, _, normalized_time = _automation_time(config)
        config["time"] = normalized_time
    if kind == "weekly":
        weekdays = []
        for value in config.get("weekdays") or []:
            try:
                day = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= day <= 6 and day not in weekdays:
                weekdays.append(day)
        if not weekdays:
            raise ValueError("每周计划至少选择一天")
        config["weekdays"] = sorted(weekdays)
    return kind, interval, config

