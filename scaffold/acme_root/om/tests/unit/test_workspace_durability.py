"""A workspace's durability as the platform runs it, over the memory roots,
the twin provider, and the local buckets. A kind chooses `cache`, the
default, or `snapshot`, and an agent project narrows it to a cache; a session that
keeps no content at rest is refused a workspace kept by snapshots. A cache
takes no snapshot, and its next loop starts from its branch. A workspace a
snapshot restores keeps the tree it holds: no branch is brought over it. A
provider that refuses for good what a prepare asks beyond its isolation
ends the loop with its reason. Past a session's content's life, the sweep
takes its snapshots from the bucket and their records. A workspace a host
holds inside its tenant's wall is snapshotted by that host, and restored
there from a snapshot decided before any host is asked."""

import logging
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from acme.infra.agent_workspaces import (
    AgentWorkspaceLost,
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
    AgentWorkspace,
)
from acme.infra.agent_workspaces.twin import AgentWorkspaceTwinImpl
from acme.infra.buckets import Buckets
from acme.infra.impl.local import InfraLocalImpl
from acme.infra.keys.memory import KeyServiceMemoryImpl
from acme.om.agent_projects.impl.retention import SessionAgentProjectBoundImpl
from acme.om.agent_steps.types.agent_step import AgentStepType, AgentStep
from acme.om.agent_steps.types.header import AgentWorkspaceSnapshot, LoopOutcome, ParkReason
from acme.om.agent_workspaces.impl.tools import PinnedToolsOptions, ToolsManagerAgentWorkspacesImpl
from acme.om.agent_workspaces.placed import PlacedWorkspacesInterface
from acme.om.agent_workspaces.rules import session_branch
from acme.om.agent_workspaces.types.host import HostOffer
from acme.om.agent_workspaces.types.snapshot import HostSnapshot
from acme.om.agents.types.kind import AgentKind
from acme.om.agents.types.request import Start
from acme.om.base import OmBase, new_id, utcnow
from acme.om.context import RequestContext, TenantContext
from acme.om.exceptions import NotFound, ValidationFailed
from acme.om.hosts.types.placement import PlacementState
from acme.om.platform_root import PlatformRootOptions
from acme.om.privacy.types.agent_session_privacy import StorageMode
from acme.om.retention.impl.keys import TenantKeysImpl
from acme.om.retention.impl.manager import RetentionManagerImpl, RetentionOptions
from acme.om.retention.types.policy import RetentionPolicy
from acme.om.tools.impl.snapshots import session_prefix
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput

from contracts.agent_project_storage import make_agent_project
from contracts.agent_workspaces import AgentProjectsTwin, GitTwin, ReaderTwin
from contracts.doubles import APP
from contracts.loops import ASSISTANT, Asked, Found, Lookup, call, reply, said
from contracts.platform_loops import PlatformLoop, platform_loop_over

KEPT = IsolationSpec(
    mode=IsolationMode.TWIN,
    egress=EgressPolicy(mode=EgressMode.NONE),
    durability=Durability.SNAPSHOT,
)
CACHED = KEPT.model_copy(update={"durability": Durability.CACHE})
WEEK, DAY = timedelta(days=7), timedelta(days=1)


class Scribble(Lookup):
    """A command's writes, on the twin: its input becomes all the
    workspace's files hold."""

    def __init__(self, twin: AgentWorkspaceTwinImpl) -> None:
        super().__init__("scribble", effect=Effect.IDEMPOTENT, authorization_class=ToolClass.WRITE)
        self._twin = twin

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> OmBase:
        assert isinstance(call_input, Asked)
        self._twin.files[runtime.agent_session_id] = call_input.q.encode()
        return Found(text="written")


@dataclass
class Syncs(GitTwin):
    """The git twin, counting each time a checkout is brought up to its
    branch."""

    synced: list[str] = field(default_factory=lambda: list[str]())

    async def sync(self, *args: Any, **kwargs: Any) -> Any:
        self.synced.append(str(args[3]))
        return await super().sync(*args, **kwargs)


def kind(name: str, spec: IsolationSpec) -> AgentKind:
    return ASSISTANT.model_copy(
        update={"name": name, "isolation": spec, "tools": (*ASSISTANT.tools, "scribble")}
    )


KEEPER = kind("keeper", KEPT)
CACHER = kind("cacher", CACHED)


