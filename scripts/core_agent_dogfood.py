#!/usr/bin/env python3
"""Resumable real-Agent evidence runner for three representative workflows."""

import argparse
import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runteams_core import RunTeamsCore
from runteams_core.agent_runtime import AgentEmployeeRuntime
from scripts.fixture_validation import publish_verified_employee


DEFAULT_ROOT = ROOT / "cache" / "core-agent-dogfood"
CONFIG_VERSION = 2
EMPLOYEE_SPECS = {
    "researcher": ("Dogfood Codex Researcher", "codex"),
    "editor": ("Dogfood Codex Editor", "codex"),
}
FLOW_SPECS = {
    "research_brief": {
        "name": "事实研究简报",
        "positions": [("research", "研究交付", "researcher")],
        "objective": "根据给定事实形成一份可核验的产品研究简报",
    },
    "decision_memo": {
        "name": "产品决策备忘录",
        "positions": [("decision", "决策建议", "editor")],
        "objective": "根据给定取舍形成一份有明确结论的产品决策备忘录",
    },
    "handoff_delivery": {
        "name": "跨 Agent 研究交付",
        "positions": [("research", "事实整理", "researcher"),
                      ("delivery", "最终交付", "editor")],
        "objective": "先整理事实，再跨员工交接并形成最终产品简报",
    },
}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _append(path, value):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def _draft(name, package_id, channel):
    return {
        "role": name,
        "program": {
            "objective": name,
            "steps": [{"id": "deliver", "instruction": (
                "Read the task and upstream handoff. Create brief.json with non-empty objective "
                "and context, run the supplied verifier, publish the file, then complete.")}],
            "acceptance": ["brief.json passes the verifier", "A final artifact is published"],
        },
        "capabilities": [{"package_id": package_id, "capability_id": "brief-validator"},
                         {"package_id": package_id, "capability_id": "validate-brief"}],
        "runtime": {"channel": channel, "model": "", "effort": "low"},
    }


def prepare(core):
    package = core.import_package("brief-validator", ROOT / "examples" / "brief-validator")
    employee_ids = {}
    for employee_key, (name, channel) in EMPLOYEE_SPECS.items():
        employee_id = core.create_employee(name, _draft(name, package["package_id"], channel))
        publish_verified_employee(core, employee_id)
        employee_ids[employee_key] = employee_id
    pipeline_ids = {}
    for key, spec in FLOW_SPECS.items():
        positions = [{"key": position_key, "name": position_name,
                      "employee_id": employee_ids[employee_key]}
                     for position_key, position_name, employee_key in spec["positions"]]
        pipeline_ids[key] = core.create_pipeline(spec["name"], {
            "positions": positions,
            "edges": [{"from": positions[index]["key"], "to": positions[index + 1]["key"]}
                      for index in range(len(positions) - 1)],
        })
    return {"config_version": CONFIG_VERSION, "employee_ids": employee_ids,
            "pipeline_ids": pipeline_ids, "completed": {key: 0 for key in FLOW_SPECS},
            "cursor": 0, "open": None, "created_at": _now()}


def migrate_to_codex(core, state):
    if int(state.get("config_version") or 0) >= CONFIG_VERSION:
        return state
    research_pipeline = core.pipeline(state["pipeline_ids"]["research_brief"])
    researcher_id = int(research_pipeline["definition_json"]["positions"][0]["employee_id"])
    package = core.import_package("brief-validator", ROOT / "examples" / "brief-validator")
    editor_name, editor_channel = EMPLOYEE_SPECS["editor"]
    editor_id = core.create_employee(
        editor_name, _draft(editor_name, package["package_id"], editor_channel))
    publish_verified_employee(core, editor_id)
    employee_ids = {"researcher": researcher_id, "editor": editor_id}
    for key, spec in FLOW_SPECS.items():
        positions = [{"key": position_key, "name": position_name,
                      "employee_id": employee_ids[employee_key]}
                     for position_key, position_name, employee_key in spec["positions"]]
        core.update_pipeline(state["pipeline_ids"][key], spec["name"], {
            "positions": positions,
            "edges": [{"from": positions[index]["key"], "to": positions[index + 1]["key"]}
                      for index in range(len(positions) - 1)],
        })
    state["config_version"] = CONFIG_VERSION
    state["employee_ids"] = employee_ids
    return state


def _task_payload(flow, run_number):
    spec = FLOW_SPECS[flow]
    return {
        "objective": spec["objective"],
        "context": {"run_number": run_number, "facts": [
            "RunTeams 把完整 Agent Runtime 组织为可复用员工。",
            "员工发布会冻结模型渠道与能力包版本。",
            "岗位之间只交接结构化工作单、结果和产物。",
        ]},
        "acceptance": ["形成可核验结论", "发布通过验证的 brief.json"],
    }


def _new_workflow(core, state, flow, run_number):
    task_id = core.create_task(
        state["pipeline_ids"][flow],
        "{} · 第 {} 次".format(FLOW_SPECS[flow]["name"], run_number),
        _task_payload(flow, run_number))
    return core.start_workflow(task_id)


