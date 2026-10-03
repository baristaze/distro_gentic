"""What a secret is declared on, as a registry. A secret owner kind names
the owners of that kind (a project, or a product's own), whether one is the
tenant's, and which one a session is placed on: the one placement whose
sessions reach a secret declared on it. The platform's project registers
here as a product's owner kind does at its roots
(`root.PlatformPorts.kinds`), and a secret is resolved through every kind
alike."""

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.trust.types.secret import OWNER_KIND, PROJECT


class SecretOwnerInterface(ABC):
    """One kind of owner a secret is declared on."""

    kind: str
    """The kind's name, as a declaration records it (`owner_kind`)."""

    @abstractmethod
    async def holds(self, ctx: TenantContext, owner_id: UUID) -> bool:
        """Whether the owner is one of the caller's tenant. Another tenant's
        is not, as one that never existed is not."""
        ...

    @abstractmethod
    async def owner_of(self, ctx: TenantContext, session_id: UUID) -> UUID | None:
        """The owner of this kind the session is placed on, whose secrets it
        reaches; None for a session placed on none."""
        ...


class ProjectOwnerImpl(SecretOwnerInterface):
    """The platform's owner kind: a project, whose secrets reach its own
    sessions alone."""

    kind = PROJECT

    def __init__(self, projects: SessionProjectsInterface) -> None:
        self._projects = projects

    async def holds(self, ctx: TenantContext, owner_id: UUID) -> bool:
        return await self._projects.holds(ctx, owner_id)

    async def owner_of(self, ctx: TenantContext, session_id: UUID) -> UUID | None:
        return await self._projects.project_of(ctx, session_id)


class SecretOwners:
    """The owner kinds a process knows, each once, in the order a session's
    secret is resolved through them: the platform's project first. A kind
    registered twice is refused, so a product never takes over a
    project's secrets."""

    def __init__(self, owners: Iterable[SecretOwnerInterface]) -> None:
        found: dict[str, SecretOwnerInterface] = {}
        for owner in owners:
            if not re.match(OWNER_KIND, owner.kind):
                raise ValueError(
                    f"a secret owner kind is named in lower case, never {owner.kind!r}"
                )
            if owner.kind in found:
                raise ValueError(f"secret owner kind {owner.kind} is registered twice")
            found[owner.kind] = owner
        self._owners: Mapping[str, SecretOwnerInterface] = MappingProxyType(found)

    def __iter__(self) -> Iterator[SecretOwnerInterface]:
        return iter(self._owners.values())

    def get(self, kind: str) -> SecretOwnerInterface | None:
        return self._owners.get(kind)

    async def placed(self, ctx: TenantContext, session_id: UUID) -> dict[str, UUID]:
        """The owner of each kind the session is placed on, by kind, in the
        registry's order; a kind it is placed on none of is left out."""
        found: dict[str, UUID] = {}
        for owner in self:
            owner_id = await owner.owner_of(ctx, session_id)
            if owner_id is not None:
                found[owner.kind] = owner_id
        return found
