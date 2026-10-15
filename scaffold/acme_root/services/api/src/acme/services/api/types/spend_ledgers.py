"""Wire types of a tenant's ledger, as an operator reads it: one entry of
whichever kind, its common fields first and each kind's own beside them,
and one read of them; and units an operator grants the tenant."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_billing.types.spend_ledger import EntryKind
from acme.om.agent_billing.types.unit_plan import MAX_NAME
from acme.services.api.types.agent_billing import MOST
from acme.services.api.types.common import RequestBody, View


class SpendLedgerEntryView(View):
    """One entry, written once. A field a kind does not carry is null:

    - `hold`: `agent_session_id`, `units` (the worst case, null when no price
      applies), and `cost_micros` (the exposure).
    - `settlement`: `spend_hold_id`, `cost_micros` and `tokens` (what it spent).
    - `charge`: `spend_hold_id`, `units`, and `amount_micros` (what the money
      buckets paid).
    - `credit`: `amount_micros` and `reference` (the payment's).
    - `grant`: `units`, `reason`, and `by` (the operator).
    - `raise`: `spend_budget_id`, `cost_micros`, `tokens`, and `by`.
    - `approval`: `agent_session_id`, `amount_micros` (the cost it allows), and
      `by`."""

    kind: EntryKind
    id: UUID
    created_at: datetime
    agent_session_id: UUID | None = None
    spend_hold_id: UUID | None = None
    spend_budget_id: UUID | None = None
    units: int | None = None
    amount_micros: int | None = None
    cost_micros: int | None = None
    tokens: int | None = None
    reference: str | None = None
    reason: str | None = None
    by: UUID | None = None


class SpendLedgerPageView(View):
    """One read of a tenant's ledger, the newest first. `has_more` says the
    read was cut at its limit and older entries match it too: narrow it by
    kind, hold, or session to reach them."""

    items: list[SpendLedgerEntryView]
    has_more: bool


class SpendUnitsGrantRequest(RequestBody):
    """Units the platform grants the tenant for its life, and why."""

    units: int = Field(gt=0, le=MOST)
    reason: str = Field(min_length=1, max_length=MAX_NAME)
