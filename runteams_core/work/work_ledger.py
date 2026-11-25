"""Canonical claim, concurrency, cancellation and durable work ledger mechanics."""
import json
import re
import threading
from datetime import datetime, timezone
from runteams_core.storage.repository import utc_now
from runteams_core.foundation.contracts import (
    ContractError, PIPELINE_APPROVAL_DECISIONS, PIPELINE_OUTCOME_PREFIX,
    PIPELINE_STATUS_FIRST,
)

def work_alerts(repository, after=None):
    """Read newly committed transitions. Opening a window starts at the ledger head."""
    if after is not None and (not isinstance(after, str) or not re.fullmatch(r'[0-9]{1,16}', after)
                              or int(after) > 2**53 - 1):
        raise ValueError('工作提醒游标无效。')
    with repository.read_snapshot() as connection:
        head = connection.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
        if after is None or int(after) >= head:
            return {'cursor': head, 'items': []}
        rows = connection.execute(
            "WITH batch AS (SELECT id,stream,type,data_json FROM events WHERE id>? ORDER BY id LIMIT 128) "
            "SELECT e.id,e.type,w.id AS workflow_id,w.state,w.cursor_key,t.trashed_at,"
            "json_extract(e.data_json,'$.to') AS target,"
            "json_extract(w.snapshot_json,'$.pipeline_work.reference') AS pipeline,"
            "json_extract(w.snapshot_json,'$.work_chat_id') AS chat_id "
            "FROM batch e LEFT JOIN workflow_runs w ON e.stream LIKE 'workflow_run:%' "
            "AND w.id=CAST(substr(e.stream,14) AS INTEGER) "
            "LEFT JOIN tasks t ON t.id=w.task_id ORDER BY e.id", (int(after),)).fetchall()
    categories = {'needs_approval': 'confirmation', 'needs_human': 'information', 'blocked': 'failure',
                  'interrupted': 'failure', 'failed': 'failure', 'completed': 'completion'}
    items = {}
    for row in rows:
        state = row['state']
        if state not in categories or row['trashed_at']:
            continue
        # A route to a final column can finish a pipeline without a workflow.completed event.
        routed = (row['type'] == 'workflow.routed' and row['target'] == row['cursor_key']
                  and state in ('completed', 'needs_human', 'blocked'))
        transition = 'workflow.approval_requested' if state == 'needs_approval' else 'workflow.' + state
        if row['type'] != transition and not routed:
            continue
        items[row['workflow_id']] = {'event_id': row['id'], 'workflow_id': row['workflow_id'],
            'category': categories[state], 'reference': json.loads(row['pipeline']) if row['pipeline'] else None,
            'chat_id': row['chat_id']}
    return {'cursor': rows[-1]['id'], 'items': list(items.values())}


