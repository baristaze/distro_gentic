"""A product's namespace as a suite declares it beside its kinds: `parcels`,
a tenant's parcels held in this process, and its purge of a deleted tenant,
which runs before the purge of the tenant's events and records how many of
them it found still there."""

from dataclasses import dataclass, field
from uuid import UUID

from acme.om.change_events.storage import ChangeEventStorageInterface
from acme.om.context import TenantContext
from acme.om.platform_root import (
    PlatformManagers,
    ProductNamespace,
    ProductNamespaces,
    ProductPurge,
)
from acme.om.storage.root import StorageInterface

PARCELS = "parcels"
"""The namespace's name: its routes' tag, its service's key, and its purge's
name in the sweep."""


@dataclass
class Parcels:
    """The namespace's managers: each tenant's parcels, by name, and what
    each purge of a tenant found of the tenant's events."""

    events: ChangeEventStorageInterface
    held: dict[UUID, list[str]] = field(default_factory=lambda: {})
    found: list[tuple[UUID, int]] = field(default_factory=lambda: [])

    async def add(self, ctx: TenantContext, name: str) -> list[str]:
        self.held.setdefault(ctx.org_id, []).append(name)
        return self.held[ctx.org_id]

    async def list(self, ctx: TenantContext) -> list[str]:
        return self.held.get(ctx.org_id, [])

    async def purge_tenant(self, ctx: TenantContext) -> int:
        events = await self.events.read_after(ctx.org_id, 0, 100)
        self.found.append((ctx.org_id, len(events)))
        return len(self.held.pop(ctx.org_id, []))


built: list[Parcels] = []
"""Each `Parcels` a process built, the latest last, for a case to read."""


def build_parcels(storage: StorageInterface, managers: PlatformManagers) -> Parcels:
    parcels = Parcels(storage.get_change_event_storage())
    built.append(parcels)
    return parcels


NAMESPACE = ProductNamespace(
    PARCELS,
    build_parcels,
    purges=(ProductPurge(PARCELS, lambda parcels: parcels.purge_tenant, before="events"),),
)

NAMESPACES = ProductNamespaces((NAMESPACE,))
"""What a product that adds `parcels` declares in `product_namespaces.py`."""
