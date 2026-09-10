# -*- coding: utf-8 -*-
"""Persistent AI conversations for designing core Employees."""
import json
import os
import re

import agent_tool_registry
import chat
import chat_attachments
import codex_threads
import model_channels
import product_store as store
import runtime_capabilities
from adapter_base import EXECUTION_USER_AGENT
from runner import run_agent
from runteams_core import RunTeamsCore
from runteams_core.contracts import (ContractError, digest, employee_coverage_targets,
                                      normalize_employee_draft)


SESSION_KIND = "employee_design"
TIMEOUT_SEC = 180
EMPLOYEE_TOOL_NAMES = ["runteams_request_choice", "runteams_present_employee_draft"]


def public_session(session):
    if not session:
        return session
    value = dict(session)
    context = dict(value.get("context") or {})
    context.pop("snapshot", None)
    context.pop("validation_spec_digest", None)
    value["context"] = context
    return value


def _runtime(config):
    config = config or {}
    channel = store.get_channel(config.get("channel_id")) or store.get_default_channel()
    if not channel or not channel.get("enabled"):
        raise ValueError("请选择可用的模型渠道")
    model, effort = model_channels.normalize_selection(
        channel, config.get("model"), config.get("reasoning_effort"))
    return channel, model, effort


def _text(value, limit):
    return str(value or "").strip()[:limit]


