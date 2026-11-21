"""A session of the cloud pool kept by snapshots, through the platform's
tools over the pool on the VMs' twin (ADR 2070). The relay is played by
the transport a VM's host runs, over the VM's folder on the twin, so the
directory is packed, read out, and brought back by the same commands a
VM's host runs. A run's end keeps the directory alone, as sealed parts in
the snapshots bucket, and its release lets the VM go: the VMs keep no
disk of it, under the session's names or any other. The next run's VM
starts from the pool's image and holds the same files, and nothing of what
was written outside the directory. A directory past the bound is refused
before it is packed. An archive that fails part way keeps no part, the
snapshot before stays the latest, and its VM stays; a restore that fails
part way lets its new VM go and touches nothing kept. The sweep removes
the archives of a session idle past 30 days, by its last activity, and
keeps a newer one's."""

import asyncio
from collections.abc import Awaitable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from unit.test_cloud_pool import IMAGE, PREFIX, Placed, Pool, stage

from acme.infra.agent_workspaces import (
    AgentWorkspace,
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    SnapshotRefused,
)
from acme.infra.buckets import Buckets, BucketsInterface
from acme.infra.buckets.local import BucketsLocalImpl
from acme.infra.exceptions import BackendFailed
from acme.infra.impl.local import InfraLocalImpl
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.pool_vm import TransportPoolVmImpl
from acme.infra.vms import VmState
from acme.om.agent_steps.types.agent_step import AgentStep, AgentStepType
from acme.om.agent_steps.types.header import AgentWorkspaceSnapshot, SnapshotHeader, SnapshotHolds
from acme.om.agent_workspaces.impl.pool_directory import KEPT as PACKS
from acme.om.agent_workspaces.impl.tools import ToolsManagerAgentWorkspacesImpl
from acme.om.agent_workspaces.types.host import HostOffer
from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.impl.manager import CloudPoolOptions
from acme.om.cloud_pool.types.archive import PoolArchive
from acme.om.context import TenantContext
from acme.om.hosts.types.placement import PlacementState
from acme.om.platform_root import PlatformRootOptions, build_platform_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tools.impl.manager import ToolsOptions
from acme.om.tools.impl.snapshots import BUCKET, SnapshotStore, session_prefix, snapshot_key
from acme.om.tools.seal import RecordSealInterface

from contracts.agent_session_storage import stored_session
from contracts.agent_workspaces import ReaderTwin
from contracts.factories import make_org
from contracts.loops import ASSISTANT
from contracts.platform_loops import PlatformLoop, platform_loop_over

PART = 1024
"""A part as small as a case's files, so an archive is many parts."""
KEPT = IsolationSpec(
    mode=IsolationMode.VM,
    egress=EgressPolicy(mode=EgressMode.OPEN),
    durability=Durability.SNAPSHOT,
)
KEEPER = ASSISTANT.model_copy(update={"name": "pool_keeper", "isolation": KEPT})
PLAIN = "the plain words of the notes, " * 200
"""What a command writes into the directory: longer than a part, so it
spans several, and plain, so a part that held it in the clear would show
it."""


class Plain(RecordSealInterface):
    """A command's record kept as it is: these cases read no record."""

    async def seal(
        self, ctx: TenantContext, agent_session_id: UUID, key: UUID, data: bytes
    ) -> bytes | None:
        return data

    async def open(
        self, ctx: TenantContext, agent_session_id: UUID, key: UUID, sealed: bytes
    ) -> bytes | None:
        return sealed


class FlakyBuckets(BucketsLocalImpl):
    """The local buckets, whose puts fail once `fail_after` more have held."""

    fail_after: int | None = None

    async def put(self, *args: Any, **kwargs: Any) -> None:
        if self.fail_after is not None:
            if self.fail_after == 0:
                raise BackendFailed("buckets", "put", "the store went away")
            self.fail_after -= 1
        await super().put(*args, **kwargs)


class FlakyInfra(InfraLocalImpl):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.buckets = FlakyBuckets(root / "flaky-buckets")

    def get_buckets(self) -> BucketsInterface:
        return self.buckets


