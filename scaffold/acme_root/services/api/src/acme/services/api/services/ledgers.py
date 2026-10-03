"""The ledgers service: an operator reads a tenant's ledger, naming the
tenant."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.billing.types.ledger import EntryKind
from acme.om.context import OperatorContext
from acme.services.api.types.ledgers import LedgerEntryView


class LedgersServiceInterface(ABC):
    @abstractmethod
    async def get_entries(
        self, admin: OperatorContext, org_id: UUID, kind: EntryKind | None, limit: int
    ) -> list[LedgerEntryView]:
        """The tenant's entries, the newest first, of one kind when named."""
        ...