def _draft(raw, fallback=None):
    source = raw if isinstance(raw, dict) else {}
    base = fallback if isinstance(fallback, dict) else {}
    source_program = source.get("program") if isinstance(source.get("program"), dict) else {}
    base_program = base.get("program") if isinstance(base.get("program"), dict) else {}
    raw_steps = source_program.get("steps", base_program.get("steps") or [])
    steps = []
    for index, item in enumerate(raw_steps if isinstance(raw_steps, list) else []):
        if not isinstance(item, dict):
            continue
        instruction = _text(item.get("instructions") or item.get("instruction") or item.get("name"), 4000)
        if instruction:
            step_id = _text(item.get("id"), 80).lower() or "step-{}".format(index + 1)
            step_id = re.sub(r"[^a-z0-9-]+", "-", step_id).strip("-") or "step-{}".format(index + 1)
            if not re.match(r"^[a-z]", step_id):
                step_id = "step-" + step_id
            if any(existing["id"] == step_id for existing in steps):
                step_id = "step-{}".format(index + 1)
            steps.append({"id": step_id[:80],
                          "name": _text(item.get("name"), 160) or "步骤 {}".format(index + 1),
                          "instructions": instruction})
    source_delivery = (source_program.get("delivery")
                       if isinstance(source_program.get("delivery"), dict) else {})
    base_delivery = (base_program.get("delivery")
                     if isinstance(base_program.get("delivery"), dict) else {})
    raw_deliverables = source_program.get(
        "deliverables", base_program.get("deliverables") or [])
    deliverables = []
    for item in raw_deliverables if isinstance(raw_deliverables, list) else []:
        if not isinstance(item, dict):
            continue
        path = _text(item.get("path"), 300)
        if not path:
            continue
        deliverables.append({
            "path": path,
            "name": _text(item.get("name"), 200) or path.rsplit("/", 1)[-1],
            "required": bool(item.get("required", True)),
        })
    raw_capabilities = source.get("capabilities", base.get("capabilities") or [])
    capabilities = []
    for item in raw_capabilities if isinstance(raw_capabilities, list) else []:
        if not isinstance(item, dict):
            continue
        plugin_id = _text(item.get("plugin_id"), 240)
        provider = _text(item.get("provider"), 80)
        if plugin_id and provider:
            reference = {"provider": provider, "plugin_id": plugin_id}
            if reference not in capabilities:
                capabilities.append(reference)
            continue
        try:
            package_id = int(item.get("package_id"))
        except (TypeError, ValueError):
            continue
        reference = {"package_id": package_id}
        if package_id > 0 and reference not in capabilities:
            capabilities.append(reference)
    raw_tests = source.get("tests", base.get("tests") or [])
    tests, test_ids = [], set()
    for index, item in enumerate(raw_tests if isinstance(raw_tests, list) else []):
        if not isinstance(item, dict):
            continue
        test_id = _text(item.get("id"), 80).lower() or "case-{}".format(index + 1)
        test_id = re.sub(r"[^a-z0-9-]+", "-", test_id).strip("-") or "case-{}".format(index + 1)
        if not re.match(r"^[a-z]", test_id):
            test_id = "case-" + test_id
        if test_id in test_ids:
            continue
        work_order = item.get("work_order") if isinstance(item.get("work_order"), dict) else {}
        objective = _text(work_order.get("objective"), 4000)
        if not objective:
            continue
        expected_status = str(item.get("expected_status") or "completed").strip()
        if expected_status not in ("completed", "blocked", "needs_human", "failed"):
            expected_status = "completed"
        expected_route = str(item.get("expected_route") or "").strip()
        if expected_route not in ("completed", "exception"):
            expected_route = ""
        try:
            downstream_id = int(item.get("downstream_employee_id"))
            if downstream_id <= 0:
                downstream_id = None
        except (TypeError, ValueError):
            downstream_id = None
        normalized_test = {
            "id": test_id[:80],
            "name": _text(item.get("name"), 160) or "用例 {}".format(index + 1),
            "work_order": {
                "objective": objective,
                "context": (work_order.get("context")
                            if isinstance(work_order.get("context"), dict) else {}),
                "inputs": (work_order.get("inputs")
                           if isinstance(work_order.get("inputs"), list) else []),
                "expected_output": (work_order.get("expected_output")
                                    if isinstance(work_order.get("expected_output"), dict) else {}),
                "acceptance": [_text(value, 1000) for value in
                               (work_order.get("acceptance") or []) if _text(value, 1000)],
            },
            "expected_status": expected_status,
            "downstream_employee_id": downstream_id,
            "covers": list(dict.fromkeys(
                _text(value, 160) for value in (item.get("covers") or [])
                if _text(value, 160))),
        }
        if expected_route:
            normalized_test["expected_route"] = expected_route
        fixtures = []
        for raw_fixture in item.get("fixtures") or []:
            if not isinstance(raw_fixture, dict):
                continue
            path = _text(raw_fixture.get("path"), 500)
            content = raw_fixture.get("content")
            if path and isinstance(content, str):
                fixture = {"path": path, "content": content}
                if bool(raw_fixture.get("executable", False)):
                    fixture["executable"] = True
                fixtures.append(fixture)
        if fixtures:
            normalized_test["fixtures"] = fixtures
        tests.append(normalized_test)
        test_ids.add(test_id)
    return {
        "name": _text(source.get("name", base.get("name")), 160),
        "goal": _text(source.get("goal", base.get("goal")), 4000),
        "instructions": _text(source.get("instructions", base.get("instructions")), 120000),
        "program": {
            "objective": _text(source_program.get("objective", base_program.get("objective")), 12000),
            "steps": steps,
            "delivery": {"acceptance_criteria": _text(
                source_delivery.get("acceptance_criteria",
                                    base_delivery.get("acceptance_criteria")), 12000)},
            "deliverables": deliverables,
        },
        "capabilities": capabilities,
        "interface": (source.get("interface") if isinstance(source.get("interface"), dict)
                      else base.get("interface") if isinstance(base.get("interface"), dict)
                      else {}),
        "tests": tests,
    }


def _employee_draft(employee, include_tests=True):
    value = (employee or {}).get("draft_json") or {}
    program = value.get("program") or {}
    return _draft({
        "name": (employee or {}).get("name"),
        "goal": program.get("objective"),
        "instructions": value.get("role"),
        "program": {
            "objective": program.get("objective"),
            "steps": [{"id": item.get("id"), "name": "步骤 {}".format(index + 1),
                       "instructions": item.get("instruction")}
                      for index, item in enumerate(program.get("steps") or [])],
            "delivery": {"acceptance_criteria": "\n".join(program.get("acceptance") or [])},
            "deliverables": program.get("deliverables") or [],
        },
        "capabilities": value.get("capabilities") or [],
        "interface": value.get("interface") or {},
        "tests": (value.get("tests") or []) if include_tests else [],
    })


