"""The checkout's operations as commands in the workspace, through the
engine's transport: one shell command each, recorded under a key of its own
and fenced by the epoch of the run that holds the session, so a run that
lost its claim moves nothing. The environment is the transport's, built
from nothing, so no credential of the platform's reaches git; what git
prints is the session's content, sealed in the transport's record like a
tool's.

The snapshot never touches the session's branch, its index, or its files:
it builds its commit in an index of its own, from HEAD and everything the
checkout holds that `.gitignore` keeps, and pushes it beside the branches."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from pydantic import Field

from acme.infra.transports import CommandResult, CommandSpec, RecordSeal, TransportInterface
from acme.infra.workspaces import Workspace
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import TenantContext
from acme.om.exceptions import Unavailable
from acme.om.steps import StepsManagerInterface
from acme.om.tools.seal import RecordSealInterface
from acme.om.workspaces.git import WorkspaceGitInterface
from acme.om.workspaces.types.source import BranchState, Checkout, RepositoryBinding, Snapshot

log = logging.getLogger(__name__)

SYNC = """set -eu
if [ ! -d .git ]; then git init -q .; fi
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REPOSITORY"
else
  git remote add origin "$REPOSITORY"
fi
git fetch -q --prune origin "+refs/heads/*:refs/remotes/origin/*"
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
"""Points `origin` at the bound repository, brings it in, and the branch
out where either side holds it, fast-forwarded to the remote's; prints
whether the remote and the checkout hold it, and whether the checkout
reached the remote's branch."""

CUT = """set -eu
git fetch -q --no-tags "$REPOSITORY" "$BASE"
git checkout -q --force --no-track -B "$BRANCH" FETCH_HEAD
git clean -q -fd
echo cut
"""
"""Cuts the branch anew from the bound repository's default branch as it is
fetched now, over whatever the checkout held: the caller keeps that first."""

SNAPSHOT = """set -eu
if [ ! -d .git ]; then echo "snapshot - no"; exit 0; fi
remote=no
if git ls-remote --exit-code --heads "$REPOSITORY" "$BRANCH" >/dev/null 2>&1; then remote=yes; fi
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
  echo "snapshot - $remote"
  exit 0
fi
git push -q "$REPOSITORY" "$commit:$REF"
echo "snapshot $commit $remote"
"""
"""Commits what the checkout holds uncommitted in an index of its own, or
takes HEAD when only commits the remote lacks are new, and pushes it to the
snapshot ref on the bound repository; prints the commit, or `-` when
nothing was new, and whether the repository holds the branch."""

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


class WorkspaceGitTransportImpl(WorkspaceGitInterface):
    def __init__(
        self,
        transport: TransportInterface,
        steps: StepsManagerInterface,
        record_seal: RecordSealInterface,
        options: GitOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._transport = transport
        self._steps = steps
        self._record_seal = record_seal
        self._options = options
        self._clock = clock

    async def sync(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> BranchState:
        words = await self._run(
            ctx, workspace, "sync", SYNC, {"REPOSITORY": binding.repository, "BRANCH": branch}
        )
        if len(words) != 4 or words[0] != "branch":
            raise Unavailable(f"the checkout of session {workspace.id} answered no branch")
        remote, local, moved = (word == "yes" for word in words[1:])
        return BranchState(remote=remote, local=local, diverged=remote and local and not moved)

    async def cut(
        self, ctx: TenantContext, workspace: Workspace, binding: RepositoryBinding, branch: str
    ) -> None:
        env = {
            "REPOSITORY": binding.repository,
            "BRANCH": branch,
            "BASE": binding.base_ref,
        }
        await self._run(ctx, workspace, "cut", CUT, env)

    async def checkout(self, ctx: TenantContext, workspace: Workspace) -> Checkout:
        words = await self._run(ctx, workspace, "checkout", CHECKOUT, {})
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
    ) -> Snapshot:
        options = self._options
        env = {
            "REPOSITORY": binding.repository,
            "BRANCH": branch,
            "REF": ref,
            "MESSAGE": options.message,
            "GIT_AUTHOR_NAME": options.author,
            "GIT_AUTHOR_EMAIL": options.email,
            "GIT_COMMITTER_NAME": options.author,
            "GIT_COMMITTER_EMAIL": options.email,
        }
        words = await self._run(ctx, workspace, "snapshot", SNAPSHOT, env)
        if len(words) != 3 or words[0] != "snapshot":
            raise Unavailable(f"the snapshot of session {workspace.id} answered nothing")
        commit = None if words[1] == "-" else words[1]
        return Snapshot(ref=ref, commit=commit, remote_branch=words[2] == "yes")

    async def _run(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        operation: str,
        script: str,
        env: dict[str, str],
    ) -> list[str]:
        """The words of the last line a script printed."""
        lines = await self._lines(ctx, workspace, operation, script, env)
        return lines[-1].split() if lines else []

    async def _lines(
        self,
        ctx: TenantContext,
        workspace: Workspace,
        operation: str,
        script: str,
        env: dict[str, str],
    ) -> list[str]:
        """Runs one script under the epoch of the run that holds the session,
        and answers the lines it printed. A script that fails is
        `Unavailable`, named by its exit and never by its output, which is
        the session's content."""
        cursor = await self._steps.get_cursor(ctx, workspace.id)
        key = new_id()
        command = CommandSpec(
            argv=("sh", "-c", script),
            env=tuple(sorted(env.items())),
            key=key,
            epoch=cursor.epoch,
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
