# -*- coding: utf-8 -*-
"""Deterministic core Workflow mobile fixture; never launches an Agent Runtime."""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


PIPELINE_PREFIX = "移动端闭环验收 · "
TASK_TITLE = "桌面到手机持续同步验收"
FIRST_POSITION = "模拟执行"
SECOND_POSITION = "模拟验收"


def _configure_import_path(data_dir):
    if data_dir:
        os.environ["RUNTEAMS_DATA"] = os.path.abspath(os.path.expanduser(data_dir))
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)


def _store():
    import product_store
    return product_store


def _core():
    from runteams_core import RunTeamsCore
    return RunTeamsCore(_store().core_data_root())


def _now():
    from runteams_core.repository import utc_now
    return utc_now()


def _employee(core, name):
    from scripts.fixture_validation import publish_verified_employee
    employee_id = core.create_employee(name, {
        "role": "移动端验收夹具",
        "program": {
            "objective": "生成确定性的脱敏移动快照",
            "steps": [{"id": "fixture-step", "instruction": "推进固定验收状态"}],
            "acceptance": ["状态与脚本定义的检查点完全一致"],
        },
        "capabilities": [],
        "runtime": {"channel": "fixture", "model": "fixture", "effort": "low"},
    })
    publish_verified_employee(core, employee_id)
    return employee_id


def _context(name):
    core = _core()
    with core.repository.connect() as connection:
        pipeline = connection.execute(
            "SELECT * FROM pipelines WHERE name=?", (name,)).fetchone()
        if pipeline is None:
            raise RuntimeError("测试流水线不存在：{}".format(name))
        task = connection.execute(
            "SELECT * FROM tasks WHERE pipeline_id=? AND title=?",
            (pipeline["id"], TASK_TITLE),).fetchone()
        if task is None:
            raise RuntimeError("测试任务不存在")
        workflow = connection.execute(
            "SELECT * FROM workflow_runs WHERE task_id=?", (task["id"],)).fetchone()
        runs = connection.execute(
            "SELECT * FROM employee_runs WHERE workflow_run_id=? ORDER BY id",
            (workflow["id"],)).fetchall()
    return {
        "core": core,
        "pipeline": core.repository.decode(pipeline, "definition_json"),
        "task": core.repository.decode(task, "payload_json"),
        "workflow": core.repository.decode(workflow, "snapshot_json"),
        "runs": [core.repository.decode(item, "input_json", "output_json") for item in runs],
    }


def create(name):
    if not name.startswith(PIPELINE_PREFIX):
        raise RuntimeError("测试流水线名称必须以 {!r} 开头".format(PIPELINE_PREFIX))
    core = _core()
    if any(item["name"] == name for item in core.pipeline_catalog()):
        raise RuntimeError("同名测试流水线已存在")
    first = _employee(core, "E2E 测试执行员")
    second = _employee(core, "E2E 测试验收员")
    pipeline_id = core.create_pipeline(name, {
        "positions": [
            {"key": "execute", "name": FIRST_POSITION, "employee_id": first},
            {"key": "review", "name": SECOND_POSITION, "employee_id": second},
        ],
        "edges": [{"from": "execute", "to": "review"}],
    })
    task_id = core.create_task(pipeline_id, TASK_TITLE, {
        "objective": "验证新核心状态可以持续同步到移动端",
    })
    core.start_workflow(task_id)
    return describe(name)


def queue(name):
    context = _context(name)
    if context["workflow"]["state"] != "ready":
        raise RuntimeError("测试工作流不在队列中")
    return describe(name)


def _snapshot_position(context, key):
    return next(item for item in context["workflow"]["snapshot_json"]["definition"]["positions"]
                if item["key"] == key)


def running(name):
    context = _context(name)
    core, workflow = context["core"], context["workflow"]
    if workflow["state"] != "ready" or core.claim_workflow(workflow["id"]) != workflow["id"]:
        raise RuntimeError("测试工作流无法开始")
    position = _snapshot_position(context, "execute")
    now = _now()
    with core.repository.connect() as connection:
        run_id = connection.execute(
            "INSERT INTO employee_runs(workflow_run_id,position_key,employee_release_id,attempt,state,"
            "input_json,output_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (workflow["id"], "execute", position["employee_release_id"], 1, "running",
             "{}", "{}", now, now),).lastrowid
        core.repository.event("employee_run:{}".format(run_id), "fixture.started", {},
                              connection=connection)
    return describe(name)


def handoff(name):
    context = _context(name)
    run = context["runs"][-1] if context["runs"] else None
    if not run or run["position_key"] != "execute" or run["state"] != "running":
        raise RuntimeError("测试工作流不在第一岗位")
    result = {
        "status": "completed", "summary": "桌面状态已生成并完成第一轮脱敏同步。",
        "output": {"fixture": "handoff"}, "artifacts": [], "issues": [],
    }
    now = _now()
    with context["core"].repository.connect() as connection:
        connection.execute(
            "UPDATE employee_runs SET state='completed',output_json=?,updated_at=? WHERE id=?",
            (json.dumps(result, ensure_ascii=False), now, run["id"]))
    return describe(name)