def _complete_draft(draft, require_tests=False):
    interface = draft.get("interface") if isinstance(draft.get("interface"), dict) else {}
    program = draft.get("program") if isinstance(draft.get("program"), dict) else {}
    complete = bool(draft.get("name") and draft.get("instructions") and
                    (program.get("objective") or draft.get("goal")) and
                    isinstance(interface.get("input"), dict) and
                    isinstance(interface.get("output"), dict))
    if not complete or not require_tests:
        return complete
    tests = draft.get("tests")
    if not isinstance(tests, list) or not tests or any(
            not isinstance(item, dict) or not item.get("covers") for item in tests):
        return False
    target_ids = {item["id"] for item in employee_coverage_targets({
        "interface": interface,
        "program": {"steps": [
            {"id": item.get("id") or "step-{}".format(index + 1),
             "instruction": item.get("instructions") or item.get("name") or "执行步骤"}
            for index, item in enumerate((draft.get("program") or {}).get("steps") or [])]},
        "capabilities": draft.get("capabilities") or [],
    })}
    covered = {coverage_id for item in tests for coverage_id in item.get("covers") or []}
    return target_ids.issubset(covered)


def _context(core, target, phase="design", channel=None):
    packages = []
    for package in core.package_catalog():
        manifest = package.get("manifest_json") or {}
        packages.append({
            "package_id": package["id"],
            "name": manifest.get("display_name") or manifest.get("name") or package["key"],
            "description": manifest.get("description") or "",
            "test_ref": "{}/{}".format(
                package["key"], ((manifest.get("capabilities") or [{}])[0].get("id") or "")),
            "version": package.get("version"),
            "verified": (package.get("verification") or {}).get("status") == "verified",
        })
    value = {
        "employees": [{"id": item["id"], "name": item["name"],
                       "role": (item.get("draft_json") or {}).get("role") or ""}
                      for item in core.employee_catalog()],
        "packages": packages,
        "channel_extensions": [],
    }
    if channel:
        environment = runtime_capabilities.inventory(channel)
        value["channel_extensions"] = [{
            "provider": channel.get("provider"),
            "plugin_id": item.get("id"),
            "name": item.get("display_name") or item.get("name") or item.get("id"),
            "description": item.get("description") or "",
        } for item in environment.get("plugins") or []
            if item.get("installed") and item.get("enabled") and item.get("has_resources")]
    if target:
        value["current_employee"] = _employee_draft(target, include_tests=False)
        if phase == "validation":
            validation_target = dict(target)
            validation_target["draft_json"] = dict(target.get("draft_json") or {})
            validation_target["draft_json"]["tests"] = []
            value["coverage"] = core.employee_coverage(validation_target)
    return json.dumps(value, ensure_ascii=False)


def create_session(config, employee_id=None, phase="design"):
    channel, model, effort = _runtime(config)
    try:
        employee_id = int(employee_id) if employee_id else None
    except (TypeError, ValueError):
        raise ValueError("指定的员工无效")
    phase = str(phase or "design").strip()
    if phase not in ("design", "validation"):
        raise ValueError("员工对话阶段无效")
    core = RunTeamsCore(store.core_data_root())
    target = core.employee(employee_id) if employee_id else None
    if employee_id and not target:
        raise ValueError("这名员工已不存在")
    context = {
        "context_type": "worker",
        "intent": "validate" if phase == "validation" else "edit" if target else "create",
        "phase": phase,
        "target_employee_id": (target or {}).get("id"),
        "label": (target or {}).get("name") or "团队",
        "snapshot": _context(core, target, phase, channel),
    }
    if phase == "validation" and target:
        context["validation_spec_digest"] = digest(
            core._employee_test_spec(target["draft_json"]))
    title = "编辑员工 · " + target["name"] if target else "创建员工"
    session_id = store.create_agent_session(
        SESSION_KIND, title[:80], channel["id"], model, effort, None, context)
    if target:
        store.update_agent_session_draft(
            session_id, _employee_draft(target, include_tests=False), "active")
    return store.get_chat(session_id)


