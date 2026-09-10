"""Employee protocol runtime routed by the frozen Agent Channel."""

import json
import hashlib
import os
from pathlib import Path
import shutil
import sys

from adapter_base import EXECUTION_PIPELINE_AGENT
import model_channels
from runner import run_agent

from .contracts import ContractError
from .packages import PackageStore
from .protocol import EmployeeProtocol, trial_unavailable_capability
from .repository import Repository
from . import task_inputs


_TOOLS = ["get_task", "report_progress", "advance_step", "run_capability",
          "publish_artifact", "complete", "request_human", "report_blocked",
          "report_failed"]
_SUPPORTED_CHANNELS = ("codex", "claude-code")
_HOST_TOOL_DIRECTORIES = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(Path.home() / ".volta" / "bin"),
)
SYSTEM_INSTRUCTION = """你是 RunTeams.ai 中发布并冻结的员工。领取任务、报告进度、推进步骤、调用员工技能与提交终态只能通过 runteams MCP 完成；工作区内普通文件的读取、创建和编辑使用当前 Agent Channel 的原生文件工具。
当前进程目录就是本任务的唯一工作区。不得访问其父目录或任何工作区外路径，不得搜索、读取或采用 RunTeams 自身的 PROJECT_MEMORY.md、DESIGN_MEMORY.md、AGENTS.md 等项目文件；未在工作单和工作区中提供的资料一律视为不可用。
第一项动作必须调用 get_task。严格按 employee.program.steps 的顺序工作，每完成一步立即调用
advance_step。capabilities 是本员工已冻结的能力；skill 的说明位于列出的 path，tool 必须通过
run_capability 调用。effect=operation 的工具每个业务动作都必须使用稳定 invocation_id；同一动作重试
必须复用同一 ID。checkpoint 中若有 in_doubt operation，禁止换 ID 重放，应先核对外部系统并报告阻塞。
required_verifiers 中的工具必须在最终内容完成后通过，否则不能提交。
产生最终文件后用 publish_artifact 登记。成功时必须调用 complete；只有确实需要
用户决定时调用 request_human，业务条件客观阻塞时调用 report_blocked，能力或运行环境发生技术故障时
调用 report_failed。四种终态只能调用一个，调用后
立即停止。普通最终回复不会被系统接收。"""


def _materialize_trial_fixtures(fixtures, workspace):
    """Write already-normalized validation fixtures into one isolated workspace."""
    root = Path(workspace).resolve()
    executable_dirs = []
    for item in fixtures or []:
        target = (root / item["path"]).resolve()
        if target == root or root not in target.parents:
            raise ContractError("测试夹具路径超出用例工作区")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8")
        if item.get("executable"):
            target.chmod(0o755)
            parent = str(target.parent)
            if parent not in executable_dirs:
                executable_dirs.append(parent)
    return executable_dirs


def _trial_executable_dirs(fixtures, workspace):
    """Return executable fixture directories for later positions in the same trial."""
    root = Path(workspace).resolve()
    result = []
    for item in fixtures or []:
        if not item.get("executable"):
            continue
        parent = str((root / item["path"]).resolve().parent)
        if parent not in result:
            result.append(parent)
    return result


def _managed_executable_dirs(core_root):
    """Return executable directories owned by this RunTeams data directory."""
    root = Path(core_root).resolve() / "runtime"
    candidates = (
        root / "bin",
        root / "node" / "node_modules" / ".bin",
        root / "python" / "bin",
    )
    return [str(path.resolve()) for path in candidates if path.is_dir()]


def _host_tool_dirs():
    """Expose a locally installed Node toolchain without relying on login-shell PATH."""
    result = []
    for raw in _HOST_TOOL_DIRECTORIES:
        directory = Path(raw).expanduser().resolve()
        node = directory / "node"
        if directory.is_dir() and node.is_file() and os.access(str(node), os.X_OK):
            value = str(directory)
            if value not in result:
                result.append(value)
    return result


