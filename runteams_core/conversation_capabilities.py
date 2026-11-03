"""Shared native-capability selection and prompting for both conversation hosts."""
import re
from runteams_core import model_channels

def _normalize_capabilities(value):
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").lower()
        if kind not in ("plugin", "skill", "mcp"):
            raise ValueError("所选能力类型无效，请移除后重试。")
        ident = str(item.get("id") or item.get("name") or "").strip()[:240]
        if not ident or not re.match(r"^[\w.\-:/@ ]+$", ident, re.UNICODE):
            continue
        label = str(item.get("label") or item.get("name") or ident).strip()[:120]
        trigger = str(item.get("trigger_name") or "").strip()[:160]
        if trigger and not re.match(r"^[\w.\-:/@]+$", trigger, re.UNICODE):
            trigger = ""
        plugin_id = str(item.get("plugin_id") or "").strip()[:240]
        mention_id = str(item.get("mention_id") or "").strip()[:80]
        if mention_id and not re.match(r"^[A-Za-z0-9_-]+$", mention_id):
            mention_id = ""
        mention_token = "[[capability:{}]]".format(mention_id) if mention_id else ""
        result.append({"kind": kind, "id": ident, "label": label or ident,
                       "trigger_name": trigger, "plugin_id": plugin_id,
                       "mention_id": mention_id, "mention_token": mention_token})
        if len(result) >= 12:
            break
    return result


def _capability_context(capabilities, provider):
    if not capabilities:
        return ("# 本轮显式能力\n用户没有为本轮消息指定重点能力。"
                "这不限制 Agent：仍可按任务需要使用当前渠道已安装并启用的插件、Skills、MCP，"
                "以及 CLI 原生的文件、终端、搜索等工具。")
    lines = ["# 本轮显式能力", "用户为本轮消息指定了以下重点能力。"
             "优先按标记理解它们负责的任务范围，但这不是能力白名单；"
             "完成任务所需时仍可使用当前渠道其他已安装并启用的能力及 CLI 原生工具："]
    for item in capabilities:
        kind, label = item["kind"], item["label"]
        mention = item.get("mention_token")
        prefix = (mention + " = ") if mention else ""
        if kind == "skill":
            trigger = item.get("trigger_name") or item["id"].split(":")[-1]
            token = model_channels.provider_info(provider)["command_prefix"] + trigger
            lines.append("- {}Skill {}（显式触发：{}）".format(prefix, label, token))
        elif kind == "plugin":
            lines.append("- {}官方扩展 {}（ID：{}）".format(prefix, label, item["id"]))
        elif kind == "mcp":
            lines.append("- {}MCP {}（使用已配置的连接）".format(prefix, label))
    if any(item.get("mention_token") for item in capabilities):
        lines.append("上述 [[capability:...]] 标记出现在用户原句的具体位置；按标记前后的语义判断该能力负责的任务范围，不要将多个能力的分工混在一起。")
    return "\n".join(lines)


def _channel_capability_context(channel):
    """Native runtime discovery is authoritative; never scan display inventories here.

    inventory() includes online plugin discovery and doctor diagnostics. Neither
    is a prerequisite for a chat turn, and an older display snapshot must not
    assert that this runtime has (or lacks) a capability.
    """
    return (
        "# 渠道原生能力\n"
        "插件、Skills、MCP及文件、终端、搜索等原生能力，以本轮官方运行时实际加载和提供的内容为准，"
        "不要求用户逐项勾选。用户显式标记表示本轮重点，不是能力白名单。\n"
        "插件、Skill与MCP是不同类型；回答是否安装或配置时必须准确区分。"
        "本段不是已安装能力清单，未列出某项不表示它不存在；"
        "需要确认本机状态时，使用本轮实际可用的原生工具按需核实，不要要求用户代为搜索。"
        "未安装能力不得静默安装；安装、移除或扩大系统权限仍需用户确认。"
    )
