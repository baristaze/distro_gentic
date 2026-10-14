from uuid import UUID

from sqlalchemy import Index, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class ExecParts(IdentifiableMixin, CreatedMixin, Base):
    """The output a host streamed, a part at a time. A row's parts are read
    in order, once each, under the unique index that holds a part's place;
    a session's go with it. org_id leads both, so it gets none of its own."""

    __tablename__ = "exec_parts"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_exec_parts_org_id_row_id_seq", "org_id", "row_id", "seq", unique=True),
        Index("ix_exec_parts_org_id_session_id", "org_id", "session_id"),
    )
    session_id: Mapped[UUID]
    row_id: Mapped[UUID]
    seq: Mapped[int]
    stream: Mapped[str]
    text: Mapped[bytes | None] = mapped_column(LargeBinary)
    sha256: Mapped[str]