def _json_object(text):
    value = str(text or "").strip()
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        first = value.find("{")
        if first < 0:
            raise ValueError("暂时无法整理这项调整，请再试一次")
        try:
            parsed, consumed = json.JSONDecoder().raw_decode(value[first:])
        except (TypeError, ValueError):
            raise ValueError("暂时无法整理这项调整，请再试一次")
        trailing = value[first + consumed:].replace("```", "").strip()
        if trailing and set(trailing) != {"}"}:
            raise ValueError("助手返回的内容不完整，请再试一次")
    if not isinstance(parsed, dict):
        raise ValueError("暂时无法整理这项调整，请再试一次")
    return parsed


def _options(raw):
    result = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            label = _text(item.get("label") or item.get("title"), 60)
            description = _text(item.get("description") or item.get("desc"), 120)
        else:
            label, description = _text(item, 60), ""
        if label and not any(option["label"] == label for option in result):
            result.append({"label": label, "description": description})
        if len(result) == 5:
            break
    return result


def _instructions(session, capabilities):
    context = session.get("context") or {}
    extension_context = chat._capability_context(capabilities, "")
    validation_phase = context.get("phase") == "validation"
    phase_rules = ("""- 这是发布验证阶段：岗位职责、program、capabilities 和 interface 已定稿，不得修改。
- 必须基于当前定稿从零建立 tests，不要沿用设计过程中的旧用例。
- tests 覆盖 interface、全部 program.steps、全部员工技能、四种结果状态和交接边界；数量由覆盖目标决定，不设固定数量。
- 每个测试必须提供 covers，精确覆盖上下文 coverage.missing 中的全部目标 id。
- covers 必须与用例信号和 expected_status 一致：result 只能声明自身预期状态；output、program、员工技能 success 和 handoff.output.valid 只能放在 completed 用例；员工技能 failure 只能放在 failed 用例。
- 上游 valid/missing/invalid 分别由 context 中同时存在、同时缺少、只存在一个 upstream_position/upstream_output 来模拟。
- work_order 必须包含 objective、对象 context、数组 inputs、对象 expected_output 和数组 acceptance；expected_status 只能是 completed、blocked、needs_human 或 failed。当员工输出包含 route 时，必须用 expected_route=completed 或 exception 覆盖每个业务去向。
- 只要场景依赖文件或目录，必须在测试用例的 fixtures 中逐文件提供相对 path 和完整文本 content；系统会在每次独立试运行前写入该用例自己的隔离工作区。禁止只写一个并不存在的路径。命令行依赖可提供 bin/ 下的文本脚本并设置 executable=true；该目录只会在本次验证中临时加入 PATH。
""" if validation_phase else """- 这是员工设计阶段：只定义岗位、程序、能力和输入输出契约，tests 保持空数组。
- 不要创建、维护或修补测试用例；测试只在用户点击“发布”、员工定稿后生成。
""")
    return """你是 RunTeams.ai 的员工设计 Agent。你和用户协作，把自然语言需求整理成一名可发布、可复用、能与其他员工结构化交接工作的员工。

规则：
- 信息足够就直接给完整草稿；只有缺失信息会实质改变职责时才问一个聚焦问题。
- name 是员工名称；instructions 是稳定的岗位职责和工作边界；goal 与 program.objective 是员工要持续达成的结果目标。目标回答“最终要取得什么结果”，职责回答“负责做什么、边界在哪里”，不得把同一段文字复制到两者。
- program.steps 必须是有序、可执行的方法，至少一项；delivery.acceptance_criteria 每行一条可判断的完成标准。program.deliverables 只声明岗位必须交付的文档，使用相对 path、用户可读 name 和 required；没有固定文档时使用空数组。
- capabilities 只能从上下文选择：员工技能使用 {{package_id}}；当前模型渠道提供的工作工具使用 {{provider, plugin_id}}。不需要时可为空，禁止编造 id。一个员工技能是完整工作能力，不得选择或暴露包内脚本、文档和校验工具。
- interface 必须用 input 和 output 两个 JSON Schema 明确这名员工的业务输入与结构化输出。input 根对象是完整 WorkOrder（objective、context、inputs、expected_output、acceptance），岗位特有输入放在 context 或 inputs 下；output 根对象是 WorkResult.output。不要只使用宽泛 object，要把职责中实际依赖和交付的字段、必填、类型与边界表达清楚。
- 同一张任务卡上的岗位共享一个持久工作区，后续岗位可以读取前序岗位留下的相对路径文件。下游工作单的 context 由平台提供 upstream_position、upstream_summary、upstream_output；上游产生的业务字段必须建模在 upstream_output 内，不得假设平台会把它们重复摊平到 context 顶层。
{}
- 模型渠道由产品单独保存，不写进岗位说明。
- 你只更新草稿；用户明确应用后系统才写入 Employee，发布仍是另一个显式动作。

运行时提供 runteams_request_choice 时，缺少关键信息必须调用它，不要把选项写成普通文本。
运行时提供 runteams_present_employee_draft 时，信息足够后必须调用它提交完整草稿；该工具只生成待审核草稿卡，不会保存或发布员工。
最终直接用自然、简洁的中文回复，不要输出 JSON 外壳，也不要在正文里重复完整草稿。

# 可用员工、员工技能、工作工具与当前员工
{}

# 当前草稿
{}

{}""".format(phase_rules, context.get("snapshot") or "{}",
              json.dumps(session.get("draft") or {}, ensure_ascii=False), extension_context)


