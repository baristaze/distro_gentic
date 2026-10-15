"""A workspace kept by snapshots inside a customer's wall, against the live
app, in process. The host that holds it keeps each snapshot in its own
store, and the platform records the reference, the digest, and the keyed
hash, never the bytes: nothing reaches the platform's bucket. A restore
travels with its prepare, and the host starts the workspace from its store
once the bytes match their digest; bytes altered there lose it. A snapshot
that holds the value of a secret the host keeps is refused, and nothing is
kept. A revoked key asks the host to erase its copies; a fork's copy, kept
as the child's, outlives the parent's erase. A person who takes
control of a workspace whose instance went since its run gets it back from
its latest snapshot, never its files alone. A host that did not
probe snapshots refuses a workspace kept by them, and a session pinned to
a pool with no such host waits, with the reason, and is never prepared as a
cache.

A take of control whose restore outlasts its wait hands nothing over, and a
take of a workspace a person holds restores nothing over their work. The
runner's sweep keeps the instance of a kept session that no snapshot
holds. A restore waits for the host that holds the
workspace while it is not revoked, the host that restores it holds it, and
a snapshot no live host keeps is lost, never waited on for good. A
session's purge asks each host that keeps its snapshots to erase them."""

import asyncio
import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from host_support import Stack, probes

from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.exec_relay import ExecutorRelayImpl
from acme.apps.host.snapshots import HostSnapshots
from acme.client.types import IsolationMode as HostMode
from acme.infra.agent_workspaces import (
    AgentWorkspaceLost,
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    AgentWorkspace,
)
from acme.infra.agent_workspaces.twin import AgentWorkspaceTwinImpl
from acme.infra.buckets import Buckets
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.om.agent_steps.types.header import HASH_SCHEME, AgentWorkspaceSnapshot, ParkReason
from acme.om.agent_workspaces.types.snapshot import HostSnapshot, KeptSnapshot
from acme.om.agents.loop_rules import changed_step
from acme.om.base import new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    RequestContext,
    TenantContext,
    build_context,
)
from acme.om.exec_relay.impl.workspaces import PlacedWorkspacesRelayedImpl
from acme.om.hosts.impl.manager import HostsOptions
from acme.om.platform_root import ProductKinds
from acme.om.tenancy.rules import permissions_of
from acme.om.tools.impl.snapshots import session_prefix
from acme.om.tools.rules import snapshotted_step
from acme.om.watch import root as watch_root
from acme.om.watch.exceptions import NotHandedOver
from acme.om.watch.impl.manager import TAKEN
from acme.om.watch.root import build_watch
from acme.om.watch.types.control import HandCommand
from acme.om.work.types.work_item import WorkKind, WorkStatus
from acme.workers.agent_session_runner.workspaces import HeldWorkspacesSweep

from contracts.agent_session_storage import make_session

KEPT = IsolationSpec(
    mode=IsolationMode.CONTAINER,
    egress=EgressPolicy(mode=EgressMode.NONE),
    durability=Durability.SNAPSHOT,
)
SECRET = "tok-0123456789abcdef"


