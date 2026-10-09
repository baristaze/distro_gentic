"""Storage of the placement swimlane: each tenant's fair share, one row a
tenant. Every operation takes org_id first, but the read of the shares
still to carry, which reads across tenants. A write after the create is a
compare-and-set on the version. The operators' plane writes it, and its
audit entry follows in the tenant's stream, so no outbox row rides it.

A share the release before wrote also holds how many of the tenant's loops
run at once. That number is the work queue's cap on the tenant's lane, and
the sweep carries it there once (`read_uncarried`, `mark_carried`); a share
this release writes holds nothing to carry."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.base import Platform
from acme.om.placement.types.share import FairShare


class ShareToCarry(Platform):
    """A share the release before wrote, with the concurrency it held."""

    org_id: UUID
    share: FairShare
    concurrency: int


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
        landing nothing. The write is newer than any concurrency the share
        held, so it leaves nothing to carry."""
        ...

    @abstractmethod
    async def read_uncarried(self, limit: int) -> list[ShareToCarry]:
        """Cross-tenant, in the system scope: at most `limit` shares whose
        concurrency is not carried yet, for the sweep's carry."""
        ...

    @abstractmethod
    async def mark_carried(self, org_id: UUID, share_id: UUID) -> bool:
        """Marks the tenant's share carried; False when it was carried
        already or is not there."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` shares of a deleted tenant past its retention;
        returns how many went."""
        ...
