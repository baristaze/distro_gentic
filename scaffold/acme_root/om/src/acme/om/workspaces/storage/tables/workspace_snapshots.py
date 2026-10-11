from uuid import UUID

from sqlalchemy import BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class WorkspaceSnapshots(IdentifiableMixin, TrackableMixin, Base):
    """Where each snapshot a session keeps lives, under the snapshot's id: the
    platform's bucket, or the store of a host inside its tenant's wall,
    named by its pool, its host, and the reference that store knows it by,
    with its hash and its size. Never its bytes. The index on (org_id,
    session_id) serves a session's purge, so org_id gets no index of its
    own."""

    __tablename__ = "workspace_snapshots"
    __org_id_index__ = False
    __table_args__ = (Index("ix_workspace_snapshots_org_id_session_id", "org_id", "session_id"),)
    session_id: Mapped[UUID]
    hash: Mapped[str]
    size: Mapped[int] = mapped_column(BigInteger)
    pool_id: Mapped[UUID | None]
    host_id: Mapped[UUID | None]
    reference: Mapped[str]
    digest: Mapped[str | None]
    machine: Mapped[bool]
