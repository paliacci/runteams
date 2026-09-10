# -*- coding: utf-8 -*-
"""OpenAI Codex 订阅适配器：JSONL 活动流 + 独立 CODEX_HOME。"""
import json
import os
import re
import shutil

from adapter_base import AGENT_AUTHORITY_PROFILES, WorkerAdapter, validate_execution_profile
from errors import RateLimited, Transient
import agent_stream


def resolve_codex():
    cands = [
        os.environ.get("CODEX_BIN"),
        "/Applications/ChatGPT.app/Contents/Resources/codex",
        os.path.expanduser("~/.local/bin/codex"),
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
    ]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    found = shutil.which("codex")
    if found:
        return found
    raise RuntimeError("找不到 codex 可执行文件；可在渠道设置里指定 CLI 路径。")


class CodexAdapter(WorkerAdapter):
    name = "codex"

    def __init__(self, executable=None, config_dir=None):
        self.executable = executable
        self.config_dir = config_dir
        self.requirements = {}

    def configure_requirements(self, requirements):
        self.requirements = requirements if isinstance(requirements, dict) else {}

    def _uses_native_dependencies(self):
        return bool(self.requirements.get("inherit_native")
                    or self.requirements.get("plugins") or self.requirements.get("mcp_servers")
                    or self.requirements.get("mcp"))

    def _isolated_plugin_args(self):
        result = []
        marketplaces = self.requirements.get("codex_marketplaces") or []
        plugins = self.requirements.get("plugins") or []
        for item in marketplaces:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            source = str(item.get("source") or "").strip()
            if not name or not source:
                continue
            key = json.dumps(name, ensure_ascii=False)
            result += ["--config", "marketplaces.{}.source_type=\"local\"".format(key),
                       "--config", "marketplaces.{}.source={}".format(
                           key, json.dumps(source, ensure_ascii=False))]
        for plugin_id in plugins:
            plugin_id = str(plugin_id or "").strip()
            if plugin_id:
                result += ["--config", "plugins.{}.enabled=true".format(
                    json.dumps(plugin_id, ensure_ascii=False))]
        return result

    def build_argv(self, prompt, *, execution_profile, mode, model,
                   reasoning_effort=None, extra_args=None):
        execution_profile = validate_execution_profile(execution_profile)
        extra = list(extra_args or [])
        argv = [self.executable or resolve_codex(), "exec", "--json", "--ephemeral",
                "--skip-git-repo-check", "--color", "never"]
        if self.requirements.get("isolated_native"):
            # 员工只读取本次发布版本声明的扩展。认证仍来自 CODEX_HOME，普通用户
            # config.toml、未声明插件和项目规则都不会进入运行结果。
            argv += ["--ignore-user-config", "--ignore-rules",
                     "--enable", "plugins", "--enable", "remote_plugin", "--enable", "apps"]
            argv += self._isolated_plugin_args()
        elif self._uses_native_dependencies():
            # 插件/MCP 配置属于官方 Codex Channel。只有 Worker 明确声明依赖时才继承；
            # 否则保持原有的隔离行为，避免无关用户配置改变可复现结果。
            argv += ["--enable", "plugins", "--enable", "remote_plugin", "--enable", "apps",
                     "--ignore-rules"]
        else:
            argv += ["--ignore-user-config", "--ignore-rules",
                     "--disable", "plugins", "--disable", "remote_plugin", "--disable", "apps",
                     "--disable", "browser_use", "--disable", "hooks", "--disable", "shell_snapshot"]
        # 权限只由显式执行策略决定；judge/build 只描述工作语义。
        if execution_profile in AGENT_AUTHORITY_PROFILES:
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            argv += ["--sandbox", "read-only"]
        if model:
            argv += ["--model", model]
        if reasoning_effort:
            # Codex CLI 的正式配置键；即使忽略用户 config.toml，本次运行覆盖仍然生效。
            argv += ["--config", 'model_reasoning_effort="{}"'.format(reasoning_effort)]
        # `--image <FILE>...` 是可变参数；若把 prompt 放在它后面，CLI 会把 prompt
        # 当成最后一张图片，随后改为从已关闭的 stdin 读取提示词。把图片参数统一
        # 放到已解析的 prompt 后面，既支持多图，也不影响 MCP 等普通参数。
        image_paths, regular = [], []
        index = 0
        while index < len(extra):
            if extra[index] == "--image" and index + 1 < len(extra):
                image_paths.append(extra[index + 1])
                index += 2
            else:
                regular.append(extra[index])
                index += 1
        argv += regular
        argv += [prompt]
        if image_paths:
            argv += ["--image"] + image_paths
        return argv

    def env(self, base_env):
        env = super().env(base_env)
        if self.config_dir:
            env["CODEX_HOME"] = self.config_dir
        for key in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN"):
            env.pop(key, None)
        return env

    def consume(self, stdout_lines, on_activity):
        final_text, is_error, meta = None, False, {}
        plain = []
        reply_stream = agent_stream.ReplyDeltaStream(on_activity)
        agent_message_phases, work_buffers = {}, {}

        def item_type(value):
            return str(value or "").replace("_", "").replace("-", "").lower()

        def is_protocol_item(value):
            # These are conversation framing emitted by the Codex runtime, not
            # user-facing tool work.  Treating them as unknown tools produces
            # misleading rows such as “已调用 userMessage”.
            return item_type(value) in ("usermessage", "reasoning", "plan")

        def emit_work(item_id, value, complete=False):
            key = str(item_id or "commentary")
            text = str(value or "")
            previous = work_buffers.get(key, "")
            delta = text[len(previous):] if complete and text.startswith(previous) else text
            if not delta:
                return
            work_buffers[key] = text if complete else previous + delta
            agent_stream.emit(on_activity, {"kind": "work_delta", "id": key, "delta": delta})

        for line in stdout_lines:
            raw = line.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except Exception:
                plain.append(line)
                continue
            ty = ev.get("type")
            item = ev.get("item") or {}
            if ty == "item.started":
                if item_type(item.get("type")) == "agentmessage":
                    agent_message_phases[str(item.get("id") or "commentary")] = item.get("phase")
                elif not is_protocol_item(item.get("type")):
                    agent_stream.emit(on_activity, agent_stream.step_event(item, "running"))
            elif ty == "item.completed":
                it = item.get("type")
                if item_type(it) == "agentmessage":
                    item_id = str(item.get("id") or "commentary")
                    phase = item.get("phase") or agent_message_phases.get(item_id)
                    text = item.get("text") or item.get("content") or ""
                    if phase == "commentary":
                        emit_work(item_id, text, complete=True)
                    else:
                        final_text = text or final_text
                        reply_stream.feed(text, complete=True)
                elif it == "error":
                    agent_stream.emit(on_activity, agent_stream.step_event({
                        "id": item.get("id") or "codex-error", "type": "tool",
                        "name": "Codex 运行", "error": item.get("message") or "Codex 错误",
                    }, "failed"))
                elif it and not is_protocol_item(it):
                    agent_stream.emit(on_activity, agent_stream.step_event(
                        item, "failed" if item.get("status") == "failed" else "completed",
                        output=item.get("aggregated_output") or item.get("output") or
                               item.get("result") or item.get("error") or ""))
            elif ty in ("item.agent_message.delta", "item/agentMessage/delta"):
                item_id = str(ev.get("item_id") or ev.get("itemId") or item.get("id") or "commentary")
                delta = ev.get("delta") or item.get("delta") or ""
                if (item.get("phase") or agent_message_phases.get(item_id)) == "commentary":
                    emit_work(item_id, delta)
                else:
                    reply_stream.feed(delta)
            elif ty in ("item.reasoning.summary_text_delta", "item/reasoning/summaryTextDelta"):
                agent_stream.emit(on_activity, {"kind": "reasoning_delta",
                                                 "delta": str(ev.get("delta") or "")})
            elif ty in ("item.plan.delta", "item/plan/delta"):
                agent_stream.emit(on_activity, {"kind": "plan_delta",
                                                 "delta": str(ev.get("delta") or "")})
            elif ty in ("item.command_execution.output_delta",
                        "item/commandExecution/outputDelta"):
                agent_stream.emit(on_activity, {
                    "kind": "step_output", "id": str(ev.get("item_id") or
                                                         ev.get("itemId") or "command"),
                    "delta": str(ev.get("delta") or "")[-2000:]})
            elif ty == "turn.completed":
                usage = ev.get("usage") or {}
                meta = {"input_tokens": usage.get("input_tokens"),
                        "cached_input_tokens": usage.get("cached_input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                        "cost_usd": None, "model": ev.get("model")}
            elif ty in ("turn.failed", "error"):
                is_error = True
                agent_stream.emit(on_activity, agent_stream.step_event({
                    "id": "codex-turn", "type": "tool", "name": "Codex 运行",
                    "error": ev.get("message") or ev.get("error") or "Codex 运行失败",
                }, "failed"))
        if final_text is None and plain:
            final_text = "".join(plain).strip() or None
        return final_text, is_error, meta

    def classify_error(self, blob, is_error, returncode):
        if returncode == 0 and not is_error:
            return
        low = blob.lower()
        # TODO(真机核对③):把 Codex 真实的限流/额度措辞补进来。以下为合理猜测。
        if ("rate limit" in low or "429" in low or "usage limit" in low
                or "quota" in low or "too many requests" in low
                or re.search(r"limit.*reset", low)):
            raise RateLimited("Codex 用量/限流:{}".format(blob[:500]))
        if ("connection closed" in low or "connection error" in low
                or "connection reset" in low or "econnreset" in low
                or "timed out" in low or "network" in low):
            raise Transient("Codex 瞬时连接错误:{}".format(blob[:300]))
        return
