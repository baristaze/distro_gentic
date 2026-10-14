from uuid import UUID

from acme.om.agent_billing import AgentBillingManagerInterface
from acme.om.agent_billing.types.spend_ledger import (
    Approval,
    Charge,
    Credit,
    Entry,
    EntryKind,
    FundedHold,
    Grant,
    WindowRaise,
)
from acme.om.budgets.types.hold import Settlement
from acme.om.context import OperatorContext
from acme.services.api.services.spend_ledgers import SpendLedgersServiceInterface
from acme.services.api.types.spend_ledgers import (
    SpendLedgerEntryView,
    SpendLedgerPageView,
    SpendUnitsGrantRequest,
)


def entry_view(entry: Entry) -> SpendLedgerEntryView:
    """One entry on the wire: its kind, its id and time, and its own fields."""
    match entry:
        case FundedHold():
            return SpendLedgerEntryView(
                kind=EntryKind.HOLD,
                id=entry.id,
                created_at=entry.created_at,
                session_id=entry.session_id,
                units=entry.units,
                cost_micros=entry.hold.exposure.cost_micros,
            )
        case Settlement():
            return SpendLedgerEntryView(
                kind=EntryKind.SETTLEMENT,
                id=entry.id,
                created_at=entry.created_at,
                hold_id=entry.hold_id,
                cost_micros=entry.spent.cost_micros,
                tokens=entry.spent.tokens,
            )
        case Charge():
            return SpendLedgerEntryView(
                kind=EntryKind.CHARGE,
                id=entry.id,
                created_at=entry.created_at,
                hold_id=entry.hold_id,
                units=entry.units,
                amount_micros=entry.amount_micros,
            )
        case Credit():
            return SpendLedgerEntryView(
                kind=EntryKind.CREDIT,
                id=entry.id,
                created_at=entry.created_at,
                amount_micros=entry.amount_micros,
                reference=entry.reference,
            )
        case Grant():
            return SpendLedgerEntryView(
                kind=EntryKind.GRANT,
                id=entry.id,
                created_at=entry.created_at,
                units=entry.units,
                reason=entry.reason,
                by=entry.granted_by,
            )
        case WindowRaise():
            return SpendLedgerEntryView(
                kind=EntryKind.RAISE,
                id=entry.id,
                created_at=entry.created_at,
                budget_id=entry.budget_id,
                cost_micros=entry.cost_micros,
                tokens=entry.tokens,
                by=entry.raised_by,
            )
        case Approval():
            return SpendLedgerEntryView(
                kind=EntryKind.APPROVAL,
                id=entry.id,
                created_at=entry.created_at,
                session_id=entry.session_id,
                amount_micros=entry.up_to_micros,
                by=entry.approved_by,
            )


class SpendLedgersServiceImpl(SpendLedgersServiceInterface):
    def __init__(self, agent_billing: AgentBillingManagerInterface) -> None:
        self._agent_billing = agent_billing

    async def get_entries(
        self,
        admin: OperatorContext,
        org_id: UUID,
        *,
        kind: EntryKind | None,
        hold_id: UUID | None,
        session_id: UUID | None,
        limit: int,
    ) -> SpendLedgerPageView:
        page = await self._agent_billing.get_entries(
            admin, org_id, kind=kind, hold_id=hold_id, session_id=session_id, limit=limit
        )
        return SpendLedgerPageView(
            items=[entry_view(entry) for entry in page.items], has_more=page.has_more
        )

    async def grant_units(
        self, admin: OperatorContext, org_id: UUID, body: SpendUnitsGrantRequest, grant_id: UUID
    ) -> SpendLedgerEntryView:
        grant = await self._agent_billing.grant_units(
            admin, org_id, body.units, body.reason, grant_id=grant_id
        )
        return entry_view(grant)