class InTheVm(Placed):
    """The relay's side of a prepare: the workspace the VM's host holds, a
    folder of the VM that serves the session, on the twin."""

    def __init__(self, pool: Pool) -> None:
        super().__init__()
        self.pool = pool

    async def held_on_host(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: object = None,
        *,
        pooled: PlacementState | None = None,
    ) -> AgentWorkspace:
        vm = await self.pool.storage.read_of_session(ctx.org_id, agent_session_id)
        assert vm is not None
        directory = self.pool.vms.root / vm.name / "workspace"
        directory.mkdir(mode=0o700, exist_ok=True)
        return AgentWorkspace(
            id=agent_session_id, org_id=ctx.org_id, spec=spec, location=str(directory)
        )


class Kept:
    """A platform's loop whose sessions of a VM run on the cloud pool, over
    the twin, and the platform's tools over it, as the runner wires them."""

    def __init__(self, tmp_path: Path, *, bound: int | None = None) -> None:
        self.infra = FlakyInfra(tmp_path / "infra")
        options = ToolsOptions(snapshot_part_bytes=PART)
        if bound is not None:
            options = options.model_copy(update={"directory_bound": bound})
        self.loop: PlatformLoop = platform_loop_over(
            tmp_path,
            kinds=(KEEPER,),
            infra=self.infra,
            platform=replace(PlatformRootOptions(), workspace_reader=ReaderTwin()),
            tools_options=options,
        )
        self.pool = Pool(tmp_path / "pool")
        self.pool.placed = InTheVm(self.pool)
        # A sudo that refuses, so every command runs as this user.
        shims = tmp_path / "shims"
        shims.mkdir()
        (shims / "sudo").write_text("#!/bin/sh\nexit 1\n")
        (shims / "sudo").chmod(0o755)
        self.transport = TransportPoolVmImpl(
            tmp_path / "records",
            SecretsLocalImpl(tmp_path / "secrets"),
            BrokerNullImpl(),
            search_path=f"{shims}:/usr/bin:/bin",
        )
        inner = self.loop.managers.tools
        self.snapshots: SnapshotStore = inner._snapshots  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
        self.tools = ToolsManagerAgentWorkspacesImpl(
            inner,
            self.loop.platform.agent_workspaces,
            self.loop.managers.agent_steps,
            HostOffer(),
            local=True,
            snapshots=self.snapshots,
            keyed_hash=self.loop.managers.privacy.keyed_hash,
            cloud=self.pool.manager,
            transport=self.transport,
            record_seal=Plain(),
        )

    @property
    def owner(self) -> TenantContext:
        return self.loop.owner

    async def with_host(self, agent_session_id: UUID, asked: Awaitable[Any]) -> Any:
        """`asked`, while the VM's host comes for the session's VM."""
        host = asyncio.ensure_future(self.pool.host_comes(agent_session_id))
        try:
            return await asked
        finally:
            host.cancel()

    async def prepared(
        self, agent_session_id: UUID, restore: AgentWorkspaceSnapshot | None = None
    ) -> tuple[AgentWorkspace, int]:
        epoch = await self.loop.managers.agent_steps.begin_run(self.owner, agent_session_id)
        workspace = await self.with_host(
            agent_session_id,
            self.tools.prepare_agent_workspace(self.owner, agent_session_id, KEPT, restore=restore),
        )
        return cast(AgentWorkspace, workspace), epoch

    async def kept(self, workspace: AgentWorkspace, epoch: int) -> AgentWorkspaceSnapshot:
        """The run's end: the directory kept, then the release."""
        step = await self.tools.snapshot_agent_workspace(
            self.owner, workspace.id, workspace, epoch=epoch, loop_id=new_id(), tools=()
        )
        await self.tools.release_agent_workspace(self.owner, workspace)
        return named(step)

    async def stored(self, agent_session_id: UUID) -> dict[str, bytes]:
        """Every blob the session's snapshots keep, by key."""
        buckets = self.infra.buckets
        org = self.owner.org_id
        keys = await buckets.list(org, BUCKET, session_prefix(agent_session_id), 1000)
        return {key: await buckets.get(org, BUCKET, key) for key in keys}

    async def history(self, agent_session_id: UUID) -> list[AgentWorkspaceSnapshot]:
        steps = await self.loop.history(agent_session_id)
        return [named(step) for step in steps if step.type is AgentStepType.SNAPSHOTTED]


def named(step: AgentStep) -> AgentWorkspaceSnapshot:
    assert isinstance(step.header, SnapshotHeader)
    return step.header.snapshot


