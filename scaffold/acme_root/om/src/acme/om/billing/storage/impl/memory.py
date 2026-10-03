"""The in-memory account and ledger. Every write reads and writes under one
lock with no await in between, which is its whole answer to two holds at
once."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from acme.om.billing.rules import (
    CountKey,
    closed,
    hold_keys,
    lifetime_key,
    moved,
    open_answer,
    opened,
    raise_keys,
)
from acme.om.billing.storage import AccountStorageInterface, Entry, MoneyLedgerStorageInterface
from acme.om.billing.types.account import Account
from acme.om.billing.types.ledger import (
    Approval,
    Bucket,
    Charge,
    Count,
    Credit,
    EntryKind,
    FundedHold,
    Grant,
    Turned,
    WindowRaise,
)
from acme.om.budgets.types.hold import Hold, Settlement
from acme.om.exceptions import NotFound, PreconditionFailed, TenantMismatch
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class AccountStorageMemoryImpl(MemoryStorageBase, AccountStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface) -> None:
        super().__init__(outbox)
        self._accounts: MemoryTable[Account] = {}

    async def create_account(
        self, org_id: UUID, account: Account, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if account.id != org_id:
                raise TenantMismatch(f"account {account.id} is not {org_id}'s")
            return self._insert(self._accounts, org_id, account, outbox_rows)

    async def read_account(self, org_id: UUID) -> Account | None:
        return self._get(self._accounts, org_id, org_id)

    async def write_account(
        self,
        org_id: UUID,
        account: Account,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            found = self._get(self._accounts, org_id, account.id)
            if found is None or found.version != expected_version:
                raise PreconditionFailed(
                    f"account {account.id} is no longer at version {expected_version}"
                )
            self._put(self._accounts, org_id, account, outbox_rows)


class _Row:
    """One entry as the ledger table keeps it."""

    def __init__(
        self,
        org_id: UUID,
        kind: EntryKind,
        entry: Entry,
        *,
        hold_id: UUID | None = None,
        session_id: UUID | None = None,
        reference: str | None = None,
    ) -> None:
        self.org_id = org_id
        self.kind = kind
        self.entry = entry
        self.hold_id = hold_id
        self.session_id = session_id
        self.reference = reference


class MoneyLedgerStorageMemoryImpl(MemoryStorageBase, MoneyLedgerStorageInterface):
    def __init__(self) -> None:
        super().__init__()
        self._entries: list[_Row] = []  # in the order they were written
        self._counts: dict[tuple[UUID, str, datetime], Count] = {}

    async def open_hold(self, org_id: UUID, hold: FundedHold) -> FundedHold | Turned:
        async with self._lock:
            found = self._row_by_id(hold.id)
            if found is not None:
                if found.org_id != org_id:
                    raise TenantMismatch(f"hold {hold.id} is not in {org_id}")
                assert isinstance(found.entry, FundedHold)
                return found.entry
            counts = self._counts_of(org_id, hold_keys(hold))
            stored, turned = open_answer(hold, counts)
            if turned is not None:
                return turned
            for key, (held, spent) in opened(stored).items():
                self._move(org_id, key, held, spent)
            self._entries.append(
                _Row(
                    org_id, EntryKind.HOLD, stored, hold_id=stored.id, session_id=stored.session_id
                )
            )
            return stored

    async def read_hold(self, org_id: UUID, hold_id: UUID) -> FundedHold | None:
        found = self._row_by_id(hold_id)
        if found is None or found.org_id != org_id or not isinstance(found.entry, FundedHold):
            return None
        return found.entry

    async def close_hold(
        self, org_id: UUID, settlement: Settlement, charge: Charge
    ) -> tuple[Settlement, Charge]:
        async with self._lock:
            hold = await self.read_hold(org_id, settlement.hold_id)
            if hold is None:
                raise NotFound(f"hold {settlement.hold_id} not found")
            first = self._of_hold(org_id, EntryKind.SETTLEMENT, hold.id)
            if first is not None:
                stored_charge = self._of_hold(org_id, EntryKind.CHARGE, hold.id)
                assert isinstance(first.entry, Settlement)
                assert stored_charge is not None and isinstance(stored_charge.entry, Charge)
                return first.entry, stored_charge.entry
            for key, (held, spent) in closed(hold, settlement, charge).items():
                self._move(org_id, key, held, spent)
            self._entries.append(_Row(org_id, EntryKind.SETTLEMENT, settlement, hold_id=hold.id))
            self._entries.append(_Row(org_id, EntryKind.CHARGE, charge, hold_id=hold.id))
            return settlement, charge

    async def post_credit(self, org_id: UUID, credit: Credit) -> Credit:
        async with self._lock:
            for row in self._entries:
                if (row.org_id, row.kind, row.reference) == (
                    org_id,
                    EntryKind.CREDIT,
                    credit.reference,
                ):
                    assert isinstance(row.entry, Credit)
                    return row.entry
            self._add(org_id, lifetime_key(Bucket.CREDITS), credit.amount_micros)
            self._entries.append(_Row(org_id, EntryKind.CREDIT, credit, reference=credit.reference))
            return credit

    async def post_grant(self, org_id: UUID, grant: Grant) -> Grant:
        async with self._lock:
            found = self._row_by_id(grant.id)
            if found is not None:
                if found.org_id != org_id:
                    raise TenantMismatch(f"grant {grant.id} is not in {org_id}")
                assert isinstance(found.entry, Grant)
                return found.entry
            self._add(org_id, lifetime_key(Bucket.GRANTED), grant.units)
            self._entries.append(_Row(org_id, EntryKind.GRANT, grant))
            return grant

    async def post_raise(self, org_id: UUID, raised: WindowRaise) -> WindowRaise:
        async with self._lock:
            found = self._row_by_id(raised.id)
            if found is not None:
                if found.org_id != org_id:
                    raise TenantMismatch(f"raise {raised.id} is not in {org_id}")
                assert isinstance(found.entry, WindowRaise)
                return found.entry
            cost_key, tokens_key = raise_keys(raised.budget_id, raised.window_start)
            self._add(org_id, cost_key, raised.cost_micros)
            self._add(org_id, tokens_key, raised.tokens)
            self._entries.append(_Row(org_id, EntryKind.RAISE, raised))
            return raised

    async def post_approval(self, org_id: UUID, approval: Approval) -> Approval:
        async with self._lock:
            found = self._row_by_id(approval.id)
            if found is not None:
                if found.org_id != org_id:
                    raise TenantMismatch(f"approval {approval.id} is not in {org_id}")
                assert isinstance(found.entry, Approval)
                return found.entry
            self._entries.append(
                _Row(org_id, EntryKind.APPROVAL, approval, session_id=approval.session_id)
            )
            return approval

    async def read_open(
        self, after: datetime, before: datetime, limit: int
    ) -> list[tuple[UUID, Hold]]:
        closed = {
            (row.org_id, row.hold_id) for row in self._entries if row.kind is EntryKind.SETTLEMENT
        }
        found = sorted(
            (
                (row.org_id, row.entry.hold)
                for row in self._entries
                if row.kind is EntryKind.HOLD
                and isinstance(row.entry, FundedHold)
                and after <= row.entry.hold.created_at < before
                and (row.org_id, row.hold_id) not in closed
            ),
            key=lambda pair: (pair[1].created_at, pair[1].id),
        )
        return found[:limit]

    async def read_entries(
        self,
        org_id: UUID,
        *,
        kind: EntryKind | None = None,
        hold_id: UUID | None = None,
        session_id: UUID | None = None,
        limit: int,
    ) -> list[Entry]:
        rows = [
            row
            for row in reversed(self._entries)
            if row.org_id == org_id
            and (kind is None or row.kind is kind)
            and (hold_id is None or row.hold_id == hold_id)
            and (session_id is None or row.session_id == session_id)
        ]
        return [row.entry for row in rows[:limit]]

    async def read_counts(
        self, org_id: UUID, keys: Sequence[tuple[str, datetime]]
    ) -> dict[tuple[str, datetime], Count]:
        found = {key: self._counts.get((org_id, *key)) for key in keys}
        return {key: count for key, count in found.items() if count is not None}

    def _row_by_id(self, entry_id: UUID) -> _Row | None:
        for row in self._entries:
            if row.entry.id == entry_id:
                return row
        return None

    def _of_hold(self, org_id: UUID, kind: EntryKind, hold_id: UUID) -> _Row | None:
        for row in self._entries:
            if (row.org_id, row.kind, row.hold_id) == (org_id, kind, hold_id):
                return row
        return None

    def _counts_of(self, org_id: UUID, keys: Sequence[CountKey]) -> dict[CountKey, Count]:
        return {
            key: self._counts.get((org_id, *key), Count(counter=key[0], start=key[1]))
            for key in keys
        }

    def _move(self, org_id: UUID, key: CountKey, held: int, spent: int) -> None:
        count = self._counts.get((org_id, *key), Count(counter=key[0], start=key[1]))
        self._counts[(org_id, *key)] = moved(count, held, spent)

    def _add(self, org_id: UUID, key: CountKey, added: int) -> None:
        count = self._counts.get((org_id, *key), Count(counter=key[0], start=key[1]))
        self._counts[(org_id, *key)] = count.model_copy(update={"added": count.added + added})
