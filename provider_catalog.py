# -*- coding: utf-8 -*-
"""RunTeams 支持的模型渠道目录。

这里只放跨前后端共享的声明式元数据。厂商协议实现仍由 ``model_channels``
里的适配器注册表负责；新增渠道时先在这里登记，再注册对应适配器即可。
"""

PROVIDERS = (
    {
        "id": "claude-code",
        "label": "Claude Code",
        "short_label": "Claude",
        "channel_name": "Claude 订阅",
        "config_env": "CLAUDE_CONFIG_DIR",
        "binary_env": "CLAUDE_BIN",
        "executable": "claude",
        "login_args": ["auth", "login"],
        "brand": "claude",
        "icon": "claude-code",
        "initial": "C",
        "default": True,
        "ui_order": 20,
        "default_effort": "high",
        "default_config_dir": "~/.claude",
        "project_skills_dir": ".claude/skills",
        "personal_skills_extra": [],
        "plugin_list_args": ["plugin", "list", "--json", "--available"],
        "plugin_add_args": ["plugin", "install", "{id}"],
        "plugin_add_command": "claude plugin install {id}",
        "plugin_remove_command": "claude plugin uninstall {id}",
        "official_marketplace": {
            "id": "claude-plugins-official",
            "source": "anthropics/claude-plugins-official",
            "catalog_cache": "plugins/plugin-catalog-cache.json",
        },
        "mcp_add_command": "claude mcp add <名称> <MCP URL 或命令>",
        "command_prefix": "/",
        "persistent_threads": False,
    },
    {
        "id": "codex",
        "label": "Codex",
        "short_label": "Codex",
        "channel_name": "Codex 订阅",
        "config_env": "CODEX_HOME",
        "binary_env": "CODEX_BIN",
        "executable": "codex",
        "login_args": ["login", "--device-auth"],
        "brand": "codex",
        "icon": "codex",
        "initial": "O",
        "default": False,
        "ui_order": 10,
        "default_effort": "high",
        "default_config_dir": "~/.codex",
        "project_skills_dir": ".agents/skills",
        "personal_skills_extra": ["~/.agents/skills"],
        "plugin_list_args": ["plugin", "list", "--available", "--json"],
        "plugin_add_args": ["plugin", "add", "{id}"],
        "plugin_add_command": "codex plugin add {id}",
        "plugin_remove_command": "codex plugin remove {id}",
        "mcp_add_command": "codex mcp add <名称> --url <MCP URL>",
        "command_prefix": "$",
        "persistent_threads": True,
    },
)

PROVIDER_MAP = {item["id"]: item for item in PROVIDERS}
DEFAULT_PROVIDER_ID = next(item["id"] for item in PROVIDERS if item.get("default"))


def provider_ids():
    return tuple(item["id"] for item in PROVIDERS)


def supports(provider):
    return provider in PROVIDER_MAP


def provider_info(provider):
    return PROVIDER_MAP.get(provider) or PROVIDER_MAP[DEFAULT_PROVIDER_ID]


def public_catalog():
    """返回可直接交给前端的有序渠道目录副本。"""
    return [dict(item) for item in sorted(PROVIDERS, key=lambda row: row.get("ui_order", 999))]