def written(workspace: AgentWorkspace, text: str) -> Path:
    """A run's command: its notes in the directory, deep and shallow, and a
    line outside it, as an install leaves one in the VM."""
    directory = Path(workspace.location)
    (directory / "deep").mkdir(exist_ok=True)
    (directory / "notes.txt").write_text(text)
    (directory / "deep" / "more.txt").write_text(text[::-1])
    (directory.parent / "installed.txt").write_text("outside the directory")
    return directory


def no_disk_kept(pool: Pool) -> bool:
    """Whether no snapshot of a disk was ever asked of the VMs' backend."""
    return not [call for call in pool.vms.calls if call[0] == "snapshot"]


@pytest.fixture
async def kept(tmp_path: Path) -> Kept:
    made = Kept(tmp_path)
    await made.pool.image()
    return made


async def test_a_run_keeps_the_directory_in_sealed_parts_its_vm_goes_and_the_next_holds_it(
    kept: Kept,
) -> None:
    agent_session_id = await kept.loop.start(KEEPER.name)
    workspace, epoch = await kept.prepared(agent_session_id)
    written(workspace, PLAIN)

    snapshot = await kept.kept(workspace, epoch)

    assert snapshot.holds is SnapshotHolds.DIRECTORY and snapshot.size > PART
    stored = await kept.stored(agent_session_id)
    parts = [key for key in stored if f"/workspace/{snapshot.id}/part-" in key]
    assert len(parts) > 2, "the directory in parts"
    assert snapshot_key(agent_session_id, snapshot.hash) in stored, "and the manifest"
    assert not any(b"plain words" in blob for blob in stored.values()), "each part sealed"
    record = await kept.loop.platform.agent_workspaces.kept_snapshot(kept.owner, snapshot.id)
    assert record is not None and not record.on_host
    assert record.reference == snapshot_key(agent_session_id, snapshot.hash)
    assert await kept.pool.rows() == [], "the VM went with the run's release"
    assert await kept.pool.vms.names(PREFIX) == [IMAGE], "no disk of it under any name"
    assert no_disk_kept(kept.pool)

    restored, epoch = await kept.prepared(agent_session_id, restore=snapshot)

    directory = Path(restored.location)
    assert directory != Path(workspace.location), "a new VM"
    assert (directory / "notes.txt").read_text() == PLAIN
    assert (directory / "deep" / "more.txt").read_text() == PLAIN[::-1]
    assert not (directory.parent / "installed.txt").exists(), "outside it, the image's again"
    assert not (directory / PACKS).exists(), "no part left in the directory"
    (row,) = await kept.pool.rows()
    assert row.restored_from == snapshot.id

    written(restored, "the second run's notes")
    again = await kept.kept(restored, epoch)
    assert [s.id for s in await kept.history(agent_session_id)] == [snapshot.id, again.id]
    assert await kept.pool.vms.names(PREFIX) == [IMAGE], "after each run, no disk kept"
    assert no_disk_kept(kept.pool)


async def test_a_directory_past_the_bound_is_refused_before_it_is_packed(
    tmp_path: Path,
) -> None:
    kept = Kept(tmp_path, bound=1000)
    await kept.pool.image()
    agent_session_id = await kept.loop.start(KEEPER.name)
    workspace, epoch = await kept.prepared(agent_session_id)
    directory = written(workspace, PLAIN)

    with pytest.raises(SnapshotRefused, match=r"holds \d+ bytes, past the bound of 1000"):
        await kept.tools.snapshot_agent_workspace(
            kept.owner, agent_session_id, workspace, epoch=epoch, loop_id=new_id(), tools=()
        )

    assert await kept.stored(agent_session_id) == {}, "nothing sent"
    assert not (directory / PACKS).exists(), "nothing packed"
    await kept.tools.release_agent_workspace(kept.owner, workspace)
    assert len(await kept.pool.rows()) == 1, "a VM no snapshot holds stays"


