"""Storage of the intake swimlane: the tenant's account links and the work
bindings of its sessions. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.intake.types.link import AccountLink, HandleKind, WorkBinding


class IntakeStorageInterface(ABC):
    @abstractmethod
    async def create_link(self, org_id: UUID, link: AccountLink) -> AccountLink:
        """The link, or the one the tenant holds for the account already,
        which answers instead: one link an account."""
        ...

    @abstractmethod
    async def read_link(
        self, org_id: UUID, integration: str, external_id: str
    ) -> AccountLink | None: ...

    @abstractmethod
    async def create_binding(self, org_id: UUID, binding: WorkBinding) -> WorkBinding:
        """The binding, or the one the tenant holds for the handle already,
        which answers instead: one session a handle."""
        ...

    @abstractmethod
    async def read_binding(
        self, org_id: UUID, kind: HandleKind, handle: str
    ) -> WorkBinding | None: ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each kind of a deleted tenant past its
        retention; returns how many went."""
        ...
