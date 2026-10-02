"""Storage of the placement swimlane: each tenant's fair share, one row a
tenant. Every operation takes org_id first. A write after the create is a
compare-and-set on the version. The operators' plane writes it, and its
audit entry follows in the tenant's stream, so no outbox row rides it."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.placement.types.share import FairShare


class PlacementStorageInterface(ABC):
    @abstractmethod
    async def read_share(self, org_id: UUID) -> FairShare | None:
        """The tenant's share, or None when no operator has written one."""
        ...

    @abstractmethod
    async def create_share(self, org_id: UUID, share: FairShare) -> bool:
        """The create; False, with nothing landed, when the id is written
        already. `UniqueKeyTaken` when the tenant holds another share."""
        ...

    @abstractmethod
    async def write_share(self, org_id: UUID, share: FairShare, expected_version: int) -> None:
        """The compare-and-set: lands the share when the stored one is at
        `expected_version`, and raises `PreconditionFailed` otherwise,
        landing nothing."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` shares of a deleted tenant past its retention;
        returns how many went."""
        ...
