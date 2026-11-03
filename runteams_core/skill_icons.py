"""Stable skill identity. Curated vectors are UI choices, never runtime permissions."""
import json
import re

from .contracts import ContractError

SCHEMA = "runteams.skill-icon/v1"
FILE_NAME = "runteams-icon.json"

# Original RunTeams vectors: 24-unit canvas, rounded 1.65-unit strokes.
# Color is supplied by the existing global semantic icon tokens in the client.
CATALOG = {
    "skill": ("专业方法", 4, ["M12 3 20 7.5V16.5L12 21 4 16.5V7.5Z", "M4 7.5 12 12 20 7.5M12 12V21"], ["技能", "skill", "方法"]),
    "skill-create": ("技能创建", 4, ["M5 5H14M5 9H10M5 13H8M5 17H8", "M15 11 18 8 21 11 14 18 10 19 11 15Z", "M17 9 20 12"], ["技能创建", "创建技能", "skill-creator", "skill author"]),
    "browser-test": ("网页测试", 2, ["M9 20H5A2 2 0 0 1 3 18V6A2 2 0 0 1 5 4H19A2 2 0 0 1 21 6V11M3 9H21", "M14 17 17 20 22 14", "M6 6.5H6.1M9 6.5H9.1"], ["项目运行", "网页测试", "webapp-testing", "browser test", "浏览器测试", "试用"]),
    "frontend": ("前端设计", 0, ["M8 20H5A2 2 0 0 1 3 18V6A2 2 0 0 1 5 4H19A2 2 0 0 1 21 6V12M3 9H21", "M15 13 12 16 15 19M19 13 22 16 19 19"], ["前端", "frontend", "网页设计", "web design"]),
    "layout": ("列表与布局", 0, ["M4 4H20V20H4ZM4 9H20M9 9V20", "M12 13H17M12 16H17"], ["列表页", "list-design", "list design", "后台列表", "layout"]),
    "communication": ("沟通写作", 1, ["M17 12H7L3 16V5A2 2 0 0 1 5 3H17A2 2 0 0 1 19 5V10", "M9 16V19H17L21 22V13A2 2 0 0 0 19 11M7 7H15"], ["内部沟通", "internal-comms", "周报", "newsletter", "公告", "沟通写作"]),
    "poster": ("海报与视觉", 3, ["M5 3H19V21H5Z", "M8 17 12 11 16 17ZM8 6H13M8 8H11", "M16 7H16.1"], ["海报", "canvas-design", "poster", "宣传图", "视觉设计"]),
    "document": ("文档写作", 0, ["M14 3H6A2 2 0 0 0 4 5V19A2 2 0 0 0 6 21H18A2 2 0 0 0 20 19V9ZM14 3V9H20", "M8 13H16M8 17H14"], ["文档", "document", "doc-coauthoring", "方案", "报告"]),
    "git": ("代码仓库", 4, ["M6 6A2 2 0 1 0 6 2A2 2 0 0 0 6 6M6 6V18M6 22A2 2 0 1 0 6 18A2 2 0 0 0 6 22", "M18 9A2 2 0 1 0 18 5A2 2 0 0 0 18 9M18 9V12A6 6 0 0 1 12 18H6"], ["代码仓库", "仓库协作", "git", "repository", "版本管理"]),
    "defect": ("缺陷分析", 3, ["M9 8H15L17 11V16A5 5 0 0 1 7 16V11ZM9 8V6L7 4M15 8V6L17 4", "M3 11H7M17 11H21M3 16H7M17 16H21M5 21 8 18M19 21 16 18M12 9V20"], ["缺陷", "defect", "bug", "复现", "排障"]),
    "issues": ("问题协作", 3, ["M8 5H19V21H5V5H8M9 3H15V7H9Z", "M9 12 10 13 12 11M14 12H16M9 17 10 18 12 16M14 17H16"], ["问题协作", "work-items", "issue", "问题交接", "问题清单"]),
    "mail-triage": ("邮件分拣", 2, ["M3 5H17V15H3ZM3 5 10 10 17 5", "M12 19H21M18 16 21 19 18 22M6 18V21"], ["邮件分拣", "mail-triage", "triage", "邮件分类"]),
    "mail-reply": ("邮件回复", 0, ["M3 5H21V15H3ZM3 5 12 11 21 5", "M9 20 6 17 9 14M6 17H15A4 4 0 0 1 19 21"], ["邮件回复", "reply-drafting", "reply draft", "回复草稿"]),
    "mailbox": ("邮箱", 2, ["M3 5H21V19H3ZM3 5 12 12 21 5", "M3 19 8 13M21 19 16 13"], ["邮箱", "mailbox", "邮件", "email", "mail"]),
    "meeting": ("会议纪要", 1, ["M9 11H6L3 14V5A2 2 0 0 1 5 3H16A2 2 0 0 1 18 5V8M7 7H14", "M12 12H21V22H12ZM14 15H19M14 18H19"], ["会议纪要", "meeting-notes", "meeting", "会议", "纪要"]),
    "data": ("数据分析", 2, ["M4 3V20H21M8 16V11H11V16M14 16V7H17V16M19 5H19.1"], ["数据", "data", "csv", "表格", "分析报表", "统计"]),
    "text": ("文本处理", 0, ["M4 5H20M12 5V19M8 19H16M4 9V5M20 9V5", "M18 13H22M18 17H22M18 21H22"], ["文本", "text", "空白", "字符", "排版", "whitespace"]),
    "calendar": ("日程安排", 1, ["M4 5H20V21H4ZM8 3V7M16 3V7M4 10H20", "M8 14H9M13 14H14M8 18H9M13 18H14"], ["日程", "日历", "calendar", "schedule", "排期"]),
}


