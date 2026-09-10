"""Unified formal attention read model.

Core workflow attention is derived from durable workflow state. Scheduled
automations remain formal assets and derive attention from their latest failed
run. Legacy card interventions are intentionally excluded from the product.
"""

import automation_store as automations
import product_store as store
from runteams_core import RunTeamsCore


def catalog(core=None, limit=100):
    limit = max(1, min(500, int(limit)))
    core = core or RunTeamsCore(store.core_data_root())
    items = list(core.attention_catalog(limit))
    items.extend(automations.automation_attention_catalog(limit))
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return items[:limit]
