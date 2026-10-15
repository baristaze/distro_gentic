"""The ledgers service: an operator reads a tenant's ledger, and grants
it units, naming the tenant."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_billing.types.spend_ledger import EntryKind
from acme.om.context import OperatorContext
from acme.services.api.types.agent_billing import (
    SpendLedgerEntryView,
    SpendLedgerPageView,
    SpendUnitsGrantRequest,
)


class SpendLedgersServiceInterface(ABC):
    @abstractmethod
    async def get_entries(
        self,
        admin: OperatorContext,
        org_id: UUID,
        *,
        kind: EntryKind | None,
        spend_hold_id: UUID | None,
        agent_session_id: UUID | None,
        limit: int,
    ) -> SpendLedgerPageView:
        """The tenant's entries, the newest first, of one kind, one hold, or
        one session when named, and whether the read was cut at its
        limit."""
        ...

    @abstractmethod
    async def grant_units(
        self, admin: OperatorContext, org_id: UUID, body: SpendUnitsGrantRequest, grant_id: UUID
    ) -> SpendLedgerEntryView:
        """The units granted the tenant for its life, under `grant_id` once;
        the sessions parked on its funds wake. An org that is gone is
        `NotFound`."""
        ...
