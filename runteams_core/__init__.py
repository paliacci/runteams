"""RunTeams' small, provider-neutral product kernel.

The package intentionally contains no model loop.  It owns durable employees,
capability packages, immutable releases, workflow snapshots and handoffs; a
complete Agent Runtime is injected at the execution boundary.
"""

from .contracts import ContractError, DocumentLossError
from .service import RunTeamsCore

__all__ = ["ContractError", "DocumentLossError", "RunTeamsCore"]
