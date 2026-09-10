# -*- coding: utf-8 -*-
"""适配器接口 —— 跨厂中立的核心。

早期实现把 `claude -p` 写死在通用运行器里。产品化的关键动作是把“每家 CLI 不同的三件事”
抽成一个接口,进程管理(runner.py)那套可靠性代码则厂中立地共享。

每家 CLI 只需实现三个方法:
  1. build_argv   —— 怎么造这家 CLI 的无头调用命令行
  2. consume      —— 怎么读这家 CLI 的输出流,拿到"最终产物文本"和"逐条活动"
  3. classify_error —— 这家 CLI 撞限流/网络断时,输出里长什么样(措辞各家不同)

加一家新模型厂 = 新写一个 ~60 行的适配器,引擎其余部分一行不动。这就是"通用编排层"。
"""
from abc import ABC, abstractmethod
import os


EXECUTION_USER_AGENT = "user_agent"
EXECUTION_PIPELINE_AGENT = "pipeline_agent"
EXECUTION_INTERNAL_ANALYSIS = "internal_analysis"
EXECUTION_ISOLATED_REPAIR = "isolated_repair"

EXECUTION_PROFILES = frozenset({
    EXECUTION_USER_AGENT,
    EXECUTION_PIPELINE_AGENT,
    EXECUTION_INTERNAL_ANALYSIS,
    EXECUTION_ISOLATED_REPAIR,
})

AGENT_AUTHORITY_PROFILES = frozenset({
    EXECUTION_USER_AGENT,
    EXECUTION_PIPELINE_AGENT,
    EXECUTION_ISOLATED_REPAIR,
})


def validate_execution_profile(value):
    """Require every Agent invocation to declare why it is running.

    Job semantics (judge/build) deliberately do not participate in this choice.
    Requiring a profile prevents a newly added user-facing path from silently
    falling back to read-only execution.
    """
    if value not in EXECUTION_PROFILES:
        raise ValueError("未知或缺失的 Agent 执行策略：{}".format(value or "(empty)"))
    return value


class WorkerAdapter(ABC):
    #: 适配器标识,如 "claude-code" / "codex" / "qwen-code"
    name = "base"

    @abstractmethod
    def build_argv(self, prompt, *, execution_profile, mode, model,
                   reasoning_effort=None, extra_args=None):
        """返回无头调用的 argv 列表。
        mode: "build"(实现与交付) 或 "judge"(分析、评审与决策)。
        mode 不是权限开关；execution_profile 显式决定本次执行边界。
        model: 显式模型版本号。reasoning_effort:由各厂商按自己的原生标准映射。"""
        raise NotImplementedError

    @abstractmethod
    def consume(self, stdout_lines, on_activity):
        """消费这家 CLI 的 stdout 行迭代器,返回 (final_text, is_error, meta)。
        final_text: CLI 的普通最终文本，仅作诊断；RunTeams.ai 不把它当作提交结果。
        is_error:   这家 CLI 自报的错误标志;拿不到就返回 None,由 runner 用退出码兜底。
        meta:       通用用量/成本字典(各家能给多少给多少,给不了就空 {}):
                    {cost_usd, input_tokens, output_tokens, model}。是可观测/成本的数据源。
        on_activity(str): 有一条可读的"当前动作"就回调一次(没有流式活动就不调,不影响结果)。"""
        raise NotImplementedError

    @abstractmethod
    def classify_error(self, blob, is_error, returncode):
        """按这家 CLI 的错误措辞分类:撞限流 raise RateLimited、瞬时网络 raise Transient、
        其它硬失败 raise RuntimeError;正常则直接 return(不抛)。
        blob = final_text + stderr 尾部,low = blob.lower() 供匹配。"""
        raise NotImplementedError

    def env(self, base_env):
        """默认剥离代理环境变量(代理会 mangle 流式长连接=连接中途断的真凶)。
        某家 CLI 若需特殊 env,覆盖此方法。"""
        env = dict(base_env)
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                  "ALL_PROXY", "all_proxy"):
            env.pop(k, None)
        path_prepend = list((getattr(self, "requirements", {}) or {}).get(
            "path_prepend") or [])
        if path_prepend:
            env["PATH"] = os.pathsep.join(
                [str(path) for path in path_prepend] + [env.get("PATH", "")])
        return env
