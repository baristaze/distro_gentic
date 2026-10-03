"""The relay storage contract: exec items with how they ended, the parts of
their output, the control messages for the host that holds them, and the
host that holds each session's workspace. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from datetime import timedelta
from uuid import UUID

import pytest

from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed
from acme.om.placement.types.work import ExecOperation
from acme.om.relay.storage import RelayStorageInterface
from acme.om.relay.types.exec import (
    ExecControl,
    ExecItem,
    ExecOutcome,
    ExecPart,
    ExecState,
    StopKind,
    WorkspaceBinding,
)

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_item",
        "read_item",
        "read_items_by_key",
        "read_running",
        "write_item",
        "add_part",
        "read_parts",
        "add_control",
        "read_controls",
        "write_binding",
        "read_binding",
        "purge_session",
        "purge_tenant",
    }
)
"""Every method of `RelayStorageInterface` that takes a tenant has a case in
this module that presents another tenant's."""

SPEC = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
SEALED = bytes(range(256))
"""Sealed content is any bytes, none of them text."""


def make_item(session_id: UUID | None = None, key: UUID | None = None) -> ExecItem:
    now = utcnow()
    actor = new_id()
    item_id = new_id()
    return ExecItem(
        id=item_id,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        session_id=session_id or new_id(),
        key=key or new_id(),
        operation=ExecOperation.RUN,
        effect="unsafe",
        host_id=new_id(),
        location="/srv/work/one",
        spec=SPEC,
        deadline=now + timedelta(minutes=5),
        epoch=3,
        request=SEALED + b"request",
        row_id=new_id(),
    )


def running(item: ExecItem, lease: timedelta) -> ExecItem:
    return item.model_copy(
        update={
            "state": ExecState.RUNNING,
            "claim": {"claimed_by": f"host:{item.host_id}"},
            "lease_expires_at": utcnow() + lease,
            "version": item.version + 1,
        }
    )


def make_part(item: ExecItem, seq: int) -> ExecPart:
    return ExecPart(
        id=new_id(),
        created_at=utcnow(),
        session_id=item.session_id,
        row_id=item.row_id,
        seq=seq,
        stream="stdout",
        text=SEALED + str(seq).encode(),
        sha256="0" * 64,
    )


def make_control(item: ExecItem, kind: StopKind = StopKind.CANCEL) -> ExecControl:
    now = utcnow()
    actor = new_id()
    return ExecControl(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        session_id=item.session_id,
        item_id=item.id,
        host_id=item.host_id,
        kind=kind,
    )


def make_binding(session_id: UUID) -> WorkspaceBinding:
    now = utcnow()
    actor = new_id()
    return WorkspaceBinding(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        session_id=session_id,
        host_id=new_id(),
        host_name="host-7",
        location="/srv/work/one",
    )