def kept_loop(tmp_path: Path, **over: Any) -> tuple[PlatformLoop, AgentWorkspaceTwinImpl]:
    infra = InfraLocalImpl(tmp_path)
    twin = infra.get_agent_workspaces()
    assert isinstance(twin, AgentWorkspaceTwinImpl)
    platform = over.pop("platform", None) or PlatformRootOptions()
    reader = platform.workspace_reader or ReaderTwin()
    loop = platform_loop_over(
        tmp_path,
        kinds=(KEEPER, CACHER),
        infra=infra,
        extra=(Scribble(twin),),
        platform=replace(platform, workspace_reader=reader),
        **over,
    )
    return loop, twin


async def wrote(loop: PlatformLoop, agent_session_id: UUID, files: str) -> LoopOutcome | None:
    await loop.say(agent_session_id, "Write it.")
    loop.anthropic.add(reply(call("scribble", q=files)), reply(said("Written.")))
    return (await loop.loops.run(loop.owner, agent_session_id)).outcome


def of_type(steps: list[AgentStep], step_type: AgentStepType) -> list[AgentStep]:
    return [step for step in steps if step.type is step_type]


async def in_bucket(loop: PlatformLoop, agent_session_id: UUID) -> list[str]:
    buckets = loop.infra.get_buckets()
    return await buckets.list(
        loop.owner.org_id, Buckets.SNAPSHOTS, session_prefix(agent_session_id), 50
    )


