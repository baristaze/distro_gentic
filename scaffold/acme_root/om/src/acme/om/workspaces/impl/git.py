"""The checkout's operations as commands in the workspace, through the
engine's transport: one shell command each, recorded under a key of its own
and fenced by the epoch the run that asks held when it began, never one
read again as each command runs, so a run that lost its claim moves
nothing. The environment is the transport's, built
from nothing, so no credential of the platform's reaches git; what git
prints is the session's content, sealed in the transport's record like a
tool's.

No command here reaches the repository. The platform reads it on its own
host and writes the bundle it made into the checkout's git directory, which
the checkout fetches from (`SYNC`). What goes out goes as a bundle the
platform makes here and reads back (`OUTGOING`), and source control pushes
it with the integration's own credential: the session's branch when its
pull request opens, a snapshot when its instance goes.

The snapshot never touches the session's branch, its index, or its files:
it builds its commit in an index of its own, from HEAD and everything the
checkout holds that `.gitignore` keeps."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from pydantic import Field

from acme.infra.transports import CommandResult, CommandSpec, RecordSeal, TransportInterface
from acme.infra.workspaces import Workspace
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import TenantContext
from acme.om.exceptions import Unavailable
from acme.om.tools.seal import RecordSealInterface
from acme.om.workspaces.git import WorkspaceGitInterface
from acme.om.workspaces.projects import SourceControlInterface
from acme.om.workspaces.types.source import (
    BranchState,
    Checkout,
    Incoming,
    RepositoryBinding,
    Snapshot,
)

log = logging.getLogger(__name__)

INCOMING = ".git/incoming.bundle"
"""Where the platform writes the bundle it brings a checkout, inside the
checkout's git directory, out of its work tree."""
OUTGOING = ".git/outgoing.bundle"
"""Where the platform makes the bundle it takes out of a checkout."""
OUTGOING_REF = "refs/outgoing/head"
"""The ref a bundle taken out is made from, for as long as it is made: a
bundle names refs, never bare commits."""

SYNC = """set -eu
if [ ! -f .git/HEAD ]; then git init -q .; fi
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REPOSITORY"
else
  git remote add origin "$REPOSITORY"
fi
git fetch -q --prune "$BUNDLE" "+refs/heads/*:refs/remotes/origin/*"
rm -f "$BUNDLE"
git symbolic-ref refs/remotes/origin/HEAD "refs/remotes/origin/$DEFAULT"
remote=no
if git rev-parse -q --verify "refs/remotes/origin/$BRANCH" >/dev/null; then remote=yes; fi
held=no
if git rev-parse -q --verify "refs/heads/$BRANCH" >/dev/null; then held=yes; fi
moved=yes
if [ "$held" = yes ]; then
  git checkout -q "$BRANCH"
  if [ "$remote" = yes ] && ! git merge -q --ff-only "refs/remotes/origin/$BRANCH" >/dev/null 2>&1; then
    moved=no
  fi
elif [ "$remote" = yes ]; then
  git checkout -q -b "$BRANCH" --track "origin/$BRANCH"
fi
echo "branch $remote $held $moved"
"""
"""Names `origin` for the bound repository, brings its branches in from the
platform's bundle, with the tags in their history that the checkout does
not hold yet, and the branch out where either side holds it,
fast-forwarded to the remote's; prints whether the remote and the checkout
hold it, and whether the checkout reached the remote's branch."""

CUT = """set -eu
git checkout -q --force --no-track -B "$BRANCH" refs/remotes/origin/HEAD
git clean -q -fd
echo cut
"""
"""Cuts the branch anew from the default branch as the sync just brought it
in, over whatever the checkout held: the caller keeps that first."""

BUNDLE_OUT = """
rm -f "$BUNDLE"
size=0
if [ -n "$(git rev-list -n 1 "$commit" --not --remotes=origin)" ]; then
  git update-ref "$OUTGOING_REF" "$commit"
  git bundle create -q "$BUNDLE" "$OUTGOING_REF" --not --remotes=origin
  git update-ref -d "$OUTGOING_REF"
  size="$(wc -c < "$BUNDLE" | tr -d ' ')"
fi
"""
"""Makes the bundle of `$commit` and what it needs beyond what the remote
held when it was last brought in; leaves `$size` at 0 when that is
nothing."""

