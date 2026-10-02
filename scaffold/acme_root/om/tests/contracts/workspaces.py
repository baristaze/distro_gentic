"""Twins of what the workspaces read from outside: a session's project and
the repository it binds, what source control says of a gone branch, and the
checkout in a workspace, kept in memory."""

from dataclasses import dataclass, field
from uuid import UUID

from acme.infra.workspaces import Workspace
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.base import new_id
from acme.om.context import TenantContext
from acme.om.exceptions import Unavailable
from acme.om.workspaces.git import WorkspaceGitInterface
from acme.om.workspaces.projects import PullRequestsInterface, WorkspaceProjectsInterface
from acme.om.workspaces.types.source import (
    BranchState,
    Checkout,
    PullRequestFate,
    RepositoryBinding,
    Snapshot,
)

REPOSITORY = "https://git.example.com/ajax/app.git"
BASE = "b" * 40
"""The commit the twin's branches start from."""


class ProjectsTwin(WorkspaceProjectsInterface):
    """Every session belongs to one project, which binds `repository`, or
    none when `repository` is None."""

    def __init__(self, repository: str | None = REPOSITORY) -> None:
        self.project_id = new_id()
        self.repository = repository

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return self.project_id

    async def binding_of(self, ctx: TenantContext, project_id: UUID) -> RepositoryBinding | None:
        if self.repository is None or project_id != self.project_id:
            return None
        return RepositoryBinding(project_id=project_id, repository=self.repository)


class PullRequestsTwin(PullRequestsInterface):
    def __init__(self) -> None:
        self.fates: dict[str, PullRequestFate] = {}

    async def fate_of(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str
    ) -> PullRequestFate | None:
        return self.fates.get(branch)


@dataclass
class GitTwin(WorkspaceGitInterface):
    """The remote's branches, the checkout's, whether the checkout holds work
    the remote lacks, and whether a push lands."""

    remote: set[str] = field(default_factory=lambda: set[str]())
    local: set[str] = field(default_factory=lambda: set[str]())
    dirty: bool = False
    refuses_push: bool = False
    pushed: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    head: str = BASE
    diverged: bool = False  # the session's branch moved here and on the remote both
    cuts: list[str] = field(default_factory=lambda: list[str]())

    async def sync(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> BranchState:
        remote, local = branch in self.remote, branch in self.local
        return BranchState(remote=remote, local=local, diverged=remote and local and self.diverged)

    async def cut(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> None:
        self.cuts.append(branch)
        self.local.add(branch)

    async def checkout(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding
    ) -> Checkout:
        changed = ("notes.txt",) if self.dirty else ()
        return Checkout(base=BASE, head=self.head, dirty=self.dirty, changed=changed)

    async def snapshot(
        self, ctx: TenantContext, workspace: Workspace, branch: str, ref: str
    ) -> Snapshot:
        if not self.dirty:
            return Snapshot(ref=ref, remote_branch=branch in self.remote)
        if self.refuses_push:
            raise Unavailable("the push was refused")
        commit = new_id().hex[:12]
        self.pushed[ref] = commit
        return Snapshot(ref=ref, commit=commit, remote_branch=branch in self.remote)
