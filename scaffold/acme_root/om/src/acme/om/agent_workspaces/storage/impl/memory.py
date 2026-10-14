from uuid import UUID

from acme.om.agent_workspaces.storage import AgentWorkspaceStorageInterface
from acme.om.agent_workspaces.types.credential import RepositoryCredential
from acme.om.agent_workspaces.types.egress import EgressAllowlist
from acme.om.agent_workspaces.types.snapshot import KeptSnapshot
from acme.om.agent_workspaces.types.workspace import AgentSessionWorkspace
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import HasId, MemoryStorageBase, MemoryTable


class AgentWorkspaceStorageMemoryImpl(MemoryStorageBase, AgentWorkspaceStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._workspaces: MemoryTable[AgentSessionWorkspace] = {}
        self._allowlists: MemoryTable[EgressAllowlist] = {}
        self._credentials: MemoryTable[RepositoryCredential] = {}
        self._snapshots: MemoryTable[KeptSnapshot] = {}

    async def read_workspace(self, org_id: UUID, session_id: UUID) -> AgentSessionWorkspace | None:
        return self._get(self._workspaces, org_id, session_id)

    async def create_workspace(self, org_id: UUID, workspace: AgentSessionWorkspace) -> bool:
        async with self._lock:
            return self._insert(self._workspaces, org_id, workspace)

    async def write_workspace(
        self, org_id: UUID, workspace: AgentSessionWorkspace, expected_version: int
    ) -> None:
        async with self._lock:
            found = self._get(self._workspaces, org_id, workspace.id)
            if found is None or found.version != expected_version:
                raise PreconditionFailed(
                    f"workspace {workspace.id} is no longer at version {expected_version}"
                )
            self._put(self._workspaces, org_id, workspace)

    async def read_allowlist(self, org_id: UUID, project_id: UUID) -> EgressAllowlist | None:
        found = [
            row for row in self._rows(self._allowlists, org_id) if row.project_id == project_id
        ]
        return found[0] if found else None

    async def create_allowlist(
        self, org_id: UUID, allowlist: EgressAllowlist, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if allowlist.id in self._allowlists:
                return False
            # One allowlist a project: the unique index the table holds.
            if await self.read_allowlist(org_id, allowlist.project_id) is not None:
                raise UniqueKeyTaken(
                    f"egress_allowlists {allowlist.id}: the project holds an allowlist"
                )
            return self._insert(self._allowlists, org_id, allowlist, outbox_rows)

    async def write_allowlist(
        self,
        org_id: UUID,
        allowlist: EgressAllowlist,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._lock:
            found = self._get(self._allowlists, org_id, allowlist.id)
            if found is None or found.version != expected_version:
                raise PreconditionFailed(
                    f"egress allowlist {allowlist.id} is no longer at version {expected_version}"
                )
            self._put(self._allowlists, org_id, allowlist, outbox_rows)

    async def read_credential(self, org_id: UUID, project_id: UUID) -> RepositoryCredential | None:
        return self._get(self._credentials, org_id, project_id)

    async def create_credential(self, org_id: UUID, credential: RepositoryCredential) -> bool:
        async with self._lock:
            return self._insert(self._credentials, org_id, credential)

    async def write_credential(
        self, org_id: UUID, credential: RepositoryCredential, expected_version: int
    ) -> None:
        async with self._lock:
            found = self._get(self._credentials, org_id, credential.id)
            if found is None or found.version != expected_version:
                raise PreconditionFailed(
                    f"repository credential {credential.id} is no longer at version "
                    f"{expected_version}"
                )
            self._put(self._credentials, org_id, credential)

    async def read_credentials(self, org_id: UUID, limit: int) -> list[RepositoryCredential]:
        return list(self._rows(self._credentials, org_id))[:limit]

    async def purge_credentials(self, org_id: UUID, project_ids: list[UUID]) -> int:
        async with self._lock:
            gone = [
                row.id for row in self._rows(self._credentials, org_id) if row.id in project_ids
            ]
            for row_id in gone:
                del self._credentials[row_id]
            return len(gone)

    async def create_snapshot(self, org_id: UUID, snapshot: KeptSnapshot) -> bool:
        async with self._lock:
            return self._insert(self._snapshots, org_id, snapshot)

    async def read_snapshot(self, org_id: UUID, snapshot_id: UUID) -> KeptSnapshot | None:
        return self._get(self._snapshots, org_id, snapshot_id)

    async def read_snapshots(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[KeptSnapshot]:
        found = [row for row in self._rows(self._snapshots, org_id) if row.session_id == session_id]
        return sorted(found, key=lambda row: (row.created_at, row.id))[:limit]

    async def purge_snapshots(self, org_id: UUID, session_id: UUID) -> int:
        async with self._lock:
            gone = [
                row.id
                for row in self._rows(self._snapshots, org_id)
                if row.session_id == session_id
            ]
            for row_id in gone:
                del self._snapshots[row_id]
            return len(gone)

    async def purge_workspace(self, org_id: UUID, session_id: UUID) -> bool:
        async with self._lock:
            if self._get(self._workspaces, org_id, session_id) is None:
                return False
            del self._workspaces[session_id]
            return True

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            purged = self._purged(self._workspaces, org_id, limit)
            purged += self._purged(self._allowlists, org_id, limit)
            return purged + self._purged(self._snapshots, org_id, limit)

    def _purged[E: HasId](self, table: MemoryTable[E], org_id: UUID, limit: int) -> int:
        gone = [row.id for row in self._rows(table, org_id)][:limit]
        for row_id in gone:
            del table[row_id]
        return len(gone)
