"""Storage of the intake swimlane: the installations the tenant connected,
its account links, the work bindings of its sessions, and the acts its
sessions made through the platform's account. Every operation takes org_id
first, but the ingress's read of the tenant an installation names, which
no tenant scopes."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.intake.types.link import (
    AccountLink,
    HandleKind,
    Installation,
    PlatformAct,
    WorkBinding,
)


class IntakeStorageInterface(ABC):
    @abstractmethod
    async def create_installation(
        self, org_id: UUID, installation: Installation
    ) -> Installation | None:
        """The installation, or the one the tenant holds for it already,
        which answers instead; None when another tenant holds it: one tenant
        an installation."""
        ...

    @abstractmethod
    async def read_installation_org(self, integration: str, installation: str) -> UUID | None:
        """Cross-tenant: the tenant that connected the installation, read
        among every tenant's in the system scope, since a delivery names no
        tenant. None when none did."""
        ...

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
    async def read_user_links(self, org_id: UUID, user_id: UUID, limit: int) -> list[AccountLink]:
        """The accounts linked to a user of the tenant, by integration."""
        ...

    @abstractmethod
    async def delete_link(self, org_id: UUID, integration: str, external_id: str) -> bool:
        """The account's link gone; False when the tenant held none."""
        ...

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
    async def record_act(self, org_id: UUID, act: PlatformAct) -> None:
        """The act, in place of any the tenant holds under its name: the
        latest act under a name holds."""
        ...

    @abstractmethod
    async def read_act(
        self, org_id: UUID, integration: str, refs: Sequence[str]
    ) -> PlatformAct | None:
        """The latest act recorded under any of `refs`."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each kind of a deleted tenant past its
        retention; returns how many went."""
        ...
