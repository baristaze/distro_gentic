from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class SpendLedgerEntries(IdentifiableMixin, CreatedMixin, Base):
    """The one ledger: every hold, settlement, charge, credit, grant, raise,
    and approval, one row each, written once. The serving logins hold
    SELECT and INSERT here and nothing more."""

    __tablename__ = "spend_ledger_entries"
    # org_id leads every index, so it gets none of its own.
    __org_id_index__ = False
    __table_args__ = (
        # A hold closes once: its settlement and its charge each meet this
        # index the second time. An entry of no hold names none, and a null
        # never meets another.
        Index(
            "uq_spend_ledger_entries_org_id_kind_hold_id",
            "org_id",
            "kind",
            "spend_hold_id",
            unique=True,
        ),
        # A payment credits once.
        Index(
            "uq_spend_ledger_entries_org_id_kind_reference",
            "org_id",
            "kind",
            "reference",
            unique=True,
        ),
        # A call's entries, and a session's recent holds and approvals, which
        # the anomaly guard reads before every call.
        Index("ix_spend_ledger_entries_org_id_hold_id", "org_id", "spend_hold_id"),
        Index(
            "ix_spend_ledger_entries_org_id_session_id_created_at",
            "org_id",
            "agent_session_id",
            "created_at",
        ),
        Index("ix_spend_ledger_entries_org_id_kind_created_at", "org_id", "kind", "created_at"),
        # The holds no settlement closed, across tenants, one slice of the
        # times they fall due at a time: what the sweep reads. A model
        # call's hold falls due at its opening, and a job's at its deadline.
        Index("ix_spend_ledger_entries_kind_created_at", "kind", "created_at"),
        Index(
            "ix_spend_ledger_entries_kind_deadline",
            "kind",
            "deadline",
            postgresql_where=text("deadline IS NOT NULL"),
        ),
    )
    kind: Mapped[str]
    spend_hold_id: Mapped[UUID | None]
    agent_session_id: Mapped[UUID | None]
    reference: Mapped[str | None]
    body: Mapped[dict[str, Any]]
    deadline: Mapped[datetime | None]  # a job's hold's, which it lives to
