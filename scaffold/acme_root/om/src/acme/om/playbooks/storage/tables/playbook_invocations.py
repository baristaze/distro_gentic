from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class PlaybookInvocations(IdentifiableMixin, CreatedMixin, Base):
    """The playbooks each session invoked: one row a version in a session,
    which the unique index on (org_id, session_id, playbook_id) holds and
    the read of a session's gates uses, so org_id gets no index of its own."""

    __tablename__ = "playbook_invocations"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_playbook_invocations_org_id_session_id_playbook_id",
            "org_id",
            "session_id",
            "playbook_id",
            unique=True,
        ),
    )
    session_id: Mapped[UUID]
    playbook_id: Mapped[UUID]
    name: Mapped[str]
    version: Mapped[int]
    invoked_by: Mapped[UUID]