def _channel_executable_dirs(adapter):
    """Expose tools shipped beside the selected, already-trusted Agent Channel CLI."""
    executable = str(getattr(adapter, "executable", "") or "").strip()
    if not executable:
        return []
    directory = Path(executable).expanduser().resolve().parent
    return [str(directory)] if directory.is_dir() else []


class AgentEmployeeRuntime:
    def __init__(self, core_root, channel_resolver=None, timeout_sec=900,
                 credential_vault_path=None, native_dependency_resolver=None):
        self.root = Path(core_root).resolve()
        self.channel_resolver = channel_resolver
        self.timeout_sec = int(timeout_sec)
        self.credential_vault_path = (str(Path(credential_vault_path).resolve())
                                      if credential_vault_path else "")
        self.native_dependency_resolver = native_dependency_resolver

    def _adapter(self, employee):
        provider = str((employee.get("runtime") or {}).get("channel") or "").strip()
        if provider not in _SUPPORTED_CHANNELS:
            raise ContractError("员工发布版本使用了不支持的 Agent Channel：{}".format(
                provider or "(empty)"))
        channel = {"provider": provider, "enabled": 1, "executable": "", "config_dir": ""}
        if self.channel_resolver is not None:
            channel = self.channel_resolver(provider)
            if not channel or channel.get("provider") != provider:
                raise ContractError("员工所需 Agent Channel 不存在：{}".format(provider))
            if not channel.get("enabled"):
                raise ContractError("员工所需 Agent Channel 未启用：{}".format(provider))
        try:
            adapter = model_channels.adapter_for(channel)
        except Exception as exc:
            raise ContractError(str(exc)) from exc
        plugins, plugin_dirs, marketplaces = [], [], []
        for frozen in employee.get("capabilities") or []:
            if not frozen.get("plugin_id"):
                continue
            if frozen.get("provider") != provider:
                raise ContractError("员工发布版本包含其他模型渠道的扩展")
            if self.native_dependency_resolver is None:
                raise ContractError("当前环境不能加载员工扩展")
            try:
                try:
                    current = self.native_dependency_resolver(
                        provider, frozen.get("plugin_id"), refresh=True)
                except TypeError:
                    current = self.native_dependency_resolver(
                        provider, frozen.get("plugin_id"))
            except Exception as exc:
                raise ContractError(str(exc)) from exc
            if current.get("fingerprint") != frozen.get("fingerprint"):
                raise ContractError("扩展 {} 已发生变化，请重新验证并发布员工".format(
                    frozen.get("name") or frozen.get("plugin_id")))
            runtime = current.get("runtime") or {}
            plugins.append(current.get("plugin_id"))
            if runtime.get("plugin_dir"):
                plugin_dirs.append(runtime["plugin_dir"])
            if runtime.get("marketplace") and runtime.get("marketplace_root"):
                item = {"name": runtime["marketplace"],
                        "source": runtime["marketplace_root"]}
                if item not in marketplaces:
                    marketplaces.append(item)
        adapter.configure_requirements({
            "isolated_native": True,
            "plugins": plugins,
            "plugin_dirs": plugin_dirs,
            "codex_marketplaces": marketplaces,
        })
        return adapter

    @staticmethod
    def _mcp_arguments(provider, command, arguments, server_env):
        if provider == "claude-code":
            config = {"mcpServers": {"runteams": {
                "type": "stdio", "command": command,
                "args": list(arguments), "env": dict(server_env),
            }}}
            return ["--mcp-config", json.dumps(config, ensure_ascii=False,
                                                separators=(",", ":")),
                    "--strict-mcp-config"]
        env_map = "{" + ",".join("{}={}".format(key, json.dumps(value))
                                  for key, value in server_env.items()) + "}"
        values = {
            "mcp_servers.runteams.command": json.dumps(command),
            "mcp_servers.runteams.args": json.dumps(arguments),
            "mcp_servers.runteams.env": env_map,
            "mcp_servers.runteams.required": "true",
            "mcp_servers.runteams.enabled_tools": json.dumps(_TOOLS),
            "mcp_servers.runteams.default_tools_approval_mode": json.dumps("approve"),
            "mcp_servers.runteams.startup_timeout_sec": "60",
            "mcp_servers.runteams.tool_timeout_sec": "300",
        }
        result = []
        for key, value in values.items():
            result += ["--config", "{}={}".format(key, value)]
        return result

    def run(self, employee, work_order, emit, *, employee_run_id, database,
            cancel_event=None):
        repository = Repository(database)
        with repository.connect() as connection:
            run = connection.execute(
                "SELECT er.workflow_run_id,er.position_key,wr.snapshot_json "
                "FROM employee_runs er JOIN workflow_runs wr ON wr.id=er.workflow_run_id "
                "WHERE er.id=?", (int(employee_run_id),)).fetchone()
        if run is None:
            raise ContractError("员工运行不存在")
        snapshot = json.loads(run["snapshot_json"])
        unavailable = trial_unavailable_capability(
            snapshot, run["position_key"], employee)
        if unavailable:
            emit("validation.signal_applied", {
                "kind": "capability_unavailable",
                "capability_ref": unavailable,
            })
        # A Workflow is one task card and therefore owns one durable workspace.
        # Positions hand work over inside that workspace; separate Workflow ids
        # remain isolated from one another.
        workspace = (self.root / "workspaces" /
                     "workflow-{}".format(run["workflow_run_id"]) / "workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        trial_fixtures = (snapshot.get("trial") or {}).get("fixtures") or []
        trial_path_prepend = _trial_executable_dirs(trial_fixtures, workspace)
        if run["position_key"] == "subject":
            trial_path_prepend = _materialize_trial_fixtures(
                trial_fixtures, workspace)
        materialized_inputs = task_inputs.materialize(
            self.root, (snapshot.get("task") or {}).get("id"),
            work_order.get("inputs") or [], workspace)
        if materialized_inputs != (work_order.get("inputs") or []):
            work_order = dict(work_order, inputs=materialized_inputs)
            with repository.connect() as connection:
                connection.execute(
                    "UPDATE employee_runs SET input_json=? WHERE id=?",
                    (json.dumps(work_order, ensure_ascii=False), int(employee_run_id)))
        capabilities_root = workspace / ".runteams" / "capabilities"
        shutil.rmtree(capabilities_root, ignore_errors=True)
        capabilities_root.mkdir(parents=True, exist_ok=True)
        package_store = PackageStore(self.root / "packages")
        unavailable_package = unavailable.split("/", 1)[0] if unavailable else ""
        materialized = set()
        for frozen in employee.get("capabilities") or []:
            if frozen.get("plugin_id"):
                continue
            if frozen["package_key"] == unavailable_package:
                continue
            marker = (frozen["package_key"], frozen["digest"])
            if marker in materialized:
                continue
            package_store.materialize_frozen(
                frozen["digest"], capabilities_root / frozen["package_key"])
            materialized.add(marker)
        command = sys.executable
        if getattr(sys, "frozen", False):
            arguments = ["--runteams-core-mcp", str(Path(database).resolve()),
                         str(employee_run_id), str(workspace)]
        else:
            server = Path(__file__).resolve().parent.parent / "core_protocol_mcp.py"
            arguments = [str(server), str(Path(database).resolve()),
                         str(employee_run_id), str(workspace)]
        server_env = {"PYTHONNOUSERSITE": "1"}
        if self.credential_vault_path:
            server_env["RUNTEAMS_SECRET_VAULT"] = self.credential_vault_path
        adapter = self._adapter(employee)
        path_prepend = list(trial_path_prepend)
        for path in _managed_executable_dirs(self.root):
            if path not in path_prepend:
                path_prepend.append(path)
        for path in _host_tool_dirs():
            if path not in path_prepend:
                path_prepend.append(path)
        for path in _channel_executable_dirs(adapter):
            if path not in path_prepend:
                path_prepend.append(path)
        if path_prepend:
            adapter.requirements["path_prepend"] = path_prepend
        extra_args = self._mcp_arguments(adapter.name, command, arguments, server_env)
        prompt = SYSTEM_INSTRUCTION
        employee_identity = employee.get("id") or employee.get("employee_id")
        # Keep one immutable transcript per employee run.  A workflow workspace
        # is shared across retries/positions, so a fixed filename would destroy
        # the evidence from an earlier attempt.
        transcript_name = "agent-transcript-{}.jsonl".format(int(employee_run_id))
        transcript_path = workspace / ".runteams" / transcript_name

        class Activity:
            def on_event(self, item):
                emit("agent.event", item)

        try:
            agent_result = run_agent(adapter, prompt, execution_profile=EXECUTION_PIPELINE_AGENT,
                      mode="build", model=(employee.get("runtime") or {}).get("model") or "",
                      reasoning_effort=(employee.get("runtime") or {}).get("effort") or None,
                      timeout_sec=self.timeout_sec, extra_args=extra_args, on_activity=Activity(),
                      cwd=str(workspace), cancel_event=cancel_event,
                      transcript_path=str(transcript_path), require_final_text=False)
            try:
                transcript_bytes = transcript_path.read_bytes()
            except OSError:
                transcript_bytes = b""
            # Test doubles and alternate channels may not return AgentResult.  The
            # execution envelope must still be written with the fields we can
            # verify locally; provider metadata is explicitly best-effort.
            raw_meta = getattr(agent_result, "meta", {}) if agent_result is not None else {}
            raw_meta = raw_meta if isinstance(raw_meta, dict) else {}
            meta = {key: raw_meta.get(key) for key in (
                "cost_usd", "input_tokens", "cached_input_tokens",
                "output_tokens", "model", "request_id", "provider_request_id")
                    if raw_meta.get(key) is not None}
            meta.update({
                "employee_run_id": int(employee_run_id),
                "workflow_run_id": int(run["workflow_run_id"]),
                "employee_id": (int(employee_identity)
                                if employee_identity is not None else None),
                "position_key": run["position_key"],
                "transcript_ref": ".runteams/{}".format(transcript_name),
                "transcript_sha256": hashlib.sha256(transcript_bytes).hexdigest(),
                "transcript_bytes": len(transcript_bytes),
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "execution_profile": EXECUTION_PIPELINE_AGENT,
            })
            emit("agent.runtime_finished", meta)
        except Exception as exc:
            # Preserve a verifiable envelope even when the provider times out,
            # exits non-zero, or is cancelled before returning AgentResult.
            # Only the exception class is recorded; messages can contain prompt
            # or provider data and are already surfaced by the workflow error.
            try:
                transcript_bytes = transcript_path.read_bytes()
            except OSError:
                transcript_bytes = b""
            try:
                emit("agent.runtime_failed", {
                    "status": "failed",
                    "employee_run_id": int(employee_run_id),
                    "workflow_run_id": int(run["workflow_run_id"]),
                    "employee_id": (int(employee_identity)
                                    if employee_identity is not None else None),
                    "position_key": run["position_key"],
                    "error_type": exc.__class__.__name__,
                    "transcript_ref": ".runteams/{}".format(transcript_name),
                    "transcript_sha256": hashlib.sha256(transcript_bytes).hexdigest(),
                    "transcript_bytes": len(transcript_bytes),
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "execution_profile": EXECUTION_PIPELINE_AGENT,
                })
            except Exception:
                pass
            protocol = EmployeeProtocol(database, employee_run_id, workspace)
            committed, _employee = protocol.context()
            if committed["state"] in ("completed", "blocked", "needs_human", "failed"):
                return json.loads(committed["output_json"])
            raise
        protocol = EmployeeProtocol(database, employee_run_id, workspace)
        run, _employee = protocol.context()
        if run["state"] not in ("completed", "blocked", "needs_human", "failed"):
            raise ContractError("Agent 未通过 RunTeams 协议提交终态")
        return json.loads(run["output_json"])
