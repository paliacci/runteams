"""Provider-neutral contracts; work services use their explicit composition modules."""
from .contracts import ContractError, DocumentLossError

__all__ = ["ContractError", "DocumentLossError"]
