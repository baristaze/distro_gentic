"""A workspace kept by snapshots inside a customer's wall, against the live
app, in process. The host that holds it keeps each snapshot in its own
store, and the platform records the reference, the digest, and the keyed
hash, never the bytes: nothing reaches the platform's bucket. A restore
travels with its prepare, and the host starts the workspace from its store
once the bytes match their digest; bytes altered there lose it. A snapshot
that holds the value of a secret the host keeps is refused, and nothing is
kept. A revoked key asks the host to erase its copies. A person who takes
control of a workspace whose instance went since its run gets it back from
its latest snapshot, never its files alone. A host that did not
probe snapshots refuses a workspace kept by them, and a session pinned to
a pool with no such host waits, with the reason, and is never prepared as a
cache."""

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from host_support import Stack, probes

from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.relay import ExecutorRelayImpl
from acme.apps.host.snapshots import HostSnapshots
from acme.client.types import IsolationMode as HostMode
from acme.infra.buckets import Buckets
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.infra.workspaces import (
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    Workspace,
)
from acme.infra.workspaces.twin import WorkspaceTwinImpl
from acme.om.base import new_id
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    RequestContext,
    TenantContext,
    build_context,
)
from acme.om.relay.impl.workspaces import PlacedWorkspacesRelayedImpl
from acme.om.steps.types.header import HASH_SCHEME, WorkspaceSnapshot
from acme.om.tenancy.rules import permissions_of
from acme.om.tools.impl.snapshots import session_prefix
from acme.om.tools.rules import snapshotted_step
from acme.om.watch.root import build_watch
from acme.om.work.types.work_item import WorkKind, WorkStatus
from acme.om.workspaces.types.snapshot import HostSnapshot

KEPT = IsolationSpec(
    mode=IsolationMode.CONTAINER,
    egress=EgressPolicy(mode=EgressMode.NONE),
    durability=Durability.SNAPSHOT,
)
SECRET = "tok-0123456789abcdef"