def _turn_timeout(session, capabilities):
    context = session.get("context") if isinstance(session.get("context"), dict) else {}
    return 900 if capabilities or context.get("phase") == "validation" else TIMEOUT_SEC


def _model_turn(session_id, session, message, history, attachments, capabilities,
                on_activity=None, cancel_event=None):
    channel, model, effort = _runtime(session)
    history_text, history_images = chat_attachments.history_context(session_id, history or [])
    persisted_thread = (session.get("runtime_thread_id")
                        if channel.get("provider") == "codex"
                        and session.get("runtime_provider") == "codex" else "")
    if persisted_thread:
        history_text, history_images = "", []
    attachment_context, image_paths = ("", [])
    if attachments:
        attachment_context, image_paths = chat_attachments.prompt_context(session_id, attachments)
    image_paths = list(dict.fromkeys(history_images + image_paths))
    prompt_message = message or "请查看附件并继续设计员工。"
    if attachment_context:
        prompt_message += "\n\n" + attachment_context
    instructions = _instructions(session, capabilities)
    workspace = store.assistant_workspace()
    context = session.get("context") if isinstance(session.get("context"), dict) else {}
    timeout = _turn_timeout(session, capabilities)
    tool_context = chat._agent_tool_context(
        session_id, None, {}, context)
    if channel.get("provider") == "codex":
        result = codex_threads.run_turn(
            channel, persisted_thread, prompt_message, instructions,
            model=model, effort=effort, cwd=workspace, image_paths=image_paths,
            extensions_enabled=bool(capabilities), timeout=timeout,
            on_activity=on_activity,
            on_thread=lambda thread_id, _title: store.set_chat_runtime(
                session_id, "codex", thread_id),
            execution_profile=EXECUTION_USER_AGENT, cancel_event=cancel_event,
            tool_context=tool_context, tool_names=EMPLOYEE_TOOL_NAMES)
        parsed = _native_employee_response(
            result.get("native_tool_results") or [], result["text"])
        return parsed, channel, model, effort, result.get("meta") or {}
    adapter = model_channels.adapter_for(channel)
    if hasattr(adapter, "configure_requirements"):
        plugins = [item.get("plugin_id") or item["id"] for item in capabilities
                   if item.get("kind") in ("plugin", "skill")]
        mcp_servers = [item["id"] for item in capabilities if item.get("kind") == "mcp"]
        adapter.configure_requirements({"inherit_native": True,
                                        "plugins": plugins, "mcp_servers": mcp_servers})
    prompt = instructions
    if history_text:
        prompt += "\n\n# 已有对话\n" + history_text
    prompt += "\n\n# 用户本轮消息\n" + prompt_message
    extra_args = []
    if channel.get("provider") == "claude-code":
        extra_args += chat._claude_agent_tool_args(tool_context, EMPLOYEE_TOOL_NAMES)
    for path in image_paths:
        extra_args += ["--image", path]
    result = run_agent(adapter, prompt, execution_profile=EXECUTION_USER_AGENT,
                        mode="judge", model=model, reasoning_effort=effort,
                        timeout_sec=timeout, extra_args=extra_args, cwd=workspace,
                        on_activity=on_activity, cancel_event=cancel_event)
    parsed = _native_employee_response(
        (result.meta or {}).get("native_tool_results") or [], result.text)
    return parsed, channel, model, effort, result.meta or {}