def prepares(twin: AgentWorkspaceTwinImpl, monkeypatch: pytest.MonkeyPatch) -> list[bytes | None]:
    """The snapshot each prepare of the twin starts from, in order."""
    started: list[bytes | None] = []
    prepare = twin.prepare

    async def spied(
        org_id: UUID,
        agent_workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> AgentWorkspace:
        started.append(snapshot)
        return await prepare(org_id, agent_workspace_id, spec, snapshot, base, building=building)

    monkeypatch.setattr(twin, "prepare", spied)
    return started


# Who chooses: a kind, narrowed by an agent project; refused without content at rest.


async def test_a_kept_kind_is_pinned_kept_and_an_agent_project_that_keeps_caches_narrows_it(
    tmp_path: Path,
) -> None:
    loop, _ = kept_loop(tmp_path)
    kept = await loop.start(KEEPER.name)
    agent_projects = loop.platform.agent_projects
    caches = await agent_projects.create_agent_project(
        loop.owner, make_agent_project().model_copy(update={"workspace_snapshots": False})
    )
    narrowed = await agent_projects.start_agent_session(
        loop.owner, caches.id, Start(id=new_id(), kind=KEEPER.name, title="a cache")
    )
    workspaces = loop.platform.agent_workspaces

    pinned = await workspaces.get_workspace(loop.owner, kept)
    assert (
        pinned.durability is Durability.SNAPSHOT and pinned.spec().durability is Durability.SNAPSHOT
    )
    cached = await workspaces.get_workspace(loop.owner, narrowed.id)
    assert cached.durability is Durability.CACHE, "its agent project keeps its workspaces as caches"


async def test_a_session_that_keeps_no_content_at_rest_is_refused_a_kept_workspace(
    tmp_path: Path,
) -> None:
    """Every snapshot of it would be refused and its instance kept live for
    good: refused at its creation, never pinned as a cache in its stead. A
    cache of the same tenant is created."""
    loop, _ = kept_loop(tmp_path)
    retention = loop.platform.retention
    policy = await retention.get_policy(loop.owner)
    nothing_at_rest = RetentionPolicy(storage_mode=StorageMode.MEMORY_ONLY)
    await retention.write_policy(loop.owner, policy.model_copy(update={"policy": nothing_at_rest}))

    with pytest.raises(ValidationFailed, match="keeps no content at rest"):
        await loop.start(KEEPER.name)

    cache = await loop.start(CACHER.name)
    assert (await loop.platform.agent_workspaces.get_workspace(loop.owner, cache)).durability is (
        Durability.CACHE
    )


# Check 2: a cache takes no snapshot, and its next loop starts from its branch.


async def test_a_cache_sessions_release_takes_no_snapshot_and_its_next_loop_starts_from_its_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = Syncs()
    loop, twin = kept_loop(
        tmp_path,
        platform=PlatformRootOptions(
            workspace_agent_projects=AgentProjectsTwin(), workspace_git=git
        ),
    )
    started = prepares(twin, monkeypatch)
    agent_session_id = await loop.start(CACHER.name)
    branch = session_branch(agent_session_id)

    assert await wrote(loop, agent_session_id, "built once") is LoopOutcome.SUCCEEDED
    assert await wrote(loop, agent_session_id, "built again") is LoopOutcome.SUCCEEDED

    assert not of_type(await loop.history(agent_session_id), AgentStepType.SNAPSHOTTED), (
        "no snapshot"
    )
    assert await in_bucket(loop, agent_session_id) == []
    assert await loop.platform.agent_workspaces.kept_snapshots(loop.owner, agent_session_id) == ()
    assert started == [None, None], "each loop starts from no snapshot"
    assert git.cuts == [branch], "its first loop cut the branch, and the next kept it"
    assert git.synced == [branch, branch], "each loop's checkout was brought up to its branch"
    assert twin.live == set(), "each instance was let go"


# A restore is never undone by the branch.


async def test_a_restored_workspace_keeps_its_tree_and_no_branch_is_brought_over_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The next run starts from the snapshot the last one took. Its branch
    moved on its repository and in the checkout both since, which a sync
    would park for a person: nothing of the branch is brought over the
    restored tree, so the run goes on from what the snapshot holds."""
    git = Syncs()
    loop, twin = kept_loop(
        tmp_path,
        platform=PlatformRootOptions(
            workspace_agent_projects=AgentProjectsTwin(), workspace_git=git
        ),
    )
    started = prepares(twin, monkeypatch)
    agent_session_id = await loop.start(KEEPER.name)
    branch = session_branch(agent_session_id)
    assert await wrote(loop, agent_session_id, "as the run left it") is LoopOutcome.SUCCEEDED
    (taken,) = of_type(await loop.history(agent_session_id), AgentStepType.SNAPSHOTTED)
    git.remote.add(branch)
    git.diverged = True

    await loop.say(agent_session_id, "Go on.")
    loop.anthropic.add(reply(said("Going on.")))
    ran = await loop.loops.run(loop.owner, agent_session_id)

    assert ran.outcome is LoopOutcome.SUCCEEDED, "never parked over a branch it did not sync"
    assert started[-1] is not None, "the run started from the snapshot"
    assert twin.files[agent_session_id] == b"as the run left it"
    assert git.cuts == [branch] and git.synced == [branch], "no branch was brought over it"
    (record, *_) = await loop.platform.agent_workspaces.kept_snapshots(loop.owner, agent_session_id)
    assert record.id == taken.header.snapshot.id and not record.on_host, "in the bucket"  # type: ignore[union-attr]


# A refusal for good of what a prepare asks beyond its isolation.


@pytest.mark.parametrize(
    ("asked", "ends"),
    [(KEEPER, LoopOutcome.ERRORED), (CACHER, None)],
    ids=["kept by snapshots: ends errored", "a cache: waits for a host"],
)
async def test_a_refusal_for_good_of_a_kept_workspace_ends_the_loop_with_its_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    asked: AgentKind,
    ends: LoopOutcome | None,
) -> None:
    """A provider that cannot snapshot refuses a workspace kept by snapshots
    on every host like it: the loop ends with the reason, never a wait that
    no host ends. A refusal of the isolation alone waits on the resource,
    since another host may give it."""
    loop, twin = kept_loop(tmp_path)
    reason = "a twin workspace cannot be snapshotted: its store is not encrypted at rest"

    async def refuses(*args: Any, **kwargs: Any) -> AgentWorkspace:
        raise IsolationRefused(reason)

    monkeypatch.setattr(twin, "prepare", refuses)
    agent_session_id = await loop.start(asked.name)
    await loop.say(agent_session_id, "Install the tool.")

    with caplog.at_level(logging.WARNING):
        ran = await loop.loops.run(loop.owner, agent_session_id)

    history = await loop.history(agent_session_id)
    assert not of_type(history, AgentStepType.MODEL_REQUEST), "no call spent"
    if ends is not None:
        assert ran.outcome is ends
        assert any(reason in record.getMessage() for record in caplog.records)
    else:
        session = await loop.managers.agent_sessions.get_agent_session(loop.owner, agent_session_id)
        assert session.park is not None and session.park.reason is ParkReason.LEASABLE_RESOURCE


# Check 5: the sweep takes a session's snapshots with its content.


async def test_the_sweep_takes_a_sessions_snapshots_past_its_contents_life(
    tmp_path: Path,
) -> None:
    """Within its content's life, the session's snapshots are in the bucket
    and recorded there. Past it, the sweep revokes its key and takes them,
    from the bucket and from the records; another session's stay."""
    keys = TenantKeysImpl(KeyServiceMemoryImpl(), {})
    loop, _ = kept_loop(tmp_path, platform=PlatformRootOptions(tenant_keys=keys))
    # A live tenant, whose org the sweep mints a context for.
    owner, _ = await loop.managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), "Ajax", "ajax-kept", "a@x.test", "Ann"
    )
    loop = replace(loop, owner=owner)
    retention = loop.platform.retention
    policy = await retention.get_policy(loop.owner)
    week = RetentionPolicy(content_lifetime=WEEK)
    await retention.write_policy(loop.owner, policy.model_copy(update={"policy": week}))
    expiring = await loop.start(KEEPER.name)
    assert await wrote(loop, expiring, "a week's work") is LoopOutcome.SUCCEEDED
    await retention.write_policy(
        loop.owner,
        (await retention.get_policy(loop.owner)).model_copy(update={"policy": RetentionPolicy()}),
    )
    staying = await loop.start(KEEPER.name)
    assert await wrote(loop, staying, "kept for good") is LoopOutcome.SUCCEEDED
    workspaces = loop.platform.agent_workspaces
    assert len(await in_bucket(loop, expiring)) == 1
    assert len(await workspaces.kept_snapshots(loop.owner, expiring)) == 1

    later = utcnow() + WEEK + DAY
    sweep = RetentionManagerImpl(
        loop.storage.get_retention_storage(),
        keys,
        loop.managers.privacy,
        loop.managers.agent_sessions,
        loop.managers.tenancy,
        loop.managers.events,
        loop.managers.outbox,
        SessionAgentProjectBoundImpl(loop.storage.get_agent_project_storage()),
        RetentionOptions(),
        clock=lambda: later,
    )
    assert await sweep.sweep(RequestContext(request_id=new_id(), app=APP)) == 1

    assert await in_bucket(loop, expiring) == [], "gone from the bucket"
    assert await workspaces.kept_snapshots(loop.owner, expiring) == (), "and from the records"
    assert len(await in_bucket(loop, staying)) == 1
    assert len(await workspaces.kept_snapshots(loop.owner, staying)) == 1
    with pytest.raises(NotFound):
        await loop.managers.tools.find_snapshot(loop.owner, expiring, new_id())


