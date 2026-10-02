"""The tenant's key service as the engine reaches it, and the local key
service that holds each session's key.

`KeyServiceByTenantImpl` is what the engine's session keys are wired over:
every call names its tenant, and goes to that tenant's key service alone.
`KeyServiceLocalImpl` is the local twin of a key service a tenant can
revoke: over the key service of the process, it keeps the custody of each
session's key, so it can destroy one and report it, and it refuses every
call of a tenant whose key is revoked. The root wires it in `local`
alone."""

from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import UUID

from acme.infra.exceptions import KeyRefused
from acme.infra.keys import DataKey, KeyServiceInterface, WrappedKey
from acme.om.base import new_id, utcnow
from acme.om.retention.keys import KeyCustodyInterface, KeyDestruction, TenantKeysInterface

LOCAL = "keys=local"
"""How the local key service names itself in a report."""


class KeyServiceLocalImpl(KeyServiceInterface, KeyCustodyInterface):
    """The local key service. It wraps under the process's key service, the
    memory one locally, and keeps here what a tenant's key service keeps of
    each session's key:
    whether it is destroyed, with the report of it, and whether the tenant
    has revoked its own key. A destroyed key, or any key of a revoked
    tenant, is refused at every call, so a wrapped copy kept anywhere opens
    nothing. Each tenant reads its own log of what was destroyed.

    The custody is this process's, as the memory service's keys are: a
    process that starts over with the same root key opens again a copy the
    engine's revocation did not empty. So it stands in for a tenant's key
    service where nothing outlives the process, and nowhere else."""

    def __init__(self, inner: KeyServiceInterface, clock: Callable[[], datetime] = utcnow) -> None:
        self._inner = inner
        self._clock = clock
        self._destroyed: dict[tuple[UUID, UUID], KeyDestruction] = {}
        self._revoked: set[UUID] = set()

    def revoke(self, org_id: UUID) -> None:
        """The tenant revokes its key: from now on nothing of the tenant is
        made, unwrapped, or re-wrapped. The stand-in for the tenant's own
        act in a cloud key service."""
        self._revoked.add(org_id)

    def log(self, org_id: UUID) -> tuple[KeyDestruction, ...]:
        """The tenant's own log: every destruction of one of its keys, in
        order."""
        return tuple(report for (org, _), report in self._destroyed.items() if org == org_id)

    def _refused(self, org_id: UUID, key_id: UUID, version: int) -> None:
        if org_id in self._revoked:
            raise KeyRefused(f"the tenant's key is revoked; version {version} of {key_id} is not")
        if (org_id, key_id) in self._destroyed:
            raise KeyRefused(f"key {key_id} is destroyed; version {version} of it is too")

    async def generate(self, org_id: UUID, key_id: UUID, version: int) -> DataKey:
        self._refused(org_id, key_id, version)
        return await self._inner.generate(org_id, key_id, version)

    async def unwrap(self, org_id: UUID, key_id: UUID, version: int, wrapped: WrappedKey) -> bytes:
        self._refused(org_id, key_id, version)
        return await self._inner.unwrap(org_id, key_id, version, wrapped)

    async def rewrap(
        self, org_id: UUID, key_id: UUID, version: int, wrapped: WrappedKey
    ) -> WrappedKey:
        self._refused(org_id, key_id, version)
        return await self._inner.rewrap(org_id, key_id, version, wrapped)

    async def destroy(self, org_id: UUID, key_id: UUID) -> KeyDestruction:
        if org_id in self._revoked:
            raise KeyRefused(f"the tenant's key is revoked; key {key_id} opens nothing")
        found = self._destroyed.get((org_id, key_id))
        if found is not None:
            return found
        report = KeyDestruction(
            service=LOCAL,
            key=f"{org_id}/{key_id}",
            destroyed_at=self._clock(),
            receipt=str(new_id()),
        )
        self._destroyed[(org_id, key_id)] = report
        return report

    def describe(self) -> str:
        return LOCAL

    async def start(self) -> None:
        await self._inner.start()

    async def close(self) -> None:
        await self._inner.close()


class TenantKeysImpl(TenantKeysInterface):
    """The platform's key service for every tenant but those that brought
    their own, each of which serves its tenant alone. `own` is read at each
    call, so a tenant added to it is served by its own service from then
    on. A key is opened only by the service that wrapped it, so a tenant
    brings its own before its first session, and never moves."""

    def __init__(
        self, platform: KeyServiceInterface, own: Mapping[UUID, KeyServiceInterface] | None = None
    ) -> None:
        self._platform = platform
        self._own: Mapping[UUID, KeyServiceInterface] = {} if own is None else own

    def service(self, org_id: UUID) -> KeyServiceInterface:
        return self._own.get(org_id, self._platform)

    def custody(self, org_id: UUID) -> KeyCustodyInterface | None:
        service = self.service(org_id)
        return service if isinstance(service, KeyCustodyInterface) else None


class KeyServiceByTenantImpl(KeyServiceInterface):
    """The key service the engine's session keys are wired over: each call
    goes to the key service of the tenant it names. The services are opened
    and closed by whoever built them; the platform's by the infra root."""

    def __init__(self, keys: TenantKeysInterface) -> None:
        self._keys = keys

    async def generate(self, org_id: UUID, key_id: UUID, version: int) -> DataKey:
        return await self._keys.service(org_id).generate(org_id, key_id, version)

    async def unwrap(self, org_id: UUID, key_id: UUID, version: int, wrapped: WrappedKey) -> bytes:
        return await self._keys.service(org_id).unwrap(org_id, key_id, version, wrapped)

    async def rewrap(
        self, org_id: UUID, key_id: UUID, version: int, wrapped: WrappedKey
    ) -> WrappedKey:
        return await self._keys.service(org_id).rewrap(org_id, key_id, version, wrapped)

    def describe(self) -> str:
        return "keys=by tenant"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
