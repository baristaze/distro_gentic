from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class WorkBindings(IdentifiableMixin, CreatedMixin, Base):
    """The pull requests and branches that are sessions' work: one row a
    handle, which the unique index on (org_id, kind, handle) holds and the
    router's read uses, so org_id gets no index of its own."""

    __tablename__ = "work_bindings"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_work_bindings_org_id_kind_handle", "org_id", "kind", "handle", unique=True),
    )
    session_id: Mapped[UUID]
    kind: Mapped[str]
    handle: Mapped[str]