SNAPSHOT = (
    """set -eu
if [ ! -d .git ]; then echo "snapshot - no 0"; exit 0; fi
remote=no
if git rev-parse -q --verify "refs/remotes/origin/$BRANCH" >/dev/null; then remote=yes; fi
head=no
if git rev-parse -q --verify HEAD >/dev/null; then head=yes; fi
if [ -n "$(git status --porcelain --untracked-files=all)" ]; then
  index="$(git rev-parse --git-dir)/snapshot-index"
  rm -f "$index"
  if [ "$head" = yes ]; then GIT_INDEX_FILE="$index" git read-tree HEAD; fi
  GIT_INDEX_FILE="$index" git add -A
  tree="$(GIT_INDEX_FILE="$index" git write-tree)"
  rm -f "$index"
  if [ "$head" = yes ]; then
    commit="$(git commit-tree "$tree" -p HEAD -m "$MESSAGE")"
  else
    commit="$(git commit-tree "$tree" -m "$MESSAGE")"
  fi
elif [ "$head" = yes ] && [ -n "$(git rev-list HEAD --not --remotes=origin)" ]; then
  commit="$(git rev-parse HEAD)"
else
  echo "snapshot - $remote 0"
  exit 0
fi
"""
    + BUNDLE_OUT
    + """echo "snapshot $commit $remote $size"
"""
)
"""Commits what the checkout holds uncommitted in an index of its own, or
takes HEAD when only commits the remote lacks are new, and bundles it for
the platform to push to the snapshot ref; prints the commit, or `-` when
nothing was new, whether the remote held the branch when it was last
brought in, and the bundle's size."""

OUTGOING_SCRIPT = (
    """set -eu
commit="$(git rev-parse -q --verify "$COMMIT^{commit}")"
"""
    + BUNDLE_OUT
    + """echo "outgoing $size"
"""
)
"""Bundles the commit the platform names for source control to push, and
prints the bundle's size, 0 when the remote held all of it."""

LANDED = """set -eu
git update-ref "refs/remotes/origin/$BRANCH" "$COMMIT"
echo landed
"""
"""Moves the checkout's view of the remote's branch to what source control
pushed there."""

CHECKOUT = """set -eu
head=-
if git rev-parse -q --verify HEAD >/dev/null; then head="$(git rev-parse HEAD)"; fi
dirty=no
if [ -n "$(git status --porcelain --untracked-files=all)" ]; then dirty=yes; fi
echo "checkout $head $dirty"
"""
"""Prints the checkout's HEAD, `-` before its first commit, and whether it
holds uncommitted work: what the checkout says of itself, which tells only
what was not delivered."""


class GitOptions(Platform):
    # How long one operation may take, the clone and the push included.
    timeout: timedelta = timedelta(minutes=5)
    # Who a snapshot commit names as its author and committer.
    author: str = Field(default="Acme workspaces", min_length=1)
    email: str = Field(default="workspaces@acme.invalid", min_length=3)
    message: str = Field(default="The work a loop left uncommitted, kept before its workspace went")
    # The most bytes a bundle taken out of a checkout holds.
    max_bundle: int = Field(default=512 * 2**20, gt=0)


