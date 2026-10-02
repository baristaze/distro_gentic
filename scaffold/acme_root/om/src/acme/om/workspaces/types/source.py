"""What a workspace's checkout is rebuilt from: the repository its project
binds, the session's branch on it and what became of it, a snapshot of work
the last loop left, and a write a call makes there."""

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from acme.om.base import Platform


class RepositoryBinding(Platform):
    """The one repository a project binds: where its sessions' branches and
    pull requests live, and the branch a new one is cut from."""

    project_id: UUID
    repository: str = Field(min_length=1, max_length=500)  # as it is cloned
    default_branch: str = Field(default="main", min_length=1, max_length=200)


class PullRequestFate(StrEnum):
    """Why a session's branch is gone, when source control knows."""

    MERGED = "merged"
    CLOSED = "closed"


class BranchState(Platform):
    """Where the session's branch is, as a workspace's checkout finds it."""

    remote: bool  # the bound repository holds it
    local: bool  # the workspace's checkout holds it
    # Both hold it, and the checkout's has commits the remote's lacks while
    # the remote's has moved too: no fast-forward reaches it.
    diverged: bool = False


class BranchPlan(StrEnum):
    """What a prepare does with the session's branch (`rules.branch_plan`)."""

    TRACK = "track"  # the remote holds it: the work goes on from it
    DIVERGED = "diverged"  # it moved here and there both: the loop fails, loudly
    KEEP = "keep"  # never pushed, and the checkout holds it: the work goes on
    CUT = "cut"  # never pushed, held nowhere: cut from the default branch
    REBUILD = "rebuild"  # gone after its pull request closed: cut again, and told
    LOST = "lost"  # gone, and nothing says why: the loop fails, loudly


class Snapshot(Platform):
    """What a release kept: the commit pushed to the snapshot ref, None when
    the checkout held nothing the remote lacked, and whether the remote
    held the session's branch then."""

    ref: str
    commit: str | None = None
    remote_branch: bool = False


class Checkout(Platform):
    """What the checkout holds now: the commit its branch started from on the
    default branch, its committed head, whether it holds uncommitted work,
    and every path changed from that base, committed or not."""

    base: str
    head: str
    dirty: bool = False
    changed: tuple[str, ...] = ()


class WriteKind(StrEnum):
    PUSH = "push"  # a ref moved on the remote
    # A pull request opened, edited, or commented on, named by its head.
    PULL_REQUEST = "pull_request"
    OTHER = "other"  # anything else: an issue, a release, a setting


class RepositoryWrite(Platform):
    """A write a call makes to source control: the repository, what kind of
    write, and the ref it touches, a pushed ref or a pull request's head."""

    repository: str = Field(min_length=1, max_length=500)
    kind: WriteKind
    ref: str = Field(default="", max_length=255)
