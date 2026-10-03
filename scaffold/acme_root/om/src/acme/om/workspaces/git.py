"""The checkout inside a workspace: the session's branch brought in before a
loop, and what a loop left pushed before its instance goes. No credential
enters it: the platform reads the bound repository on its own host and
hands the checkout a bundle (`RepositoryReaderInterface.incoming`), and
takes the session's commits out as a bundle it makes there, for source
control to push. A root wires the transport's
(`acme.om.workspaces.impl.git.WorkspaceGitTransportImpl`), which runs each
operation as one command in the workspace, the engine's one way in, under
the epoch of the run that holds the session."""

from abc import ABC, abstractmethod

from acme.infra.workspaces import Workspace
from acme.om.context import TenantContext
from acme.om.workspaces.types.credential import FetchCredential
from acme.om.workspaces.types.source import (
    BranchState,
    Checkout,
    Delivered,
    Incoming,
    RepositoryBinding,
    Snapshot,
)


class WorkspaceGitInterface(ABC):
    @abstractmethod
    async def sync(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        binding: RepositoryBinding,
        branch: str,
        incoming: Incoming,
    ) -> BranchState:
        """Names the checkout's `origin` for the bound repository, brings in
        its branches from the `incoming` bundle, never from the repository
        itself, and checks out `branch` where the remote or the checkout
        holds it, fast-forwarded to the remote's. Where neither does,
        nothing is checked out, and where the two have diverged, nothing is
        merged: what follows is the caller's (`rules.branch_plan`)."""
        ...

    @abstractmethod
    async def cut(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> None:
        """Checks `branch` out anew from the default branch as the last
        `sync` brought it in, over whatever the checkout held: the caller
        keeps that first (`snapshot`)."""
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
        never on it, and has source control push it to `ref` on the bound
        repository with any commit the remote lacks, carried out as a bundle
        the platform makes. A clean checkout the remote holds whole pushes
        nothing. Raises when the push does not land, so nothing is let go, or
        cut over, that is not kept."""
        ...

    @abstractmethod
    async def outgoing(self, ctx: TenantContext, workspace: Workspace, head: str) -> bytes:
        """A git bundle the platform makes of the commit `head` and every
        commit it needs that the remote lacked when it was last brought in;
        empty when the remote held them all. `Unavailable` when the checkout
        holds no such commit, or the bundle is past its bound."""
        ...

    @abstractmethod
    async def landed(
        self, ctx: TenantContext, workspace: Workspace, branch: str, head: str
    ) -> None:
        """Tells the checkout that the remote's `branch` is at `head` now, once
        source control pushed it, so a release keeps no snapshot of work the
        branch holds."""
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

    @abstractmethod
    async def incoming(
        self, binding: RepositoryBinding, branch: str, credential: FetchCredential | None = None
    ) -> Incoming:
        """The bound repository's default branch, and the session's `branch`
        where the repository holds it, fetched by the repository's URL as
        `delivered` fetches them, with the same `credential`, and handed on
        as a bundle with no credential in it. `Unavailable` when the
        repository cannot be read, or the bundle is past its bound."""
        ...
