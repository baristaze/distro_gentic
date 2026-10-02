"""Storage of the workspaces swimlane: each session's workspace, its isolation
pinned and what the cache knows between loops, and each project's egress
allowlist. Every operation takes org_id first. A write after a create is a
compare-and-set on the version; an allowlist lands with the outbox rows
that announce it, in one commit."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.outbox.types.row import OutboxRow
from acme.om.workspaces.types.egress import EgressAllowlist
from acme.om.workspaces.types.workspace import SessionWorkspace


class WorkspaceStorageInterface(ABC):
    @abstractmethod
    async def read_workspace(self, org_id: UUID, session_id: UUID) -> SessionWorkspace | None:
        """The session's workspace, or None when it was never pinned."""
        ...

    @abstractmethod
    async def create_workspace(self, org_id: UUID, workspace: SessionWorkspace) -> bool:
        """The pin; False, with nothing landed, when the session's is written
        already."""
        ...

    @abstractmethod
    async def write_workspace(
        self, org_id: UUID, workspace: SessionWorkspace, expected_version: int
    ) -> None:
        """The compare-and-set: lands the workspace when the stored one is at
        `expected_version`, and raises `PreconditionFailed` otherwise,
        landing nothing."""
        ...

    @abstractmethod
    async def read_allowlist(self, org_id: UUID, project_id: UUID) -> EgressAllowlist | None:
        """The project's allowlist, or None when it has never written one."""
        ...

    @abstractmethod
    async def create_allowlist(
        self, org_id: UUID, allowlist: EgressAllowlist, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already.
        `UniqueKeyTaken` when the project holds another allowlist."""
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
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` workspaces and `limit` allowlists of a deleted
        tenant past its retention; returns how many went."""
        ...