class WorkLedger:
    def claim_workflow(self, workflow_run_id=None):
        """Atomically claim one due workflow for this local executor."""
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            arguments = [datetime.now(timezone.utc).isoformat()]
            where = ("wr.state IN ('ready','waiting_retry') "
                     "AND (wr.available_at IS NULL OR julianday(wr.available_at)<=julianday(?)) "
                     "AND " + self._workflow_claim_filter())
            if workflow_run_id is not None:
                where += " AND wr.id=?"
                arguments.append(int(workflow_run_id))
            rows = connection.execute(
                "SELECT wr.id,wr.task_id,wr.state,wr.snapshot_json FROM workflow_runs wr "
                "JOIN tasks t ON t.id=wr.task_id "
                + self._workflow_claim_join() +
                "WHERE {} ORDER BY wr.id".format(where),
                tuple(arguments)).fetchall()
            active = connection.execute(
                "SELECT id,state,snapshot_json FROM workflow_runs "
                "WHERE state IN ('running','needs_human','waiting_retry')").fetchall()
            row = next((item for item in rows
                        if self._workflow_has_execution_slot(item, active)), None)
            if row is None:
                return None
            self._cancel_event(row["id"], reset=True)
            changed = connection.execute(
                "UPDATE workflow_runs SET state='running',available_at=NULL,updated_at=? "
                "WHERE id=? AND state=?", (now, row["id"], row["state"])).rowcount
            if changed != 1:
                return None
            connection.execute("UPDATE tasks SET state='running',updated_at=? WHERE id=?",
                               (now, row["task_id"]))
            self.repository.event(
                "workflow_run:{}".format(row["id"]), "workflow.claimed",
                {"from_state": row["state"]}, connection=connection)
        return row["id"]


    def _workflow_claim_join(self):
        return ''


    def _workflow_claim_filter(self):
        return 't.pipeline_id IS NULL'


    @staticmethod
    def _workflow_has_execution_slot(candidate, active):
        """Honor frozen skill concurrency policies without recognizing skill names.

        Reserve the employee for the entire workflow handoff. Checking and
        claiming happen inside the same SQLite write transaction, across executors.
        """
        def limits(snapshot_json):
            result = {}
            for position in (json.loads(snapshot_json).get("definition") or {}).get("positions") or []:
                employee_id = position.get("employee_id")
                if not employee_id:
                    continue
                caps = [(position.get("employee") or {}).get("selected_work") or {}]
                values = [(cap.get("execution") or {}).get("max_concurrent_runs")
                          for cap in caps]
                values = [value for value in values if type(value) is int and value > 0]
                previous = result.get(employee_id)
                if previous is not None:
                    values.append(previous)
                result[employee_id] = min(values) if values else None
            return result

        requested = limits(candidate["snapshot_json"])
        occupants = [limits(item["snapshot_json"]) for item in active
                     if item["id"] != candidate["id"]
                     and (item["state"] != "waiting_retry" or item["id"] < candidate["id"])]
        for employee_id, limit in requested.items():
            overlapping = [item[employee_id] for item in occupants if employee_id in item]
            # A newer unrestricted release cannot bypass a running serial release.
            declared = [value for value in [limit] + overlapping if value is not None]
            if declared and len(overlapping) >= min(declared):
                return False
        return True


    def cancel_workflow(self, workflow_run_id):
        now = utc_now()
        with self.repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT task_id,state,snapshot_json FROM workflow_runs WHERE id=?",
                                     (int(workflow_run_id),)).fetchone()
            if row is None:
                raise ContractError("工作流运行不存在")
            if row["state"] in ("completed", "canceled"):
                return self.workflow(workflow_run_id)
            connection.execute(
                "UPDATE workflow_runs SET state='canceled',available_at=NULL,updated_at=? WHERE id=?",
                (now, int(workflow_run_id)))
            connection.execute("UPDATE tasks SET state='canceled',updated_at=? WHERE id=?",
                               (now, row["task_id"]))
            connection.execute(
                "UPDATE employee_runs SET state='canceled',updated_at=? "
                "WHERE workflow_run_id=? AND state='running'", (now, int(workflow_run_id)))
            source = json.loads(row["snapshot_json"]).get("source") or {}
            self._cancel_event(workflow_run_id).set()
            self.repository.event("workflow_run:{}".format(workflow_run_id),
                                  "workflow.canceled", {}, connection=connection)
        return self.workflow(workflow_run_id)


    def _cancel_event(self, workflow_run_id, reset=False):
        key = int(workflow_run_id)
        with self._cancel_lock:
            event = self._cancel_events.get(key)
            if event is None:
                event = threading.Event()
                self._cancel_events[key] = event
            if reset:
                event.clear()
            return event


    @staticmethod
    def _matching_edge(definition, position_key, result):
        edges = [item for item in definition.get("edges") or []
                 if item.get("from") == position_key]
        output = result.get("output") if isinstance(result, dict) else {}
        route = str(output.get("route") or "").strip() if isinstance(output, dict) else ""
        status = str(result.get("status") or "") if isinstance(result, dict) else ""
        exception = "exception" if status in ("failed", "blocked") else ""
        if definition.get("routing_policy") == PIPELINE_STATUS_FIRST:
            if status == "completed":
                outcome = PIPELINE_OUTCOME_PREFIX + route if route else ""
                conditions = (outcome, "completed", "always")
            elif status in ("failed", "blocked", "needs_human", *PIPELINE_APPROVAL_DECISIONS):
                conditions = (status, exception)
            else:
                return None
        else:
            conditions = (route, status, exception, "always")
        for value in conditions:
            if not value:
                continue
            match = next((item for item in edges
                          if str(item.get("when") or "completed") == value), None)
            if match is not None:
                return match
        return None


    def _route_workflow(self, workflow_run_id, edge, employee_run_id=None):
        now = utc_now()
        data = {"from": edge["from"], "to": edge["to"],
                "when": edge.get("when") or "completed"}
        if employee_run_id:
            data["employee_run_id"] = int(employee_run_id)
        with self.repository.connect() as connection:
            connection.execute(
                "UPDATE workflow_runs SET cursor_key=?,manual_column_key=NULL,updated_at=? "
                "WHERE id=?", (edge["to"], now, int(workflow_run_id)))
            self.repository.event(
                "workflow_run:{}".format(workflow_run_id), "workflow.routed", data,
                connection=connection)


    def _workflow_visit_count(self, workflow_run_id):
        with self.repository.connect() as connection:
            employee_visits = int(connection.execute(
                "SELECT COUNT(*) FROM employee_runs WHERE workflow_run_id=?",
                (int(workflow_run_id),)).fetchone()[0])
            approvals = int(connection.execute(
                "SELECT COUNT(*) FROM events WHERE stream=? AND type='workflow.approval_decided'",
                ("workflow_run:{}".format(int(workflow_run_id)),)).fetchone()[0])
        return employee_visits + approvals

