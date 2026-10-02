"""What the trust swimlane reads of a session's placement: whether it runs
inside a customer's wall, and the machine credential its calls run under.

Placement is the hosts' concept, and they own it; this interface declares
the one fact the secrets need and the one answer the audit needs, so the
rules here hold before the hosts arrive. The default places every session
in the cloud, on the pool it is built with
(`acme.om.trust.impl.placement.PlacementCloudImpl`)."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.trust.types.identities import Executor


class PlacementInterface(ABC):
    @abstractmethod
    async def inside_wall(self, org_id: UUID, session_id: UUID) -> bool:
        """Whether the session's calls run on a host inside a customer's wall,
        rather than in the platform's cloud."""
        ...

    @abstractmethod
    async def executor_of(self, org_id: UUID, session_id: UUID) -> Executor:
        """The machine credential the session's next call runs under: a host
        of its pool inside the wall, or the cloud's."""
        ...
