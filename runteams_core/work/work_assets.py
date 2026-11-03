"""Canonical asset preflight and mounts shared by both employee hosts."""
import os,shutil
from pathlib import Path
from runteams_core.assets import local_assets
from runteams_core.foundation.contracts import ContractError, normalize_work_result
class WorkAssets:
    def __init__(self,root,asset_grant_resolver):
        self.root=Path(root);self.asset_grant_resolver=asset_grant_resolver

    @staticmethod
    def _asset_blocked_result(reason):
        return normalize_work_result({
            "status": "needs_human", "summary": "",
            "output": {"question": "员工运行前需要处理本地资产授权：{}".format(reason),
                       "context": reason, "asset_preflight": True},
            "issues": [reason], "artifacts": [],
        })


    def _mount_assets(self, employee, snapshot, workspace, emit):
        """Preflight, mount and fingerprint every asset slot this skill needs.

        Returns ``(None, [], {})`` when the skill has no slots, ``("blocked",
        result, None)`` when a run cannot proceed (the caller must return this
        result without invoking the agent at all), or ``(None, records,
        grants_by_name)`` once every slot is safely mounted — ``records`` is
        the path-free description injected into the work order and
        ``grants_by_name`` carries what a later divergence check needs.
        """
        payload = (snapshot.get("task") or {}).get("payload") or {}
        slots = list(employee["selected_work"]["work"]["assets"])
        bindings = dict(payload.get("asset_bindings") or {})
        for entry in payload.get("inputs") or []:
            if "asset_grant_id" not in entry:
                continue
            name = entry.get("name", "")
            if not name or "/" in name or "\\" in name or name in (".", ".."):
                return True, self._asset_blocked_result("本地资料名称无效"), None
            if any(slot["name"] == name for slot in slots):
                return True, self._asset_blocked_result("本地资料输入名称重复"), None
            slots.append({"name": name, "required": True})
            bindings[name] = entry["asset_grant_id"]
        if not slots:
            return False, [], {}
        assets_root = workspace / ".runteams" / "assets"
        shutil.rmtree(assets_root, ignore_errors=True)
        records, grants_by_name = [], {}
        for slot in slots:
            name = slot["name"]
            grant_id = bindings.get(name)
            grant = None
            if grant_id not in (None, ""):
                if self.asset_grant_resolver is None:
                    return True, self._asset_blocked_result(
                        "当前环境未配置本地资产授权"), None
                try:
                    from runteams_core.storage.business_storage import bound_storage, storage_for
                    from runteams_core.work.device_work import DeviceWorkStorage, recognizes
                    storage=bound_storage(self.root/'runteams.db')
                    if storage is None and recognizes(self.root/'runteams.db'):
                        storage=storage_for(self.root/'runteams.db')
                    if str(grant_id).startswith('local-host://'):
                        storage=storage or storage_for(self.root/'runteams.db')
                        host,identifier=str(grant_id).removeprefix('local-host://').split('/',1)
                        if isinstance(storage, DeviceWorkStorage):
                            from runteams_core.storage import local_database
                            from runteams_core.work.hosts.execution_host import identity
                            actual=identity(Path(local_database.DB_PATH).parent)['host_id']
                        else:
                            actual=storage.cloud.host_identity['host_id']
                        if host!=actual:raise ContractError('此资料由另一台设备授权，请在当前设备重新选择资料')
                        local_id=int(identifier)
                    elif storage is not None and not hasattr(storage,'cloud'):
                        local_id=int(grant_id)
                    else:
                        raise ContractError('本地资料缺少设备授权，请重新选择资料')
                    if local_id < 1:
                        raise ContractError('本地资产授权标识无效')
                    grant = self.asset_grant_resolver(local_id)
                except Exception as exc:
                    return True, self._asset_blocked_result(str(exc)[:300]), None
            if grant is None:
                if slot.get("required", True):
                    return True, self._asset_blocked_result(
                        "「{}」还没有绑定本地资产授权，请到设置 → 本地资产 里选择或新建".format(name)
                    ), None
                continue
            ok, reason = local_assets.preflight(grant, name)
            if not ok:
                return True, self._asset_blocked_result(
                    "{}，请到设置 → 本地资产 里处理".format(reason)), None
            destination = assets_root / name
            destination.mkdir(parents=True, exist_ok=True)
            try:
                record, before = local_assets.mount(grant, destination)
            except local_assets.AssetError as exc:
                shutil.rmtree(assets_root, ignore_errors=True)
                return True, self._asset_blocked_result(str(exc)), None
            record = dict(record, name=name, repository_key="asset-{}".format(local_id),
                         path=str(destination.relative_to(workspace)).replace(os.sep, "/"))
            records.append(record)
            grants_by_name[name] = {"grant": grant, "before": before}
            emit("asset.mounted", {
                "name": name, "grant_id": local_id, "mode": record["mode"],
                "path": record['path'], "repository_key": record['repository_key'],
                "commit": record.get("commit", ""), "digest": record.get("digest", ""),
                "bytes": record.get("bytes", 0), "files": record.get("files", 0),
                "working_tree": record.get("working_tree", {}),
                "excluded": record.get("excluded", [])})
        return False, records, grants_by_name

