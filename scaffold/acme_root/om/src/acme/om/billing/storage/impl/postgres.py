from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Update, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from acme.om.base import EMPTY_UUID
from acme.om.billing.rules import (
    CountKey,
    closed,
    hold_keys,
    lifetime_key,
    open_answer,
    opened,
    raise_keys,
)
from acme.om.billing.storage import AccountStorageInterface, Entry, MoneyLedgerStorageInterface
from acme.om.billing.storage.tables.billing_accounts import BillingAccounts
from acme.om.billing.storage.tables.ledger_counts import LedgerCounts
from acme.om.billing.storage.tables.ledger_entries import LedgerEntries
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
from acme.om.exceptions import NotFound, PreconditionFailed, TenantMismatch, ValidationFailed
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PLAN_WITH_VALUES, PgStorageBase
from acme.om.storage.utils.translation import to_model, to_row, to_values

ENTRY_TYPES: Mapping[EntryKind, type[Entry]] = {
    EntryKind.HOLD: FundedHold,
    EntryKind.SETTLEMENT: Settlement,
    EntryKind.CHARGE: Charge,
    EntryKind.CREDIT: Credit,
    EntryKind.GRANT: Grant,
    EntryKind.RAISE: WindowRaise,
    EntryKind.APPROVAL: Approval,
}


def cas_statement(org_id: UUID, account: Account, expected_version: int) -> Update:
    """The compare-and-set of the tenant's account: the version is in the
    WHERE, so two writers from one snapshot cannot both land."""
    values = {k: v for k, v in to_values(account, BillingAccounts).items() if k != "id"}
    return (
        update(BillingAccounts)
        .where(
            BillingAccounts.id == account.id,
            BillingAccounts.org_id == org_id,
            BillingAccounts.version == expected_version,
        )
        .values(**values)
        .returning(BillingAccounts.id)
    )


