"""The ledgers service: an operator reads a tenant's ledger, and grants
it units, naming the tenant."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.billing.types.ledger import EntryKind
from acme.om.context import OperatorContext
from acme.services.api.types.ledgers import LedgerEntryView, LedgerPageView, UnitsGrantRequest


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

    @abstractmethod
    async def grant_units(
        self, admin: OperatorContext, org_id: UUID, body: UnitsGrantRequest, grant_id: UUID
    ) -> LedgerEntryView:
        """The units granted the tenant for its life, under `grant_id` once;
        the sessions parked on its funds wake. An org that is gone is
        `NotFound`."""
        ...