def _native_employee_response(native_results, fallback_text):
    draft_result = chat._native_tool_result(native_results, "employee_draft")
    if draft_result:
        return dict(draft_result["data"])
    question, options = chat._native_choice_from_results(native_results)
    if question and options:
        return {"reply": question, "draft_ready": False, "options": options}
    # Compatibility for a pre-native response already in flight. New turns
    # return ordinary prose when they do not produce a draft or choice tool.
    try:
        return _json_object(fallback_text)
    except ValueError:
        return {"reply": str(fallback_text or "").strip(), "draft_ready": False}


def _core_draft(draft, channel, model, effort, validation_phase):
    """Build the exact payload apply_ready_draft hands to the core."""
    steps = [{"id": item["id"], "instruction": item["instructions"]}
             for item in draft["program"]["steps"] if item.get("instructions")]
    if not steps:
        steps = [{"id": "step-1", "instruction": "完成岗位职责并结构化交付"}]
    acceptance = [item.strip() for item in re.split(
        r"[\n；;]+", draft["program"]["delivery"].get("acceptance_criteria") or "")
                  if item.strip()]
    if not acceptance:
        acceptance = ["结果满足岗位职责并可被下一名员工使用"]
    return {
        "role": draft["instructions"],
        "program": {"objective": draft["program"].get("objective") or draft.get("goal"),
                    "steps": steps, "acceptance": acceptance,
                    "deliverables": draft["program"].get("deliverables") or []},
        "capabilities": draft.get("capabilities") or [],
        "interface": draft.get("interface") or {},
        "tests": (draft.get("tests") or []) if validation_phase else [],
        "runtime": {"channel": channel.get("provider") or "codex", "model": model,
                    "effort": effort},
    }


def _contract_error(draft, session, validation_phase):
    """Dry-run the core contract gate; return the error text or None.

    生成端无权自审：草稿在标记 ready 之前必须先通过核心契约的同一道
    机器闸，否则 apply 阶段才暴露 409，且用户无从修复。"""
    try:
        channel, model, effort = _runtime(session)
        normalize_employee_draft(_core_draft(draft, channel, model, effort, validation_phase))
        return None
    except ContractError as exc:
        return str(exc)
    except (ValueError, TypeError, KeyError) as exc:
        return str(exc) or "草稿结构无效"


def _apply_requested(message):
    compact = re.sub(r"[\s，。！？!,.]+", "", str(message or "")).lower()
    return compact in {"确认", "确认保存", "保存吧", "就这样保存", "按这个保存",
                       "确认创建", "创建吧", "确认修改", "应用修改"}


def run_turn(session_id, message, history=None, attachments=None, supplied_draft=None,
             on_activity=None, capabilities=None, cancel_event=None):
    session = store.get_chat(int(session_id))
    if not session or session.get("kind") != SESSION_KIND:
        raise ValueError("这段对话已不存在")
    message = str(message or "").strip()
    attachments = attachments or []
    if not message and not attachments:
        raise ValueError("请输入消息或添加附件")
    current = _draft(session.get("draft") or {})
    require_tests = (session.get("context") or {}).get("phase") == "validation"
    if _apply_requested(message) and _complete_draft(current, require_tests=require_tests):
        applied = apply_ready_draft(session_id, current)
        return {"reply": applied["reply"], "draft": current, "draft_ready": False,
                "applied": applied["applied"], "channel_id": session.get("channel_id"),
                "model": session.get("model"), "reasoning_effort": session.get("reasoning_effort"),
                "cost": None}
    if isinstance(supplied_draft, dict) and supplied_draft:
        current = _draft(supplied_draft, current)
        session["draft"] = current
        store.update_agent_session_draft(session_id, current, session.get("status") or "active")
    normalized_capabilities = chat._normalize_capabilities(capabilities)
    parsed, channel, model, effort, meta = _model_turn(
        session_id, session, message, history or [], attachments, normalized_capabilities,
        on_activity=on_activity, cancel_event=cancel_event)
    incoming = parsed.get("draft")
    draft = _draft(incoming, current) if isinstance(incoming, dict) else current
    ready = bool(parsed.get("draft_ready") and _complete_draft(
        draft, require_tests=require_tests))
    contract_note = ""
    if ready:
        contract_issue = _contract_error(draft, session, require_tests)
        if contract_issue:
            ready = False
            contract_note = "\n\n草稿还没通过核心校验，暂不能应用：{}。请修正后再确认。".format(contract_issue)
    next_status = "applied" if session.get("status") == "applied" else ("ready" if ready else "active")
    store.update_agent_session_draft(session_id, draft, next_status)
    return {"reply": (_text(parsed.get("reply"), 12000) or "员工草稿已更新。") + contract_note,
            "draft": draft, "draft_ready": ready,
            "options": [] if ready else _options(parsed.get("options")), "applied": [],
            "channel_id": channel["id"], "model": model,
            "reasoning_effort": effort, "cost": meta.get("cost_usd")}


