from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class RepositoryCredentials(IdentifiableMixin, TrackableMixin, Base):
    """That an agent project's repository has a fetch credential: one row an agent project,
    under the agent project's id. The value is in the tenant's store."""

    __tablename__ = "repository_credentials"
    version: Mapped[int]
