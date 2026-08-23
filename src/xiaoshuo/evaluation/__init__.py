"""P1-AE evaluation bounded context.

O1 exposes only rejection-only contract types.  Runtime producer integration is
intentionally absent until a separately authorized phase.
"""

from .contracts.owner import ContractResult, OwnerResult

__all__ = ["ContractResult", "OwnerResult"]