# A workspace a host holds inside its tenant's wall.


class Placed(PlacedWorkspacesInterface):
    """A pool of one host, as the relay answers for it: the restore each
    prepare carried, the snapshots asked, and the host's answer to each,
    recorded as the relay records it."""

    def __init__(self, tools: list[ToolsManagerAgentWorkspacesImpl], pool_id: UUID) -> None:
        self._tools = tools
        self.pool_id, self.host_id = pool_id, new_id()
        self.restores: list[HostSnapshot | None] = []
        self.asked: list[UUID] = []
        self.kept_for: list[UUID | None] = []
        self.refuses: str | None = None

    async def pool_of(self, ctx: TenantContext, agent_session_id: UUID) -> UUID | None:
        return self.pool_id

    async def held_on_host(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        restore: HostSnapshot | None = None,
        *,
        pooled: PlacementState | None = None,
    ) -> AgentWorkspace | None:
        self.restores.append(restore)
        return AgentWorkspace(id=agent_session_id, org_id=ctx.org_id, spec=spec, location="host:1")

    async def snapshot_on_host(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        spec: IsolationSpec,
        snapshot_id: UUID,
        *,
        kept_for: UUID | None = None,
    ) -> UUID:
        self.asked.append(snapshot_id)
        self.kept_for.append(kept_for)
        if self.refuses is None:
            kept = HostSnapshot(
                id=snapshot_id,
                reference=f"{ctx.org_id}/{kept_for or agent_session_id}/{snapshot_id}",
                digest="sha256:" + "ab" * 32,
                size=7,
            )
            await self._tools[0].keep_on_host(
                ctx, agent_session_id, kept, self.pool_id, self.host_id
            )
        return snapshot_id

    async def refusal_of(self, ctx: TenantContext, item_id: UUID) -> str | None:
        return self.refuses

    async def erase_on_host(
        self, ctx: TenantContext, agent_session_id: UUID, host_id: UUID
    ) -> None:
        return None


