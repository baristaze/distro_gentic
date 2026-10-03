from datetime import datetime
from uuid import UUID

from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.hosts.storage import HostsStorageInterface
from acme.om.hosts.types.credential import EnrollmentToken, HostCredential, Rotation
from acme.om.hosts.types.host import Host, HostReport
from acme.om.hosts.types.placement import SessionPlacement
from acme.om.hosts.types.pool import HostPool
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class HostsStorageMemoryImpl(MemoryStorageBase, HostsStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._pools: MemoryTable[HostPool] = {}
        self._tokens: MemoryTable[EnrollmentToken] = {}
        self._hosts: MemoryTable[Host] = {}
        self._credentials: MemoryTable[HostCredential] = {}
        self._placements: MemoryTable[SessionPlacement] = {}

    async def create_pool(
        self, org_id: UUID, pool: HostPool, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._pools, org_id, pool, outbox_rows)

    async def read_pool(self, org_id: UUID, pool_id: UUID) -> HostPool | None:
        return self._get(self._pools, org_id, pool_id)

    async def read_pools(self, org_id: UUID, limit: int) -> list[HostPool]:
        return self._rows(self._pools, org_id)[:limit]

    async def create_enrollment_token(
        self, org_id: UUID, token: EnrollmentToken, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if token.id not in self._tokens and any(
                held.digest == token.digest for held in self._every(self._tokens)
            ):
                raise UniqueKeyTaken(f"host_enrollment_tokens {token.id}: the digest is taken")
            return self._insert(self._tokens, org_id, token, outbox_rows)

    async def read_enrollment_token_by_digest(
        self, digest: str
    ) -> tuple[UUID, EnrollmentToken] | None:
        for org_id, token in self._rows_across_tenants(self._tokens):
            if token.digest == digest:
                return org_id, token
        return None

    async def revoke_enrollment_token(
        self,
        org_id: UUID,
        token_id: UUID,
        at: datetime,
        by: UUID,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> EnrollmentToken | None:
        async with self._lock:
            token = self._get(self._tokens, org_id, token_id)
            if token is None or token.revoked_at is not None:
                return token
            revoked = token.model_copy(
                update={"revoked_at": at, "revoked_by": by, "updated_at": at, "updated_by": by}
            )
            self._put(self._tokens, org_id, revoked, outbox_rows)
            return revoked

    async def enroll_host(
        self,
        org_id: UUID,
        host: Host,
        credential: HostCredential,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            if host.id in self._hosts or credential.id in self._credentials:
                raise UniqueKeyTaken(f"hosts {host.id}: the id is taken")
            if any(held.digest == credential.digest for held in self._every(self._credentials)):
                raise UniqueKeyTaken(f"host_credentials {credential.id}: the digest is taken")
            self._insert(self._hosts, org_id, host, outbox_rows)
            self._insert(self._credentials, org_id, credential)

    async def read_host(self, org_id: UUID, host_id: UUID) -> Host | None:
        return self._get(self._hosts, org_id, host_id)

    async def read_hosts(self, org_id: UUID, pool_id: UUID, limit: int) -> list[Host]:
        hosts = [host for host in self._rows(self._hosts, org_id) if host.pool_id == pool_id]
        return hosts[:limit]

    async def count_hosts(self, seen_since: datetime, floor: int) -> dict[tuple[bool, bool], int]:
        found: dict[tuple[bool, bool], int] = {}
        for _, host in self._rows_across_tenants(self._hosts):
            if host.revoked_at is None:
                key = (host.last_seen_at > seen_since, host.exec_version >= floor)
                found[key] = found.get(key, 0) + 1
        return found

    async def read_host_by_credential_digest(
        self, digest: str
    ) -> tuple[UUID, HostCredential, Host] | None:
        for org_id, credential in self._rows_across_tenants(self._credentials):
            if credential.digest == digest:
                host = self._get(self._hosts, org_id, credential.host_id)
                return None if host is None else (org_id, credential, host)
        return None

    async def rotate_credential(
        self,
        org_id: UUID,
        retiring_id: UUID,
        at: datetime,
        retire_at: datetime,
        minted: HostCredential,
    ) -> Rotation:
        async with self._lock:
            retiring = self._get(self._credentials, org_id, retiring_id)
            if retiring is None or retiring.host_id != minted.host_id:
                return Rotation.MISSING
            if retiring.rotated_at is not None:
                return Rotation.REUSED
            if minted.id in self._credentials or any(
                held.digest == minted.digest for held in self._every(self._credentials)
            ):
                raise UniqueKeyTaken(f"host_credentials {minted.id}: the id or digest is taken")
            for held in self._rows(self._credentials, org_id):
                if (
                    held.host_id == minted.host_id
                    and held.id != retiring_id
                    and held.expires_at > at
                ):
                    self._put(self._credentials, org_id, held.model_copy(update={"expires_at": at}))
            rotated = retiring.model_copy(
                update={"rotated_at": at, "expires_at": min(retiring.expires_at, retire_at)}
            )
            self._put(self._credentials, org_id, rotated)
            self._insert(self._credentials, org_id, minted)
            return Rotation.ROTATED

    async def mark_seen(
        self, org_id: UUID, host_id: UUID, at: datetime, report: HostReport
    ) -> bool:
        async with self._lock:
            host = self._get(self._hosts, org_id, host_id)
            if host is None:
                return False
            seen = host.model_copy(
                update={
                    "last_seen_at": at,
                    "advertisement": report.advertisement,
                    "exec_version": report.exec_version,
                }
            )
            self._put(self._hosts, org_id, seen)
            return True

    async def revoke_host(
        self,
        org_id: UUID,
        host_id: UUID,
        at: datetime,
        by: UUID,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> Host | None:
        async with self._lock:
            host = self._get(self._hosts, org_id, host_id)
            if host is None or host.revoked_at is not None:
                return host
            revoked = host.model_copy(
                update={"revoked_at": at, "revoked_by": by, "updated_at": at, "updated_by": by}
            )
            self._put(self._hosts, org_id, revoked, outbox_rows)
            for credential in self._rows(self._credentials, org_id):
                if credential.host_id == host_id and credential.expires_at > at:
                    ended = credential.model_copy(update={"expires_at": at})
                    self._put(self._credentials, org_id, ended)
            return revoked

    async def read_placement(self, org_id: UUID, session_id: UUID) -> SessionPlacement | None:
        for placement in self._rows(self._placements, org_id):
            if placement.session_id == session_id:
                return placement
        return None

    async def write_placement(
        self,
        org_id: UUID,
        placement: SessionPlacement,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            stored = await self.read_placement(org_id, placement.session_id)
            stored_version = 0 if stored is None else stored.version
            if stored_version != expected_version or (
                stored is not None and stored.id != placement.id
            ):
                raise PreconditionFailed(
                    f"the placement of session {placement.session_id} is no longer at "
                    f"version {expected_version}"
                )
            if stored is None and placement.id in self._placements:
                raise PreconditionFailed(f"placement {placement.id} is another session's")
            self._put(self._placements, org_id, placement, outbox_rows)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            purged = 0
            for table in (
                self._credentials,
                self._hosts,
                self._tokens,
                self._pools,
                self._placements,
            ):
                gone = [
                    entity_id for entity_id, (row_org, _) in table.items() if row_org == org_id
                ][:limit]
                for entity_id in gone:
                    del table[entity_id]
                purged += len(gone)
            return purged
