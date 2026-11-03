# -*- coding: utf-8 -*-
"""Claude Code Agent Channel 适配器。

调用形态:claude -p <prompt> --output-format stream-json --verbose
输出形态:逐行 JSON 事件流。type=assistant 里是逐条工具调用(活动);type=result 是最终产物。
"""
import json
import os
import re
import shutil

from adapter_base import (AGENT_AUTHORITY_PROFILES, WorkerAdapter,
                          validate_execution_profile)
from errors import RateLimited, Transient
import agent_stream
import agent_tool_registry


def _tool_result_text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    values = []
    for item in content:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            values.append(str(item.get("text") or ""))
    return "\n".join(value for value in values if value)


def resolve_claude():
    from cli_discovery import resolve
    return resolve("claude-code")


class ClaudeCodeAdapter(WorkerAdapter):
    name = "claude-code"

    def __init__(self, executable=None, config_dir=None):
        self.executable = executable
        self.config_dir = config_dir
        self.requirements = {}

    def configure_requirements(self, requirements):
        self.requirements = requirements if isinstance(requirements, dict) else {}

    def build_argv(self, prompt, *, execution_profile, mode, model,
                   reasoning_effort=None, extra_args=None):
        if getattr(self, "resolve_executable", None):
            self.executable = self.resolve_executable()
        execution_profile = validate_execution_profile(execution_profile)
        extra_args = list(extra_args or [])
        argv = [self.executable or resolve_claude(), "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--no-session-persistence"]
        # Preserve the CLI's user/project settings, Skills, plugins, hooks and MCP.
        # Injected RunTeams tools merge with native configuration; no declaration is required.
        if model:
            argv += ["--model", model]
        if reasoning_effort:
            argv += ["--effort", reasoning_effort]
        # 权限只由显式执行策略决定；judge/build 只描述工作语义。
        if execution_profile in AGENT_AUTHORITY_PROFILES:
            argv += ["--permission-mode", "bypassPermissions"]
        else:
            argv += ["--permission-mode", "dontAsk"]
        argv += extra_args
        argv += ["-p", prompt]
        return argv

    def env(self, base_env):
        from cli_discovery import execution_env
        env = super().env(execution_env(self.name, self.executable, base_env))
        if self.config_dir:
            env["CLAUDE_CONFIG_DIR"] = self.config_dir
        # 渠道定义的是订阅账号，避免 shell 中的 API 凭据静默覆盖订阅登录。
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
            env.pop(key, None)
        env["MCP_TOOL_TIMEOUT"] = "2500000"
        return env

    def consume(self, stdout_lines, on_activity):
        result_text, is_error = None, False
        meta = {}
        native_tool_results = []
        reply_stream = agent_stream.ReplyDeltaStream(on_activity)
        partial_text_seen = False
        text_block = 0
        message_id = 'claude-message'
        emitted_tools = set()
        tool_names = {}
        tool_inputs = {}
        reasoning_announced = False
        for line in stdout_lines:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            ty = ev.get("type")
            if ty == "stream_event":
                stream = ev.get("event") or {}
                stream_type = stream.get("type")
                if stream_type == 'message_start':
                    message_id = str((stream.get('message') or {}).get('id') or message_id)
                if stream_type == "content_block_delta":
                    delta = stream.get("delta") or {}
                    delta_type = delta.get("type")
                    if delta_type == "text_delta":
                        partial_text_seen = True
                        agent_stream.emit(on_activity, {'kind': 'work_delta',
                            'id': message_id + ':' + str(stream.get('index', text_block)),
                            'delta': delta.get('text') or ''})
                    elif delta_type == "thinking_delta" and not reasoning_announced:
                        # Extended thinking is private model reasoning.  Surface only a safe,
                        # user-facing phase instead of exposing the raw chain of thought.
                        reasoning_announced = True
                        agent_stream.emit(on_activity, {
                            "kind": "reasoning_delta", "delta": "正在分析任务与上下文"})
                elif stream_type == "content_block_start":
                    text_block = stream.get('index', text_block + 1)
                    block = stream.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        tool_id = str(block.get("id") or "")
                        emitted_tools.add(tool_id)
                        tool_names[tool_id] = str(block.get("name") or "工具调用")
                        if block.get("input") is not None:
                            tool_inputs[tool_id] = block.get("input") or {}
                        agent_stream.emit(on_activity, agent_stream.step_event({
                            "id": tool_id, "type": "dynamicToolCall", "tool": block.get("name"),
                            "arguments": tool_inputs.get(tool_id) or {}}, "running"))
            elif ty == "assistant":
                for blk in ev.get("message", {}).get("content", []):
                    if blk.get("type") == "text" and not partial_text_seen:
                        agent_stream.emit(on_activity, {'kind': 'work_delta',
                            'id': str((ev.get('message') or {}).get('id') or message_id) + ':' + str(text_block),
                            'delta': blk.get('text') or ''})
                        text_block += 1
                    elif blk.get("type") == "thinking" and not reasoning_announced:
                        reasoning_announced = True
                        agent_stream.emit(on_activity, {
                            "kind": "reasoning_delta", "delta": "正在分析任务与上下文"})
                    elif blk.get("type") == "tool_use":
                        tool_id = str(blk.get("id") or "")
                        tool_names[tool_id] = str(blk.get("name") or "工具调用")
                        tool_inputs[tool_id] = blk.get("input") or {}
                        if tool_id not in emitted_tools:
                            emitted_tools.add(tool_id)
                            agent_stream.emit(on_activity, agent_stream.step_event({
                                "id": tool_id, "type": "dynamicToolCall", "tool": blk.get("name"),
                                "arguments": tool_inputs[tool_id]}, "running"))
            elif ty == "user":
                for blk in ev.get("message", {}).get("content", []):
                    if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                        continue
                    tool_id = str(blk.get("tool_use_id") or "")
                    output = _tool_result_text(blk.get("content"))
                    try:
                        envelope = json.loads(output)
                    except (TypeError, ValueError):
                        envelope = None
                    if (isinstance(envelope, dict)
                            and envelope.get("protocol") == agent_tool_registry.PROTOCOL
                            and envelope.get("kind") in (
                                "choice", "change_proposal", "creator_source")):
                        native_tool_results.append(envelope)
                    agent_stream.emit(on_activity, agent_stream.step_event({
                        "id": tool_id, "type": "dynamicToolCall",
                        "tool": tool_names.get(tool_id, "工具调用"),
                        "arguments": tool_inputs.get(tool_id) or {}},
                        "failed" if blk.get("is_error") else "completed",
                        output=output))
            elif ty == "result":
                result_text = ev.get("result")
                reply_stream.feed(result_text, complete=True)
                is_error = bool(ev.get("is_error"))
                # result 事件是权威成本口径:total_cost_usd 已含缓存分层,别拿 assistant.usage 求和。
                u = ev.get("usage") or {}
                raw_input = u.get("input_tokens")
                cache_read = u.get("cache_read_input_tokens")
                cache_create = u.get("cache_creation_input_tokens")
                input_parts = [raw_input, cache_read, cache_create]
                input_total = (sum(int(value or 0) for value in input_parts)
                               if any(value is not None for value in input_parts) else None)
                meta = {
                    "cost_usd": ev.get("total_cost_usd"),
                    # 统一口径：输入包含普通输入、缓存写入和缓存命中；缓存命中另列为子集。
                    "input_tokens": input_total,
                    "cached_input_tokens": cache_read,
                    "output_tokens": u.get("output_tokens"),
                    "model": ev.get("model") or None,
                    "native_tool_results": list(native_tool_results),
                }
        if native_tool_results and "native_tool_results" not in meta:
            meta["native_tool_results"] = list(native_tool_results)
        return result_text, is_error, meta

    def classify_error(self, blob, is_error, returncode):
        if returncode == 0 and not is_error:
            return
        low = blob.lower()
        # 限流/用量上限=瞬时外因。通配 `hit your <任意词> limit`,别逐个枚举额度种类
        # (周/月/会话/用量…),否则漏一种就掉进普通失败分支疯狂空转(2026-07-20 实案:482次)。
        if ('"api_error_status":429' in blob or "session limit" in low
                or "usage limit" in low or "rate limit" in low or "quota" in low
                or re.search(r"hit your \w+ limit", low)
                or re.search(r"limit\s*[·・|]\s*resets", low)):
            raise RateLimited("用量/限流:{}".format(blob[:500]))
        # 瞬时网络错误(API 连接中途断)= 外因,不计失败、下轮直接重试。
        if ("connection closed" in low or "connection error" in low
                or "connection reset" in low or "econnreset" in low
                or "closed mid-response" in low):
            raise Transient("瞬时连接错误:{}".format(blob[:300]))
        return
