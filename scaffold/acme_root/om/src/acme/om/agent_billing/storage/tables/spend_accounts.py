from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class BillingAccounts(IdentifiableMixin, TrackableMixin, Base):
    """One row per org, under the org's own id: who pays, on which plan,
    from when its billing periods run, and its zones in the order it set
    them."""

    __tablename__ = "billing_accounts"
    funding: Mapped[str]
    key_ref: Mapped[str | None]
    plan_id: Mapped[str]
    plan_version: Mapped[int]
    period_anchor: Mapped[datetime]
    # Millionths of the reference currency each billing period.
    credit_line_micros: Mapped[int] = mapped_column(BigInteger)
    zones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    version: Mapped[int]
