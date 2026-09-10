# -*- coding: utf-8 -*-
"""Agent CLI 进程生命周期管理。

这是本项目的"壁垒"部分:每一行都是 solo-company 用真实事故换来的可靠性知识。
它不关心底层是哪家 CLI(那交给 adapter),只负责把一个子进程**干净地跑完或干净地杀掉**:

- start_new_session + 进程组清杀:Agent 派生的后台子进程(孤儿)会被整组杀干净。
  (旧实现只 p.kill() 杀主进程,孤儿继续空转拖满超时=整条线卡死,2026-07-23 事故根因。)
- 代理剥离:代理会 mangle 流式长连接 = connection closed mid-response 的真凶。
- stderr 单独抽干:防管道塞满死锁。
- 超时看门狗:Popen 逐行读没内建 timeout,靠独立线程硬杀。
"""
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field

import cli_compatibility
from errors import Cancelled
from adapter_base import validate_execution_profile


# 空转检测:CLI 进程还活着但长时间无任何流式输出时,提前把"可能卡住"surface 到活动流。
# 只观测不自动杀——真挂死仍由 timeout 兜底,避免误杀合法的长工具调用(大构建/慢测试)。
STALL_WARN_SEC = int(os.environ.get("RUNTEAMS_STALL_WARN_SEC") or 240)


@dataclass
class AgentResult:
    """一次 Agent CLI 运行的结果。text=最终文本；meta=通用用量/成本。"""
    text: str
    meta: dict = field(default_factory=dict)


def run_agent(adapter, prompt, *, execution_profile, mode="judge", model,
              reasoning_effort=None, timeout_sec,
              extra_args=None, on_activity=None, transcript_path=None, cwd=None,
              cancel_event=None, require_final_text=True):
    """用指定 adapter 无头运行一次 Agent CLI。

    失败语义(与 driver.py 一致,由 adapter.classify_error 判定):
      - 撞限流 → raise errors.RateLimited(外因,不计失败)
      - 瞬时网络 → raise errors.Transient(外因,不计失败)
      - 超时/硬失败 → raise RuntimeError(计入未来的 max_fail)
    """
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled("运行已停止")

    execution_profile = validate_execution_profile(execution_profile)
    argv = adapter.build_argv(prompt, execution_profile=execution_profile, mode=mode, model=model,
                              reasoning_effort=reasoning_effort, extra_args=extra_args)
    env = adapter.env(os.environ.copy())
    compatibility = cli_compatibility.check(adapter.name, argv[0], env)
    if not compatibility["compatible"]:
        raise RuntimeError(compatibility["detail"])
    # start_new_session=True:Agent 及其派生子进程自成进程组，超时可整组杀干净。
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=env, cwd=cwd, bufsize=1, start_new_session=True)
    try:
        pgid = os.getpgid(p.pid)
    except Exception:
        pgid = None

    def _killtree():
        try:
            if os.name == "nt":
                # Windows 没有 POSIX 进程组信号；taskkill /T 会连同 CLI 派生进程一起结束。
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            elif pgid is not None:
                os.killpg(pgid, signal.SIGKILL)
            else:
                p.kill()
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    killed = {"timeout": False, "cancelled": False}
    state_lock = threading.Lock()

    def _kill():
        with state_lock:
            if killed["cancelled"]:
                return
            killed["timeout"] = True
        _killtree()

    timer = threading.Timer(timeout_sec, _kill)
    timer.daemon = True
    timer.start()

    finished = threading.Event()
    last_activity = [time.monotonic()]
    event_handler = getattr(on_activity, "on_event", None)

    class _TrackedEvents:
        def on_event(self, event):
            last_activity[0] = time.monotonic()
            if callable(event_handler):
                event_handler(event)

    tracked_events = _TrackedEvents()

    def _watch_stall():
        # 距上次活动超过 STALL_WARN_SEC 就往活动流打一条预警(每静默一个周期复读一次),不杀进程。
        warned_at = 0.0
        while not finished.wait(min(STALL_WARN_SEC, 30)):
            with state_lock:
                if killed["timeout"] or killed["cancelled"]:
                    return
            silent = time.monotonic() - last_activity[0]
            if silent < STALL_WARN_SEC:
                warned_at = 0.0
                continue
            if silent - warned_at >= STALL_WARN_SEC:
                warned_at = silent
                try:
                    tracked_events.on_event({
                        "kind": "step", "id": "agent-stall", "step_kind": "status",
                        "label": "员工已约 {} 分钟无新动作".format(
                            max(1, int(silent // 60))),
                        "status": "running", "detail": "{} 秒后触发超时终止".format(timeout_sec),
                        "output": "",
                    })
                except Exception:
                    pass

    def _watch_cancel():
        if cancel_event is None:
            return
        while not finished.wait(0.1):
            if cancel_event.is_set():
                with state_lock:
                    if killed["timeout"]:
                        return
                    killed["cancelled"] = True
                _killtree()
                return

    cancel_watcher = threading.Thread(target=_watch_cancel, daemon=True)
    cancel_watcher.start()

    # 只有真正有人在看活动流(on_activity 存在)且超时窗口够长,才值得起空转监视线程。
    if on_activity is not None and timeout_sec > STALL_WARN_SEC:
        threading.Thread(target=_watch_stall, daemon=True).start()

    # stderr 单独抽干,防管道塞满死锁;同时留作错误分类的证据。
    err_buf = []

    def _drain_err():
        try:
            for l in p.stderr:
                err_buf.append(l)
        except Exception:
            pass

    et = threading.Thread(target=_drain_err, daemon=True)
    et.start()

    # 把 stdout 逐行 tee 到 transcript(留存),同时喂给 adapter.consume 解析。
    tf = open(transcript_path, "w", encoding="utf-8") if transcript_path else None

    def _lines():
        try:
            for line in p.stdout:
                if tf:
                    tf.write(line)
                yield line
        finally:
            if tf:
                tf.close()

    final_text, is_error, meta = None, None, {}
    try:
        final_text, is_error, meta = adapter.consume(_lines(), tracked_events)
    finally:
        try:
            p.wait(timeout=30)
        except Exception:
            pass
        timer.cancel()
        finished.set()
        et.join(timeout=2)
        try:
            p.stdout.close()
            p.stderr.close()
        except Exception:
            pass
        # Agent 已退出，但违规开启的后台孤儿可能还活着；整组补杀一次。
        if not killed["timeout"] and not killed["cancelled"]:
            _killtree()

    if killed["cancelled"]:
        raise Cancelled("运行已停止")
    if killed["timeout"]:
        raise RuntimeError("Agent 超时 {}s".format(timeout_sec))

    blob = (final_text or "") + "".join(err_buf)
    # 交给这家 CLI 的适配器按它自己的错误措辞分类(可能 raise RateLimited/Transient)。
    adapter.classify_error(blob, is_error, p.returncode)

    # is_error 拿不到(如 Codex 非 json 模式)就用退出码兜底。
    hard_fail = is_error if is_error is not None else (p.returncode != 0)
    if hard_fail or (require_final_text and final_text is None):
        raise RuntimeError("{} 退出码 {}: {}".format(
            adapter.name, p.returncode, (blob or "")[:400]))
    return AgentResult(text=final_text or "", meta=meta or {})