class RelayStorageContract:
    @pytest.fixture
    def storage(self) -> RelayStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    # Items.

    async def test_an_item_round_trips_once(self, storage: RelayStorageInterface) -> None:
        org = new_id()
        item = make_item()
        assert await storage.create_item(org, item)
        assert not await storage.create_item(org, item.model_copy(update={"epoch": 9}))
        assert await storage.read_item(org, item.id) == item

    async def test_a_calls_items_are_read_oldest_first(
        self, storage: RelayStorageInterface
    ) -> None:
        org, session, key = new_id(), new_id(), new_id()
        first, second = make_item(session, key), make_item(session, key)
        await storage.create_item(org, second)
        await storage.create_item(org, first)
        await storage.create_item(org, make_item(session))
        found = await storage.read_items_by_key(org, session, key, 10)
        assert [item.id for item in found] == [
            item.id for item in sorted([first, second], key=lambda i: (i.created_at, i.id))
        ]
        assert len(await storage.read_items_by_key(org, session, key, 1)) == 1

    async def test_a_write_lands_only_at_the_version_it_read(
        self, storage: RelayStorageInterface
    ) -> None:
        org = new_id()
        item = make_item()
        await storage.create_item(org, item)
        done = item.model_copy(
            update={
                "state": ExecState.DONE,
                "outcome": ExecOutcome(exit_code=0),
                "output": SEALED + b"output",
                "version": 2,
            }
        )
        assert await storage.write_item(org, done, 1) == done
        assert await storage.write_item(org, done.model_copy(update={"version": 3}), 1) is None
        assert await storage.read_item(org, item.id) == done

    async def test_the_sweep_reads_running_items_whose_lease_ended_with_their_tenant(
        self, storage: RelayStorageInterface
    ) -> None:
        ours, theirs = new_id(), new_id()
        ended, live, queued = make_item(), make_item(), make_item()
        for org, item in ((ours, ended), (theirs, live), (ours, queued)):
            await storage.create_item(org, item)
        await storage.write_item(ours, running(ended, timedelta(seconds=-5)), 1)
        await storage.write_item(theirs, running(live, timedelta(minutes=5)), 1)
        found = await storage.read_expired(utcnow(), 100)
        assert [
            (org, item.id) for org, item in found if item.id in {ended.id, live.id, queued.id}
        ] == [(ours, ended.id)]

    async def test_a_sessions_running_items_are_read_oldest_first_and_no_others(
        self, storage: RelayStorageInterface
    ) -> None:
        org, other, session = new_id(), new_id(), new_id()
        first, second, queued, elsewhere = (
            make_item(session),
            make_item(session),
            make_item(session),
            make_item(),
        )
        for item in (second, first, queued, elsewhere):
            await storage.create_item(org, item)
        for item in (second, first, elsewhere):
            await storage.write_item(org, running(item, timedelta(minutes=5)), 1)
        found = await storage.read_running(org, session, 10)
        assert [item.id for item in found] == [
            item.id for item in sorted([first, second], key=lambda i: (i.created_at, i.id))
        ]
        assert len(await storage.read_running(org, session, 1)) == 1
        assert await storage.read_running(other, session, 10) == []

    async def test_items_of_another_tenant_are_not_read_or_written(
        self, storage: RelayStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        item = make_item()
        assert await storage.create_item(org, item)
        assert not await storage.create_item(other, item)
        assert await storage.read_item(other, item.id) is None
        assert await storage.read_items_by_key(other, item.session_id, item.key, 10) == []
        moved = item.model_copy(update={"state": ExecState.DONE, "version": 2})
        assert await storage.write_item(other, moved, 1) is None
        assert await storage.read_item(org, item.id) == item

    # Parts.

    async def test_parts_are_read_in_order_after_a_place_once_each(
        self, storage: RelayStorageInterface
    ) -> None:
        org = new_id()
        item = make_item()
        parts = [make_part(item, seq) for seq in (2, 0, 1)]
        for part in parts:
            assert await storage.add_part(org, part)
        assert not await storage.add_part(org, make_part(item, 1))
        read = await storage.read_parts(org, item.row_id, -1, 10)
        assert [part.seq for part in read] == [0, 1, 2]
        assert [part.seq for part in await storage.read_parts(org, item.row_id, 0, 1)] == [1]
        assert await storage.read_parts(org, new_id(), -1, 10) == []

    async def test_parts_of_another_tenant_are_not_read_or_taken(
        self, storage: RelayStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        item = make_item()
        part = make_part(item, 0)
        assert await storage.add_part(org, part)
        assert not await storage.add_part(other, part)
        assert await storage.read_parts(other, item.row_id, -1, 10) == []

    # Controls.

    async def test_a_hosts_controls_are_read_after_the_last_it_saw(
        self, storage: RelayStorageInterface
    ) -> None:
        org = new_id()
        item = make_item()
        first, second = make_control(item), make_control(item, StopKind.REVOKE)
        elsewhere = make_control(make_item())
        for control in (first, second, elsewhere):
            await storage.add_control(org, control, ())
        since = utcnow() - timedelta(minutes=1)
        assert await storage.read_controls(org, item.host_id, None, since, 10) == [first, second]
        assert await storage.read_controls(org, item.host_id, first.id, since, 10) == [second]
        later = utcnow() + timedelta(minutes=1)
        assert await storage.read_controls(org, item.host_id, None, later, 10) == []

    async def test_controls_of_another_tenant_are_not_read(
        self, storage: RelayStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        item = make_item()
        await storage.add_control(org, make_control(item), ())
        since = utcnow() - timedelta(minutes=1)
        assert await storage.read_controls(other, item.host_id, None, since, 10) == []

    async def test_add_control_under_another_tenant_lands_there_alone(
        self, storage: RelayStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        item = make_item()
        await storage.add_control(other, make_control(item), ())
        since = utcnow() - timedelta(minutes=1)
        assert await storage.read_controls(org, item.host_id, None, since, 10) == []

    # Bindings.

    async def test_a_binding_is_a_compare_and_set(self, storage: RelayStorageInterface) -> None:
        org, session = new_id(), new_id()
        binding = make_binding(session)
        await storage.write_binding(org, binding, 0, ())
        with pytest.raises(PreconditionFailed):
            await storage.write_binding(org, make_binding(session), 0, ())
        moved = binding.model_copy(update={"location": "/srv/work/two", "version": 2})
        await storage.write_binding(org, moved, 1, ())
        with pytest.raises(PreconditionFailed):
            await storage.write_binding(org, moved.model_copy(update={"version": 3}), 1, ())
        assert await storage.read_binding(org, session) == moved

    async def test_a_binding_of_another_tenant_is_not_read_or_written(
        self, storage: RelayStorageInterface
    ) -> None:
        org, other, session = new_id(), new_id(), new_id()
        binding = make_binding(session)
        await storage.write_binding(org, binding, 0, ())
        assert await storage.read_binding(other, session) is None
        with pytest.raises(PreconditionFailed):
            await storage.write_binding(other, binding.model_copy(update={"version": 2}), 1, ())
        assert await storage.read_binding(org, session) == binding

    # Purges.

    async def test_purge_session_takes_that_session_alone(
        self, storage: RelayStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        gone, kept = make_item(), make_item()
        for item in (gone, kept):
            await storage.create_item(org, item)
            await storage.add_part(org, make_part(item, 0))
            await storage.add_control(org, make_control(item), ())
            await storage.write_binding(org, make_binding(item.session_id), 0, ())
        assert await storage.purge_session(other, gone.session_id, 100) == 0
        assert await storage.purge_session(org, gone.session_id, 100) == 4
        assert await storage.read_item(org, gone.id) is None
        assert await storage.read_parts(org, gone.row_id, -1, 10) == []
        assert await storage.read_binding(org, gone.session_id) is None
        assert await storage.read_item(org, kept.id) is not None
        assert await storage.read_binding(org, kept.session_id) is not None

    async def test_purge_tenant_takes_that_tenant_alone(
        self, storage: RelayStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        item, theirs = make_item(), make_item()
        await storage.create_item(org, item)
        await storage.create_item(other, theirs)
        await storage.add_part(org, make_part(item, 0))
        assert await storage.purge_tenant(org, 100) == 2
        assert await storage.read_item(org, item.id) is None
        assert await storage.read_item(other, theirs.id) == theirs