def reviewing(name):
    context = _context(name)
    if (context["workflow"]["state"] != "running" or not context["runs"]
            or context["runs"][-1]["position_key"] != "execute"
            or context["runs"][-1]["state"] != "completed"):
        raise RuntimeError("测试工作流尚未交接")
    position = _snapshot_position(context, "review")
    now = _now()
    with context["core"].repository.connect() as connection:
        run_id = connection.execute(
            "INSERT INTO employee_runs(workflow_run_id,position_key,employee_release_id,attempt,state,"
            "input_json,output_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (context["workflow"]["id"], "review", position["employee_release_id"], 1,
             "running", "{}", "{}", now, now),).lastrowid
        context["core"].repository.event(
            "employee_run:{}".format(run_id), "fixture.started", {}, connection=connection)
    return describe(name)


def complete(name):
    context = _context(name)
    run = context["runs"][-1] if context["runs"] else None
    if not run or run["position_key"] != "review" or run["state"] != "running":
        raise RuntimeError("测试工作流不在验收岗位")
    result = {
        "status": "completed", "summary": "iPhone 与 iPad 已收到完整的只读工作记录。",
        "output": {"fixture": "accepted"},
        "artifacts": [{"name": "移动端闭环验收报告", "ref": "fixture-report"}],
        "issues": [],
    }
    now = _now()
    with context["core"].repository.connect() as connection:
        connection.execute(
            "UPDATE employee_runs SET state='completed',output_json=?,updated_at=? WHERE id=?",
            (json.dumps(result, ensure_ascii=False), now, run["id"]))
        connection.execute(
            "INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) VALUES(?,?,?,?,?)",
            (run["id"], "移动端闭环验收报告", "fixture-report", "{}", now))
        connection.execute(
            "UPDATE workflow_runs SET state='completed',available_at=NULL,updated_at=? WHERE id=?",
            (now, context["workflow"]["id"]))
        connection.execute("UPDATE tasks SET state='completed',updated_at=? WHERE id=?",
                           (now, context["task"]["id"]))
    return describe(name)


def describe(name):
    import mobile_projection
    context = _context(name)
    snapshot = mobile_projection.build_dashboard_snapshot(app_version="mobile-e2e")
    pipeline = next(item for item in snapshot["pipelines"]
                    if item["id"] == "pipeline:{}".format(context["pipeline"]["id"]))
    cards = [card for column in pipeline["positions"] for card in column["tasks"]]
    card = next(item for item in cards
                if item["id"] == "workflow:{}".format(context["workflow"]["id"]))
    column = next(column for column in pipeline["positions"] if card in column["tasks"])
    return {
        "pipeline": pipeline["name"],
        "pipeline_id": context["pipeline"]["id"],
        "workflow_id": context["workflow"]["id"],
        "column": column["name"],
        "card_status": card["status"],
        "record_count": len(card["records"]),
        "artifact_count": card["artifact_count"],
        "workflow_status": context["workflow"]["state"],
        "snapshot_version": snapshot["snapshot_version"],
    }


def _trashed_document_count(catalog, item_id):
    entry = next((item for item in catalog if int(item["id"]) == int(item_id)), None)
    return int((entry or {}).get("document_count") or 0)


def cleanup(name):
    if not name.startswith(PIPELINE_PREFIX):
        raise RuntimeError("拒绝清理非测试流水线")
    context = _context(name)
    core = context["core"]
    employee_ids = [item["employee_id"]
                    for item in context["pipeline"]["definition_json"]["positions"]]
    pipeline_id = context["pipeline"]["id"]
    core.trash_pipeline(pipeline_id)
    # 夹具自己造的东西自己收：文档份数必须显式确认，删除闸不给任何人开后门。
    core.delete_trashed_pipeline(
        pipeline_id, acknowledged_documents=_trashed_document_count(
            core.pipeline_trash_catalog(), pipeline_id))
    for employee_id in employee_ids:
        core.trash_employee(employee_id)
        core.delete_trashed_employee(
            employee_id, acknowledged_documents=_trashed_document_count(
                core.employee_trash_catalog(), employee_id))
    return {"removed": True, "pipeline": name}


def sync_relay(server):
    request = urllib.request.Request(
        server.rstrip("/") + "/api/mobile-relay/sync", data=b"{}",
        headers={"Content-Type": "application/json"}, method="POST")
    result = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(3):
        try:
            with opener.open(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (502, 503, 504) or attempt == 2:
                raise
        except urllib.error.URLError:
            if attempt == 2:
                raise
        time.sleep(attempt + 1)
    if result is None or result.get("failed"):
        raise RuntimeError("移动中转同步失败：{}".format((result or {}).get("errors") or result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=(
        "create", "queue", "running", "handoff", "reviewing", "complete", "describe", "cleanup"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--data-dir")
    parser.add_argument("--sync-server")
    args = parser.parse_args(argv)
    _configure_import_path(args.data_dir)
    _store().init_product_db()
    result = globals()[args.action](args.name)
    if args.sync_server:
        result["relay"] = sync_relay(args.sync_server)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
