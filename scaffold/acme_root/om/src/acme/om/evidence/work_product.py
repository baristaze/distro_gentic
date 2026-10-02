"""The work product: what a session delivered, read from the system that
keeps it (its workspace, its source control), never from what the agent
says of it. A root wires the platform's; the null of a root that wired
none cannot read one, and says so, so no success counts on a guess."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.evidence.types.validation import Delivery


class WorkProductInterface(ABC):
    @abstractmethod
    async def delivered(self, ctx: TenantContext, session_id: UUID) -> Delivery | None:
        """The session's work product as it stands: its project, its base,
        its committed head, whether its tree is dirty, and the paths changed
        from the base. None when the session holds no work product."""
        ...