class ContainerTwin(WorkspaceTwinImpl):
    """The twin, standing in for a host's container provider: a workspace's
    files are bytes a test writes, and a snapshot is those bytes."""

    async def prepare(
        self,
        org_id: UUID,
        workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> Workspace:
        twin = spec.model_copy(update={"mode": IsolationMode.TWIN, "durability": Durability.CACHE})
        made = await super().prepare(org_id, workspace_id, twin, snapshot, base, building=building)
        return made.model_copy(update={"spec": spec})


async def a_host(
    api: Stack, pool_id: UUID, where: Path, *, probed: bool = True
) -> tuple[HostAgent, ContainerTwin, Path]:
    """A host of the pool that runs a container per workspace and keeps
    their snapshots in its own store, when its probe showed it can; its
    secret store holds one value for the tenant."""
    twin = ContainerTwin()
    store = where / "snapshots"
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
        Ceilings(projects=None, min_isolation=HostMode.container, egress=frozenset()),
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


async def prepared(api: Stack, host: HostAgent, session_id: UUID) -> None:
    assert await api.container.managers.relay.ask_prepare(api.owner, session_id, KEPT)
    await claimed(host)
    assert await api.container.managers.relay.binding_of(api.owner, session_id) is not None


# Check 3: inside a customer's wall, a snapshot stays in its host's store.


async def test_a_hosts_snapshot_stays_in_its_store_and_the_platform_records_its_reference_and_hash(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, session_id)
    twin.files[session_id] = b"what the loop wrote, and the packages it installed"
    snapshot_id = new_id()

    item_id = await managers.relay.ask_snapshot(api.owner, session_id, KEPT, snapshot_id)
    await claimed(host)

    assert item_id is not None
    assert (await managers.relay.workspace_work(api.owner, item_id)).status is WorkStatus.DONE
    record = await managers.workspaces.kept_snapshot(api.owner, snapshot_id)
    assert record is not None and record.on_host
    assert (record.pool_id, record.host_id) == (pool.id, UUID(host.credential.claimant_id))
    kept = twin.files[session_id]
    kept_digest = "sha256:" + hashlib.sha256(kept).hexdigest()
    assert record.digest == kept_digest
    assert record.size == len(kept) and record.hash.startswith(HASH_SCHEME)
    assert record.hash.removeprefix(HASH_SCHEME) != kept_digest.removeprefix("sha256:")
    assert (store / record.reference).read_bytes() == kept, "its bytes are in the host's store"
    assert kept not in record.model_dump_json().encode(), "the record holds no bytes"
    buckets = api.container.infra.get_buckets()
    in_bucket = await buckets.list(
        api.owner.org_id, Buckets.SNAPSHOTS, session_prefix(session_id), 10
    )
    assert in_bucket == [], "nothing of it reached the platform's bucket"


async def test_a_restore_travels_with_its_prepare_and_altered_bytes_lose_it(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, session_id)
    twin.files[session_id] = b"as the run left it"
    snapshot_id = new_id()
    await managers.relay.ask_snapshot(api.owner, session_id, KEPT, snapshot_id)
    await claimed(host)
    record = await managers.workspaces.kept_snapshot(api.owner, snapshot_id)
    assert record is not None
    restore = HostSnapshot(
        id=record.id, reference=record.reference, digest=record.digest, size=record.size
    )
    twin.files[session_id] = b"written since"

    restored = await managers.relay.ask_restore(api.owner, session_id, KEPT, restore)
    await claimed(host)

    assert (await managers.relay.workspace_work(api.owner, restored)).status is WorkStatus.DONE
    assert twin.files[session_id] == b"as the run left it", "replaced whole from the store"

    (store / record.reference).write_bytes(b"altered in the store")
    lost = await managers.relay.ask_restore(api.owner, session_id, KEPT, restore)
    await claimed(host)

    row = await managers.relay.workspace_work(api.owner, lost)
    assert row.status is WorkStatus.FAILED and "does not match" in (row.last_error or "")
    assert twin.files[session_id] == b"as the run left it", "nothing started from it"
    placed = PlacedWorkspacesRelayedImpl(lambda: managers.relay, lambda: managers.hosts)
    assert await placed.refusal_of(api.owner, lost) == row.last_error


async def test_a_snapshot_that_holds_a_hosts_secret_is_refused_and_nothing_is_kept(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, session_id)
    twin.files[session_id] = f"export TOKEN={SECRET}".encode()
    snapshot_id = new_id()

    item_id = await managers.relay.ask_snapshot(api.owner, session_id, KEPT, snapshot_id)
    await claimed(host)

    assert item_id is not None
    row = await managers.relay.workspace_work(api.owner, item_id)
    assert row.status is WorkStatus.FAILED and "SERVICE_TOKEN" in (row.last_error or "")
    assert SECRET not in (row.last_error or "")
    assert await managers.workspaces.kept_snapshot(api.owner, snapshot_id) is None
    assert not (store / str(api.owner.org_id) / str(session_id)).exists()


async def test_a_revoked_key_asks_the_host_to_erase_its_copies_and_the_records_go(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    session_id = await a_pinned_session(api, pool.id)
    host, twin, store = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, session_id)
    twin.files[session_id] = b"a day's work"
    await managers.relay.ask_snapshot(api.owner, session_id, KEPT, new_id())
    await claimed(host)
    assert (store / str(api.owner.org_id) / str(session_id)).is_dir()

    await managers.privacy.revoke_key(api.owner, session_id)
    await claimed(host)

    assert not (store / str(api.owner.org_id) / str(session_id)).exists(), "erased on the host"
    assert await managers.workspaces.kept_snapshots(api.owner, session_id) == ()


# Check 4: a host that did not probe snapshots.


async def test_a_kept_session_on_a_pool_with_no_probed_host_waits_and_is_never_a_cache(
    api: Stack, tmp_path: Path
) -> None:
    managers = api.container.managers
    pool = await api.pool()
    session_id = await a_pinned_session(api, pool.id)
    host, twin, _ = await a_host(api, pool.id, tmp_path, probed=False)
    placed = PlacedWorkspacesRelayedImpl(lambda: managers.relay, lambda: managers.hosts)

    with pytest.raises(IsolationRefused) as waits:
        await placed.held_on_host(api.owner, session_id, KEPT)

    assert waits.value.clears, "it waits on the resource"
    assert "has probed snapshots of a container workspace" in waits.value.message
    assert not await managers.work.has_open(api.owner, WorkKind.WORKSPACE, session_id)

    # Asked anyway, the host refuses it: nothing is made as a cache.
    assert await managers.relay.ask_prepare(api.owner, session_id, KEPT)
    await claimed(host)
    assert await managers.relay.binding_of(api.owner, session_id) is None
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
        credential_kind=CredentialKind.SESSION_TOKEN,
    )


async def test_taking_control_of_a_released_kept_workspace_restores_its_latest_snapshot(
    api: Stack, tmp_path: Path
) -> None:
    """Past its run, its host let the instance go and kept its files alone.
    A person who takes control gets the workspace its latest snapshot holds,
    as the next run would, before any command of theirs runs."""
    managers = api.container.managers
    pool = await api.pool()
    session_id = await a_pinned_session(api, pool.id)
    await managers.workspaces.pinned(api.owner, session_id, KEPT)
    host, twin, _ = await a_host(api, pool.id, tmp_path)
    await prepared(api, host, session_id)
    twin.files[session_id] = b"the tree and the tool the run installed"
    snapshot_id = new_id()
    await managers.relay.ask_snapshot(api.owner, session_id, KEPT, snapshot_id)
    await claimed(host)
    record = await managers.workspaces.kept_snapshot(api.owner, snapshot_id)
    assert record is not None
    epoch = await managers.steps.begin_run(api.owner, session_id)
    taken = WorkspaceSnapshot(
        id=record.id, hash=record.hash, size=record.size, workspace_id=session_id
    )
    step = snapshotted_step(new_id(), record.created_at, session_id, new_id(), taken)
    await managers.steps.append_steps(api.owner, session_id, epoch, [step])
    twin.live.discard(session_id)  # let go past its grace
    twin.files[session_id] = b"its files alone"

    watch = build_watch(managers, api.container.stream)
    taking = asyncio.ensure_future(watch.take_control(in_person(api.owner), session_id))
    for _ in range(100):
        if await host.claim_once() is not None:
            break
        await asyncio.sleep(0.01)
    await host.idle()
    await taking

    assert session_id in twin.live
    assert twin.files[session_id] == b"the tree and the tool the run installed"
