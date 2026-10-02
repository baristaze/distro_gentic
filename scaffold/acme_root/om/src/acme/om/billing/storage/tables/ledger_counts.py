from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base


class LedgerCounts(Base):
    """One row per counter and period: a budget's cost or tokens in a window,
    or a bucket in a billing period or for the account's life. What open
    holds reserve, what was spent, and what was added. An entry moves it
    under its lock, in the transaction that writes the entry, and a call's
    rows are locked in one order (by counter, then period), so two holds
    over one counter queue here and never wait on each other crosswise. It
    can be rebuilt from the entries."""

    __tablename__ = "ledger_counts"
    org_id: Mapped[UUID] = mapped_column(primary_key=True)
    counter: Mapped[str] = mapped_column(primary_key=True)
    start: Mapped[datetime] = mapped_column(primary_key=True)
    held: Mapped[int] = mapped_column(BigInteger)
    spent: Mapped[int] = mapped_column(BigInteger)
    added: Mapped[int] = mapped_column(BigInteger)