class ContainerTwin(AgentWorkspaceTwinImpl):
    """The twin, standing in for a host's container provider: a workspace's
    files are bytes a test writes, and a snapshot is those bytes."""

    async def prepare(
        self,
        org_id: UUID,
        agent_workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> AgentWorkspace:
        twin = spec.model_copy(update={"mode": IsolationMode.TWIN, "durability": Durability.CACHE})
        made = await super().prepare(
            org_id, agent_workspace_id, twin, snapshot, base, building=building
        )
        return made.model_copy(update={"spec": spec})


async def a_host(
    api: Stack, pool_id: UUID, where: Path, *, probed: bool = True, store: Path | None = None
) -> tuple[HostAgent, ContainerTwin, Path]:
    """A host of the pool that runs a container per workspace and keeps
    their snapshots in its own store, or in `store` when it shares one,
    when its probe showed it can; its secret store holds one value for the
    tenant."""
    twin = ContainerTwin()
    store = store or where / "snapshots"
    secrets = where / "secrets"
    await SecretsLocalImpl(secrets).put(api.owner.org_id, "SERVICE_TOKEN", SECRET)
    snapshots = HostSnapshots(store, secrets)
    agents: list[HostAgent] = []
    transport = TransportLocalImpl(where / "records", SecretsLocalImpl(None), BrokerNullImpl())
    executor = ExecutorRelayImpl(
        lambda: agents[0].client(),
        {IsolationMode.CONTAINER: transport},
        {IsolationMode.CONTAINER: twin},
        snapshots=snapshots,
        snapshot_modes=lambda: frozenset({IsolationMode.CONTAINER} if probed else ()),
        flush_seconds=0.0,
        renew_seconds=0.2,
    )
    checks = probes(HostMode.container)
    if probed:
        checks = replace(checks, snapshots={HostMode.container: snapshots.usable})
    pool_token = await api.token(pool_id)
    host = HostAgent(
        replace(api.settings(where / "home", None), enrollment_token=pool_token),
        Ceilings(agent_projects=None, min_isolation=HostMode.container, egress=frozenset()),
        checks,
        api.client,
        executor,
    )
    agents.append(host)
    await host.start()
    return host, twin, store


async def claimed(host: HostAgent) -> None:
    assert await host.claim_once() is not None
    await host.idle()


async def a_pinned_session(api: Stack, pool_id: UUID) -> UUID:
    managers = api.container.managers
    session = await managers.agent_sessions.create_session(api.owner, make_session())
    await managers.hosts.place_session(api.owner, session.id, pool_id)
    return session.id


async def prepared(api: Stack, host: HostAgent, agent_session_id: UUID) -> None:
    assert await api.container.managers.exec_relay.ask_prepare(api.owner, agent_session_id, KEPT)
    await claimed(host)
    assert (
        await api.container.managers.exec_relay.binding_of(api.owner, agent_session_id) is not None
    )


# Check 3: inside a customer's wall, a snapshot stays in its host's store.


async def test_a_hosts_snapshot_stays_in_its_store_and_the_platform_records_its_reference_and_hash(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, agent_session_id)
    twin.files[agent_session_id] = b"what the loop wrote, and the packages it installed"
    snapshot_id = new_id()

    item_id = await managers.exec_relay.ask_snapshot(api.owner, agent_session_id, KEPT, snapshot_id)
    await claimed(host)

    assert item_id is not None
    assert (await managers.exec_relay.workspace_work(api.owner, item_id)).status is WorkStatus.DONE
    record = await managers.agent_workspaces.kept_snapshot(api.owner, snapshot_id)
    assert record is not None and record.on_host
    assert (record.pool_id, record.host_id) == (pool.id, UUID(host.credential.claimant_id))
    kept = twin.files[agent_session_id]
    kept_digest = "sha256:" + hashlib.sha256(kept).hexdigest()
    assert record.digest == kept_digest
    assert record.size == len(kept) and record.hash.startswith(HASH_SCHEME)
    assert record.hash.removeprefix(HASH_SCHEME) != kept_digest.removeprefix("sha256:")
    assert (store / record.reference).read_bytes() == kept, "its bytes are in the host's store"
    assert kept not in record.model_dump_json().encode(), "the record holds no bytes"
    buckets = api.container.infra.get_buckets()
    in_bucket = await buckets.list(
        api.owner.org_id, Buckets.SNAPSHOTS, session_prefix(agent_session_id), 10
    )
    assert in_bucket == [], "nothing of it reached the platform's bucket"


async def test_a_restore_travels_with_its_prepare_and_altered_bytes_lose_it(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, agent_session_id)
    twin.files[agent_session_id] = b"as the run left it"
    snapshot_id = new_id()
    await managers.exec_relay.ask_snapshot(api.owner, agent_session_id, KEPT, snapshot_id)
    await claimed(host)
    record = await managers.agent_workspaces.kept_snapshot(api.owner, snapshot_id)
    assert record is not None
    restore = HostSnapshot(
        id=record.id, reference=record.reference, digest=record.digest, size=record.size
    )
    twin.files[agent_session_id] = b"written since"

    restored = await managers.exec_relay.ask_restore(api.owner, agent_session_id, KEPT, restore)
    await claimed(host)

    assert (await managers.exec_relay.workspace_work(api.owner, restored)).status is WorkStatus.DONE
    assert twin.files[agent_session_id] == b"as the run left it", "replaced whole from the store"

    (store / record.reference).write_bytes(b"altered in the store")
    lost = await managers.exec_relay.ask_restore(api.owner, agent_session_id, KEPT, restore)
    await claimed(host)

    row = await managers.exec_relay.workspace_work(api.owner, lost)
    assert row.status is WorkStatus.FAILED and "does not match" in (row.last_error or "")
    assert twin.files[agent_session_id] == b"as the run left it", "nothing started from it"
    placed = PlacedWorkspacesRelayedImpl(lambda: managers.exec_relay, lambda: managers.hosts)
    assert await placed.refusal_of(api.owner, lost) == row.last_error


async def test_a_snapshot_that_holds_a_hosts_secret_is_refused_and_nothing_is_kept(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, agent_session_id)
    twin.files[agent_session_id] = f"export TOKEN={SECRET}".encode()
    snapshot_id = new_id()

    item_id = await managers.exec_relay.ask_snapshot(api.owner, agent_session_id, KEPT, snapshot_id)
    await claimed(host)

    assert item_id is not None
    row = await managers.exec_relay.workspace_work(api.owner, item_id)
    assert row.status is WorkStatus.FAILED and "SERVICE_TOKEN" in (row.last_error or "")
    assert SECRET not in (row.last_error or "")
    assert await managers.agent_workspaces.kept_snapshot(api.owner, snapshot_id) is None
    assert not (store / str(api.owner.org_id) / str(agent_session_id)).exists()


async def test_a_revoked_key_asks_the_host_to_erase_its_copies_and_the_records_go(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, agent_session_id)
    twin.files[agent_session_id] = b"a day's work"
    await managers.exec_relay.ask_snapshot(api.owner, agent_session_id, KEPT, new_id())
    await claimed(host)
    assert (store / str(api.owner.org_id) / str(agent_session_id)).is_dir()

    await managers.privacy.revoke_key(api.owner, agent_session_id)
    await claimed(host)

    assert not (store / str(api.owner.org_id) / str(agent_session_id)).exists(), (
        "erased on the host"
    )
    assert await managers.agent_workspaces.kept_snapshots(api.owner, agent_session_id) == ()


async def test_a_forks_copy_is_kept_as_the_childs_and_outlives_the_parents_erase(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    org = str(api.owner.org_id)
    pool = await api.pool()
    parent = await a_pinned_session(api, pool.id)
    child = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, parent)
    twin.files[parent] = b"as the spawn took it"
    taken_id = new_id()

    await managers.exec_relay.ask_snapshot(api.owner, parent, KEPT, taken_id, kept_for=child)
    await claimed(host)
    await managers.exec_relay.ask_snapshot(api.owner, parent, KEPT, new_id())  # the parent's own
    await claimed(host)

    taken = await managers.agent_workspaces.kept_snapshot(api.owner, taken_id)
    assert taken is not None and taken.agent_session_id == parent, "the take is the parent's answer"
    copy = store / taken.reference
    assert copy.is_relative_to(store / org / str(child)), "kept as the child's"
    assert copy.read_bytes() == b"as the spawn took it"

    await managers.privacy.revoke_key(api.owner, parent)
    await claimed(host)

    assert not (store / org / str(parent)).exists(), "the parent's own are erased"
    assert copy.read_bytes() == b"as the spawn took it", "the child's copy outlives them"
    await managers.exec_relay.ask_erase(api.owner, child, UUID(host.credential.claimant_id))
    await claimed(host)
    assert not copy.exists(), "the child's erase takes it"


# Check 4: a host that did not probe snapshots.


async def test_a_kept_session_on_a_pool_with_no_probed_host_waits_and_is_never_a_cache(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host, twin, _ = await a_host(api, pool.id, tmp_path, probed=False)
    placed = PlacedWorkspacesRelayedImpl(lambda: managers.exec_relay, lambda: managers.hosts)

    with pytest.raises(IsolationRefused) as waits:
        await placed.held_on_host(api.owner, agent_session_id, KEPT)

    assert waits.value.clears, "it waits on the resource"
    assert "has probed snapshots of a container workspace" in waits.value.message
    assert not await managers.work.has_open(api.owner, WorkKind.WORKSPACE, agent_session_id)

    # Asked anyway, the host refuses it: nothing is made as a cache.
    assert await managers.exec_relay.ask_prepare(api.owner, agent_session_id, KEPT)
    await claimed(host)
    assert await managers.exec_relay.binding_of(api.owner, agent_session_id) is None
    assert twin.live == set()


async def test_a_host_advertises_snapshots_only_at_a_mode_it_probed_with_a_usable_store(
    api: Stack, tmp_path: Path
) -> None:
    pool = await api.pool()
    probed, _, _ = await a_host(api, pool.id, tmp_path / "a")
    unprobed, _, _ = await a_host(api, pool.id, tmp_path / "b", probed=False)

    def capabilities(host: HostAgent) -> list[Any]:
        return [name.root for name in host.probed.advertisement.capabilities or ()]

    assert "snapshot.container" in capabilities(probed)
    assert not [name for name in capabilities(unprobed) if name.startswith("snapshot.")]


def in_person(of: TenantContext) -> TenantContext:
    """The owner at the portal, signed in on a session of their own."""
    return build_context(
        RequestContext(request_id=new_id(), app=AppContext(type=AppType.PORTAL, version="t")),
        user_id=of.user_id,
        org_id=of.org_id,
        role=of.role,
        permissions=permissions_of(of.role),
        credential_kind=CredentialKind.AUTH_SESSION_TOKEN,
    )


async def test_taking_control_of_a_released_kept_workspace_restores_its_latest_snapshot(
    api: Stack, tmp_path: Path
) -> None:
    """Past its run, its host let the instance go and kept its files alone.
    A person who takes control gets the workspace its latest snapshot holds,
    as the next run would, before any command of theirs runs."""
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    await managers.agent_workspaces.pinned(api.owner, agent_session_id, KEPT)
    host, twin, _ = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, agent_session_id)
    twin.files[agent_session_id] = b"the tree and the tool the run installed"
    snapshot_id = new_id()
    await managers.exec_relay.ask_snapshot(api.owner, agent_session_id, KEPT, snapshot_id)
    await claimed(host)
    record = await managers.agent_workspaces.kept_snapshot(api.owner, snapshot_id)
    assert record is not None
    epoch = await managers.steps.begin_run(api.owner, agent_session_id)
    taken = AgentWorkspaceSnapshot(
        id=record.id, hash=record.hash, size=record.size, agent_workspace_id=agent_session_id
    )
    step = snapshotted_step(new_id(), record.created_at, agent_session_id, new_id(), taken)
    await managers.steps.append_agent_steps(api.owner, agent_session_id, epoch, [step])
    twin.live.discard(agent_session_id)  # let go past its grace
    twin.files[agent_session_id] = b"its files alone"

    watch = build_watch(managers, api.container.stream)
    taking = asyncio.ensure_future(watch.take_control(in_person(api.owner), agent_session_id))
    for _ in range(100):
        if await host.claim_once() is not None:
            break
        await asyncio.sleep(0.01)
    await host.idle()
    await taking

    assert agent_session_id in twin.live
    assert twin.files[agent_session_id] == b"the tree and the tool the run installed"


def restore_of(record: KeptSnapshot) -> HostSnapshot:
    """A restore of the snapshot `record` names, as the platform's tools ask it."""
    return HostSnapshot(
        id=record.id,
        reference=record.reference,
        digest=record.digest,
        size=record.size,
        kept_by=record.host_id,
    )


async def kept_on(
    api: Stack, host: HostAgent, twin: ContainerTwin, agent_session_id: UUID, files: bytes
) -> KeptSnapshot:
    """A snapshot of the session's workspace, holding `files`, kept in the
    store of the host that holds it, whose provider is `twin`."""
    managers = api.container.managers
    twin.files[agent_session_id] = files
    snapshot_id = new_id()
    await managers.exec_relay.ask_snapshot(api.owner, agent_session_id, KEPT, snapshot_id)
    await claimed(host)
    record = await managers.agent_workspaces.kept_snapshot(api.owner, snapshot_id)
    assert record is not None and record.on_host
    return record


async def offline(api: Stack, host: HostAgent) -> None:
    """The host went silent: its last call is older than the online window."""
    hosts = api.container.storage.get_hosts_storage()
    silent_since = utcnow() - 2 * HostsOptions().online_window
    await hosts.mark_seen(api.owner.org_id, UUID(host.credential.claimant_id), silent_since)


async def with_snapshot_step(api: Stack, agent_session_id: UUID, record: KeptSnapshot) -> int:
    """A run's end that named `record` in the history; the run's epoch."""
    managers = api.container.managers
    epoch = await managers.steps.begin_run(api.owner, agent_session_id)
    taken = AgentWorkspaceSnapshot(
        id=record.id, hash=record.hash, size=record.size, agent_workspace_id=agent_session_id
    )
    step = snapshotted_step(new_id(), record.created_at, agent_session_id, new_id(), taken)
    await managers.steps.append_agent_steps(api.owner, agent_session_id, epoch, [step])
    return epoch


async def test_a_take_whose_restore_outlasts_its_wait_hands_nothing_over_and_a_held_one_is_never_restored(
    api: Stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    await managers.agent_workspaces.pinned(api.owner, agent_session_id, KEPT)
    host, twin, _ = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, agent_session_id)
    record = await kept_on(api, host, twin, agent_session_id, b"the snapshot")
    await with_snapshot_step(api, agent_session_id, record)
    monkeypatch.setattr(watch_root, "TAKE_RESTORE_WAIT", timedelta(milliseconds=200))
    watch = build_watch(managers, api.container.stream)
    person = in_person(api.owner)

    # The host does not get to the restore in time: nothing is handed over.
    with pytest.raises(IsolationRefused) as waits:
        await watch.take_control(person, agent_session_id)
    assert waits.value.clears
    session = await managers.agent_sessions.get_agent_session(api.owner, agent_session_id)
    assert session.park is None or session.park.reason is not ParkReason.HANDOVER
    events = await managers.events.get_change_events(api.owner, 0, 500)
    assert [event for event in events if event.kind == TAKEN] == [], "no take to audit"
    command = HandCommand(key=new_id(), argv=("ls",))
    with pytest.raises(NotHandedOver):
        await watch.run_command(person, agent_session_id, command)

    # A take again waits for the same restore, and hands over once it lands.
    twin.files[agent_session_id] = b"its files alone"
    taking = asyncio.ensure_future(watch.take_control(person, agent_session_id))
    for _ in range(100):
        if await host.claim_once() is not None:
            break
        await asyncio.sleep(0.01)
    await host.idle()
    taken = await taking
    assert taken.park is not None and taken.park.reason is ParkReason.HANDOVER
    assert twin.files[agent_session_id] == b"the snapshot"
    events = await managers.events.get_change_events(api.owner, 0, 500)
    assert len([event for event in events if event.kind == TAKEN]) == 1, "audited once"

    # The person works by hand; a take again restores nothing over it.
    twin.files[agent_session_id] = b"the person's work by hand"
    await watch.take_control(person, agent_session_id)
    assert not await managers.work.has_open(api.owner, WorkKind.WORKSPACE, agent_session_id)
    assert await host.claim_once() is None
    assert twin.files[agent_session_id] == b"the person's work by hand"


async def test_the_sweep_keeps_a_kept_sessions_hosted_instance_that_no_snapshot_holds(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    await managers.agent_workspaces.pinned(api.owner, agent_session_id, KEPT)
    host, twin, _ = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, agent_session_id)
    record = await kept_on(api, host, twin, agent_session_id, b"the snapshot")
    epoch = await with_snapshot_step(api, agent_session_id, record)
    # The next run changed the workspace and died before its end's snapshot.
    step = changed_step(new_id(), utcnow(), agent_session_id, new_id())
    await managers.steps.append_agent_steps(api.owner, agent_session_id, epoch, [step])
    twin.files[agent_session_id] = b"the snapshot, and what the run installed since"
    now = [utcnow()]
    sweep = HeldWorkspacesSweep(
        api.container.infra.get_agent_workspaces(),
        managers.tools,
        managers.agent_workspaces,
        managers.agent_sessions,
        managers.steps,
        managers.work,
        managers.tenancy,
        ProductKinds().warm_grace,
        clock=lambda: now[0],
        exec_relay=managers.exec_relay,
    )
    stage = RequestContext(request_id=new_id(), app=AppContext(type=AppType.WORKER, version="t"))

    assert await sweep(stage) == 0, "the grace begins"
    now[0] += timedelta(minutes=10)
    assert await sweep(stage) == 0, "no snapshot holds it: it stays"
    assert await sweep(stage) == 0
    asked = await managers.work.latest_for_target(api.owner, WorkKind.WORKSPACE, agent_session_id)
    assert asked is not None and asked.payload["operation"] == "snapshot", "no release is asked"
    assert agent_session_id in twin.live
    assert twin.files[agent_session_id] == b"the snapshot, and what the run installed since"


async def test_a_restore_whose_snapshot_no_live_host_keeps_is_lost_never_waited_on(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    keeper, keeper_twin, _ = await a_host(api, pool.id, tmp_path / "a")
    await prepared(api, keeper, agent_session_id)
    record = await kept_on(api, keeper, keeper_twin, agent_session_id, b"kept on the first host")
    other, other_twin, _ = await a_host(api, pool.id, tmp_path / "b")

    # While the host that kept it is live, one whose store lacks it hands
    # the restore back for another host.
    fork = await a_pinned_session(api, pool.id)
    waiting = await managers.exec_relay.ask_restore(api.owner, fork, KEPT, restore_of(record))
    await claimed(other)
    row = await managers.exec_relay.workspace_work(api.owner, waiting)
    assert row.status is WorkStatus.QUEUED, "another host may still restore it"

    # Once that host is revoked, no live host keeps it: the restore is lost,
    # and the run that waits parks for a person.
    await managers.hosts.revoke_host(api.owner, UUID(keeper.credential.claimant_id))
    placed = PlacedWorkspacesRelayedImpl(
        lambda: managers.exec_relay, lambda: managers.hosts, restore_wait=timedelta(seconds=5)
    )
    restoring = asyncio.ensure_future(
        placed.held_on_host(api.owner, agent_session_id, KEPT, restore_of(record))
    )
    for _ in range(100):
        if await other.claim_once() is not None:
            break
        await asyncio.sleep(0.01)
    await other.idle()
    with pytest.raises(AgentWorkspaceLost):
        await restoring
    asked = await managers.work.latest_for_target(api.owner, WorkKind.WORKSPACE, agent_session_id)
    assert asked is not None and asked.status is WorkStatus.FAILED
    assert agent_session_id not in other_twin.live


async def test_a_restore_waits_for_its_offline_holder_and_the_host_that_restores_holds_it(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    shared = tmp_path / "shared"
    agent_session_id = await a_pinned_session(api, pool.id)
    holder, holder_twin, _ = await a_host(api, pool.id, tmp_path / "a", store=shared)
    await prepared(api, holder, agent_session_id)
    record = await kept_on(api, holder, holder_twin, agent_session_id, b"the snapshot")
    other, other_twin, _ = await a_host(api, pool.id, tmp_path / "b", store=shared)
    holder_id, other_id = (UUID(h.credential.claimant_id) for h in (holder, other))

    # Its holder is offline: the restore waits on its lane, and no other host
    # restores a workspace that would stay bound to it.
    await offline(api, holder)
    holder_twin.files[agent_session_id] = b"written since"
    placed = PlacedWorkspacesRelayedImpl(
        lambda: managers.exec_relay,
        lambda: managers.hosts,
        restore_wait=timedelta(milliseconds=200),
    )
    restoring = asyncio.ensure_future(
        placed.held_on_host(api.owner, agent_session_id, KEPT, restore_of(record))
    )
    assert await other.claim_once() is None
    with pytest.raises(IsolationRefused) as waits:
        await restoring
    assert waits.value.clears, "the run is not told it restored"
    assert agent_session_id not in other_twin.live
    await claimed(holder)  # back online, it restores its own
    assert holder_twin.files[agent_session_id] == b"the snapshot"
    binding = await managers.exec_relay.binding_of(api.owner, agent_session_id)
    assert binding is not None and binding.host_id == holder_id

    # A restore another host makes binds the workspace to it, whatever host
    # was bound meanwhile.
    fork = await a_pinned_session(api, pool.id)
    asked = await managers.exec_relay.ask_restore(api.owner, fork, KEPT, restore_of(record))
    await managers.exec_relay.bind_workspace(api.owner, fork, holder_id, "elsewhere")
    await claimed(other)
    assert (await managers.exec_relay.workspace_work(api.owner, asked)).status is WorkStatus.DONE
    binding = await managers.exec_relay.binding_of(api.owner, fork)
    assert binding is not None and binding.host_id == other_id
    assert fork in other_twin.live and other_twin.files[fork] == b"the snapshot"


async def test_a_sessions_purge_asks_each_host_that_keeps_its_snapshots_to_erase_them(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    agent_session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, agent_session_id)
    await kept_on(api, host, twin, agent_session_id, b"a day's work")
    kept = store / str(api.owner.org_id) / str(agent_session_id)
    assert kept.is_dir()

    await managers.tools.purge_agent_workspace(api.owner.org_id, agent_session_id)
    assert await managers.agent_workspaces.kept_snapshots(api.owner, agent_session_id) == ()
    await claimed(host)

    assert not kept.exists(), "erased on the host, with no key revoked"
    asked = await managers.work.latest_for_target(api.owner, WorkKind.WORKSPACE, agent_session_id)
    assert asked is not None and asked.payload["operation"] == "erase"
    assert asked.status is WorkStatus.DONE
