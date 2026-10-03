from uuid import UUID

from acme.om.billing import BillingManagerInterface
from acme.om.billing.types.ledger import (
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
from acme.services.api.services.ledgers import LedgersServiceInterface
from acme.services.api.types.ledgers import LedgerEntryView


def entry_view(entry: Entry) -> LedgerEntryView:
    """One entry on the wire: its kind, its id and time, and its own fields."""
    match entry:
        case FundedHold():
            return LedgerEntryView(
                kind=EntryKind.HOLD,
                id=entry.id,
                created_at=entry.created_at,
                session_id=entry.session_id,
                units=entry.units,
                cost_micros=entry.hold.exposure.cost_micros,
            )
        case Settlement():
            return LedgerEntryView(
                kind=EntryKind.SETTLEMENT,
                id=entry.id,
                created_at=entry.created_at,
                hold_id=entry.hold_id,
                cost_micros=entry.spent.cost_micros,
                tokens=entry.spent.tokens,
            )
        case Charge():
            return LedgerEntryView(
                kind=EntryKind.CHARGE,
                id=entry.id,
                created_at=entry.created_at,
                hold_id=entry.hold_id,
                units=entry.units,
                amount_micros=entry.amount_micros,
            )
        case Credit():
            return LedgerEntryView(
                kind=EntryKind.CREDIT,
                id=entry.id,
                created_at=entry.created_at,
                amount_micros=entry.amount_micros,
                reference=entry.reference,
            )
        case Grant():
            return LedgerEntryView(
                kind=EntryKind.GRANT,
                id=entry.id,
                created_at=entry.created_at,
                units=entry.units,
                reason=entry.reason,
                by=entry.granted_by,
            )
        case WindowRaise():
            return LedgerEntryView(
                kind=EntryKind.RAISE,
                id=entry.id,
                created_at=entry.created_at,
                budget_id=entry.budget_id,
                cost_micros=entry.cost_micros,
                tokens=entry.tokens,
                by=entry.raised_by,
            )
        case Approval():
            return LedgerEntryView(
                kind=EntryKind.APPROVAL,
                id=entry.id,
                created_at=entry.created_at,
                session_id=entry.session_id,
                amount_micros=entry.up_to_micros,
                by=entry.approved_by,
            )


class LedgersServiceImpl(LedgersServiceInterface):
    def __init__(self, billing: BillingManagerInterface) -> None:
        self._billing = billing

    async def get_entries(
        self, admin: OperatorContext, org_id: UUID, kind: EntryKind | None, limit: int
    ) -> list[LedgerEntryView]:
        entries = await self._billing.get_entries(admin, org_id, kind, limit)
        return [entry_view(entry) for entry in entries]
