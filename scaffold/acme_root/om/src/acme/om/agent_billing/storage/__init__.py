"""Storage of the agent billing swimlane. Every operation takes org_id first.

Two interfaces, one per role. The spend account is the system of record, in
`core`, written with its outbox rows. The ledger is in `activity`: one table
of entries, each written once, and a count per counter and period, which an
entry moves under its lock in the transaction that writes it. A hold
carries the spend account as the gate read it, so the ledger never reads `core`."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.agent_billing.types.spend_account import SpendAccount
from acme.om.agent_billing.types.spend_ledger import (
    Approval,
    Charge,
    Count,
    Credit,
    Entry,
    EntryKind,
    FundedHold,
    Grant,
    Turned,
    WindowRaise,
)
from acme.om.context import tenantless
from acme.om.outbox.types.row import OutboxRow
from acme.om.spend_budgets.types.spend_hold import SpendHold, SpendSettlement


class SpendAccountStorageInterface(ABC):
    @abstractmethod
    async def create_spend_account(
        self, org_id: UUID, spend_account: SpendAccount, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the tenant's spend account is written already."""
        ...

    @abstractmethod
    async def read_spend_account(self, org_id: UUID) -> SpendAccount | None:
        """The tenant's spend account. A stored one this process cannot read, such
        as a funding mode it does not know, is `ValidationFailed`: never
        read as another."""
        ...

    @abstractmethod
    async def write_spend_account(
        self,
        org_id: UUID,
        spend_account: SpendAccount,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """The compare-and-set: lands the spend account and its outbox rows
        together when the stored one is at `expected_version`, and raises
        `PreconditionFailed` otherwise, landing nothing."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID) -> int:
        """The sweep, for a deleted tenant: deletes its spend account, and answers
        how many rows went, 1 or 0."""
        ...


class SpendLedgerStorageInterface(ABC):
    @abstractmethod
    async def open_spend_hold(self, org_id: UUID, hold: FundedHold) -> FundedHold | Turned:
        """The gate's one write, in one transaction: the counts of every
        counter the hold moves (its lines' windows, its buckets) are made
        where missing and locked in one order; the hold is checked against
        its lines with their window's raise and drawn on its buckets in the
        fixed order (`agent_billing.rules.open_answer`). When it fits, it is
        written as drawn, its reserve joins every count, and it is answered.
        Otherwise nothing is written, and every reason is answered. A hold
        opened already answers as stored; an id another tenant holds is
        `TenantMismatch`."""
        ...

    @abstractmethod
    async def read_hold(self, org_id: UUID, spend_hold_id: UUID) -> FundedHold | None: ...

    @abstractmethod
    async def close_spend_hold(
        self, org_id: UUID, settlement: SpendSettlement, charge: Charge
    ) -> tuple[SpendSettlement, Charge]:
        """The settlement of the hold it names and its charge, in one
        transaction with the counts of the hold, locked in the same order:
        the reserve leaves what is held, and what was spent joins. A hold
        closes once: one closed already answers its first settlement and
        charge, and nothing moves. A hold the tenant does not hold is
        `NotFound`, and nothing moves."""
        ...

    @abstractmethod
    @tenantless
    async def read_open(
        self, after: datetime, before: datetime, limit: int
    ) -> list[tuple[UUID, SpendHold, datetime]]:
        """Cross-tenant, for the sweep, in the system scope: at most `limit`
        holds due at or after `after` and before `before` that no
        settlement has closed, whatever their tenant, each with its tenant
        and the time it fell due, the earliest due first. A model call's
        hold falls due at its opening, and a job's at its deadline, which it
        lives to."""
        ...

    @abstractmethod
    async def post_credit(self, org_id: UUID, credit: Credit) -> Credit:
        """The credit and the sum it adds to the credits' count, in one
        transaction. A payment reference credits once: one posted already
        answers the first credit, and nothing moves."""
        ...

    @abstractmethod
    async def post_grant(self, org_id: UUID, grant: Grant) -> Grant:
        """The grant and the units it adds to the granted count, in one
        transaction; an id posted already answers as stored."""
        ...

    @abstractmethod
    async def post_raise(self, org_id: UUID, raised: WindowRaise) -> WindowRaise:
        """The raise and what it adds to its budget's counts in its window,
        and no other, in one transaction; an id posted already answers as
        stored."""
        ...

    @abstractmethod
    async def post_approval(self, org_id: UUID, approval: Approval) -> Approval:
        """The approval, written once; an id posted already answers as
        stored."""
        ...

    @abstractmethod
    async def read_entries(
        self,
        org_id: UUID,
        *,
        kind: EntryKind | None = None,
        spend_hold_id: UUID | None = None,
        agent_session_id: UUID | None = None,
        limit: int,
    ) -> list[Entry]:
        """The tenant's entries, newest first, at most `limit`: of one kind,
        of one hold (its hold, settlement, and charge), or of one session's
        holds and approvals, as asked."""
        ...

    @abstractmethod
    async def read_counts(
        self, org_id: UUID, keys: Sequence[tuple[str, datetime]]
    ) -> dict[tuple[str, datetime], Count]:
        """The counts of the keys asked for that exist."""
        ...

    @abstractmethod
    async def count_tenant(self, org_id: UUID, limit: int) -> int:
        """How many entries and counts the tenant keeps, counted up to
        `limit` and no further. A deleted tenant's ledger stays, since no
        serving login deletes it, and the sweep marks the tenant purged
        without reading it."""
        ...
