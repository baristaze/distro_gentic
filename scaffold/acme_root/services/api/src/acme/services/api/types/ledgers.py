"""Wire types of a tenant's ledger, as an operator reads it: one entry of
whichever kind, its common fields first and each kind's own beside them."""

from datetime import datetime
from uuid import UUID

from acme.om.billing.types.ledger import EntryKind
from acme.services.api.types.common import View


class LedgerEntryView(View):
    """One entry, written once. A field a kind does not carry is null:

    - `hold`: `session_id`, `units` (the worst case, null when no price
      applies), and `cost_micros` (the exposure).
    - `settlement`: `hold_id`, `cost_micros` and `tokens` (what it spent).
    - `charge`: `hold_id`, `units`, and `amount_micros` (what the money
      buckets paid).
    - `credit`: `amount_micros` and `reference` (the payment's).
    - `grant`: `units`, `reason`, and `by` (the operator).
    - `raise`: `budget_id`, `cost_micros`, `tokens`, and `by`.
    - `approval`: `session_id`, `amount_micros` (the cost it allows), and
      `by`."""

    kind: EntryKind
    id: UUID
    created_at: datetime
    session_id: UUID | None = None
    hold_id: UUID | None = None
    budget_id: UUID | None = None
    units: int | None = None
    amount_micros: int | None = None
    cost_micros: int | None = None
    tokens: int | None = None
    reference: str | None = None
    reason: str | None = None
    by: UUID | None = None
