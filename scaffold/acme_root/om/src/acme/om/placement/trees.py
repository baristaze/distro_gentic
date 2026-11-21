"""What a claim reads of the session tree an item serves, for a claimant
that serves a session's tree, a person's own client
(`Claimant.serves_tree`).

Sessions and the instances their checks ask for are the agent sessions' and
the exec relay's, which own them; this interface declares the one fact a
claim needs, so placement's rule holds before either arrives. With none,
such a claimant is handed its own session's work alone."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.work.types.work_item import WorkItem


class ItemTreesInterface(ABC):
    @abstractmethod
    async def root_of(self, org_id: UUID, item: WorkItem) -> UUID | None:
        """The root of the session tree the item serves, in its tenant: the
        session it names, or the one an instance it names is made for, read
        up to its tree's root. None when it names no session this reads."""
        ...
