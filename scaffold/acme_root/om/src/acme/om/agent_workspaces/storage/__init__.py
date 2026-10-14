"""Storage of the workspaces swimlane: each session's workspace, its isolation
pinned and what the cache knows between loops, each agent project's egress
allowlist, and the record that an agent project's repository has a fetch
credential. Every operation takes org_id first. A write after a create is a
compare-and-set on the version; an allowlist lands with the outbox rows
that announce it, in one commit."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_workspaces.types.credential import RepositoryCredential
from acme.om.agent_workspaces.types.egress import EgressAllowlist
from acme.om.agent_workspaces.types.snapshot import KeptSnapshot
from acme.om.agent_workspaces.types.workspace import AgentSessionWorkspace
from acme.om.outbox.types.row import OutboxRow


class AgentWorkspaceStorageInterface(ABC):
    @abstractmethod
    async def read_workspace(self, org_id: UUID, session_id: UUID) -> AgentSessionWorkspace | None:
        """The session's workspace, or None when it was never pinned."""
        ...

    @abstractmethod
    async def create_workspace(self, org_id: UUID, workspace: AgentSessionWorkspace) -> bool:
        """The pin; False, with nothing landed, when the session's is written
        already."""
        ...

    @abstractmethod
    async def write_workspace(
        self, org_id: UUID, workspace: AgentSessionWorkspace, expected_version: int
    ) -> None:
        """The compare-and-set: lands the workspace when the stored one is at
        `expected_version`, and raises `PreconditionFailed` otherwise,
        landing nothing."""
        ...

    @abstractmethod
    async def read_allowlist(self, org_id: UUID, agent_project_id: UUID) -> EgressAllowlist | None:
        """The agent project's allowlist, or None when it has never written one."""
        ...

    @abstractmethod
    async def create_allowlist(
        self, org_id: UUID, allowlist: EgressAllowlist, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already.
        `UniqueKeyTaken` when the agent project holds another allowlist."""
        ...

    @abstractmethod
    async def write_allowlist(
        self,
        org_id: UUID,
        allowlist: EgressAllowlist,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """The compare-and-set: lands the allowlist and its outbox rows
        together when the stored one is at `expected_version`, and raises
        `PreconditionFailed` otherwise, landing nothing."""
        ...

    @abstractmethod
    async def read_credential(
        self, org_id: UUID, agent_project_id: UUID
    ) -> RepositoryCredential | None:
        """The record of the agent project's fetch credential, or None when it has
        none."""
        ...

    @abstractmethod
    async def create_credential(self, org_id: UUID, credential: RepositoryCredential) -> bool:
        """The first record of an agent project's fetch credential; False, with
        nothing landed, when the agent project has one already."""
        ...

    @abstractmethod
    async def write_credential(
        self, org_id: UUID, credential: RepositoryCredential, expected_version: int
    ) -> None:
        """The compare-and-set: lands the record when the stored one is at
        `expected_version`, and raises `PreconditionFailed` otherwise."""
        ...

    @abstractmethod
    async def read_credentials(self, org_id: UUID, limit: int) -> list[RepositoryCredential]:
        """At most `limit` records of the tenant's fetch credentials, for the
        purge, which takes each value from the store before its record."""
        ...

    @abstractmethod
    async def purge_credentials(self, org_id: UUID, agent_project_ids: list[UUID]) -> int:
        """The records of these agent projects' fetch credentials; returns how many
        went."""
        ...

    @abstractmethod
    async def create_snapshot(self, org_id: UUID, snapshot: KeptSnapshot) -> bool:
        """The record of where a snapshot lives; False, with nothing landed,
        when its id is recorded already."""
        ...

    @abstractmethod
    async def read_snapshot(self, org_id: UUID, snapshot_id: UUID) -> KeptSnapshot | None:
        """The record of the snapshot under `snapshot_id`, or None."""
        ...

    @abstractmethod
    async def read_snapshots(
        self, org_id: UUID, session_id: UUID, limit: int
    ) -> list[KeptSnapshot]:
        """At most `limit` records of the snapshots the session keeps, oldest
        first."""
        ...

    @abstractmethod
    async def purge_snapshots(self, org_id: UUID, session_id: UUID) -> int:
        """The records of every snapshot the session keeps; returns how many
        went."""
        ...

    @abstractmethod
    async def purge_workspace(self, org_id: UUID, session_id: UUID) -> bool:
        """The workspace row of a session its purge has claimed. False when
        none was left."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` workspaces, `limit` allowlists, and `limit`
        records of snapshots of a deleted tenant past its retention; returns
        how many went."""
        ...
