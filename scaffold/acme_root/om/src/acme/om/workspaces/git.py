"""The checkout inside a workspace: the session's branch brought in before a
loop, and what a loop left pushed before its instance goes. A root wires the
transport's (`acme.om.workspaces.impl.git.WorkspaceGitTransportImpl`), which
runs each operation as one command in the workspace, the engine's one way
in, under the epoch of the run that holds the session."""

from abc import ABC, abstractmethod

from acme.infra.workspaces import Workspace
from acme.om.context import TenantContext
from acme.om.workspaces.types.source import BranchState, Checkout, RepositoryBinding, Snapshot


class WorkspaceGitInterface(ABC):
    @abstractmethod
    async def sync(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> BranchState:
        """Clones the bound repository into a workspace that holds none,
        fetches it, and checks out `branch` where the remote or the checkout
        holds it. Where neither does, nothing is checked out: what follows is
        the caller's (`rules.branch_plan`)."""
        ...

    @abstractmethod
    async def cut(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> None:
        """Checks `branch` out anew from the remote's default branch, over
        whatever the checkout held of it."""
        ...

    @abstractmethod
    async def checkout(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding
    ) -> Checkout:
        """What the checkout holds as it stands, read from git and never from
        what the agent says: its base, where its head meets the bound
        repository's default branch as the repository answers it, never a
        ref the checkout holds; its head; whether it is dirty; and every path
        changed from the base, a moved file by both its paths."""
        ...

    @abstractmethod
    async def snapshot(
        self, ctx: TenantContext, workspace: Workspace, branch: str, ref: str
    ) -> Snapshot:
        """Commits what the checkout holds uncommitted, beside its branch and
        never on it, and pushes it to `ref` with any commit the remote lacks.
        A clean checkout the remote holds whole pushes nothing. Raises when
        the push does not land, so nothing is let go that is not kept."""
        ...