class WorkspaceGitTransportImpl(WorkspaceGitInterface):
    def __init__(
        self,
        transport: TransportInterface,
        record_seal: RecordSealInterface,
        options: GitOptions,
        source_control: SourceControlInterface,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._transport = transport
        self._record_seal = record_seal
        self._options = options
        self._source_control = source_control
        self._clock = clock

    async def sync(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        binding: RepositoryBinding,
        branch: str,
        incoming: Incoming,
        *,
        epoch: int,
    ) -> BranchState:
        await self._transport.write_file(workspace, INCOMING, incoming.bundle, epoch)
        env = {
            "REPOSITORY": binding.repository,
            "BRANCH": branch,
            "BUNDLE": INCOMING,
            "DEFAULT": incoming.default_branch,
        }
        words = await self._run(ctx, workspace, epoch, "sync", SYNC, env)
        if len(words) != 4 or words[0] != "branch":
            raise Unavailable(f"the checkout of session {workspace.id} answered no branch")
        remote, local, moved = (word == "yes" for word in words[1:])
        return BranchState(remote=remote, local=local, diverged=remote and local and not moved)

    async def cut(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        binding: RepositoryBinding,
        branch: str,
        *,
        epoch: int,
    ) -> None:
        await self._run(ctx, workspace, epoch, "cut", CUT, {"BRANCH": branch})

    async def checkout(self, ctx: TenantContext, workspace: Workspace, *, epoch: int) -> Checkout:
        words = await self._run(ctx, workspace, epoch, "checkout", CHECKOUT, {})
        if len(words) != 3 or words[0] != "checkout":
            raise Unavailable(f"the checkout of session {workspace.id} answered no state")
        return Checkout(head=None if words[1] == "-" else words[1], dirty=words[2] == "yes")

    async def snapshot(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        binding: RepositoryBinding,
        branch: str,
        ref: str,
        *,
        epoch: int,
    ) -> Snapshot:
        options = self._options
        env = {
            "BRANCH": branch,
            "BUNDLE": OUTGOING,
            "OUTGOING_REF": OUTGOING_REF,
            "MESSAGE": options.message,
            "GIT_AUTHOR_NAME": options.author,
            "GIT_AUTHOR_EMAIL": options.email,
            "GIT_COMMITTER_NAME": options.author,
            "GIT_COMMITTER_EMAIL": options.email,
        }
        words = await self._run(ctx, workspace, epoch, "snapshot", SNAPSHOT, env)
        if len(words) != 4 or words[0] != "snapshot" or not words[3].isdigit():
            raise Unavailable(f"the snapshot of session {workspace.id} answered nothing")
        commit = None if words[1] == "-" else words[1]
        if commit is not None:
            bundle = await self._bundle(workspace, int(words[3]))
            await self._source_control.push(binding, ref, commit, bundle)
        return Snapshot(ref=ref, commit=commit, remote_branch=words[2] == "yes")

    async def outgoing(
        self, ctx: TenantContext, workspace: Workspace, head: str, *, epoch: int
    ) -> bytes:
        env = {"COMMIT": head, "BUNDLE": OUTGOING, "OUTGOING_REF": OUTGOING_REF}
        words = await self._run(ctx, workspace, epoch, "outgoing", OUTGOING_SCRIPT, env)
        if len(words) != 2 or words[0] != "outgoing" or not words[1].isdigit():
            raise Unavailable(f"the checkout of session {workspace.id} bundled nothing")
        return await self._bundle(workspace, int(words[1]))

    async def landed(
        self, ctx: TenantContext, workspace: Workspace, branch: str, head: str, *, epoch: int
    ) -> None:
        env = {"BRANCH": branch, "COMMIT": head}
        await self._run(ctx, workspace, epoch, "landed", LANDED, env)

    async def _bundle(self, workspace: Workspace, size: int) -> bytes:
        """The bundle a script made, read back whole: empty when it made none,
        and `Unavailable` past its bound or short of the size it printed."""
        if size == 0:
            return b""
        bound = self._options.max_bundle
        if size > bound:
            raise Unavailable(
                f"the work of session {workspace.id} is past the {bound} bytes taken out at once"
            )
        data = await self._transport.read_file(workspace, OUTGOING, bound + 1)
        if len(data) != size:
            raise Unavailable(f"the bundle of session {workspace.id} changed while it was read")
        return data

    async def _run(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        epoch: int,
        operation: str,
        script: str,
        env: dict[str, str],
    ) -> list[str]:
        """The words of the last line a script printed."""
        lines = await self._lines(ctx, workspace, epoch, operation, script, env)
        return lines[-1].split() if lines else []

    async def _lines(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        epoch: int,
        operation: str,
        script: str,
        env: dict[str, str],
    ) -> list[str]:
        """Runs one script under `epoch`, the one the asking run held when it
        began, and answers the lines it printed. A script that fails is
        `Unavailable`, named by its exit and never by its output, which is
        the session's content."""
        key = new_id()
        command = CommandSpec(
            argv=("sh", "-c", script),
            env=tuple(sorted(env.items())),
            key=key,
            epoch=epoch,
            deadline=self._clock() + self._options.timeout,
        )
        seal = RecordSeal(
            seal=lambda data: self._record_seal.seal(ctx, workspace.id, key, data),
            open=lambda sealed: self._record_seal.open(ctx, workspace.id, key, sealed),
        )
        result: CommandResult = await self._transport.run(workspace, command, seal=seal)
        if result.exit_code != 0:
            log.error(
                "session %s of org %s: the checkout's %s ended %s",
                workspace.id,
                workspace.org_id,
                operation,
                "past its deadline" if result.timed_out else f"with exit {result.exit_code}",
            )
            raise Unavailable(f"the checkout's {operation} of session {workspace.id} failed")
        return result.stdout.strip().splitlines()
