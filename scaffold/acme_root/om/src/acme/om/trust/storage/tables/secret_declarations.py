from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class SecretDeclarations(IdentifiableMixin, TrackableMixin, Base):
    """A tenant's secrets by name: one row a name, which the unique index on
    (org_id, name) holds and the reads walk, so org_id gets no index of its
    own. No column holds a value."""

    __tablename__ = "secret_declarations"
    __org_id_index__ = False
    __table_args__ = (Index("uq_secret_declarations_org_id_name", "org_id", "name", unique=True),)
    name: Mapped[str]
    variable: Mapped[str]
    owner_kind: Mapped[str]
    owner_id: Mapped[UUID]
    scope: Mapped[str]
    store: Mapped[str]
