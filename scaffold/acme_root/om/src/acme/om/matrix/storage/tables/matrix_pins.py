from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class MatrixPins(IdentifiableMixin, CreatedMixin, Base):
    """The matrix version each pinned version of a session's fill set came
    from, one row each, which the unique index holds; it is led by org_id,
    so org_id gets no index of its own. A deleted tenant's rows go in the
    sweep's batches."""

    __tablename__ = "matrix_pins"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_matrix_pins_org_id_session_id_fill_set_version",
            "org_id",
            "session_id",
            "fill_set_version",
            unique=True,
        ),
    )
    session_id: Mapped[UUID]
    fill_set_version: Mapped[int]
    matrix_version: Mapped[int]
