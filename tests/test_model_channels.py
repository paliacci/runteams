# -*- coding: utf-8 -*-
import json
import base64
import os
import tempfile
import unittest
import io
from unittest import mock

import pymupdf
from PIL import Image

TEST_DATA_DIR = tempfile.mkdtemp(prefix="runteams-tests-")
os.environ["RUNTEAMS_DATA"] = TEST_DATA_DIR

import local_database
import product_store as store
import model_channels
import provider_catalog
import chat
import codex_threads
import chat_attachments
import agent_stream
from adapter_claude import ClaudeCodeAdapter
from adapter_codex import CodexAdapter
from adapter_base import (EXECUTION_INTERNAL_ANALYSIS, EXECUTION_PIPELINE_AGENT,
                          EXECUTION_USER_AGENT)
from errors import RateLimited


class ModelChannelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(TEST_DATA_DIR, "runteams.db")
        store.init_product_db()

    @classmethod
    def tearDownClass(cls):
        local_database.DB_PATH = cls.old_db

    def test_default_channels_are_created_once(self):
        channels = store.list_channels()
        self.assertEqual([c["provider"] for c in channels], ["claude-code", "codex"])
        self.assertTrue(channels[0]["is_default"])

    def test_provider_catalog_is_the_shared_ordered_source(self):
        self.assertEqual(provider_catalog.provider_ids(), ("claude-code", "codex"))
        self.assertIs(model_channels.PROVIDERS, provider_catalog.PROVIDER_MAP)
        self.assertEqual(set(model_channels._ADAPTERS), set(provider_catalog.provider_ids()))
        public = model_channels.public_providers()
        self.assertEqual([item["id"] for item in public], ["codex", "claude-code"])
        self.assertEqual(provider_catalog.DEFAULT_PROVIDER_ID, "claude-code")
        self.assertTrue(all(item["default_effort"] == "high" for item in provider_catalog.PROVIDERS))
        self.assertEqual(provider_catalog.provider_info("codex")["config_env"], "CODEX_HOME")
        self.assertEqual(provider_catalog.provider_info("codex")["plugin_add_command"],
                         "codex plugin add {id}")

    def test_provider_channel_is_singleton(self):
        original = next(c for c in store.list_channels() if c["provider"] == "claude-code")
        cid = store.upsert_channel(None, {
            "name": "Claude 工作账号", "provider": "claude-code", "executable": "",
            "config_dir": "~/.claude-work", "default_model": "sonnet",
            "default_effort": "high", "enabled": 1, "is_default": 0,
        })
        self.assertEqual(cid, original["id"])
        self.assertEqual(len([c for c in store.list_channels() if c["provider"] == "claude-code"]), 1)
        channel = store.get_channel(cid)
        self.assertEqual(channel["config_dir"], "~/.claude-work")
        self.assertEqual(channel["default_model"], "")
        self.assertEqual(channel["default_effort"], "")
        store.init_product_db()
        channel = store.get_channel(cid)
        self.assertEqual(channel["name"], "Claude 订阅")
        self.assertEqual(channel["executable"], "")
        self.assertEqual(channel["config_dir"], "")
        ok, error = store.delete_channel(cid)
        self.assertFalse(ok)
        self.assertIn("不能删除", error)

    def test_rewind_chat_removes_selected_turn_and_resets_runtime_only(self):
        cid = store.create_chat()
        first = store.add_chat_message(cid, "user", "保留这条")
        store.add_chat_message(cid, "bot", "第一条回复")
        target = store.add_chat_message(
            cid, "user", "编辑这条", attachments=[{"id": "a" * 24, "name": "brief.md"}],
            capabilities=[{"kind": "command", "id": "plan"}])
        store.add_chat_message(cid, "bot", "将被回退")
        store.set_chat_runtime(cid, "codex", "thread-old")

        original = store.rewind_chat(cid, target)

        self.assertEqual(original["text"], "编辑这条")
        self.assertEqual(original["attachments"][0]["name"], "brief.md")
        chat_session = store.get_chat(cid)
        self.assertEqual([item["id"] for item in chat_session["messages"]], [first, first + 1])
        self.assertEqual(chat_session["runtime_provider"], "")
        self.assertEqual(chat_session["runtime_thread_id"], "")

    def test_channel_can_be_removed_and_reconnected(self):
        codex = next(c for c in store.list_channels() if c["provider"] == "codex")
        self.assertTrue(store.set_channel_enabled(codex["id"], False))
        self.assertFalse(store.get_channel(codex["id"])["enabled"])
        self.assertTrue(store.set_channel_enabled(codex["id"], True))
        self.assertTrue(store.get_channel(codex["id"])["enabled"])

    def test_codex_plan_labels(self):
        self.assertEqual(model_channels._plan_label("pro"), "Pro")
        self.assertEqual(model_channels._plan_label("enterprise"), "Enterprise")

    def test_codex_rate_limits_select_weekly_window_and_remaining(self):
        result = {"rateLimits": {
            "primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": 10},
            "secondary": {"usedPercent": 38, "windowDurationMins": 10080, "resetsAt": 20},
        }}
        with mock.patch.object(model_channels, "_codex_app_server_request", return_value=result):
            usage = model_channels._codex_rate_limits("/tmp/codex", {})
        self.assertEqual(usage["window"], "weekly")
        self.assertEqual(usage["remaining_percent"], 62)
        self.assertEqual(usage["resets_at"], 20)

    def test_channel_usage_does_not_fabricate_when_cli_has_no_weekly_limit(self):
        channel = {"id": 94, "provider": "codex", "enabled": 1, "config_dir": ""}
        with mock.patch.object(model_channels, "resolve_channel_executable", return_value="/tmp/codex"), \
                mock.patch.object(model_channels, "_probe_codex_auth", return_value={"authenticated": True}), \
                mock.patch.object(model_channels, "_codex_rate_limits", return_value={}):
            usage = model_channels.channel_usage(channel)
        self.assertEqual(usage["status"], "unavailable")
        self.assertIsNone(usage["remaining_percent"])

    def test_codex_models_are_discovered_from_app_server(self):
        channel = {"provider": "codex", "default_model": "", "config_dir": ""}
        result = {
            "data": [
                {"id": "gpt-live-a", "model": "gpt-live-a", "displayName": "Live A",
                 "isDefault": True, "defaultReasoningEffort": "high",
                 "supportedReasoningEfforts": [
                     {"reasoningEffort": "low", "description": "Fast"},
                     {"reasoningEffort": "high", "description": "Deep"}]},
                {"id": "gpt-hidden", "model": "gpt-hidden", "hidden": True},
                {"id": "gpt-live-b", "displayName": "Live B"},
            ]
        }
        with mock.patch.object(model_channels, "resolve_channel_executable", return_value="/tmp/codex"), \
                mock.patch.object(model_channels, "_codex_app_server_request", return_value=result):
            found = model_channels._codex_models(channel)
        self.assertEqual([item["value"] for item in found], ["gpt-live-a", "gpt-live-b"])
        self.assertEqual(found[0]["resolved_model"], "gpt-live-a")
        self.assertEqual(found[0]["default_effort"], "high")
        self.assertEqual(found[0]["efforts"], ["low", "high"])
        self.assertEqual(found[1]["display_name"], "Live B")

    def test_codex_models_prefer_high_as_product_default(self):
        channel = {"provider": "codex", "default_model": "", "config_dir": ""}
        result = {
            "data": [{
                "model": "gpt-live", "defaultReasoningEffort": "low",
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "low"},
                    {"reasoningEffort": "medium"},
                    {"reasoningEffort": "high"},
                ],
            }]
        }
        with mock.patch.object(model_channels, "resolve_channel_executable", return_value="/tmp/codex"), \
                mock.patch.object(model_channels, "_codex_app_server_request", return_value=result):
            found = model_channels._codex_models(channel)
        self.assertEqual(found[0]["default_effort"], "high")

    def test_codex_missing_catalog_selection_defaults_to_high(self):
        channel = {"id": 93, "provider": "codex"}
        with mock.patch.object(model_channels, "channel_catalog", return_value={"models": []}):
            self.assertEqual(model_channels.normalize_selection(channel, "gpt-custom", ""),
                             ("gpt-custom", "high"))
            self.assertEqual(model_channels.normalize_selection(channel, "gpt-custom", "low"),
                             ("gpt-custom", "low"))

    def test_global_catalog_uses_cli_discovery_without_static_models(self):
        model_channels._MODEL_CACHE.clear()
        channel = {"id": 91, "provider": "claude-code", "config_dir": "/tmp/claude-91"}
        cli_models = [{"value": "sonnet-live", "display_name": "Sonnet Live", "efforts": ["low", "high"],
                       "default_effort": "high"}]
        with mock.patch.object(model_channels, "resolve_channel_executable", return_value="/tmp/claude"), \
                mock.patch.object(model_channels, "_claude_models", return_value=cli_models):
            found = model_channels.global_catalog([channel])
        self.assertEqual(found["channels"][0]["source"], "cli")
        self.assertEqual(found["channels"][0]["models"], cli_models)

    def test_selection_is_normalized_from_global_catalog_capabilities(self):
        channel = {"id": 92, "provider": "claude-code"}
        catalog = {"models": [
            {"value": "haiku-live", "efforts": [], "default_effort": ""},
            {"value": "sonnet-live", "efforts": ["low", "high"], "default_effort": "high"},
            {"value": "adaptive-live", "efforts": ["low", "medium"], "default_effort": ""},
        ]}
        with mock.patch.object(model_channels, "channel_catalog", return_value=catalog):
            self.assertEqual(model_channels.normalize_selection(channel, "", ""),
                             ("haiku-live", ""))
            self.assertEqual(model_channels.normalize_selection(channel, "haiku-live", "high"),
                             ("haiku-live", ""))
            self.assertEqual(model_channels.normalize_selection(channel, "sonnet-live", "medium"),
                             ("sonnet-live", "high"))
            self.assertEqual(model_channels.normalize_selection(channel, "adaptive-live", ""),
                             ("adaptive-live", "low"))

    def test_every_model_prefers_high_when_supported(self):
        channel = {"id": 92, "provider": "claude-code"}
        catalog = {"models": [{
            "value": "sonnet-live", "efforts": ["low", "medium", "high"],
            "default_effort": "low",
        }]}
        with mock.patch.object(model_channels, "channel_catalog", return_value=catalog):
            self.assertEqual(model_channels.normalize_selection(channel, "sonnet-live", ""),
                             ("sonnet-live", "high"))
            self.assertEqual(model_channels.normalize_selection(channel, "sonnet-live", "low"),
                             ("sonnet-live", "low"))


    def test_chat_persists_model_configuration(self):
        codex = next(c for c in store.list_channels() if c["provider"] == "codex")
        pipeline_id = 123
        cid = store.create_chat(codex["id"], "gpt-custom", "high", pipeline_id, True)
        chat = store.get_chat(cid)
        self.assertEqual(chat["channel_id"], codex["id"])
        self.assertEqual(chat["model"], "gpt-custom")
        self.assertEqual(chat["reasoning_effort"], "high")
        self.assertEqual(chat["scope_pipeline_id"], pipeline_id)
        self.assertTrue(chat["extensions_enabled"])
        store.update_chat_config(cid, codex["id"], "gpt-custom", "high", None, False)
        updated = store.get_chat(cid)
        self.assertIsNone(updated["scope_pipeline_id"])
        self.assertFalse(updated["extensions_enabled"])

    def test_empty_chat_is_hidden_until_first_message(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], "", "")
        self.assertNotIn(cid, [chat["id"] for chat in store.list_chats()])
        store.add_chat_message(cid, "user", "开始对话")
        self.assertIn(cid, [chat["id"] for chat in store.list_chats()])
        self.assertEqual(store.get_chat(cid)["title"], "新对话")
        self.assertEqual(store.get_chat(cid)["title_source"], "pending")

    def test_codex_chat_persists_official_thread_and_title(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "low")
        captured = {}

        def fake_turn(_channel, thread_id, message, instructions, **kwargs):
            captured.update({"thread_id": thread_id, "message": message,
                             "instructions": instructions})
            kwargs["on_thread"]("thread-official", "")
            kwargs["on_title"]("官方总结标题")
            return {"text": "已完成",
                    "thread_id": "thread-official", "title": "官方总结标题", "meta": {}}

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn), \
                mock.patch.object(chat, "run_agent") as cli_run:
            result = chat.run_chat(
                "处理这个问题", [], store.get_chat(cid), chat_id=cid,
                view_context={"surface": "pipeline", "label": "发布流水线"})

        saved = store.get_chat(cid)
        self.assertEqual(captured["thread_id"], "")
        self.assertEqual(captured["message"], "处理这个问题")
        self.assertIn("用户发送这条消息时正在查看「发布流水线」", captured["instructions"])
        self.assertIn("这是环境感知上下文", captured["instructions"])
        self.assertEqual(saved["runtime_provider"], "codex")
        self.assertEqual(saved["runtime_thread_id"], "thread-official")
        self.assertEqual(saved["title"], "官方总结标题")
        self.assertEqual(saved["title_source"], "official")
        self.assertEqual(result["official_title"], "官方总结标题")
        cli_run.assert_not_called()

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn):
            chat.run_chat("继续", [], saved, chat_id=cid)
        self.assertEqual(captured["thread_id"], "thread-official")

    def test_chat_ignores_an_unresolved_bound_scope_and_keeps_visible_core_context(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        bound = 999
        visible = 888
        cid = store.create_chat(channel["id"], "gpt-test", "low", bound)
        captured = {}

        def fake_turn(_channel, _thread_id, _message, instructions, **kwargs):
            captured["instructions"] = instructions
            kwargs["on_thread"]("thread-scope", "范围测试")
            return {"text": "已确认",
                    "thread_id": "thread-scope", "title": "范围测试", "meta": {}}

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn):
            chat.run_chat(
                "检查问题", [], store.get_chat(cid), chat_id=cid,
                view_context={"surface": "pipeline", "label": "Visible pipeline",
                              "pipeline_id": visible})

        self.assertIn("全部核心流水线", captured["instructions"])
        self.assertIn("正在查看「Visible pipeline」", captured["instructions"])
        self.assertNotIn("当前默认流水线是「Bound pipeline」", captured["instructions"])

    def test_codex_completed_turn_is_a_final_text_fallback(self):
        turn = {"items": [
            {"type": "agentMessage", "text": "draft", "phase": "commentary"},
            {"type": "commandExecution", "command": "true"},
            {"type": "agentMessage", "text": "ready",
             "phase": "final_answer"},
        ]}

        self.assertEqual(codex_threads._agent_text_from_turn(turn), "ready")

    def test_codex_first_turn_uses_official_title_with_native_text_reply(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "low")

        def fake_turn(_channel, _thread_id, _message, instructions, **kwargs):
            self.assertIn("不要输出 JSON 外壳", instructions)
            kwargs["on_thread"]("thread-generated", "优化对话标题体验")
            return {"text": "可以", "thread_id": "thread-generated",
                    "title": "优化对话标题体验", "meta": {}}

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn), \
                mock.patch.object(chat.codex_threads, "set_name") as set_name:
            result = chat.run_chat("修复重复的新对话标题", [], store.get_chat(cid), chat_id=cid)

        saved = store.get_chat(cid)
        set_name.assert_not_called()
        self.assertEqual(saved["title"], "优化对话标题体验")
        self.assertEqual(saved["title_source"], "official")
        self.assertEqual(result["official_title"], "优化对话标题体验")

    def test_codex_user_chat_requests_full_agent_authority(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "high")

        def fake_turn(_channel, _thread_id, _message, _instructions, **kwargs):
            self.assertEqual(kwargs["execution_profile"], EXECUTION_USER_AGENT)
            self.assertEqual(kwargs["timeout"], 900)
            kwargs["on_thread"]("thread-authority", "权限自测")
            return {"text": "可以执行",
                    "thread_id": "thread-authority", "title": "权限自测", "meta": {}}

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "high")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn):
            result = chat.run_chat(
                "创建一个测试文件", [], store.get_chat(cid), chat_id=cid,
                capabilities=[{"kind": "plugin", "id": "documents@official",
                               "label": "Documents"}])

        self.assertEqual(result["reply"], "可以执行")

    def test_general_chat_accepts_plain_markdown_without_json_wrapper(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "high")
        reply = "已经定位问题。\n\n- 保留现有数据\n- 修复字段映射"

        def fake_turn(_channel, _thread_id, _message, instructions, **kwargs):
            self.assertIn("不要输出 JSON 外壳", instructions)
            kwargs["on_thread"]("thread-plain", "修复字段映射")
            return {"text": reply, "thread_id": "thread-plain",
                    "title": "修复字段映射", "meta": {}}

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "high")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn):
            result = chat.run_chat("检查字段映射", [], store.get_chat(cid), chat_id=cid)

        self.assertEqual(result["reply"], reply)
        self.assertEqual(result["applied"], [])

    def test_codex_first_turn_falls_back_when_cli_omits_title(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "low")

        def fake_turn(_channel, _thread_id, _message, _instructions, **kwargs):
            kwargs["on_thread"]("thread-weather", "")
            return {"text": "请告诉我城市",
                    "thread_id": "thread-weather", "title": "", "meta": {}}

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn), \
                mock.patch.object(chat, "_generate_missing_title",
                                  return_value="查询今日天气") as fallback, \
                mock.patch.object(chat.codex_threads, "set_name") as set_name:
            result = chat.run_chat("今天天气怎么样", [], store.get_chat(cid), chat_id=cid)

        fallback.assert_called_once_with(
            channel, "今天天气怎么样", "请告诉我城市", "gpt-test", "low")
        set_name.assert_called_once_with(channel, "thread-weather", "查询今日天气")
        saved = store.get_chat(cid)
        self.assertEqual(saved["title"], "查询今日天气")
        self.assertEqual(saved["title_source"], "channel")
        self.assertEqual(result["official_title"], "查询今日天气")

    def test_chat_forwards_cli_events_to_stream_callback(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        events = []
        configured = {}
        captured = {}

        def fake_run_agent(adapter, prompt, **kwargs):
            configured.update(adapter.requirements)
            captured["prompt"] = prompt
            kwargs["on_activity"].on_event({"kind": "work_delta", "id": "check",
                                             "delta": "正在检查上下文"})
            return mock.Mock(text="可以使用", meta={})

        class Activity:
            on_event = staticmethod(events.append)

        with mock.patch.object(chat.model_channels, "normalize_selection", return_value=("gpt-test", "low")), \
                mock.patch.object(chat, "run_agent", side_effect=fake_run_agent):
            result = chat.run_chat(
                "测试对话", [], {"channel_id": channel["id"]},
                on_activity=Activity(),
                capabilities=[{"kind": "skill", "id": "documents", "label": "Documents",
                               "trigger_name": "documents"}])

        self.assertEqual(result["reply"], "可以使用")
        self.assertEqual(events, [{"kind": "work_delta", "id": "check",
                                   "delta": "正在检查上下文"}])
        self.assertTrue(configured["plugins"])
        self.assertTrue(result["extensions_enabled"])
        self.assertIn("$documents", captured["prompt"])

    def test_general_chat_uses_native_request_user_input_as_choice_card(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "low")

        def fake_turn(_channel, _thread_id, _message, _instructions, **kwargs):
            kwargs["on_thread"]("thread-native-choice", "选择测试范围")
            return {
                "text": "等待用户选择",
                "thread_id": "thread-native-choice", "title": "选择测试范围", "meta": {},
                "user_input_requests": [{"questions": [{
                    "id": "scope", "question": "请选择测试范围", "options": [
                        {"label": "当前流水线", "description": "只检查当前流水线"},
                        {"label": "全部流水线", "description": "检查全部流水线"},
                        {"label": "仅当前页面", "description": "只检查当前页面"},
                    ],
                }]}],
            }

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn) as run_turn:
            result = chat.run_chat("请选择测试范围", [], store.get_chat(cid), chat_id=cid)

        self.assertEqual(run_turn.call_count, 1)
        self.assertEqual(result["reply"], "请选择测试范围")
        self.assertEqual([item["label"] for item in result["options"]],
                         ["当前流水线", "全部流水线", "仅当前页面"])

    def test_general_chat_uses_native_change_proposal_as_pending_plan(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "low")
        envelope = {
            "protocol": "runteams.agent-tool/v1", "kind": "change_proposal",
            "message": "自动化方案已准备好。", "data": {
                "summary": "创建自动化「每日复盘」", "count": 1,
                "actions": [{"op": "upsert_automation", "name": "每日复盘",
                             "prompt": "整理今日工作"}],
            },
        }

        def fake_turn(_channel, _thread_id, _message, _instructions, **kwargs):
            kwargs["on_thread"]("thread-native-proposal", "创建每日复盘")
            return {
                "text": "方案已准备好",
                "thread_id": "thread-native-proposal", "title": "创建每日复盘",
                "meta": {}, "native_tool_results": [envelope],
            }

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn):
            result = chat.run_chat("创建每日复盘", [], store.get_chat(cid), chat_id=cid)

        self.assertTrue(result["pending"])
        self.assertEqual(result["plan"]["actions"], envelope["data"]["actions"])
        self.assertEqual(result["applied"], [])

    def test_general_chat_keeps_plain_markdown_choice_without_a_second_model_call(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "low")
        plain = "请选择测试范围\n\n- 当前流水线\n- 全部流水线\n- 仅当前页面"

        def fake_turn(_channel, _thread_id, _message, _instructions, **kwargs):
            if kwargs.get("on_thread"):
                kwargs["on_thread"]("thread-repair", "选择测试范围")
            return {"text": plain, "thread_id": "thread-repair",
                    "title": "选择测试范围", "meta": {}}

        with mock.patch.object(chat.model_channels, "normalize_selection",
                               return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn) as run_turn:
            result = chat.run_chat("请选择测试范围", [], store.get_chat(cid), chat_id=cid)

        self.assertEqual(run_turn.call_count, 1)
        self.assertEqual(result["reply"], plain)
        self.assertEqual(result["options"], [])

    def test_chat_message_persists_selected_capabilities(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], "", "")
        capabilities = [{"kind": "command", "id": "plan", "label": "计划模式"}]
        store.add_chat_message(cid, "user", "先做计划", capabilities=capabilities)
        self.assertEqual(store.get_chat(cid)["messages"][-1]["capabilities"], capabilities)

    def test_inline_capability_reference_is_normalized_and_explained(self):
        capabilities = chat._normalize_capabilities([{
            "kind": "plugin", "id": "documents@official", "label": "Documents",
            "mention_id": "m-documents",
        }])
        self.assertEqual(capabilities[0]["mention_token"], "[[capability:m-documents]]")
        context = chat._capability_context(capabilities, "codex")
        self.assertIn("[[capability:m-documents]] = 官方扩展 Documents", context)
        self.assertIn("按标记前后的语义", context)

    def test_unselected_capabilities_do_not_disable_agent_chat(self):
        context = chat._capability_context([], "codex")
        self.assertIn("这不限制 Agent", context)
        self.assertIn("CLI 原生的文件、终端、搜索等工具", context)
        self.assertNotIn("不得调用", context)

    def test_channel_capability_context_distinguishes_plugins_skills_and_mcp(self):
        inventory = {
            "runtime": {"installed": True},
            "plugins": [{"id": "github@official", "display_name": "GitHub",
                         "installed": True, "enabled": True}],
            "skills": [{"id": "documents", "name": "Documents", "enabled": True}],
            "mcp_servers": [{"name": "claude-design", "enabled": True,
                             "status": "configured"}],
        }
        with mock.patch.object(chat.runtime_capabilities, "inventory",
                               return_value=inventory):
            context = chat._channel_capability_context({"provider": "codex"})
        self.assertIn("已安装并启用的插件：GitHub", context)
        self.assertIn("已启用的 Skills：Documents", context)
        self.assertIn("已配置并启用的 MCP：claude-design", context)

    def test_agent_chat_inherits_channel_capabilities_without_manual_selection(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "codex")
        cid = store.create_chat(channel["id"], "gpt-test", "low")
        captured = {}
        inventory = {
            "runtime": {"installed": True}, "plugins": [], "skills": [],
            "mcp_servers": [{"name": "claude-design", "enabled": True}],
        }

        def fake_turn(_channel, _thread_id, _message, instructions, **kwargs):
            captured.update(kwargs)
            captured["instructions"] = instructions
            kwargs["on_thread"]("thread-native", "能力继承")
            return {"text": "已确认",
                    "thread_id": "thread-native", "title": "能力继承", "meta": {}}

        with mock.patch.object(chat.runtime_capabilities, "inventory",
                               return_value=inventory), \
                mock.patch.object(chat.model_channels, "normalize_selection",
                                  return_value=("gpt-test", "low")), \
                mock.patch.object(chat.codex_threads, "run_turn", side_effect=fake_turn):
            result = chat.run_chat("检查 claude-design 是否安装", [], store.get_chat(cid),
                                   chat_id=cid, capabilities=[])

        self.assertTrue(captured["extensions_enabled"])
        self.assertEqual(captured["timeout"], 900)
        self.assertIn("已配置并启用的 MCP：claude-design", captured["instructions"])
        self.assertIn("runteams_get_context", captured["tool_names"])
        self.assertIn("runteams_request_choice", captured["tool_names"])
        self.assertEqual(captured["tool_context"]["chat_id"], cid)
        self.assertTrue(result["extensions_enabled"])

    def test_chat_rate_limit_error_is_actionable(self):
        channel = next(c for c in store.list_channels() if c["provider"] == "claude-code")
        message = chat.public_error(
            RateLimited("You've hit your weekly limit · resets Aug 3 at 4pm"),
            {"channel_id": channel["id"]})
        self.assertIn("Claude Code 当前订阅用量已达上限", message)
        self.assertIn("切换到其他已连接渠道", message)
        self.assertNotIn("You've hit", message)

    def test_chat_attachment_is_saved_and_persisted(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], channel["default_model"], "medium")
        content = b"hello attachment"
        items = chat_attachments.save(cid, [{
            "name": "brief.md", "mime_type": "text/markdown",
            "data": base64.b64encode(content).decode("ascii"),
        }])
        store.add_chat_message(cid, "user", "read this", attachments=items)
        loaded = store.get_chat(cid)["messages"][-1]["attachments"][0]
        self.assertEqual(loaded["name"], "brief.md")
        with open(chat_attachments.path_for(cid, loaded), "rb") as handle:
            self.assertEqual(handle.read(), content)
        self.assertEqual(chat_attachments.public(items)[0]["kind"], "file")
        self.assertEqual(items[0]["normalized"][0]["kind"], "text")
        with open(chat_attachments._normalized_inputs(cid, items[0])[0][1], "rb") as handle:
            self.assertEqual(handle.read(), content)
        history, _images = chat_attachments.history_context(cid, store.get_chat(cid)["messages"])
        self.assertIn("brief.md", history)

    def test_image_attachment_is_verified_and_normalized(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], channel["default_model"], "medium")
        raw = io.BytesIO()
        Image.new("RGBA", (8, 6), (20, 40, 60, 128)).save(raw, "WEBP")
        items = chat_attachments.save(cid, [{
            "name": "sample.webp", "mime_type": "image/webp",
            "data": base64.b64encode(raw.getvalue()).decode("ascii"),
        }])
        derived, path = chat_attachments._normalized_inputs(cid, items[0])[0]
        self.assertEqual(derived["kind"], "image")
        self.assertTrue(path.endswith(".png"))
        with Image.open(path) as image:
            self.assertEqual(image.format, "PNG")

    def test_pdf_attachment_extracts_text_and_renders_every_page(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], channel["default_model"], "medium")
        document = pymupdf.open()
        for number in (1, 2):
            page = document.new_page(width=240, height=180)
            page.insert_text((24, 48), "Page {} content".format(number))
        raw = document.tobytes()
        document.close()
        items = chat_attachments.save(cid, [{
            "name": "brief.pdf", "mime_type": "application/pdf",
            "data": base64.b64encode(raw).decode("ascii"),
        }])
        inputs = chat_attachments._normalized_inputs(cid, items[0])
        self.assertEqual([item[0]["kind"] for item in inputs], ["text", "image", "image"])
        with open(inputs[0][1], encoding="utf-8") as handle:
            self.assertIn("Page 2 content", handle.read())
        context, images = chat_attachments.prompt_context(cid, items)
        self.assertIn("PDF 提取文本", context)
        self.assertEqual(len(images), 2)

    def test_spoofed_image_is_rejected(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], channel["default_model"], "medium")
        with self.assertRaisesRegex(ValueError, "损坏|格式"):
            chat_attachments.save(cid, [{
                "name": "not-an-image.png",
                "data": base64.b64encode(b"plain text").decode("ascii"),
            }])

    def test_non_utf8_text_is_rejected(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], channel["default_model"], "medium")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            chat_attachments.save(cid, [{
                "name": "legacy.txt",
                "data": base64.b64encode(b"\xff\xfe\x00").decode("ascii"),
            }])

    def test_chat_attachment_rejects_unsupported_format(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], channel["default_model"], "medium")
        with self.assertRaisesRegex(ValueError, "暂不支持"):
            chat_attachments.save(cid, [{"name": "archive.zip", "data": "eA=="}])

    def test_native_folder_selection_preserves_relative_tree_and_ignores_noise(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], "", "")
        with tempfile.TemporaryDirectory() as source:
            root = os.path.join(source, "project")
            os.makedirs(os.path.join(root, "src"))
            os.makedirs(os.path.join(root, ".git"))
            os.makedirs(os.path.join(root, "node_modules"))
            with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("hello")
            with open(os.path.join(root, "src", "main.py"), "w", encoding="utf-8") as handle:
                handle.write("print('ok')")
            with open(os.path.join(root, ".git", "config"), "w", encoding="utf-8") as handle:
                handle.write("ignored")
            with open(os.path.join(root, "node_modules", "index.js"), "w", encoding="utf-8") as handle:
                handle.write("ignored")
            with open(os.path.join(root, "archive.zip"), "wb") as handle:
                handle.write(b"ignored")
            os.symlink(os.path.join(root, "README.md"), os.path.join(root, "linked.md"))

            staged = chat_attachments._stage_native_paths([root])
            self.assertEqual(staged[0]["kind"], "folder")
            self.assertEqual(staged[0]["file_count"], 2)
            saved = chat_attachments.consume_native(cid, [staged[0]["token"]])

        item = saved[0]
        self.assertEqual(item["kind"], "folder")
        derived, folder_path = chat_attachments._normalized_inputs(cid, item)[0]
        self.assertEqual(derived["kind"], "folder")
        self.assertTrue(os.path.isfile(os.path.join(folder_path, "README.md")))
        self.assertTrue(os.path.isfile(os.path.join(folder_path, "src", "main.py")))
        self.assertFalse(os.path.exists(os.path.join(folder_path, ".git")))
        context, images = chat_attachments.prompt_context(cid, saved)
        self.assertIn("2 个文件", context)
        self.assertEqual(images, [])

    def test_native_folder_selection_preserves_xcode_text_resources(self):
        channel = store.get_default_channel()
        cid = store.create_chat(channel["id"], "", "")
        with tempfile.TemporaryDirectory() as source:
            root = os.path.join(source, "ExampleApp")
            resources = os.path.join(root, "Resources")
            project = os.path.join(root, "ExampleApp.xcodeproj")
            os.makedirs(resources)
            os.makedirs(project)
            files = {
                "Info.plist": "<?xml version=\"1.0\"?><plist version=\"1.0\"></plist>",
                "Resources/Localizable.xcstrings": '{"sourceLanguage":"en"}',
                "Resources/PrivacyInfo.xcprivacy": "<?xml version=\"1.0\"?><plist version=\"1.0\"></plist>",
                "ExampleApp.entitlements": "<?xml version=\"1.0\"?><plist version=\"1.0\"></plist>",
                "ExampleApp.xcodeproj/project.pbxproj": "// !$*UTF8*$!",
            }
            for relative, content in files.items():
                path = os.path.join(root, relative)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)

            staged = chat_attachments._stage_native_paths([root])
            self.assertEqual(staged[0]["file_count"], len(files))
            saved = chat_attachments.consume_native(cid, [staged[0]["token"]])

        _, folder_path = chat_attachments._normalized_inputs(cid, saved[0])[0]
        for relative in files:
            self.assertTrue(os.path.isfile(os.path.join(folder_path, relative)), relative)

    def test_native_folder_selection_enforces_file_limit(self):
        with tempfile.TemporaryDirectory() as source:
            for index in range(3):
                with open(os.path.join(source, "{}.txt".format(index)), "w", encoding="utf-8") as handle:
                    handle.write("x")
            with mock.patch.object(chat_attachments, "MAX_NATIVE_FILES", 2):
                with self.assertRaisesRegex(ValueError, "最多处理 2 个"):
                    chat_attachments._stage_native_paths([source])

    def test_subscription_env_isolation(self):
        ca = ClaudeCodeAdapter(executable="/tmp/claude", config_dir="/tmp/claude-work")
        ce = ca.env({"ANTHROPIC_API_KEY": "secret", "PATH": "/bin"})
        self.assertEqual(ce["CLAUDE_CONFIG_DIR"], "/tmp/claude-work")
        self.assertNotIn("ANTHROPIC_API_KEY", ce)
        co = CodexAdapter(executable="/tmp/codex", config_dir="/tmp/codex-work")
        oe = co.env({"OPENAI_API_KEY": "secret", "PATH": "/bin"})
        self.assertEqual(oe["CODEX_HOME"], "/tmp/codex-work")
        self.assertNotIn("OPENAI_API_KEY", oe)

    def test_codex_jsonl_parser(self):
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "t"}) + "\n",
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}}) + "\n",
            json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 12, "cached_input_tokens": 7, "output_tokens": 3}}) + "\n",
        ]
        text, is_error, meta = CodexAdapter().consume(lines, lambda _x: None)
        self.assertEqual(text, "OK")
        self.assertFalse(is_error)
        self.assertEqual(meta["input_tokens"], 12)
        self.assertEqual(meta["cached_input_tokens"], 7)
        self.assertEqual(meta["output_tokens"], 3)

    def test_reply_delta_stream_does_not_repeat_final_replay(self):
        events = []
        def activity(_line):
            pass
        activity.on_event = events.append
        stream = agent_stream.ReplyDeltaStream(activity)
        stream.feed("已经")
        stream.feed("完成。")
        stream.feed("已经完成。", complete=True)
        self.assertEqual("".join(event.get("delta", "") for event in events), "已经完成。")

    def test_codex_jsonl_parser_forwards_reply_and_tool_lifecycle(self):
        events = []
        def activity(_line):
            pass
        activity.on_event = events.append
        lines = [
            json.dumps({"type": "item.started", "item": {
                "id": "cmd-1", "type": "command_execution", "command": "pytest"}}) + "\n",
            json.dumps({"type": "item.completed", "item": {
                "id": "cmd-1", "type": "command_execution", "command": "pytest",
                "status": "completed", "aggregated_output": "1 passed"}}) + "\n",
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": "完成"}}) + "\n",
            json.dumps({"type": "turn.completed", "usage": {}}) + "\n",
        ]
        text_value, is_error, _meta = CodexAdapter().consume(lines, activity)
        self.assertFalse(is_error)
        self.assertEqual(text_value, "完成")
        self.assertEqual([event["status"] for event in events if event["kind"] == "step"],
                         ["running", "completed"])
        self.assertEqual("".join(event.get("delta", "") for event in events
                                 if event["kind"] == "reply_delta"), "完成")

    def test_codex_jsonl_parser_hides_protocol_message_items_from_tool_steps(self):
        events = []

        def activity(_line):
            pass

        activity.on_event = events.append
        lines = [
            json.dumps({"type": "item.started", "item": {
                "id": "user-1", "type": "userMessage", "text": "322"}}) + "\n",
            json.dumps({"type": "item.completed", "item": {
                "id": "user-1", "type": "userMessage", "text": "322"}}) + "\n",
            json.dumps({"type": "item.started", "item": {
                "id": "reason-1", "type": "reasoning"}}) + "\n",
            json.dumps({"type": "item.completed", "item": {
                "id": "reason-1", "type": "reasoning"}}) + "\n",
        ]

        CodexAdapter().consume(lines, activity)

        self.assertEqual([event for event in events if event["kind"] == "step"], [])

    def test_dynamic_request_choice_is_a_visible_tool_step(self):
        event = agent_stream.step_event({
            "id": "choice-1",
            "type": "dynamicToolCall",
            "tool": "runteams_request_choice",
            "arguments": {
                "question": "请选择测试范围",
                "options": [
                    {"label": "当前流水线", "description": "只检查当前流水线"},
                    {"label": "全部流水线", "description": "检查全部流水线"},
                ],
            },
        }, "completed")

        self.assertEqual(event["step_kind"], "tool")
        self.assertEqual(event["label"], "请求用户选择")
        self.assertEqual(event["meta"]["tool"], "runteams_request_choice")
        self.assertEqual(event["meta"]["arguments"]["question"], "请选择测试范围")

    def test_codex_jsonl_parser_keeps_commentary_separate_from_final_reply(self):
        events = []
        def activity(_line):
            pass
        activity.on_event = events.append
        lines = [
            json.dumps({"type": "item.started", "item": {
                "id": "note-1", "type": "agent_message", "phase": "commentary"}}) + "\n",
            json.dumps({"type": "item.agent_message.delta", "item_id": "note-1",
                        "delta": "我先读取配置。"}) + "\n",
            json.dumps({"type": "item.completed", "item": {
                "id": "note-1", "type": "agent_message", "phase": "commentary",
                "text": "我先读取配置。"}}) + "\n",
            json.dumps({"type": "item.completed", "item": {
                "id": "final-1", "type": "agent_message", "phase": "final_answer",
                "text": "已经修复。"}}) + "\n",
            json.dumps({"type": "turn.completed", "usage": {}}) + "\n",
        ]
        text_value, is_error, _meta = CodexAdapter().consume(lines, activity)
        self.assertFalse(is_error)
        self.assertEqual(text_value, "已经修复。")
        self.assertEqual("".join(event.get("delta", "") for event in events
                                 if event["kind"] == "work_delta"), "我先读取配置。")
        self.assertEqual("".join(event.get("delta", "") for event in events
                                 if event["kind"] == "reply_delta"), "已经修复。")

    def test_codex_tool_events_keep_safe_arguments_and_results_without_plain_duplicates(self):
        events, plain = [], []

        def activity(line):
            plain.append(line)

        activity.on_event = events.append
        lines = [
            json.dumps({"type": "item.started", "item": {
                "id": "mcp-1", "type": "mcp_tool_call", "server": "runteams",
                "tool": "run_task_tool", "arguments": {
                    "tool_id": "meta-adlib-collect", "arguments": ["collect", "--tasks", "8"],
                    "api_token": "do-not-render"}}}) + "\n",
            json.dumps({"type": "item.completed", "item": {
                "id": "mcp-1", "type": "mcp_tool_call", "server": "runteams",
                "tool": "run_task_tool", "status": "completed", "arguments": {
                    "tool_id": "meta-adlib-collect", "arguments": ["collect", "--tasks", "8"],
                    "api_token": "do-not-render"}, "result": {"exit_code": 0, "rows": 386}}}) + "\n",
        ]

        CodexAdapter().consume(lines, activity)

        steps = [event for event in events if event["kind"] == "step"]
        self.assertEqual([step["status"] for step in steps], ["running", "completed"])
        self.assertEqual(steps[-1]["label"], "meta-adlib-collect")
        self.assertEqual(steps[-1]["meta"]["tool"], "run_task_tool")
        self.assertEqual(steps[-1]["meta"]["arguments"]["arguments"],
                         ["collect", "--tasks", "8"])
        self.assertEqual(steps[-1]["meta"]["arguments"]["api_token"], "••••")
        self.assertIn('"rows": 386', steps[-1]["output"])
        self.assertEqual(plain, [])

    def test_claude_parser_normalizes_all_input_token_categories(self):
        lines = [json.dumps({
            "type": "result", "result": "OK", "is_error": False,
            "usage": {"input_tokens": 5, "cache_creation_input_tokens": 11,
                      "cache_read_input_tokens": 17, "output_tokens": 3},
            "total_cost_usd": 0.01,
        }) + "\n"]
        text_value, is_error, meta = ClaudeCodeAdapter().consume(lines, lambda _x: None)
        self.assertEqual(text_value, "OK")
        self.assertFalse(is_error)
        self.assertEqual(meta["input_tokens"], 33)
        self.assertEqual(meta["cached_input_tokens"], 17)
        self.assertEqual(meta["output_tokens"], 3)

    def test_claude_partial_stream_forwards_reply_and_tool_lifecycle(self):
        events = []
        def activity(_line):
            pass
        activity.on_event = events.append
        lines = [
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_start", "content_block": {
                    "type": "tool_use", "id": "tool-1", "name": "Read"}}}) + "\n",
            json.dumps({"type": "assistant", "message": {"content": [{
                "type": "tool_use", "id": "tool-1", "name": "Read",
                "input": {"file_path": "brief.json"}}]}}) + "\n",
            json.dumps({"type": "user", "message": {"content": [{
                "type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}]}}) + "\n",
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_delta", "delta": {
                    "type": "text_delta", "text": "正在"}}}) + "\n",
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_delta", "delta": {
                    "type": "text_delta", "text": "完成"}}}) + "\n",
            json.dumps({"type": "result", "result": "正在完成",
                        "is_error": False, "usage": {}}) + "\n",
        ]
        text_value, is_error, _meta = ClaudeCodeAdapter().consume(lines, activity)
        self.assertFalse(is_error)
        self.assertEqual(text_value, "正在完成")
        self.assertEqual([event["status"] for event in events if event["kind"] == "step"],
                         ["running", "completed"])
        completed_step = [event for event in events
                          if event["kind"] == "step" and event["status"] == "completed"][0]
        self.assertEqual(completed_step["meta"]["arguments"], {"file_path": "brief.json"})
        self.assertEqual("".join(event.get("delta", "") for event in events
                                 if event["kind"] == "reply_delta"), "正在完成")

    def test_claude_parser_captures_native_runteams_tool_result(self):
        envelope = {
            "protocol": "runteams.agent-tool/v1", "kind": "change_proposal",
            "message": "待确认", "data": {"summary": "更新流水线", "actions": []},
        }
        lines = [
            json.dumps({"type": "user", "message": {"content": [{
                "type": "tool_result", "tool_use_id": "proposal-1",
                "content": [{"type": "text", "text": json.dumps(envelope)}],
            }]}}) + "\n",
            json.dumps({"type": "result", "result": "请确认",
                        "is_error": False, "usage": {}}) + "\n",
        ]

        _text, is_error, meta = ClaudeCodeAdapter().consume(lines, lambda _x: None)

        self.assertFalse(is_error)
        self.assertEqual(meta["native_tool_results"], [envelope])


    def test_codex_argv_is_noninteractive_and_isolated(self):
        argv = CodexAdapter(executable="/tmp/codex").build_argv(
            "hello", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="gpt-test", reasoning_effort="xhigh")
        self.assertIn("--json", argv)
        self.assertIn("--ephemeral", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("read-only", argv)
        self.assertIn('model_reasoning_effort="xhigh"', argv)
        self.assertEqual(argv[-1], "hello")

    def test_codex_build_semantics_do_not_expand_internal_authority(self):
        argv = CodexAdapter(executable="/tmp/codex").build_argv(
            "build", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="build", model="gpt-test")
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")

    def test_codex_internal_analysis_remains_read_only(self):
        argv = CodexAdapter(executable="/tmp/codex").build_argv(
            "review", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="gpt-test")
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")

    def test_codex_pipeline_judges_inherit_agent_authority(self):
        argv = CodexAdapter(executable="/tmp/codex").build_argv(
            "review", execution_profile=EXECUTION_PIPELINE_AGENT,
            mode="judge", model="gpt-test",
            extra_args=["--config", "mcp_servers.runteams.command=\"python3\""])
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertNotIn("--sandbox", argv)

    def test_codex_ui_agent_turns_inherit_agent_authority(self):
        argv = CodexAdapter(executable="/tmp/codex").build_argv(
            "work", execution_profile=EXECUTION_USER_AGENT,
            mode="judge", model="gpt-test")
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertNotIn("--sandbox", argv)

    def test_codex_argv_accepts_image_inputs(self):
        argv = CodexAdapter(executable="/tmp/codex").build_argv(
            "inspect", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="gpt-test",
            extra_args=["--image", "/tmp/ui.png", "--image", "/tmp/page.png"])
        image_index = argv.index("--image")
        self.assertEqual(argv[image_index + 1:], ["/tmp/ui.png", "/tmp/page.png"])
        self.assertLess(argv.index("inspect"), image_index)

    def test_claude_effort_uses_native_flag(self):
        argv = ClaudeCodeAdapter(executable="/tmp/claude").build_argv(
            "hello", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="sonnet", reasoning_effort="max")
        self.assertEqual(argv[argv.index("--effort") + 1], "max")
        self.assertIn("--safe-mode", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertNotIn("bypassPermissions", argv)

    def test_claude_inherits_extensions_only_when_enabled(self):
        adapter = ClaudeCodeAdapter(executable="/tmp/claude")
        self.assertIn("--safe-mode", adapter.build_argv(
            "hello", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="sonnet"))
        adapter.configure_requirements({"inherit_native": True})
        self.assertNotIn("--safe-mode", adapter.build_argv(
            "hello", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="sonnet"))

    def test_claude_keeps_explicit_mcp_config_while_isolating_user_settings(self):
        adapter = ClaudeCodeAdapter(executable="/tmp/claude")
        argv = adapter.build_argv(
            "hello", execution_profile=EXECUTION_PIPELINE_AGENT,
            mode="judge", model="sonnet",
            extra_args=["--mcp-config", "/tmp/runteams.json", "--strict-mcp-config"])
        self.assertNotIn("--safe-mode", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertIn("--disable-slash-commands", argv)
        self.assertIn("--mcp-config", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")

    def test_claude_ui_agent_turns_inherit_agent_authority(self):
        argv = ClaudeCodeAdapter(executable="/tmp/claude").build_argv(
            "work", execution_profile=EXECUTION_USER_AGENT,
            mode="judge", model="sonnet")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")

    def test_codex_app_server_supports_full_agent_authority(self):
        mode, policy = codex_threads._sandbox_settings(EXECUTION_USER_AGENT, "/tmp/work")
        self.assertEqual(mode, "danger-full-access")
        self.assertEqual(policy, {"type": "dangerFullAccess"})

    def test_claude_omits_model_flag_for_cli_default(self):
        argv = ClaudeCodeAdapter(executable="/tmp/claude").build_argv(
            "hello", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="", reasoning_effort="medium")
        self.assertNotIn("--model", argv)


if __name__ == "__main__":
    unittest.main()
