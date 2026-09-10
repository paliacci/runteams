#!/usr/bin/env python3
"""Resumable real-Agent resilience soak for the Employee Workflow kernel."""

import argparse
import datetime
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from errors import Transient
from runteams_core import RunTeamsCore
from runteams_core.agent_runtime import AgentEmployeeRuntime
from scripts.fixture_validation import publish_verified_employee


DEFAULT_ROOT = ROOT / "cache" / "core-agent-soak"
SCENARIOS = ("normal", "restart", "cancel", "transient")
CONFIG_VERSION = 2


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _draft(name, package_id, channel):
    return {
        "role": name,
        "program": {
            "objective": name,
            "steps": [{"id": "deliver", "instruction": (
                "Create brief.json from the supplied facts and upstream handoff, run the verifier, "
                "publish the artifact and submit the structured result.")}],
            "acceptance": ["brief.json contains non-empty objective and context",
                           "The required verifier passes after the final edit"],
        },
        "capabilities": [{"package_id": package_id, "capability_id": "brief-validator"},
                         {"package_id": package_id, "capability_id": "validate-brief"}],
        "runtime": {"channel": channel, "model": "", "effort": "low"},
    }


def prepare(core):
    package = core.import_package(
        "brief-validator", ROOT / "examples" / "brief-validator")
    codex = core.create_employee(
        "Soak Codex Researcher", _draft("Create a factual research handoff.",
                                        package["package_id"], "codex"))
    writer = core.create_employee(
        "Soak Codex Writer", _draft("Turn the handoff into a concise final brief.",
                                     package["package_id"], "codex"))
    publish_verified_employee(core, codex)
    publish_verified_employee(core, writer)
    pipeline_id = core.create_pipeline("Real Agent resilience soak", {
        "positions": [{"key": "research", "employee_id": codex},
                      {"key": "writing", "employee_id": writer}],
        "edges": [{"from": "research", "to": "writing"}],
    })
    return {"config_version": CONFIG_VERSION, "pipeline_id": pipeline_id,
            "cycle": 0, "active_seconds": 0.0,
            "open_workflow_id": None, "created_at": _now()}


def migrate_to_codex(core, root, state, evidence_path):
    if int(state.get("config_version") or 0) >= CONFIG_VERSION:
        return state
    open_workflow_id = state.get("open_workflow_id")
    if open_workflow_id:
        workflow = core.workflow(open_workflow_id)
        if workflow and workflow.get("state") not in ("completed", "canceled"):
            core.cancel_workflow(open_workflow_id)
    _write_json(root / "soak-state-v1-claude.json", state)
    if evidence_path.exists():
        archived = root / "soak-evidence-v1-claude.jsonl"
        if not archived.exists():
            evidence_path.replace(archived)
    return prepare(core)


def evidence(workflow, scenario, result):
    snapshot = workflow.get("snapshot_json") or {}
    positions = (snapshot.get("definition") or {}).get("positions") or []
    runs = workflow.get("employee_runs") or []
    return {
        "recorded_at": _now(), "scenario": scenario,
        "workflow_id": workflow.get("id"), "workflow_state": workflow.get("state"),
        "result_status": (result or {}).get("status"),
        "channels": [((item.get("employee") or {}).get("runtime") or {}).get("channel")
                     for item in positions],
        "employee_states": [item.get("state") for item in runs],
        "artifact_count": sum(len(item.get("artifacts") or []) for item in runs),
        "available_at": workflow.get("available_at"),
    }


def _append(path, record):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _new_workflow(core, pipeline_id, cycle, scenario):
    task_id = core.create_task(pipeline_id, "Soak cycle {} · {}".format(cycle, scenario), {
        "objective": "Create a concise factual RunTeams brief",
        "context": {"facts": [
            "RunTeams organizes complete Agent Runtimes into reusable employees.",
            "Employee releases freeze Agent Channels and capability package revisions.",
            "Employees exchange WorkOrders, WorkResults and explicit Artifacts.",
        ]},
    })
    return core.start_workflow(task_id)


class _TransientOnce:
    def __init__(self, delegate):
        self.delegate = delegate
        self.pending = True

    def run(self, *args, **kwargs):
        if self.pending:
            self.pending = False
            raise Transient("soak injected connection reset")
        return self.delegate.run(*args, **kwargs)


