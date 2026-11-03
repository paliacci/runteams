"""Repository-bound service identity shared by work and document views."""


class RepositoryService:
    def _actor(self):
        context = self.repository.current_audit_context()
        actor = context.get("actor_id")
        cloud = getattr(self.repository.storage,'cloud',None)
        if cloud is not None:
            trusted = cloud.identity()
            if actor and str(actor)!=trusted:
                raise PermissionError('账户已变化，请重新打开。')
            return trusted
        if not actor and context.get("source") == "http":
            raise PermissionError("请先登录")
        return str(actor or "local-user")