def apply_ready_draft(session_id, supplied_draft=None):
    session = store.get_chat(int(session_id))
    if not session or session.get("kind") != SESSION_KIND:
        raise ValueError("这段对话已不存在")
    if session.get("status") != "ready":
        raise ValueError("这项调整已经处理，或还没有准备好")
    draft = _draft(supplied_draft if isinstance(supplied_draft, dict) else session.get("draft"))
    validation_phase = (session.get("context") or {}).get("phase") == "validation"
    if not _complete_draft(draft, require_tests=validation_phase):
        raise ValueError("验证集还没准备好：必须覆盖当前定稿的全部场景"
                         if validation_phase else
                         "员工设置还没准备好：请先补齐输入输出接口")
    channel, model, effort = _runtime(session)
    core_draft = _core_draft(draft, channel, model, effort, validation_phase)
    core = RunTeamsCore(store.core_data_root())
    context = session.get("context") or {}
    target_id = context.get("target_employee_id")
    applied_id = context.get("applied_employee_id")
    if validation_phase:
        if not target_id:
            raise ValueError("验证阶段缺少已定稿的员工")
        current_employee = core.employee(target_id)
        if not current_employee:
            raise ValueError("这名员工已不存在")
        expected_spec = (session.get("context") or {}).get("validation_spec_digest")
        current_spec = digest(core._employee_test_spec(current_employee["draft_json"]))
        if not expected_spec or current_spec != expected_spec:
            raise ValueError("员工定稿已变更，这批测试已作废；请重新验证并发布")
        current_draft = dict(current_employee["draft_json"])
        current_draft["tests"] = core_draft["tests"]
        core.update_employee(target_id, current_employee["name"], current_draft)
        employee_id, updated = int(target_id), True
    elif not target_id and applied_id and core.employee(applied_id):
        employee_id, updated = int(applied_id), False
    elif target_id:
        core.update_employee(target_id, draft["name"], core_draft)
        employee_id, updated = int(target_id), True
    else:
        employee_id = core.create_employee(draft["name"], core_draft)
        context["applied_employee_id"] = employee_id
        updated = False
    context["target_employee_id"] = employee_id
    context["label"] = draft["name"]
    store.update_agent_session_draft(session_id, draft, "applied")
    store.update_agent_session_context(session_id, context, "applied")
    label = "已更新员工「{}」".format(draft["name"]) if updated else "已保存员工「{}」".format(draft["name"])
    return {"ok": True, "employee_id": employee_id, "reply": label + "。", "draft": draft,
            "draft_ready": False, "status": "applied", "applied": [label]}


def discard_ready_draft(session_id):
    session = store.get_chat(int(session_id))
    if not session or session.get("kind") != SESSION_KIND:
        raise ValueError("这段对话已不存在")
    if session.get("status") != "ready":
        raise ValueError("这项调整已经处理，或还没有准备好")
    store.update_agent_session_draft(session_id, {}, "active")
    return {"ok": True, "draft": {}, "draft_ready": False, "status": "active"}