def _controlled(core, workflow_id, runtime, action, fault_after_sec):
    outcome = []
    failure = []

    def execute():
        try:
            outcome.append(core.run_workflow(workflow_id, runtime))
        except BaseException as exc:  # evidence runner must surface process-thread failures
            failure.append(exc)

    thread = threading.Thread(target=execute, name="runteams-soak-agent", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        workflow = core.workflow(workflow_id)
        if workflow and workflow.get("state") == "running" and workflow.get("employee_runs"):
            break
        time.sleep(0.1)
    time.sleep(max(0.1, float(fault_after_sec)))
    if action == "cancel":
        core.cancel_workflow(workflow_id)
    else:
        core.interrupt_workflow(workflow_id)
    thread.join(timeout=30)
    if thread.is_alive():
        raise RuntimeError("Agent process did not stop after {}".format(action))
    if failure:
        raise failure[0]
    return outcome[0] if outcome else {"status": "interrupted"}


def execute_cycle(core, workflow_id, runtime, scenario, fault_after_sec):
    if scenario == "transient":
        result = core.run_workflow(workflow_id, _TransientOnce(runtime))
        if result.get("reason") == "transient":
            core.retry_workflow(workflow_id)
            return core.run_workflow(workflow_id, runtime)
        return result
    if scenario == "cancel":
        return _controlled(core, workflow_id, runtime, "cancel", fault_after_sec)
    if scenario == "restart":
        result = _controlled(core, workflow_id, runtime, "restart", fault_after_sec)
        if result.get("status") == "interrupted":
            restarted = RunTeamsCore(core.root)
            restarted.recover_interrupted_workflows()
            return restarted.run_workflow(workflow_id, runtime)
        return result
    return core.run_workflow(workflow_id, runtime)


def run(args):
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    state_path, evidence_path = root / "soak-state.json", root / "soak-evidence.jsonl"
    core = RunTeamsCore(root / "core")
    state = (json.loads(state_path.read_text(encoding="utf-8"))
             if state_path.exists() else prepare(core))
    state = migrate_to_codex(core, root, state, evidence_path)
    _write_json(state_path, state)
    runtime = AgentEmployeeRuntime(core.root, timeout_sec=args.agent_timeout_sec)
    scenarios = tuple(item.strip() for item in args.scenarios.split(",") if item.strip())
    invalid = [item for item in scenarios if item not in SCENARIOS]
    if not scenarios or invalid:
        raise ValueError("unknown scenarios: {}".format(",".join(invalid)))

    while state["active_seconds"] < args.duration_sec:
        cycle_started = time.monotonic()
        scenario = scenarios[max(0, state["cycle"] - 1) % len(scenarios)]
        workflow_id = state.get("open_workflow_id")
        if workflow_id:
            current = core.workflow(workflow_id)
            available = current.get("available_at") if current else None
            if current and current.get("state") == "waiting_retry" and available:
                due = datetime.datetime.fromisoformat(available)
                if due > datetime.datetime.now(datetime.timezone.utc):
                    _append(evidence_path, evidence(current, scenario, {
                        "status": "waiting_retry"}))
                    print("paused until {} (resume with the same command)".format(available))
                    return 2
        else:
            state["cycle"] += 1
            scenario = scenarios[(state["cycle"] - 1) % len(scenarios)]
            workflow_id = _new_workflow(
                core, state["pipeline_id"], state["cycle"], scenario)
            state["open_workflow_id"] = workflow_id
            _write_json(state_path, state)
        result = execute_cycle(core, workflow_id, runtime, scenario, args.fault_after_sec)
        workflow = core.workflow(workflow_id)
        _append(evidence_path, evidence(workflow, scenario, result))
        state["active_seconds"] += time.monotonic() - cycle_started
        if workflow["state"] == "waiting_retry":
            state["open_workflow_id"] = workflow_id
            _write_json(state_path, state)
            print("waiting_retry until {} (resume with the same command)".format(
                workflow.get("available_at")))
            return 2
        state["open_workflow_id"] = None
        _write_json(state_path, state)
        print("cycle {} {} -> {} ({:.0f}/{:.0f}s)".format(
            state["cycle"], scenario, workflow["state"],
            state["active_seconds"], args.duration_sec))
    print("soak complete; evidence={}".format(evidence_path))
    return 0


def status(root):
    root = Path(root).resolve()
    state_path, evidence_path = root / "soak-state.json", root / "soak-evidence.jsonl"
    state = (json.loads(state_path.read_text(encoding="utf-8"))
             if state_path.exists() else {})
    records = (sum(1 for line in evidence_path.read_text(encoding="utf-8").splitlines()
                   if line.strip()) if evidence_path.exists() else 0)
    return {"state": state, "evidence_records": records,
            "evidence_path": str(evidence_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--duration-sec", type=float, default=7200)
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--fault-after-sec", type=float, default=15)
    parser.add_argument("--agent-timeout-sec", type=int, default=600)
    args = parser.parse_args()
    if args.status:
        print(json.dumps(status(args.root), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
