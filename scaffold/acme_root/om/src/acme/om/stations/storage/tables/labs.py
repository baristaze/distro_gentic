from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class Labs(IdentifiableMixin, TrackableMixin, Base):
    """A tenant's labs, each the place one station daemon serves, read by
    id."""

    __tablename__ = "labs"
    name: Mapped[str]