def on_host(
    loop: PlatformLoop, placed: Placed, tools: list[ToolsManagerAgentWorkspacesImpl]
) -> None:
    """The platform's tools over the loop's, with a pool of one host; the
    inner tools never take a hosted workspace's snapshot."""

    async def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the platform's own provider snapshotted a host's workspace")

    inner = loop.managers.tools
    inner.snapshot_agent_workspace = never  # type: ignore[method-assign]
    tools.append(
        ToolsManagerAgentWorkspacesImpl(
            inner,
            loop.platform.agent_workspaces,
            loop.managers.steps,
            HostOffer(),
            local=True,
            placed=placed,
            keyed_hash=loop.managers.privacy.keyed_hash,
            options=PinnedToolsOptions(snapshot_wait=timedelta(seconds=1)),
        )
    )


async def test_a_hosted_workspace_is_snapshotted_by_its_host_and_restored_there_from_it(
    tmp_path: Path,
) -> None:
    """The run's end asks the host that holds the workspace for its
    snapshot, and the step names the hash keyed from the digest the host
    declared. The next prepare decides its restore first: it travels with
    the ask, by the reference and the digest the record holds."""
    loop, _ = kept_loop(tmp_path)
    tools: list[ToolsManagerAgentWorkspacesImpl] = []
    placed = Placed(tools, new_id())
    on_host(loop, placed, tools)
    agent_session_id = await loop.start(KEEPER.name)
    epoch = await loop.managers.steps.begin_run(loop.owner, agent_session_id)
    workspace = await tools[0].prepare_agent_workspace(loop.owner, agent_session_id, KEPT)
    assert placed.restores == [None]

    step = await tools[0].snapshot_agent_workspace(
        loop.owner, agent_session_id, workspace, epoch=epoch, loop_id=new_id()
    )

    assert step.type is AgentStepType.SNAPSHOTTED and step.header is not None
    named: AgentWorkspaceSnapshot = step.header.snapshot  # type: ignore[union-attr]
    record = await loop.platform.agent_workspaces.kept_snapshot(loop.owner, named.id)
    assert record is not None and record.on_host and placed.asked == [named.id]
    assert (named.hash, named.size) == (record.hash, record.size)

    await tools[0].prepare_agent_workspace(loop.owner, agent_session_id, KEPT, restore=named)

    restore = placed.restores[-1]
    assert restore is not None
    assert (restore.id, restore.reference, restore.digest) == (
        record.id,
        record.reference,
        record.digest,
    )


async def test_a_hosts_refusal_keeps_no_snapshot_and_a_bucket_snapshot_never_reaches_a_host(
    tmp_path: Path,
) -> None:
    """A host that keeps none answers why, and no step names one. A restore
    of a snapshot the platform's bucket keeps is lost before any host of
    the pool is asked: its bytes never cross into the wall."""
    loop, _ = kept_loop(tmp_path)
    agent_session_id = await loop.start(KEEPER.name)
    assert await wrote(loop, agent_session_id, "kept in the bucket") is LoopOutcome.SUCCEEDED
    (taken,) = of_type(await loop.history(agent_session_id), AgentStepType.SNAPSHOTTED)
    in_the_bucket: AgentWorkspaceSnapshot = taken.header.snapshot  # type: ignore[union-attr]
    tools: list[ToolsManagerAgentWorkspacesImpl] = []
    placed = Placed(tools, new_id())
    on_host(loop, placed, tools)
    epoch = await loop.managers.steps.begin_run(loop.owner, agent_session_id)

    with pytest.raises(AgentWorkspaceLost, match="never crosses into the wall"):
        await tools[0].prepare_agent_workspace(
            loop.owner, agent_session_id, KEPT, restore=in_the_bucket
        )
    assert placed.restores == [], "no host was asked"

    workspace = await tools[0].prepare_agent_workspace(loop.owner, agent_session_id, KEPT)
    placed.refuses = "the workspace holds the secret 'SERVICE_TOKEN', so it is not kept"
    with pytest.raises(SnapshotRefused, match="SERVICE_TOKEN"):
        await tools[0].snapshot_agent_workspace(
            loop.owner, agent_session_id, workspace, epoch=epoch, loop_id=new_id()
        )
    assert len(of_type(await loop.history(agent_session_id), AgentStepType.SNAPSHOTTED)) == 1
