from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class Hosts(IdentifiableMixin, TrackableMixin, Base):
    """The enrolled claimants, a host or a product's kind, read a pool at a
    time: org_id leads the one compound index, so it gets none of its own.
    What a host advertised and the version it reads are a host's alone."""

    __tablename__ = "hosts"
    __org_id_index__ = False
    __table_args__ = (Index("ix_hosts_org_id_pool_id", "org_id", "pool_id"),)
    kind: Mapped[str]
    pool_id: Mapped[UUID]
    name: Mapped[str]
    enrolled_with: Mapped[UUID]
    advertisement: Mapped[dict[str, Any] | None]
    exec_version: Mapped[int | None]
    last_seen_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None]