def normalize_icon(value):
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ContractError("技能图标格式无效")
    if set(value) - {"schema", "id", "tone"}:
        raise ContractError("技能图标只接受图形和主题配色")
    icon_id = value.get("id")
    if not isinstance(icon_id, str) or icon_id not in CATALOG:
        raise ContractError("技能图形不存在，请从图标库选择")
    tone = value.get("tone", CATALOG[icon_id][1])
    if type(tone) is not int or not 0 <= tone <= 5:
        raise ContractError("技能图标配色无效")
    return {"schema": SCHEMA, "id": icon_id, "tone": tone}


def choose_icon(manifest):
    """Name is stronger than incidental words in the description; unknowns stay generic."""
    name = str(manifest.get("display_name") or manifest.get("name") or "").lower()
    description = str(manifest.get("description") or "").lower()
    def matches(term, text):
        return bool(re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", text)) if term.isascii() else term in text
    scores = {}
    for icon_id, (_, _, _, terms) in CATALOG.items():
        scores[icon_id] = sum((30 + len(term) * 2 if matches(term, name) else 0) +
                              (1 if matches(term, description) else 0) for term in terms)
    icon_id = max(scores, key=scores.get) if any(scores.values()) else "skill"
    return normalize_icon({"schema": SCHEMA, "id": icon_id})


def public_icon(value):
    descriptor = normalize_icon(value)
    label, _, paths, _ = CATALOG[descriptor["id"]]
    return {**descriptor, "label": label, "paths": list(paths)}


def icon_options():
    return [{"id": icon_id, "meaning": value[0], "tone": value[1]} for icon_id, value in CATALOG.items()]


def read_icon(files):
    if FILE_NAME not in files:
        return None
    if len(files[FILE_NAME]) > 2048:
        raise ContractError("技能图标描述过大")
    try:
        return normalize_icon(json.loads(files[FILE_NAME].decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ContractError("技能图标不是有效的UTF-8 JSON") from exc


def ensure_draft_icon(directory, manifest, previous=None):
    """Materialize before snapshot/check. Existing valid choices are never regenerated."""
    target = directory / FILE_NAME
    if target.exists() or target.is_symlink():
        if target.is_symlink():
            raise ContractError("技能图标不支持符号链接")
        return read_icon({FILE_NAME: target.read_bytes()})
    icon = normalize_icon(previous) if previous else choose_icon(manifest)
    # Exclusive creation avoids overwriting an Agent or another writer's choice.
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(icon, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:
        return read_icon({FILE_NAME: target.read_bytes()})
    return icon
