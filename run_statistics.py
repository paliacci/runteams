"""Small read-only projections over durable Workflow and Automation facts."""

import re

import automation_store as automations


_CATEGORIES = (
    ("模型额度不足", r"quota|rate.?limit|usage.?limit|weekly limit|too many requests|额度|限额|配额"),
    ("网络或服务暂时不可用",
     r"timeout|timed out|network|connection|connect reset|temporar|unavailable|断网|网络|超时|暂时不可用"),
    ("模型渠道未连接",
     r"not logged|unauthori[sz]ed|forbidden|authentication|credential|未登录|未连接|认证|授权"),
    ("能力或工具不可用",
     r"capabilit|\btool\b|\bmcp\b|package|plugin|executable|command not found|能力|工具|插件"),
    ("交付格式无效",
     r"protocol|schema|structured|invalid json|parse|result format|协议|结构化|格式"),
    ("缺少运行条件", r"\bmissing\b|\brequired\b|blocked|缺少|阻塞|前置条件"),
)


def _category(reason):
    text = str(reason or "")
    for label, pattern in _CATEGORIES:
        if re.search(pattern, text, re.I):
            return label
    return "其他运行错误"


def summary(core, limit=2000):
    """Return the smallest useful aggregate, derived on every read."""
    limit = max(1, min(10000, int(limit)))
    reasons = list(core.failure_reasons(limit))
    reasons.extend(automations.failure_reasons(limit))
    counts = {}
    for reason in reasons:
        label = _category(reason)
        counts[label] = counts.get(label, 0) + 1
    order = [label for label, _pattern in _CATEGORIES] + ["其他运行错误"]
    return {
        "total": len(reasons),
        "reasons": [
            {"reason": label, "count": counts[label]}
            for label in order if counts.get(label)
        ],
    }
