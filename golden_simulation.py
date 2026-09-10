#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a deterministic Employee → Pipeline → Task → Workflow golden path."""
import json
import tempfile

from runteams_core import RunTeamsCore
from scripts.fixture_validation import publish_verified_employee


PIPELINE_NAME = "黄金场景 · 市场机会备忘录"
TASK_TITLE = "为独立开发者评估 AI 客服质检产品机会"

DELIVERIES = {
    "需求拆解": "已拆出目标用户、人工成本、竞品盲区和最小产品四个验证问题。",
    "调研执行": (
        "中小客服团队存在抽检覆盖率低和复盘滞后的问题；10—100 人团队可作为首批用户。"
    ),
    "初稿产出": (
        "目标用户是仍依赖人工抽检的中小客服团队；核心价值是全量会话质检。"
        "建议先验证上传记录后生成报告的窄场景，主要风险是隐私合规。"
    ),
    "最终交付": (
        "最终建议：有条件推进。先服务 10—100 人客服团队，以“全量会话质检 + 每周复盘”"
        "作为核心价值。两周内访谈 8 位负责人并制作 3 份样例报告；若至少 3 位愿意持续付费，"
        "再进入产品开发。主要风险是隐私合规和平台能力下沉。"
    ),
}


def _employee(core, name, role):
    employee_id = core.create_employee(name, {
        "role": role,
        "program": {
            "objective": role,
            "steps": [
                {"id": "analyze", "instruction": "分析当前任务和上游交付"},
                {"id": "deliver", "instruction": "形成结构化、可复核的岗位交付"},
            ],
            "acceptance": ["结论完整、明确，并可直接交给下一位员工"],
        },
        "capabilities": [],
        "runtime": {"channel": "fixture", "model": "fixture", "effort": "medium"},
    })
    publish_verified_employee(core, employee_id)
    return employee_id


def simulate_golden_pipeline():
    """Return one complete core workflow report without touching user data."""
    with tempfile.TemporaryDirectory(prefix="runteams-golden-core-") as root:
        core = RunTeamsCore(root)
        employee_names = ["需求分析师（模拟）", "市场研究员（模拟）",
                          "方案撰稿人（模拟）", "决策备忘录编辑（模拟）"]
        roles = ["把模糊方向变成可验证问题", "根据问题产出证据和机会判断",
                 "形成供用户确认的市场机会初稿", "根据用户决定形成最终交付"]
        employees = [_employee(core, name, role)
                     for name, role in zip(employee_names, roles)]
        names = ["需求拆解", "调研执行", "初稿产出", "最终交付"]
        position_by_employee = dict(zip(employee_names, names))
        keys = ["requirements", "research", "draft", "finalize"]
        pipeline_id = core.create_pipeline(PIPELINE_NAME, {
            "positions": [
                {"key": key, "name": name, "employee_id": employee_id}
                for key, name, employee_id in zip(keys, names, employees)
            ],
            "edges": [{"from": keys[index], "to": keys[index + 1]}
                      for index in range(len(keys) - 1)],
        })
        task_id = core.create_task(pipeline_id, TASK_TITLE, {
            "objective": "判断该方向是否值得独立开发者投入，并给出最小验证计划。",
            "acceptance": ["给出明确结论", "说明目标用户、验证计划和主要风险"],
        })
        workflow_id = core.start_workflow(task_id)
        trace = []

        def runtime(employee, work_order, emit):
            position_name = position_by_employee[employee["name"]]
            context = work_order.get("context") or {}
            trace.append({
                "position": position_name,
                "employee": employee["name"],
                "has_upstream": bool(context.get("upstream_summary")),
                "has_human_response": bool(context.get("human_response")),
            })
            emit("agent.progress", {"summary": "{}正在形成交付".format(employee["name"])})
            if position_name == "初稿产出" and not context.get("human_response"):
                return {
                    "status": "needs_human", "summary": DELIVERIES[position_name],
                    "issues": [], "artifacts": [],
                    "output": {
                        "question": "是否批准这个方向并生成最终决策备忘录？",
                        "context": DELIVERIES[position_name],
                    },
                }
            summary = DELIVERIES[position_name]
            return {
                "status": "completed", "summary": summary, "issues": [],
                "artifacts": ([{"name": "最终决策备忘录", "ref": "golden-final"}]
                              if position_name == "最终交付" else []),
                "output": {"position": position_name, "delivery": summary},
            }

        core.run_workflow(workflow_id, runtime)
        waiting = core.workflow(workflow_id)
        attention = core.attention_catalog()
        if waiting["state"] != "needs_human" or len(attention) != 1:
            raise AssertionError("核心工作流没有停在唯一的人工确认点")
        gate = attention[0]

        core.respond_to_human(workflow_id, "批准，继续形成最终备忘录")
        core.run_workflow(workflow_id, runtime)
        completed = core.workflow(workflow_id)
        remaining_attention = core.attention_catalog()
        positions = {
            item["key"]: item for item in completed["snapshot_json"]["definition"]["positions"]
        }
        timeline = []
        for employee_run in completed["employee_runs"]:
            position = positions[employee_run["position_key"]]
            result = employee_run.get("output_json") or {}
            timeline.append({
                "position": position["name"],
                "employee": position["employee"]["name"],
                "attempt": employee_run["attempt"],
                "state": employee_run["state"],
                "summary": result.get("summary") or "",
            })
        final_run = timeline[-1]
        final_output = completed["employee_runs"][-1]["output_json"]
        return {
            "pipeline": PIPELINE_NAME,
            "task": TASK_TITLE,
            "first_workflow_status": waiting["state"],
            "human_gate": {
                "position": gate["node_name"],
                "open_items": 1,
                "kind": gate["kind"],
                "decision": "批准",
            },
            "resumed_workflow_status": completed["state"],
            "final_position": final_run["position"],
            "final_status": completed["state"],
            "open_attention_after_completion": len(remaining_attention),
            "employee_run_count": len(completed["employee_runs"]),
            "timeline": timeline,
            "handoff_trace": trace,
            "artifact_count": sum(len(item.get("artifacts") or [])
                                  for item in completed["employee_runs"]),
            "final_delivery": (final_output.get("output") or {}).get("delivery") or "",
        }


if __name__ == "__main__":
    print(json.dumps(simulate_golden_pipeline(), ensure_ascii=False, indent=2))