async def test_an_archive_that_fails_part_way_keeps_no_part_and_the_snapshot_before_stays(
    kept: Kept,
) -> None:
    agent_session_id = await kept.loop.start(KEEPER.name)
    workspace, epoch = await kept.prepared(agent_session_id)
    written(workspace, PLAIN)
    first = await kept.kept(workspace, epoch)
    before = await kept.stored(agent_session_id)
    workspace, epoch = await kept.prepared(agent_session_id, restore=first)
    written(workspace, PLAIN + " and more")

    kept.infra.buckets.fail_after = 2
    with pytest.raises(BackendFailed, match="the store went away"):
        await kept.tools.snapshot_agent_workspace(
            kept.owner, agent_session_id, workspace, epoch=epoch, loop_id=new_id(), tools=()
        )
    kept.infra.buckets.fail_after = None

    assert await kept.stored(agent_session_id) == before, "no part of it kept"
    assert [s.id for s in await kept.history(agent_session_id)] == [first.id]
    assert not (Path(workspace.location) / PACKS).exists(), "its pack dropped"
    await kept.tools.release_agent_workspace(kept.owner, workspace)
    (row,) = await kept.pool.rows()
    assert await kept.pool.vms.state(row.name) is VmState.RUNNING, "a VM no snapshot holds stays"
    assert (Path(workspace.location) / "notes.txt").read_text().endswith("and more")


async def test_a_restore_that_fails_part_way_lets_its_vm_go_and_touches_nothing_kept(
    kept: Kept, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_session_id = await kept.loop.start(KEEPER.name)
    workspace, epoch = await kept.prepared(agent_session_id)
    written(workspace, PLAIN)
    snapshot = await kept.kept(workspace, epoch)
    before = await kept.stored(agent_session_id)
    write = kept.transport.write_file
    sent: list[str] = []

    async def cut(workspace: AgentWorkspace, path: str, data: bytes, epoch: int) -> None:
        if len(sent) == 2:
            raise BackendFailed("relay", "write", "the host went away")
        sent.append(path)
        await write(workspace, path, data, epoch)

    monkeypatch.setattr(kept.transport, "write_file", cut)
    with pytest.raises(BackendFailed, match="the host went away"):
        await kept.prepared(agent_session_id, restore=snapshot)
    monkeypatch.undo()

    assert await kept.pool.rows() == [], "its VM went: no half-restored directory stands"
    assert await kept.stored(agent_session_id) == before, "the archive as it was"
    assert [s.id for s in await kept.history(agent_session_id)] == [snapshot.id]

    restored, _ = await kept.prepared(agent_session_id, restore=snapshot)
    assert (Path(restored.location) / "notes.txt").read_text() == PLAIN


# The sweep removes a session's archives once it is idle past 30 days.


async def test_the_sweep_removes_an_idle_sessions_archives_and_keeps_a_newer_ones(
    tmp_path: Path,
) -> None:
    storage = StorageMemoryImpl()
    infra = InfraLocalImpl(tmp_path)
    managers = build_platform_managers(
        storage,
        infra,
        platform_root_options=PlatformRootOptions(
            cloud_pool_options=CloudPoolOptions(prefix=PREFIX, image=IMAGE),
            cloud_pool_stage=stage,
        ),
    )
    org = make_org()
    await storage.get_tenancy_storage().write_org(org.id, org)
    buckets, rows = infra.get_buckets(), storage.get_cloud_pool_storage()
    now = utcnow()

    async def archived(idle: timedelta, kept_at: datetime) -> UUID:
        session = stored_session().model_copy(update={"updated_at": now - idle})
        await storage.get_agent_session_storage().create_agent_session(org.id, session, ())
        key = session_prefix(session.id) + f"workspace/{new_id()}/part-0000"
        await buckets.put(org.id, Buckets.SNAPSHOTS, key, b"sealed", "application/octet-stream")
        await rows.keep_archive(
            PoolArchive(
                id=new_id(),
                created_at=kept_at,
                tenant_id=org.id,
                agent_session_id=session.id,
                kept_at=kept_at,
            )
        )
        return session.id

    month = timedelta(days=30)
    idle = await archived(month + timedelta(days=1), now - month - timedelta(days=1))
    active = await archived(timedelta(days=2), now - month - timedelta(days=3))
    newer = await archived(timedelta(days=1), now - timedelta(days=1))

    await managers.cloud_pool.sweep(stage())

    async def held(agent_session_id: UUID) -> list[str]:
        return await buckets.list(org.id, Buckets.SNAPSHOTS, session_prefix(agent_session_id), 10)

    assert await held(idle) == [], "idle past 30 days: its archives went"
    assert len(await held(active)) == 1 and len(await held(newer)) == 1
    standing = {a.agent_session_id: a.kept_at for a in await rows.read_archives(now, 10)}
    assert idle not in standing
    assert standing[active] == now - timedelta(days=2), "moved to its last activity"
