"""Canonical durable scheduler loop, claims, cancellation and outcome recording."""
import threading,time
from contextlib import nullcontext
from runteams_core.errors import Cancelled
from .automation_dispatch import dispatch_enabled

class AutomationScheduler:

    def __init__(self,execute_run,*,backends,max_concurrency=2,poll_interval=.5,on_state_change=None,has_open_work=None,has_open_work_by_backend=None,on_tick=None,scope=nullcontext,operation_scope=nullcontext,dispatch_enabled=dispatch_enabled):
        if not backends:raise ValueError('Scheduler requires an explicit owning backend')
        self.execute_run=execute_run;self.backends=list(backends);self.default_backend=self.backends[0]
        self.max_concurrency=max(1,int(max_concurrency));self.poll_interval=float(poll_interval)
        self.on_state_change=on_state_change;self.has_open_work=has_open_work;self.has_open_work_by_backend=has_open_work_by_backend or {};self.on_tick=on_tick
        self.scope=scope;self.operation_scope=operation_scope;self.dispatch_enabled=dispatch_enabled
        self._active={};self._lock=threading.Lock();self._wake=threading.Event();self._stopping=threading.Event();self._thread=None;self.cloud_error=''

    def _bound(self,method,*args):
        with self.scope():return method(*args)

    def _register(self):pass

    def _unregister(self):pass

    def _claim_job(self,store):return store.claim_next_automation_run()

    def _run(self,job,cancel_event):
        try:
            with self.operation_scope():self._run_authorized(job,cancel_event)
        finally:
            with self._lock:self._active.pop((id(job['_backend']),int(job['id'])),None)


    def start(self):
        if not self._dispatch_backends():
            return
        if self._thread and self._thread.is_alive():
            return
        self._register()
        self._stopping.clear()
        self._thread = threading.Thread(target=lambda:self._bound(self._loop), name="runteams-automations", daemon=True)
        self._thread.start()

    def _dispatch_backends(self):
        if self.dispatch_enabled():
            return self.backends
        return [store for store in self.backends
                if callable(getattr(type(store), 'scoped_dispatch_enabled', None))
                and store.scoped_dispatch_enabled() is True]

    def wake(self):
        self._wake.set()

    def stop(self):
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
        self._unregister()

    def cancel_automation(self, automation_id, reason="自动化已暂停", wait_timeout=0, backend=None):
        automation_id = int(automation_id)
        targets = [backend] if backend is not None else self.backends
        for store in targets:
            store.cancel_queued_automation_runs(automation_id, reason)
        with self._lock:
            controls = [control for control in self._active.values()
                        if int(control["automation_id"]) == automation_id and
                        (backend is None or control["backend"] is backend)]
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
        self._last_tick=0.0
        while not self._stopping.is_set():
            try:
                with self.operation_scope():launched=self._step()
            except Exception as error:
                self.cloud_error=str(error);launched=False
            self._wake.wait(0.05 if launched else self.poll_interval)
            self._wake.clear()

    def _step(self):
        if self._dispatch_backends() and self.on_tick and time.monotonic() - self._last_tick >= 2:
            self._last_tick = time.monotonic()
            try:
                self.on_tick()
            except Exception:
                pass
        try:
            for store in self._dispatch_backends():
                store.materialize_due_automations(
                    limit=20, has_open_work=self.has_open_work_by_backend.get(
                        store, self.has_open_work if store is self.default_backend else None))
        except Exception:
            pass
        launched = False
        while not self._stopping.is_set():
            with self._lock:
                if len(self._active) >= self.max_concurrency:
                    break
                job = None; backend = None
                for store in self._dispatch_backends():
                    if self._stopping.is_set():
                        break
                    try:
                        job = self._claim_job(store)
                        self.cloud_error = ''
                    except Exception as exc:
                        self.cloud_error = str(exc)
                        job = None
                    if job:
                        backend = store; break
                if not job:
                    break
                if self._stopping.is_set():
                    # A claim completed after shutdown. No Agent has started;
                    # normal durable recovery handles this owned occurrence.
                    break
                job["_backend"] = backend
                cancel_event = threading.Event()
                thread = threading.Thread(
                    target=self._bound, args=(self._run, job, cancel_event), daemon=True,
                    name="runteams-automation-{}".format(job["id"]))
                active_key = (id(backend), int(job["id"]))
                self._active[active_key] = {
                    "automation_id": job.get("automation_id"),
                    "backend": backend,
                    "cancel": cancel_event,
                    "thread": thread,
                    "key": active_key,
                }
                # Claim + registration + start are one scheduler critical
                # section. Pause/delete can therefore never miss a claimed
                # occurrence in the tiny gap before it becomes cancellable.
                thread.start()
            launched = True
        return launched


    def _run_authorized(self, job, cancel_event):
        try:
            backend = job.get("_backend", self.default_backend)
            backend.add_automation_run_event(job["id"], "system", {"message": "自动化开始运行"})
            self.execute_run(job, cancel_event)
        except Cancelled as exc:
            backend.add_automation_run_event(
                job["id"], "system", {"message": str(exc) or "自动化已取消"})
            backend.finish_automation_run(job["id"], "cancelled", str(exc)[:1000])
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Automation execution failed")
            reason = str(exc)[:1000] or "自动化运行失败"
            backend.add_automation_run_event(job["id"], "error", {"message": reason})
            backend.finish_automation_run(job["id"], "failed", reason)
        finally:
            with self._lock:
                self._active.pop((id(job.get("_backend", self.default_backend)), int(job["id"])), None)
            if self.on_state_change:
                try:
                    self.on_state_change()
                except Exception:
                    pass
            self._wake.set()
