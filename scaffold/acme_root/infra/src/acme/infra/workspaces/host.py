import asyncio
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from acme.infra.workspaces import (
    EgressMode,
    HeldInstance,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    Workspace,
    WorkspaceProviderInterface,
    refusal,
)
from acme.infra.workspaces.stragglers import end_stragglers

HELD = ".held"
"""The suffix of the mark a prepare leaves beside a workspace's directory,
which its release takes away: the directory outlives its release, so the
mark says whether an instance holds it."""


class WorkspaceHostImpl(WorkspaceProviderInterface):
    """A directory on this host, one per workspace, under `root`. A directory
    confines where files go and nothing else: not a process's network, and
    not what it takes of the machine. So it meets the host mode with open
    egress and no resource limit, and refuses any spec that asks for more.
    Its instance is the processes running in it: a release ends what its
    commands left running there, and keeps the files. A prepare marks the
    directory held, beside it and never in it, so no command and no checkout
    sees the mark, and the release or the purge takes the mark away."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def prepare(self, org_id: UUID, workspace_id: UUID, spec: IsolationSpec) -> Workspace:
        why = refusal(spec, mode=IsolationMode.HOST, egress={EgressMode.OPEN}, limits=())
        if why is not None:
            raise IsolationRefused(why)
        directory = self._directory(org_id, workspace_id)
        await asyncio.to_thread(directory.mkdir, mode=0o700, parents=True, exist_ok=True)
        await asyncio.to_thread(self._mark(org_id, workspace_id).touch, mode=0o600)
        return Workspace(id=workspace_id, org_id=org_id, spec=spec, location=str(directory))

    async def release(self, workspace: Workspace) -> None:
        await end_stragglers(self._directory(workspace.org_id, workspace.id))
        await asyncio.to_thread(self._mark(workspace.org_id, workspace.id).unlink, missing_ok=True)

    async def purge(self, org_id: UUID, workspace_id: UUID) -> None:
        directory = self._directory(org_id, workspace_id)
        await end_stragglers(directory)
        await asyncio.to_thread(_removed, directory)
        await asyncio.to_thread(self._mark(org_id, workspace_id).unlink, missing_ok=True)

    async def held(self) -> list[HeldInstance]:
        return await asyncio.to_thread(self._held)

    def describe(self) -> str:
        return f"workspaces=host({self._root})"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _directory(self, org_id: UUID, workspace_id: UUID) -> Path:
        """Named by ids alone, so no name climbs out of the root."""
        return self._root.resolve() / org_id.hex / workspace_id.hex

    def _mark(self, org_id: UUID, workspace_id: UUID) -> Path:
        return self._root.resolve() / org_id.hex / f"{workspace_id.hex}{HELD}"

    def _held(self) -> list[HeldInstance]:
        """Each mark under the root named by two ids in the form a prepare
        writes them; anything else there, such as the transport's records,
        is none of its own."""
        found: list[HeldInstance] = []
        for mark in sorted(self._root.resolve().glob(f"*/*{HELD}")):
            org, workspace = mark.parent.name, mark.name.removesuffix(HELD)
            try:
                org_id, workspace_id = UUID(hex=org), UUID(hex=workspace)
            except ValueError:
                continue
            if (org, workspace) != (org_id.hex, workspace_id.hex):
                continue
            directory = self._directory(org_id, workspace_id)
            found.append(HeldInstance(id=workspace_id, org_id=org_id, location=str(directory)))
        return found


def _removed(directory: Path) -> None:
    """The directory and everything in it gone, a directory a command left
    read-only, or unreadable, included, as a module cache leaves its own.
    One already gone is no error, and a file that still cannot be removed
    is."""
    try:
        shutil.rmtree(directory, onexc=_given_back)
    except FileNotFoundError:
        return


def _given_back(function: Callable[..., object], path: str, error: BaseException) -> None:
    """What `rmtree` could not remove for want of a permission: the
    directory that holds it, and it when it is a directory, are given back
    to their owner, and the removal is tried again. A link is never
    followed, so nothing outside the workspace changes."""
    if isinstance(error, FileNotFoundError):
        return
    if not isinstance(error, PermissionError):
        raise error
    for place in (os.path.dirname(path), path):
        if os.path.isdir(place) and not os.path.islink(place):
            os.chmod(place, stat.S_IRWXU)
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, onexc=_given_back)
    else:
        function(path)
