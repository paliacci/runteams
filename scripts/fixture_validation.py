"""Deterministic publish validation for simulations, soak setup and test fixtures."""

from runteams_core.contracts import employee_coverage_targets, normalize_employee_draft


def _sample(schema):
    schema = schema or {}
    if schema.get("enum"):
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), kind[0] if kind else None)
    if kind == "object" or schema.get("properties"):
        return {name: _sample(child)
                for name, child in (schema.get("properties") or {}).items()}
    if kind == "array":
        count = max(0, int(schema.get("minItems") or 0))
        return [_sample(schema.get("items") or {}) for _index in range(count)]
    if kind == "string":
        return "x" * max(1, int(schema.get("minLength") or 1))
    if kind == "integer":
        return int(schema.get("minimum") or 0)
    if kind == "number":
        return float(schema.get("minimum") or 0)
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return {}


def _work_order(interface, context, upstream_shape=None):
    value = _sample(interface.get("input") or {})
    value = value if isinstance(value, dict) else {}
    base_context = value.get("context") if isinstance(value.get("context"), dict) else {}
    base_context = {**base_context, **context}
    if upstream_shape in ("missing", "invalid"):
        base_context.pop("upstream_position", None)
        base_context.pop("upstream_output", None)
    if upstream_shape == "valid":
        base_context.update({"upstream_position": "upstream", "upstream_output": {}})
    elif upstream_shape == "invalid":
        base_context["upstream_position"] = "upstream"
    return {
        "objective": str(value.get("objective") or "Validate employee"),
        "context": base_context,
        "inputs": value.get("inputs") if isinstance(value.get("inputs"), list) else [],
        "expected_output": (value.get("expected_output")
                            if isinstance(value.get("expected_output"), dict) else {}),
        "acceptance": (value.get("acceptance")
                       if isinstance(value.get("acceptance"), list) else []),
    }


def verify_employee(core, employee_id):
    """Create a complete deterministic matrix and execute it through Workflow."""
    employee = core.employee(employee_id)
    draft = employee["draft_json"]
    normalized = normalize_employee_draft({**draft, "tests": []})
    interface = normalized["interface"]
    targets = [item["id"] for item in employee_coverage_targets(normalized)]
    context_required = set(((interface.get("input") or {}).get("properties") or {}).get(
        "context", {}).get("required") or [])
    positive_upstream = ("valid" if {"upstream_position", "upstream_output"} <= context_required
                         else "missing")
    excluded = {"result.blocked", "result.needs_human", "result.failed",
                "handoff.upstream.valid", "handoff.upstream.missing",
                "handoff.upstream.invalid"}
    positive = [target for target in targets
                if target not in excluded and not target.endswith(".failure")]
    positive.append("handoff.upstream." + positive_upstream)
    alternate = "missing" if positive_upstream == "valid" else "valid"
    failures = [target for target in targets if target.endswith(".failure")]
    failure_tests = []
    for index, target in enumerate(failures):
        package_id = target[len("skill."):].rsplit(".", 1)[0]
        package = core.package(int(package_id))
        capability = (package.get("manifest_json") or {}).get("capabilities", [])[0]
        reference = "{}/{}".format(package["key"], capability["id"])
        failure_tests.append({
            "id": "verified-capability-failed-{}".format(index + 1),
            "name": "Verified capability failure {}".format(index + 1),
            "work_order": _work_order(interface, {"test_signal": {
                "capability_ref": reference, "state": "unavailable",
            }}, positive_upstream),
            "expected_status": "failed",
            "covers": (["result.failed"] if index == 0 else []) + [target],
        })
    if not failure_tests:
        failure_tests.append({
            "id": "verified-failed", "name": "Verified failed",
            "work_order": _work_order(interface, {}, positive_upstream),
            "expected_status": "failed", "covers": ["result.failed"],
        })
    draft["tests"] = [
        {"id": "verified-completed", "name": "Verified completed",
         "work_order": _work_order(interface, {}, positive_upstream),
         "expected_status": "completed", "covers": positive},
        {"id": "verified-upstream", "name": "Verified upstream boundary",
         "work_order": _work_order(interface, {}, alternate),
         "expected_status": "completed", "covers": ["handoff.upstream." + alternate]},
        {"id": "verified-invalid-upstream", "name": "Verified invalid upstream",
         "work_order": _work_order(interface, {}, "invalid"),
         "expected_status": "needs_human",
         "covers": ["result.needs_human", "handoff.upstream.invalid"]},
        {"id": "verified-blocked", "name": "Verified blocked",
         "work_order": _work_order(interface, {}, positive_upstream),
         "expected_status": "blocked", "covers": ["result.blocked"]},
    ] + failure_tests
    core.update_employee(employee_id, employee["name"], draft)
    expected = {item["id"]: item["expected_status"] for item in draft["tests"]}
    output = _sample(interface.get("output") or {})

    for started in core.start_all_employee_trials(employee_id):
        test_id = started["snapshot_json"]["trial"]["test_id"]
        status = expected[test_id]

        def runtime(snapshot, _order, emit, result_status=status):
            if result_status == "completed":
                for step in (snapshot.get("program") or {}).get("steps") or []:
                    emit("step.completed", {"step_id": step["id"]})
                for frozen in snapshot.get("capabilities") or []:
                    capabilities = frozen.get("capabilities") or [
                        frozen.get("capability") or {}]
                    for capability in capabilities:
                        if capability.get("kind") == "tool":
                            emit("capability.executed", {
                                "capability_ref": "{}/{}".format(
                                    frozen.get("package_key"), capability.get("id")),
                            })
            return {"status": result_status,
                    "summary": "verified" if result_status == "completed" else "",
                    "output": output if result_status == "completed" else {},
                    "artifacts": [], "issues": []}

        core.run_workflow(started["id"], runtime, max_attempts=1)
    coverage = core.employee_coverage(employee_id, trials=core.employee_trials(employee_id))
    if not coverage["passed"]:
        raise AssertionError("fixture validation did not pass: {}".format(coverage))
    return coverage


def publish_verified_employee(core, employee_id):
    verify_employee(core, employee_id)
    return core.publish_employee(employee_id)
