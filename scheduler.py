# -*- coding: utf-8 -*-
"""Durable scheduler for prompt-first automations."""
import threading
import time

from errors import Cancelled
import automation_store as automations


_AUTOMATION_SCHEDULER = None


def cancel_scheduled_automation(automation_id, reason="自动化已暂停", wait_timeout=0):
    """Cancel one schedule through the same lifecycle from HTTP or Agent actions."""
    instance = _AUTOMATION_SCHEDULER
    if instance is not None:
        return instance.cancel_automation(automation_id, reason, wait_timeout)
    automations.cancel_queued_automation_runs(automation_id, reason)
    return True


class AutomationScheduler:
    """Run prompt-first automations as ordinary Agent conversations."""

    def __init__(self, execute_run, max_concurrency=2, poll_interval=0.5,
                 on_state_change=None, has_open_work=None):
        self.execute_run = execute_run
        self.max_concurrency = max(1, int(max_concurrency))
        self.poll_interval = float(poll_interval)
        self.on_state_change = on_state_change
        self.has_open_work = has_open_work
        self._active = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread = None

    def start(self):
        global _AUTOMATION_SCHEDULER
        if self._thread and self._thread.is_alive():
            return
        _AUTOMATION_SCHEDULER = self
        self._thread = threading.Thread(target=self._loop, name="runteams-automations", daemon=True)
        self._thread.start()

    def wake(self):
        self._wake.set()

    def stop(self):
        global _AUTOMATION_SCHEDULER
        self._stopping.set()
        self._wake.set()
        with self._lock:
            controls = list(self._active.values())
        for control in controls:
            control["cancel"].set()
        deadline = time.time() + 5
        for control in controls:
            control["thread"].join(max(0, deadline - time.time()))
        if self._thread:
            self._thread.join(1)
        if _AUTOMATION_SCHEDULER is self:
            _AUTOMATION_SCHEDULER = None

    def cancel_automation(self, automation_id, reason="自动化已暂停", wait_timeout=0):
        automation_id = int(automation_id)
        automations.cancel_queued_automation_runs(automation_id, reason)
        with self._lock:
            controls = [control for control in self._active.values()
                        if int(control["automation_id"]) == automation_id]
        for control in controls:
            control["cancel"].set()
        deadline = time.time() + max(0, float(wait_timeout or 0))
        for control in controls:
            if control["thread"] is threading.current_thread():
                continue
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            control["thread"].join(remaining)
        self._wake.set()
        return not any(control["thread"].is_alive() for control in controls)

    def _loop(self):
        while not self._stopping.is_set():
            try:
                automations.materialize_due_automations(
                    limit=20, has_open_work=self.has_open_work)
            except Exception:
                pass
            launched = False
            while not self._stopping.is_set():
                with self._lock:
                    if len(self._active) >= self.max_concurrency:
                        break
                    try:
                        job = automations.claim_next_automation_run()
                    except Exception:
                        break
                    if not job:
                        break
                    cancel_event = threading.Event()
                    thread = threading.Thread(
                        target=self._run, args=(job, cancel_event), daemon=True,
                        name="runteams-automation-{}".format(job["id"]))
                    self._active[job["id"]] = {
                        "automation_id": job["automation_id"],
                        "cancel": cancel_event,
                        "thread": thread,
                    }
                    # Claim + registration + start are one scheduler critical
                    # section. Pause/delete can therefore never miss a claimed
                    # occurrence in the tiny gap before it becomes cancellable.
                    thread.start()
                launched = True
            self._wake.wait(0.05 if launched else self.poll_interval)
            self._wake.clear()

    def _run(self, job, cancel_event):
        try:
            automations.add_automation_run_event(job["id"], "system", {"message": "自动化开始运行"})
            self.execute_run(job, cancel_event)
        except Cancelled as exc:
            automations.finish_automation_run(job["id"], "cancelled", str(exc)[:1000])
            automations.add_automation_run_event(
                job["id"], "system", {"message": str(exc) or "自动化已取消"})
        except Exception as exc:
            reason = str(exc)[:1000] or "自动化运行失败"
            automations.finish_automation_run(job["id"], "failed", reason)
            automations.add_automation_run_event(job["id"], "error", {"message": reason})
        finally:
            with self._lock:
                self._active.pop(job["id"], None)
            if self.on_state_change:
                try:
                    self.on_state_change()
                except Exception:
                    pass
            self._wake.set()
