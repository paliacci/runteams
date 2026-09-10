# -*- coding: utf-8 -*-
"""Headless AI repair for one validated Employee draft.

The runtime deliberately has no RunTeams chat/session identity.  It may improve
employee behavior instructions, while the core service preserves tests and
business contracts before applying the result.
"""
import json

import chat
import codex_threads
import model_channels
from adapter_base import EXECUTION_INTERNAL_ANALYSIS
from runner import run_agent


_TOOL_NAMES = ["runteams_present_employee_draft"]


def _repair_draft(employee):
    draft = employee.get("draft_json") or {}
    program = draft.get("program") or {}
    return {
        "name": employee.get("name") or "",
        "goal": program.get("objective") or draft.get("role") or "",
        "instructions": draft.get("role") or "",
        "program": {
            "objective": program.get("objective") or draft.get("role") or "",
            "steps": [{
                "id": item.get("id"),
                "name": "步骤 {}".format(index + 1),
                "instructions": item.get("instruction") or "",
            } for index, item in enumerate(program.get("steps") or [])],
            "delivery": {
                "acceptance_criteria": "\n".join(program.get("acceptance") or []),
            },
        },
        "capabilities": draft.get("capabilities") or [],
        "interface": draft.get("interface") or {},
        "tests": draft.get("tests") or [],
    }


class AgentEmployeeRepairRuntime:
    def __init__(self, root, channel_resolver=None, timeout_sec=900):
        self.root = str(root)
        self.channel_resolver = channel_resolver
        self.timeout_sec = int(timeout_sec)

    def _channel(self, employee):
        provider = str((employee.get("draft_json") or {}).get(
            "runtime", {}).get("channel") or "").strip()
        channel = {"provider": provider, "enabled": 1, "executable": "",
                   "config_dir": ""}
        if self.channel_resolver is not None:
            channel = self.channel_resolver(provider)
        if not channel or not channel.get("enabled"):
            raise RuntimeError("员工使用的模型渠道不可用")
        return channel

    def __call__(self, employee, failures, protected_tests=None):
        channel = self._channel(employee)
        runtime = (employee.get("draft_json") or {}).get("runtime") or {}
        model, effort = model_channels.normalize_selection(
            channel, runtime.get("model"), runtime.get("effort"))
        current = _repair_draft(employee)
        instructions = """你是 RunTeams 的后台员工修复器。根据真实失败样本，对员工行为说明做最小修复。

硬性规则：
- 不询问用户，不创建对话，不解释过程。
- 测试用例是不可修改的验收目标，禁止删除、增加、弱化或改写 tests。
- 禁止修改员工名称、capabilities、interface、runtime。
- program.steps 的 id、数量和顺序必须保持不变；只可改进 role/instructions、objective、已有步骤的 instructions 和 delivery.acceptance_criteria。
- 修复必须解决全部失败样本，不能只针对某一次输出写死答案。
- 已通过场景是不可回归约束；修复不得改变它们原本正确的状态和交付行为。
- skill 是说明和资源，不是可传给 run_capability 的工具引用；run_capability 只能使用下方 callable_tools 中的精确引用。
- 同一冻结能力包中的 callable_tools 可直接调用。不要因为 skill 引用与工具 ID 不同，就把正常场景误判为能力不可用。
- 验证场景把某个能力包标记为 unavailable 时，该包的 skill 和 tool 会一起不可用，此时才应报告 failed。
- 完成后必须调用 runteams_present_employee_draft，提交完整员工草稿；不要只返回普通文本。

# 当前员工草稿
{}

# 未通过场景与真实样本
{}

# 已通过场景与真实样本（不可回归）
{}

# 冻结能力的运行边界
{}""".format(
            json.dumps(current, ensure_ascii=False, indent=2),
            json.dumps(failures, ensure_ascii=False, indent=2),
            json.dumps(protected_tests or [], ensure_ascii=False, indent=2),
            json.dumps(employee.get("repair_capability_contract") or [],
                       ensure_ascii=False, indent=2))
        tool_context = {
            "chat_id": None,
            "scope_pipeline_id": None,
            "view_context": {"surface": "employee_repair",
                             "employee_id": employee.get("id")},
            "conversation_context": {"context_type": "worker",
                                     "target_employee_id": employee.get("id")},
        }
        if channel.get("provider") == "codex":
            result = codex_threads.run_turn(
                channel, "", "修复这名员工并提交完整草稿。", instructions,
                model=model, effort=effort, cwd=self.root,
                extensions_enabled=False, timeout=self.timeout_sec,
                execution_profile=EXECUTION_INTERNAL_ANALYSIS,
                tool_context=tool_context, tool_names=_TOOL_NAMES,
                require_final_text=False)
            native_results = result.get("native_tool_results") or []
        else:
            adapter = model_channels.adapter_for(channel)
            adapter.configure_requirements({"inherit_native": True})
            result = run_agent(
                adapter, instructions, execution_profile=EXECUTION_INTERNAL_ANALYSIS,
                mode="judge", model=model, reasoning_effort=effort,
                timeout_sec=self.timeout_sec,
                extra_args=chat._claude_agent_tool_args(tool_context, _TOOL_NAMES),
                cwd=self.root, require_final_text=False)
            native_results = (result.meta or {}).get("native_tool_results") or []
        envelope = chat._native_tool_result(native_results, "employee_draft")
        if not envelope or not isinstance((envelope.get("data") or {}).get("draft"), dict):
            raise RuntimeError("AI 没有提交可应用的员工修复")
        return envelope["data"]["draft"]