def evidence(workflow, flow, run_number, duration_sec):
    runs = workflow.get("employee_runs") or []
    artifacts = sum(len(item.get("artifacts") or []) for item in runs)
    state = workflow.get("state")
    qualifying = state in ("needs_human", "blocked") or (state == "completed" and artifacts > 0)
    return {
        "recorded_at": _now(), "flow": flow, "run_number": int(run_number),
        "workflow_id": int(workflow["id"]), "state": state,
        "qualifying": qualifying, "artifact_count": artifacts,
        "attempt_count": len(runs),
        "interrupted_attempts": sum(item.get("state") == "interrupted" for item in runs),
        "duration_sec": round(float(duration_sec), 3),
    }


def _read_records(path):
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def summarize(records, target=30):
    latest = {}
    for record in records:
        latest[int(record.get("workflow_id") or 0)] = record
    rows = list(latest.values())
    flows = []
    for key, spec in FLOW_SPECS.items():
        selected = [item for item in rows if item.get("flow") == key and
                    item.get("state") != "waiting_retry"]
        qualifying = sum(bool(item.get("qualifying")) for item in selected)
        flows.append({"flow": key, "name": spec["name"], "runs": len(selected),
                      "qualifying": qualifying,
                      "rate": round(qualifying / len(selected), 4) if selected else 0.0,
                      "target": int(target)})
    terminal = [item for item in rows if item.get("state") != "waiting_retry"]
    qualifying = sum(bool(item.get("qualifying")) for item in terminal)
    recoveries = [item for item in terminal if int(item.get("interrupted_attempts") or 0) > 0]
    return {
        "flows": flows,
        "overall": {"runs": len(terminal), "qualifying": qualifying,
                    "rate": round(qualifying / len(terminal), 4) if terminal else 0.0},
        "recovery": {"opportunities": len(recoveries),
                     "successful": sum(bool(item.get("qualifying")) for item in recoveries)},
    }


def _next_flow(state, selected, target):
    for offset in range(len(selected)):
        index = (int(state.get("cursor") or 0) + offset) % len(selected)
        flow = selected[index]
        if int((state.get("completed") or {}).get(flow) or 0) < target:
            state["cursor"] = (index + 1) % len(selected)
            return flow
    return None


def run(args):
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "dogfood-state.json"
    evidence_path = root / "dogfood-evidence.jsonl"
    report_path = root / "dogfood-report.json"
    if args.report_only:
        report = summarize(_read_records(evidence_path), args.runs_per_flow)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    core = RunTeamsCore(root / "core")
    state = (json.loads(state_path.read_text(encoding="utf-8"))
             if state_path.exists() else prepare(core))
    state = migrate_to_codex(core, state)
    _write_json(state_path, state)
    selected = tuple(item.strip() for item in args.flows.split(",") if item.strip())
    invalid = [item for item in selected if item not in FLOW_SPECS]
    if not selected or invalid:
        raise ValueError("unknown flows: {}".format(",".join(invalid)))
    runtime = AgentEmployeeRuntime(core.root, timeout_sec=args.agent_timeout_sec)
    while True:
        opened = state.get("open")
        if opened:
            flow, run_number, workflow_id = (
                opened["flow"], int(opened["run_number"]), int(opened["workflow_id"]))
            current = core.workflow(workflow_id)
            available = current.get("available_at") if current else None
            if current and current.get("state") == "waiting_retry" and available:
                due = datetime.datetime.fromisoformat(available)
                if due > datetime.datetime.now(datetime.timezone.utc):
                    print("paused until {} (resume with the same command)".format(available))
                    return 2
        else:
            flow = _next_flow(state, selected, args.runs_per_flow)
            if flow is None:
                report = summarize(_read_records(evidence_path), args.runs_per_flow)
                _write_json(report_path, report)
                print("dogfood complete; report={}".format(report_path))
                return 0
            run_number = int(state["completed"].get(flow) or 0) + 1
            workflow_id = _new_workflow(core, state, flow, run_number)
            state["open"] = {"flow": flow, "run_number": run_number,
                             "workflow_id": workflow_id}
            _write_json(state_path, state)
        started = time.monotonic()
        result = core.run_workflow(workflow_id, runtime)
        workflow = core.workflow(workflow_id)
        record = evidence(workflow, flow, run_number, time.monotonic() - started)
        _append(evidence_path, record)
        _write_json(report_path, summarize(_read_records(evidence_path), args.runs_per_flow))
        if result.get("status") == "waiting_retry" or workflow.get("state") == "waiting_retry":
            _write_json(state_path, state)
            print("waiting_retry until {} (resume with the same command)".format(
                workflow.get("available_at")))
            return 2
        state["completed"][flow] = run_number
        state["open"] = None
        _write_json(state_path, state)
        print("{} {}/{} -> {}".format(
            flow, run_number, args.runs_per_flow, workflow.get("state")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--runs-per-flow", type=int, default=30)
    parser.add_argument("--flows", default=",".join(FLOW_SPECS))
    parser.add_argument("--agent-timeout-sec", type=int, default=600)
    parser.add_argument("--report-only", action="store_true")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