class AccountStoragePostgresImpl(PgStorageBase, AccountStorageInterface):
    async def create_account(
        self, org_id: UUID, account: Account, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        if account.id != org_id:
            raise TenantMismatch(f"account {account.id} is not {org_id}'s")
        return await self._insert(BillingAccounts, org_id, account, outbox_rows)

    async def read_account(self, org_id: UUID) -> Account | None:
        stmt = select(BillingAccounts).where(
            BillingAccounts.org_id == org_id, BillingAccounts.id == org_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            try:
                return to_model(row, Account)
            except ValidationError as unread:
                # A row this process cannot read, such as a funding mode it
                # does not know, is never read as another.
                raise ValidationFailed(f"the account of {org_id} cannot be read") from unread

    async def write_account(
        self,
        org_id: UUID,
        account: Account,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._session_for(BillingAccounts, org_id=org_id) as db:
            stmt = cas_statement(org_id, account, expected_version)
            if (await db.execute(stmt)).scalar_one_or_none() is None:
                await db.rollback()
                raise PreconditionFailed(
                    f"account {account.id} is no longer at version {expected_version}"
                )
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await db.commit()


def _row(
    org_id: UUID,
    kind: EntryKind,
    entry: Entry,
    *,
    hold_id: UUID | None = None,
    session_id: UUID | None = None,
    reference: str | None = None,
) -> LedgerEntries:
    return LedgerEntries(
        id=entry.id,
        org_id=org_id,
        created_at=entry.created_at,
        kind=kind.value,
        hold_id=hold_id,
        session_id=session_id,
        reference=reference,
        body=entry.model_dump(mode="json"),
    )


def _entry(row: LedgerEntries) -> Entry:
    return ENTRY_TYPES[EntryKind(row.kind)].model_validate(row.body)


class MoneyLedgerStoragePostgresImpl(PgStorageBase, MoneyLedgerStorageInterface):
    async def open_hold(self, org_id: UUID, hold: FundedHold) -> FundedHold | Turned:
        async with self._session_for(LedgerEntries, org_id=org_id) as db:
            try:
                counts = await _lock_counts(db, org_id, hold_keys(hold))
                # Read after the lock: an open of the same hold that got there
                # first has committed by now, and this one answers as it did.
                found = await _entry_row(db, org_id, hold.id)
                if found is not None:
                    stored = _entry(found)
                    await db.rollback()
                    assert isinstance(stored, FundedHold)
                    return stored
                written, turned = open_answer(hold, counts)
                if turned is not None:
                    await db.rollback()
                    return turned
                await _move_all(db, org_id, opened(written))
                db.add(
                    _row(
                        org_id,
                        EntryKind.HOLD,
                        written,
                        hold_id=written.id,
                        session_id=written.session_id,
                    )
                )
                await db.commit()
                return written
            except IntegrityError as error:
                # The same hold opened at once with no count to queue on, or
                # an id another tenant holds: the rollback takes the counts
                # back.
                await db.rollback()
                stored = await self.read_hold(org_id, hold.id)
                if stored is None:
                    raise TenantMismatch(f"hold {hold.id} is not in {org_id}") from error
                return stored

    async def read_hold(self, org_id: UUID, hold_id: UUID) -> FundedHold | None:
        stmt = select(LedgerEntries).where(
            LedgerEntries.org_id == org_id,
            LedgerEntries.id == hold_id,
            LedgerEntries.kind == EntryKind.HOLD.value,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            found = _entry(row)
            assert isinstance(found, FundedHold)
            return found

    async def close_hold(
        self, org_id: UUID, settlement: Settlement, charge: Charge
    ) -> tuple[Settlement, Charge]:
        async with self._session_for(LedgerEntries, org_id=org_id) as db:
            try:
                row = await _entry_row(db, org_id, settlement.hold_id, EntryKind.HOLD)
                if row is None:
                    await db.rollback()
                    raise NotFound(f"hold {settlement.hold_id} not found")
                hold = _entry(row)
                assert isinstance(hold, FundedHold)
                await _lock_counts(db, org_id, hold_keys(hold))
                # Read after the lock: a settlement that got there first has
                # committed by now, and it is the one that counts.
                first = await _closing(db, org_id, hold.id)
                if first is not None:
                    await db.rollback()
                    return first
                await _move_all(db, org_id, closed(hold, settlement, charge))
                db.add(_row(org_id, EntryKind.SETTLEMENT, settlement, hold_id=hold.id))
                db.add(_row(org_id, EntryKind.CHARGE, charge, hold_id=hold.id))
                await db.commit()
                return settlement, charge
            except IntegrityError:
                # A settlement of the same hold landed at once, with no count
                # to queue on: the rollback takes the counts back.
                await db.rollback()
                async with self._session_for(LedgerEntries, org_id=org_id) as again:
                    found = await _closing(again, org_id, settlement.hold_id)
                if found is None:
                    raise
                return found

    async def post_credit(self, org_id: UUID, credit: Credit) -> Credit:
        async with self._session_for(LedgerEntries, org_id=org_id) as db:
            try:
                await _lock_counts(db, org_id, [lifetime_key(Bucket.CREDITS)])
                first = await _credit_row(db, org_id, credit.reference)
                if first is not None:
                    stored = _entry(first)
                    await db.rollback()
                    assert isinstance(stored, Credit)
                    return stored
                await _add(db, org_id, lifetime_key(Bucket.CREDITS), credit.amount_micros)
                db.add(_row(org_id, EntryKind.CREDIT, credit, reference=credit.reference))
                await db.commit()
                return credit
            except IntegrityError as error:
                await db.rollback()
                async with self._session_for(LedgerEntries, org_id=org_id) as again:
                    found = await _credit_row(again, org_id, credit.reference)
                    stored = None if found is None else _entry(found)
                if not isinstance(stored, Credit):
                    raise TenantMismatch(f"credit {credit.id} is not in {org_id}") from error
                return stored

    async def post_grant(self, org_id: UUID, grant: Grant) -> Grant:
        key = lifetime_key(Bucket.GRANTED)
        stored = await self._post_once(org_id, EntryKind.GRANT, grant, {key: grant.units})
        assert isinstance(stored, Grant)
        return stored

    async def post_raise(self, org_id: UUID, raised: WindowRaise) -> WindowRaise:
        cost_key, tokens_key = raise_keys(raised.budget_id, raised.window_start)
        adds = {cost_key: raised.cost_micros, tokens_key: raised.tokens}
        stored = await self._post_once(org_id, EntryKind.RAISE, raised, adds)
        assert isinstance(stored, WindowRaise)
        return stored

    async def post_approval(self, org_id: UUID, approval: Approval) -> Approval:
        stored = await self._post_once(
            org_id, EntryKind.APPROVAL, approval, {}, session_id=approval.session_id
        )
        assert isinstance(stored, Approval)
        return stored

    async def read_open(
        self, after: datetime, before: datetime, limit: int
    ) -> list[tuple[UUID, Hold]]:
        # The holds of the slice by their time, each kept while no settlement
        # names it: the index by kind and time bounds the read, and the
        # ledger's unique index by hold answers each probe.
        settlement = aliased(LedgerEntries)
        settled = select(settlement.id).where(
            settlement.org_id == LedgerEntries.org_id,
            settlement.kind == EntryKind.SETTLEMENT.value,
            settlement.hold_id == LedgerEntries.hold_id,
        )
        stmt = (
            select(LedgerEntries)
            .where(
                LedgerEntries.kind == EntryKind.HOLD.value,
                LedgerEntries.created_at >= after,
                LedgerEntries.created_at < before,
                ~settled.exists(),
            )
            .order_by(LedgerEntries.created_at, LedgerEntries.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            await session.execute(PLAN_WITH_VALUES)
            found: list[tuple[UUID, Hold]] = []
            for row in (await session.execute(stmt)).scalars():
                entry = _entry(row)
                assert isinstance(entry, FundedHold)
                found.append((row.org_id, entry.hold))
            return found

    async def read_entries(
        self,
        org_id: UUID,
        *,
        kind: EntryKind | None = None,
        hold_id: UUID | None = None,
        session_id: UUID | None = None,
        limit: int,
    ) -> list[Entry]:
        stmt = select(LedgerEntries).where(LedgerEntries.org_id == org_id)
        if kind is not None:
            stmt = stmt.where(LedgerEntries.kind == kind.value)
        if hold_id is not None:
            stmt = stmt.where(LedgerEntries.hold_id == hold_id)
        if session_id is not None:
            stmt = stmt.where(LedgerEntries.session_id == session_id)
        stmt = stmt.order_by(LedgerEntries.created_at.desc(), LedgerEntries.id.desc()).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            return [_entry(row) for row in (await session.execute(stmt)).scalars()]

    async def read_counts(
        self, org_id: UUID, keys: Sequence[tuple[str, datetime]]
    ) -> dict[tuple[str, datetime], Count]:
        if not keys:
            return {}
        stmt = select(LedgerCounts).where(
            LedgerCounts.org_id == org_id,
            tuple_(LedgerCounts.counter, LedgerCounts.start).in_(sorted(set(keys))),
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return {(row.counter, row.start): to_model(row, Count) for row in rows}

    async def _post_once(
        self,
        org_id: UUID,
        kind: EntryKind,
        entry: Grant | WindowRaise | Approval,
        adds: Mapping[CountKey, int],
        *,
        session_id: UUID | None = None,
    ) -> Entry:
        """An entry that adds to counts, written once by its id: one posted
        already answers as stored, and nothing moves."""
        async with self._session_for(LedgerEntries, org_id=org_id) as db:
            try:
                await _lock_counts(db, org_id, list(adds))
                found = await _entry_row(db, org_id, entry.id)
                if found is not None:
                    stored = _entry(found)
                    await db.rollback()
                    return stored
                for key, amount in adds.items():
                    await _add(db, org_id, key, amount)
                db.add(_row(org_id, kind, entry, session_id=session_id))
                await db.commit()
                return entry
            except IntegrityError as error:
                await db.rollback()
                async with self._session_for(LedgerEntries, org_id=org_id) as again:
                    found = await _entry_row(again, org_id, entry.id)
                    if found is None:
                        raise TenantMismatch(
                            f"{kind.value} {entry.id} is not in {org_id}"
                        ) from error
                    return _entry(found)


async def _lock_counts(
    db: AsyncSession, org_id: UUID, keys: Sequence[CountKey]
) -> dict[CountKey, Count]:
    """The count of each key, made where it has none, then locked to the
    commit. Both statements take the rows in one order, by counter then
    period, so two calls over the same counters queue and never deadlock."""
    ordered = sorted(set(keys))
    if not ordered:
        return {}
    await db.execute(
        pg_insert(LedgerCounts)
        .values(
            [
                {
                    "org_id": org_id,
                    "counter": counter,
                    "start": start,
                    "held": 0,
                    "spent": 0,
                    "added": 0,
                }
                for counter, start in ordered
            ]
        )
        .on_conflict_do_nothing()
    )
    locked = (
        select(LedgerCounts)
        .where(
            LedgerCounts.org_id == org_id,
            tuple_(LedgerCounts.counter, LedgerCounts.start).in_(ordered),
        )
        .order_by(LedgerCounts.counter, LedgerCounts.start)
        .with_for_update()
    )
    rows = (await db.execute(locked)).scalars().all()
    return {(row.counter, row.start): to_model(row, Count) for row in rows}


async def _move_all(
    db: AsyncSession, org_id: UUID, moves: Mapping[CountKey, tuple[int, int]]
) -> None:
    """Each count as an entry moves it: what is held, never below nothing,
    and what was spent."""
    for (counter, start), (held, spent) in sorted(moves.items()):
        values: dict[str, Any] = {
            "held": _floor(LedgerCounts.held + held),
            "spent": LedgerCounts.spent + spent,
        }
        await db.execute(
            update(LedgerCounts)
            .where(
                LedgerCounts.org_id == org_id,
                LedgerCounts.counter == counter,
                LedgerCounts.start == start,
            )
            .values(**values)
        )


def _floor(value: Any) -> Any:
    return func.greatest(value, 0)


async def _add(db: AsyncSession, org_id: UUID, key: CountKey, amount: int) -> None:
    counter, start = key
    await db.execute(
        update(LedgerCounts)
        .where(
            LedgerCounts.org_id == org_id,
            LedgerCounts.counter == counter,
            LedgerCounts.start == start,
        )
        .values(added=LedgerCounts.added + amount)
    )


async def _entry_row(
    db: AsyncSession, org_id: UUID, entry_id: UUID, kind: EntryKind | None = None
) -> LedgerEntries | None:
    stmt = select(LedgerEntries).where(LedgerEntries.org_id == org_id, LedgerEntries.id == entry_id)
    if kind is not None:
        stmt = stmt.where(LedgerEntries.kind == kind.value)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _credit_row(db: AsyncSession, org_id: UUID, reference: str) -> LedgerEntries | None:
    stmt = select(LedgerEntries).where(
        LedgerEntries.org_id == org_id,
        LedgerEntries.kind == EntryKind.CREDIT.value,
        LedgerEntries.reference == reference,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _closing(
    db: AsyncSession, org_id: UUID, hold_id: UUID
) -> tuple[Settlement, Charge] | None:
    """A hold's settlement and charge, read before any rollback expires them."""
    stmt = select(LedgerEntries).where(
        LedgerEntries.org_id == org_id,
        LedgerEntries.hold_id == hold_id,
        LedgerEntries.kind.in_((EntryKind.SETTLEMENT.value, EntryKind.CHARGE.value)),
    )
    found = {row.kind: _entry(row) for row in (await db.execute(stmt)).scalars()}
    settlement = found.get(EntryKind.SETTLEMENT.value)
    charge = found.get(EntryKind.CHARGE.value)
    if not isinstance(settlement, Settlement) or not isinstance(charge, Charge):
        return None
    return settlement, charge
