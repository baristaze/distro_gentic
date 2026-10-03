"""The checkout inside a workspace: the session's branch brought in before a
loop, and what a loop left pushed before its instance goes. A root wires the
transport's (`acme.om.workspaces.impl.git.WorkspaceGitTransportImpl`), which
runs each operation as one command in the workspace, the engine's one way
in, under the epoch of the run that holds the session."""

from abc import ABC, abstractmethod

from acme.infra.workspaces import Workspace
from acme.om.context import TenantContext
from acme.om.workspaces.types.credential import FetchCredential
from acme.om.workspaces.types.source import (
    BranchState,
    Checkout,
    Delivered,
    RepositoryBinding,
    Snapshot,
)


class WorkspaceGitInterface(ABC):
    @abstractmethod
    async def sync(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> BranchState:
        """Points the checkout's `origin` at the bound repository, fetches it,
        and checks out `branch` where the remote or the checkout holds it,
        fast-forwarded to the remote's. Where neither does, nothing is
        checked out, and where the two have diverged, nothing is merged: what
        follows is the caller's (`rules.branch_plan`)."""
        ...

    @abstractmethod
    async def cut(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> None:
        """Checks `branch` out anew from the bound repository's default
        branch as it is fetched now, over whatever the checkout held: the
        caller keeps that first (`snapshot`)."""
        ...

    @abstractmethod
    async def checkout(self, ctx: TenantContext, workspace: Workspace) -> Checkout:
        """What the checkout says of itself: its HEAD and whether it holds
        uncommitted work. The agent can write all of it, so it tells only
        what was not delivered (`RepositoryReaderInterface`)."""
        ...

    @abstractmethod
    async def snapshot(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        binding: RepositoryBinding,
        branch: str,
        ref: str,
    ) -> Snapshot:
        """Commits what the checkout holds uncommitted, beside its branch and
        never on it, and pushes it to `ref` on the bound repository with any
        commit the remote lacks. A clean checkout the remote holds whole
        pushes nothing. Raises when the push does not land, so nothing is let
        go, or cut over, that is not kept."""
        ...


class RepositoryReaderInterface(ABC):
    """What a session delivered, read from the bound repository by the
    platform, outside anything the agent can write: never in its checkout,
    whose config, refs, and replacements the agent holds. A root wires the
    reader that fetches into a fresh repository of the platform's own
    (`acme.om.workspaces.impl.reader.RepositoryReaderGitImpl`)."""

    @abstractmethod
    async def delivered(
        self, binding: RepositoryBinding, branch: str, credential: FetchCredential | None = None
    ) -> Delivered:
        """The bound repository's default branch and the session's `branch`
        there, fetched by the repository's URL: where the branch meets the
        default branch, its head, and every path changed between them, a
        moved file by both its paths. A private repository is read with the
        project's fetch `credential`, which reaches only the read's own git
        and the repository's URL. `Unavailable` when the repository cannot be
        read."""
        ...
