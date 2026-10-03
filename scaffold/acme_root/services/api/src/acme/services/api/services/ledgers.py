"""The ledgers service: an operator reads a tenant's ledger, naming the
tenant."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.billing.types.ledger import EntryKind
from acme.om.context import OperatorContext
from acme.services.api.types.ledgers import LedgerPageView


class LedgersServiceInterface(ABC):
    @abstractmethod
    async def get_entries(
        self,
        admin: OperatorContext,
        org_id: UUID,
        *,
        kind: EntryKind | None,
        hold_id: UUID | None,
        session_id: UUID | None,
        limit: int,
    ) -> LedgerPageView:
        """The tenant's entries, the newest first, of one kind, one hold, or
        one session when named, and whether the read was cut at its
        limit."""
        ...
