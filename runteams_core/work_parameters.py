"""Original declared and typed pipeline handoff parameters."""
import copy

class WorkParameters:
    @staticmethod
    def _result_team_parameters(result):
        """Read employee-produced values from the normal WorkResult output."""
        if not isinstance(result, dict):
            return {}
        output = result.get("output")
        if not isinstance(output, dict):
            return {}
        raw = output.get("team_parameters")
        if isinstance(raw, dict):
            return copy.deepcopy(raw)
        if isinstance(raw, list):
            values = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if key and "value" in item:
                    values[key] = copy.deepcopy(item["value"])
            return values
        return {}


    @classmethod
    def _collect_team_parameter_values(cls, definition, payload, employee_runs):
        declarations = {item["key"]: item for item in
                        (definition.get("parameters") or [])
                        if item.get("type") != "secret"}
        supplied = payload.get("parameters") or {}
        values = {key: copy.deepcopy(value) for key, value in supplied.items()
                  if key in declarations and declarations[key].get("source") == "user"}
        for key, declaration in declarations.items():
            if (declaration.get("source") == "user" and key not in values and
                    "default" in declaration):
                values[key] = copy.deepcopy(declaration["default"])
        for run in employee_runs or []:
            if str(run.get("state") or "") != "completed":
                continue
            position_key = str(run.get("position_key") or "")
            result = run.get("output_json") or {}
            # New work schemas expose their declared output fields directly.
            # Older works may use the explicit team_parameters envelope.
            produced = copy.deepcopy(result.get('output') or {})
            produced.update(cls._result_team_parameters(result))
            for key, value in produced.items():
                declaration = declarations.get(key)
                if not declaration or declaration.get("source") != "employee":
                    continue
                writers = declaration.get("writers") or []
                if writers and position_key not in writers:
                    continue
                values[key] = copy.deepcopy(value)
        return values


    def _workflow_team_parameter_values(self, workflow_run_id, definition, payload):
        with self.repository.connect() as connection:
            floor = int(connection.execute(
                "SELECT COALESCE(MAX(CAST(json_extract(data_json,'$.after_employee_run_id') AS INTEGER)),0) "
                "FROM events WHERE stream=? AND type='workflow.task_recompiled'",
                ('workflow_run:'+str(int(workflow_run_id)),)).fetchone()[0])
            rows = connection.execute(
                "SELECT position_key,state,output_json FROM employee_runs "
                "WHERE workflow_run_id=? AND id>? ORDER BY id", (int(workflow_run_id),floor)
            ).fetchall()
        runs = [self.repository.decode(row, "output_json") for row in rows]
        return self._collect_team_parameter_values(definition, payload, runs)


    @staticmethod
    def _pipeline_work_parameters(unit, definition, position_key, values):
        """Route typed values by declared visibility and the selected work schema.

        Display widgets such as textarea never coerce a handoff array to text.
        Employee-owned fields cannot be supplied by the task creator.
        """
        declarations = {p['key']:p for p in definition.get('parameters') or []}
        properties = unit['work']['input_schema'].get('properties')
        return {key:copy.deepcopy(value) for key,value in values.items()
                if (properties is None or key in properties)
                and (not declarations.get(key,{}).get('visible_to')
                     or position_key in declarations[key]['visible_to'])
                and declarations.get(key,{}).get('type') != 'secret'}


    @staticmethod
    def _team_parameters(definition, payload, position_key, values=None):
        values = values if isinstance(values, dict) else payload.get("parameters") or {}
        if not isinstance(values, dict):
            values = {}
        context, expected = [], []
        for parameter in definition.get("parameters") or []:
            if parameter.get("type") == "secret":
                continue
            visible = parameter.get("visible_to") or []
            if visible and position_key not in visible:
                continue
            declaration = {key: parameter[key] for key in
                           ("key", "label", "type", "note") if key in parameter}
            if parameter.get("source") == "employee":
                if parameter["key"] in values:
                    context.append(dict(
                        declaration,
                        value=copy.deepcopy(values[parameter["key"]]),
                    ))
                writers = parameter.get("writers") or []
                if not writers or position_key in writers:
                    expected.append(declaration)
                continue
            declaration["value"] = values.get(
                parameter["key"], parameter.get("default"))
            context.append(declaration)
        return context, expected

