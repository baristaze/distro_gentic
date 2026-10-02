"""The relay over memory: a tool call into a customer's wall travels as
keyed exec work. It runs once on the host that holds the workspace, its
output streamed and its result stored under its key, and a resumed run
attaches to it rather than starting another. An expired lease completes an
unsafe item `interrupted` and requeues a repeatable one to its workspace's
host alone. A stop reaches the host's control stream at once, and nothing a
stale writer sends acts. A part or a result whose hash does not verify is
refused at the relay."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.transports import CommandResult, CommandSpec, RecordSeal, StaleCommand
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec, Workspace
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.exceptions import ToolFailed
from acme.om.hosts.exceptions import PinnedToHosts
from acme.om.hosts.impl.manager import HostsOptions
from acme.om.hosts.impl.placement import PlacementHostsImpl
from acme.om.hosts.types.host import Advertisement, Enrollment, HostIdentity
from acme.om.hosts.types.host import IsolationMode as Mode
from acme.om.hosts.types.pool import HostPool
from acme.om.placement.rules import host_lane
from acme.om.placement.types.work import ExecEffect, ExecPayload
from acme.om.relay.exceptions import ItemNotHeld, NoWorkspaceHost, StaleExec
from acme.om.relay.impl.manager import RelayOptions
from acme.om.relay.impl.placement import PlacementRelayedImpl
from acme.om.relay.impl.transport import TransportPlacedImpl, TransportRelayImpl
from acme.om.relay.rules import exec_id, key_time
from acme.om.relay.types.exec import (
    ExecCall,
    ExecOutcome,
    ExecOutput,
    ExecResult,
    ExecState,
    RunRequest,
    StopKind,
)
from acme.om.retention.crossing import CrossingKind, CrossingRefused, declared
from acme.om.root import Managers, build_managers
from acme.om.steps.types.header import ToolFailure
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.work.types.work_item import WorkItem

APP = AppContext(type=AppType.PORTAL, version="portal@test")
RUNNER = AppContext(type=AppType.WORKER, version="runner@test")
CONTAINER = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
PROBED = Advertisement(os="Linux 6.8", shell="/bin/bash", isolation_modes=(Mode.CONTAINER,))
WHERE = "/srv/work/session"
# A lease short enough that a case outlives it.
SHORT = timedelta(milliseconds=50)


def request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=APP)


@dataclass
class Wall:
    """One tenant's session pinned to a pool of two hosts, its workspace
    held by the first."""

    managers: Managers
    storage: StorageMemoryImpl
    owner: TenantContext
    pool: HostPool
    holder: HostIdentity
    other: HostIdentity
    workspace: Workspace
    epoch: int


@pytest.fixture
def storage() -> StorageMemoryImpl:
    return StorageMemoryImpl()


@pytest.fixture
def managers(tmp_path: Path, storage: StorageMemoryImpl) -> Managers:
    return build_managers(
        storage,
        InfraLocalImpl(tmp_path),
        hosts_options=HostsOptions(claim_lease=SHORT),
        relay_options=RelayOptions(lease=SHORT),
    )


async def enrolled(
    managers: Managers, owner: TenantContext, pool: HostPool, name: str
) -> HostIdentity:
    issued = await managers.hosts.issue_enrollment_token(owner, pool.id)
    credential = await managers.hosts.enroll(
        request(), issued.token, Enrollment(name=name, advertisement=PROBED, exec_version=1)
    )
    return await managers.hosts.authenticate(request(), credential.credential)


@pytest.fixture
async def wall(managers: Managers, storage: StorageMemoryImpl) -> Wall:
    owner, _ = await managers.tenancy.bootstrap(request(), "Ajax", "ajax", "ann@ajax.test", "Ann")
    now = utcnow()
    pool = await managers.hosts.create_pool(
        owner,
        HostPool(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=owner.user_id,
            updated_by=owner.user_id,
            name="lab",
            region="eu-west",
        ),
    )
    holder = await enrolled(managers, owner, pool, "host-1")
    other = await enrolled(managers, owner, pool, "host-2")
    session = await managers.agent_sessions.create_session(owner, make_session())
    await managers.hosts.place_session(owner, session.id, pool.id)
    await managers.relay.bind_workspace(owner, session.id, holder.host_id, WHERE)
    epoch = await managers.steps.begin_run(owner, session.id)
    workspace = Workspace(id=session.id, org_id=owner.org_id, spec=CONTAINER, location="")
    return Wall(managers, storage, owner, pool, holder, other, workspace, epoch)


def transport(managers: Managers) -> TransportRelayImpl:
    return TransportRelayImpl(
        lambda: managers.relay,
        lambda: RequestContext(request_id=new_id(), app=RUNNER),
        first_poll=timedelta(milliseconds=1),
        last_poll=timedelta(milliseconds=5),
    )


async def _nothing(data: bytes) -> bytes | None:
    return None


NO_SEAL = RecordSeal(seal=_nothing, open=_nothing)
"""The relay keeps a command's output sealed itself, under the session's
key; the seal the engine hands over is not read."""


def command(
    epoch: int, effect: ExecEffect = "unsafe", key: UUID | None = None, seconds: float = 30
) -> CommandSpec:
    return CommandSpec(
        argv=("make", "deploy"),
        key=key or new_id(),
        epoch=epoch,
        deadline=utcnow() + timedelta(seconds=seconds),
        effect=effect,
    )


class Host:
    """A host as the relay sees it: it claims through placement, reads what
    it holds, streams parts, and pushes how the command ended, each with the
    hash it declares. It counts what it was handed."""

    def __init__(self, managers: Managers, identity: HostIdentity) -> None:
        self.managers = managers
        self.identity = identity
        self.handed: list[WorkItem] = []

    async def claim(self) -> WorkItem | None:
        claimed = await self.managers.hosts.claim(request(), self.identity, 1)
        if claimed is None:
            return None
        self.handed.append(claimed[1])
        return claimed[1]

    async def claim_soon(self) -> WorkItem:
        for _ in range(500):
            if (item := await self.claim()) is not None:
                return item
            await asyncio.sleep(0.002)
        raise AssertionError("nothing was handed to the host")

    def item_id(self, row: WorkItem) -> UUID:
        return ExecPayload.model_validate(row.payload).item_id

    async def part(self, row: WorkItem, seq: int, text: str) -> None:
        data = text.encode()
        await self.managers.relay.push_part(
            request(),
            self.identity,
            self.item_id(row),
            seq,
            "stdout",
            declared(CrossingKind.STREAM_PART, data),
            data,
        )

    async def finish(self, row: WorkItem, exit_code: int = 0, stdout: str = "") -> None:
        result = ExecResult(
            outcome=ExecOutcome(exit_code=exit_code), output=ExecOutput(stdout=stdout)
        )
        data = result.model_dump_json().encode()
        await self.managers.relay.push_result(
            request(),
            self.identity,
            self.item_id(row),
            declared(CrossingKind.RESULT, data),
            data,
        )


async def item_of(wall: Wall, row: WorkItem):
    payload = ExecPayload.model_validate(row.payload)
    item = await wall.managers.relay.watch(request(), wall.owner.org_id, payload.item_id, -1)
    return payload, item


# Check 1: a relayed call runs once on its host, its output streamed and its
# result stored under its key, and a resumed run attaches to it.


async def test_a_relayed_call_runs_once_on_its_host_streamed_and_stored_under_its_key(
    wall: Wall,
) -> None:
    host = Host(wall.managers, wall.holder)
    elsewhere = Host(wall.managers, wall.other)
    printed: list[tuple[str, str]] = []

    async def sink(stream: str, text: str) -> None:
        printed.append((stream, text))

    spec = command(wall.epoch)

    async def on_the_host() -> None:
        row = await host.claim_soon()
        detail = await wall.managers.relay.detail(request(), wall.holder, host.item_id(row))
        assert detail.request == RunRequest(argv=("make", "deploy"))
        assert (detail.key, detail.epoch, detail.location) == (spec.key, wall.epoch, WHERE)
        await host.part(row, 0, "building\n")
        await host.part(row, 1, "deployed\n")
        await host.finish(row, 0, "building\ndeployed\n")

    ran, _ = await asyncio.gather(
        transport(wall.managers).run(wall.workspace, spec, sink, seal=NO_SEAL),
        on_the_host(),
    )
    assert isinstance(ran, CommandResult)
    assert (ran.key, ran.exit_code, ran.stdout) == (spec.key, 0, "building\ndeployed\n")
    assert printed == [("stdout", "building\n"), ("stdout", "deployed\n")]
    # One item, under the call's key, on the lane of the host that holds the
    # workspace, and the queue row an unsafe call takes is claimed once.
    (row,) = host.handed
    payload = ExecPayload.model_validate(row.payload)
    request_bytes = RunRequest(argv=("make", "deploy")).model_dump_json().encode()
    assert payload.item_id == exec_id(spec.key, request_bytes, 0)
    assert payload.key == spec.key and row.lane == host_lane(wall.holder.host_id)
    assert row.max_attempts == 1
    # What it asks of its host: a container's files are its own, so its
    # result reads no path of the host's.
    assert (payload.isolation, payload.egress, payload.reads) == ("container", (), ())
    assert elsewhere.handed == [] and await elsewhere.claim() is None
    # A resumed run reads the stored result and runs nothing again.
    epoch = await wall.managers.steps.begin_run(wall.owner, wall.workspace.id)
    recovered = await transport(wall.managers).outcome(
        wall.workspace, spec.key, epoch, seal=NO_SEAL
    )
    assert recovered is not None and recovered.stdout == "building\ndeployed\n"
    assert await host.claim() is None and len(host.handed) == 1


async def test_a_resumed_run_attaches_to_the_first_execution_and_never_starts_another(
    wall: Wall,
) -> None:
    host = Host(wall.managers, wall.holder)
    spec = command(wall.epoch)
    lost = asyncio.ensure_future(transport(wall.managers).run(wall.workspace, spec, seal=NO_SEAL))
    row = await host.claim_soon()
    await host.part(row, 0, "half way\n")
    # The runner is lost mid-command; the next run holds the session before
    # the lost one's wait ends, so the lost run's stop is refused as stale.
    epoch = await wall.managers.steps.begin_run(wall.owner, wall.workspace.id)
    lost.cancel()
    with pytest.raises(asyncio.CancelledError):
        await lost
    _, progress = await item_of(wall, row)
    assert progress.state is ExecState.RUNNING  # still running on its host
    attached = asyncio.ensure_future(
        transport(wall.managers).outcome(wall.workspace, spec.key, epoch, seal=NO_SEAL)
    )
    await asyncio.sleep(0.02)
    assert not attached.done()  # it waits on the first execution
    await host.finish(row, 0, "half way\ndone\n")
    recovered = await attached
    assert recovered is not None and recovered.stdout == "half way\ndone\n"
    # The same call sent again by the resumed run meets the same item.
    again = await transport(wall.managers).run(
        wall.workspace,
        spec.model_copy(update={"epoch": epoch}),
        seal=NO_SEAL,
    )
    assert again.stdout == "half way\ndone\n"
    assert len(host.handed) == 1 and await host.claim() is None


# Check 2: an expired lease completes an unsafe item interrupted, never
# requeued; a repeatable one is requeued to its workspace's host alone.


async def test_an_unsafe_items_lease_runs_out_and_it_completes_interrupted_never_requeued(
    wall: Wall,
) -> None:
    host = Host(wall.managers, wall.holder)
    waiting = asyncio.ensure_future(
        transport(wall.managers).run(wall.workspace, command(wall.epoch), seal=NO_SEAL)
    )
    row = await host.claim_soon()
    await asyncio.sleep(SHORT.total_seconds() * 2)
    # The sweep: the queue's requeue of expired leases, and the relay's.
    await wall.managers.work.requeue_stale(request(), 100)
    assert await wall.managers.relay.settle_expired(request()) == 1
    with pytest.raises(ToolFailed) as stopped:
        await waiting
    assert stopped.value.failure is ToolFailure.INTERRUPTED
    assert "outcome is unknown" in stopped.value.message
    payload, progress = await item_of(wall, row)
    assert progress.state is ExecState.INTERRUPTED
    # Never requeued: the row failed in the queue, and no claim finds it.
    assert await host.claim() is None and len(host.handed) == 1
    controls = await wall.managers.relay.controls(request(), wall.holder, None)
    assert [(c.item_id, c.kind) for c in controls] == [(payload.item_id, StopKind.REVOKE)]
    # A result its host pushes after that lands nothing.
    with pytest.raises(ItemNotHeld):
        await host.finish(row)


async def test_a_repeatable_items_lease_runs_out_and_it_goes_back_to_its_workspaces_host_alone(
    wall: Wall,
) -> None:
    host = Host(wall.managers, wall.holder)
    elsewhere = Host(wall.managers, wall.other)
    waiting = asyncio.ensure_future(
        transport(wall.managers).run(
            wall.workspace,
            command(wall.epoch, "idempotent"),
            seal=NO_SEAL,
        )
    )
    first = await host.claim_soon()
    await asyncio.sleep(SHORT.total_seconds() * 2)
    await wall.managers.work.requeue_stale(request(), 100)
    assert await wall.managers.relay.settle_expired(request()) == 1
    _, progress = await item_of(wall, first)
    assert progress.state is ExecState.QUEUED
    # Another host of the pool is handed nothing; the holder gets it again.
    await asyncio.sleep(0.05)  # past the requeue's stagger
    assert await elsewhere.claim() is None
    again = await host.claim_soon()
    assert again.id == first.id and again.lane == host_lane(wall.holder.host_id)
    await host.finish(again, 0, "ok\n")
    assert (await waiting).stdout == "ok\n"


# Check 3: a stop reaches the host's control stream at once, and a command
# carrying a stale writer epoch is refused.


async def test_a_cancel_or_an_interrupt_reaches_the_hosts_control_stream(wall: Wall) -> None:
    host = Host(wall.managers, wall.holder)
    relay = wall.managers.relay
    for kind in (StopKind.CANCEL, StopKind.INTERRUPT):
        waiting = asyncio.ensure_future(
            transport(wall.managers).run(wall.workspace, command(wall.epoch), seal=NO_SEAL)
        )
        row = await host.claim_soon()
        item_id = host.item_id(row)
        before = await relay.controls(request(), wall.holder, None)
        await relay.stop(request(), wall.owner.org_id, item_id, kind, wall.epoch)
        after = await relay.controls(request(), wall.holder, before[-1].id if before else None)
        assert [(c.item_id, c.kind) for c in after] == [(item_id, kind)]
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        # The run that stopped waiting stopped it too.
        latest = await relay.controls(request(), wall.holder, after[-1].id)
        assert [(c.item_id, c.kind) for c in latest] == [(item_id, StopKind.CANCEL)]


async def test_a_stop_no_host_took_yet_means_it_never_runs(wall: Wall) -> None:
    host = Host(wall.managers, wall.holder)
    relay = wall.managers.relay
    sent = await relay.send(
        request(),
        wall.owner.org_id,
        _call(wall, command(wall.epoch)),
        0,
    )
    await relay.stop(request(), wall.owner.org_id, sent.id, StopKind.CANCEL, wall.epoch)
    assert await host.claim() is None and host.handed == []
    progress = await relay.watch(request(), wall.owner.org_id, sent.id, -1)
    assert progress.state is ExecState.INTERRUPTED


async def test_nothing_a_stale_writer_sends_or_stops_acts(wall: Wall) -> None:
    host = Host(wall.managers, wall.holder)
    relay = wall.managers.relay
    stale = wall.epoch
    queued = await relay.send(request(), wall.owner.org_id, _call(wall, command(stale)), 0)
    running_task = asyncio.ensure_future(
        transport(wall.managers).run(wall.workspace, command(stale), seal=NO_SEAL)
    )
    held = await host.claim_soon()
    while host.item_id(held) == queued.id:
        # The queue hands the first sent first; let it go and take the next.
        await host.finish(held)
        held = await host.claim_soon()
    current = await wall.managers.steps.begin_run(wall.owner, wall.workspace.id)
    # A command the lost run sends is refused, and the engine reads it as a
    # lost claim.
    with pytest.raises(StaleCommand):
        await transport(wall.managers).run(wall.workspace, command(stale), seal=NO_SEAL)
    with pytest.raises(StaleExec):
        await relay.send(request(), wall.owner.org_id, _call(wall, command(stale)), 0)
    # Its stop of a command a host runs does not reach the host.
    before = await relay.controls(request(), wall.holder, None)
    with pytest.raises(StaleExec):
        await relay.stop(request(), wall.owner.org_id, host.item_id(held), StopKind.CANCEL, stale)
    assert await relay.controls(request(), wall.holder, None) == before
    running_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running_task
    assert await relay.controls(request(), wall.holder, None) == before
    # A lost run's command no host took yet is refused at the claim.
    lost = await relay.send(
        request(), wall.owner.org_id, _call(wall, command(current, key=new_id())), 0
    )
    await wall.managers.steps.begin_run(wall.owner, wall.workspace.id)
    assert await host.claim() is None
    progress = await relay.watch(request(), wall.owner.org_id, lost.id, -1)
    assert progress.state is ExecState.INTERRUPTED
    assert progress.outcome is not None and progress.outcome.refused == StaleExec.code


# Check 5: what crosses the wall is verified by its hash at the relay.


async def test_a_part_or_a_result_whose_hash_does_not_verify_is_refused(wall: Wall) -> None:
    host = Host(wall.managers, wall.holder)
    relay = wall.managers.relay
    waiting = asyncio.ensure_future(
        transport(wall.managers).run(wall.workspace, command(wall.epoch), seal=NO_SEAL)
    )
    row = await host.claim_soon()
    item_id = host.item_id(row)
    sent = b"the real output\n"
    tampered = b"the fake output\n"
    with pytest.raises(CrossingRefused):
        await relay.push_part(
            request(),
            wall.holder,
            item_id,
            0,
            "stdout",
            declared(CrossingKind.STREAM_PART, sent),
            tampered,
        )
    real = ExecResult(outcome=ExecOutcome(exit_code=0), output=ExecOutput(stdout="ok"))
    forged = ExecResult(outcome=ExecOutcome(exit_code=0), output=ExecOutput(stdout="forged"))
    for crossing, data in (
        (
            declared(CrossingKind.RESULT, real.model_dump_json().encode()),
            forged.model_dump_json().encode(),
        ),
        # The right bytes declared as another kind of crossing.
        (declared(CrossingKind.STREAM_PART, sent), sent),
    ):
        with pytest.raises(CrossingRefused):
            await relay.push_result(request(), wall.holder, item_id, crossing, data)
    progress = await relay.watch(request(), wall.owner.org_id, item_id, -1)
    assert progress.state is ExecState.RUNNING and progress.parts == ()
    await host.finish(row, 0, "ok")
    assert (await waiting).stdout == "ok"


# Where a call runs: the placement picks the transport, and names the host.


async def test_a_pinned_session_runs_through_the_relay_on_the_host_that_holds_it(
    wall: Wall, tmp_path: Path
) -> None:
    runner = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label="runner-1")
    placement = PlacementRelayedImpl(
        PlacementHostsImpl(wall.storage.get_hosts_storage(), runner),
        wall.storage.get_relay_storage(),
    )
    executor = await placement.executor_of(wall.owner.org_id, wall.workspace.id)
    assert (executor.kind, executor.credential_id, executor.label) == (
        ExecutorKind.HOST,
        wall.holder.host_id,
        "host-1",
    )
    # A cloud session stays on the runner; a pinned one no host holds is refused.
    cloud = await wall.managers.agent_sessions.create_session(wall.owner, make_session())
    assert await placement.executor_of(wall.owner.org_id, cloud.id) == runner
    unheld = await wall.managers.agent_sessions.create_session(wall.owner, make_session())
    await wall.managers.hosts.place_session(wall.owner, unheld.id, wall.pool.id)
    with pytest.raises(PinnedToHosts):
        await placement.executor_of(wall.owner.org_id, unheld.id)
    relayed = transport(wall.managers)
    placed = TransportPlacedImpl(InfraLocalImpl(tmp_path).get_transport(), relayed, placement)
    unheld_workspace = wall.workspace.model_copy(update={"id": unheld.id})
    with pytest.raises(Exception, match="no host holds its workspace"):
        await placed.run(unheld_workspace, command(0), seal=NO_SEAL)
    with pytest.raises(NoWorkspaceHost):
        await wall.managers.relay.send(
            request(),
            wall.owner.org_id,
            _call(wall, command(0)).model_copy(update={"session_id": unheld.id}),
            0,
        )


def _call(wall: Wall, spec: CommandSpec) -> ExecCall:
    return ExecCall(
        session_id=wall.workspace.id,
        key=spec.key,
        request=RunRequest(argv=spec.argv),
        effect=spec.effect,
        deadline=spec.deadline,
        epoch=spec.epoch,
        spec=wall.workspace.spec,
    )


def test_an_id_derived_from_a_key_is_the_same_on_every_run() -> None:
    key = new_id()
    request_bytes = b'{"operation":"run","argv":["ls"]}'
    assert exec_id(key, request_bytes, 0) == exec_id(key, request_bytes, 0)
    assert exec_id(key, request_bytes, 0) != exec_id(key, request_bytes, 1)
    assert isinstance(key_time(key), datetime)
