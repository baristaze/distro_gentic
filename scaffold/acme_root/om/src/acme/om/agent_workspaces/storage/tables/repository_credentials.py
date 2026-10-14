from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class RepositoryCredentials(IdentifiableMixin, TrackableMixin, Base):
    """That a project's repository has a fetch credential: one row a project,
    under the project's id. The value is in the tenant's store."""

    __tablename__ = "repository_credentials"
    version: Mapped[int]
