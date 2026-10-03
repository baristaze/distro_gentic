"""A workspace a pinned session needs is prepared by a host of its pool,
against the live app, in process. The ask waits once on the pool's lane,
however often the loop asks. The first host's answer binds the session to
it; a second host that made one too lets its own go. A host that cannot
make it hands the work back to its pool, and a host answers only a prepare
it holds."""

from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from host_support import Stack, directory_host

from acme.apps.host.ceilings import Ceilings
from acme.client.client import ApiError
from acme.client.types import IsolationMode as HostMode
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.base import new_id
from acme.om.work.types.work_item import WorkKind

DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))


def made_in(location: str, root: Path) -> bool:
    """Whether the host made the workspace as a directory under its root."""
    path = Path(location)
    return path.is_dir() and path.is_relative_to(root)


async def a_pinned_session(api: Stack, pool_id: UUID) -> UUID:
    managers = api.container.managers
    session = await managers.agent_sessions.create_session(api.owner, make_session())
    await managers.hosts.place_session(api.owner, session.id, pool_id)
    return session.id


async def test_the_first_host_to_answer_holds_the_workspace_and_a_second_lets_its_own_go(
    api: Stack, tmp_path: Path
) -> None:
    relay = api.container.managers.relay
    pool = await api.pool()
    session_id = await a_pinned_session(api, pool.id)
    assert await relay.ask_prepare(api.owner, session_id, DIRECTORY)
    assert not await relay.ask_prepare(api.owner, session_id, DIRECTORY)  # one ask waits

    first, first_root = await directory_host(api, pool.id, tmp_path / "a", name="host-a")
    assert await first.claim_once() is not None
    await first.idle()
    assert await first.claim_once() is None  # the one ask is taken
    bound = await relay.binding_of(api.owner, session_id)
    assert bound is not None and bound.host_id == UUID(first.credential.host_id)
    assert made_in(bound.location, first_root)

    # A second prepare reaches another host of the pool while the first
    # holds the workspace: the binding stays, and the second's directory goes.
    assert await relay.ask_prepare(api.owner, session_id, DIRECTORY)
    second, second_root = await directory_host(api, pool.id, tmp_path / "b", name="host-b")
    assert await second.claim_once() is not None
    await second.idle()
    assert await relay.binding_of(api.owner, session_id) == bound
    assert not (second_root / api.owner.org_id.hex / session_id.hex).exists()
    assert (first_root.resolve() / api.owner.org_id.hex / session_id.hex).is_dir()


async def test_a_host_that_cannot_make_it_hands_the_prepare_back_to_its_pool(
    api: Stack, tmp_path: Path
) -> None:
    relay = api.container.managers.relay
    pool = await api.pool()
    session_id = await a_pinned_session(api, pool.id)
    await relay.ask_prepare(api.owner, session_id, DIRECTORY)
    # Its owner takes no project's work: the ceilings refuse the prepare.
    closed = Ceilings(projects=frozenset(), min_isolation=HostMode.directory, egress=None)
    host, root = await directory_host(api, pool.id, tmp_path, ceilings=closed)

    assert await host.claim_once() is not None
    assert await relay.binding_of(api.owner, session_id) is None
    assert not root.exists()
    # Back on the pool's lane after a wait, for a host that can give it.
    assert await api.container.managers.work.has_open(api.owner, WorkKind.WORKSPACE, session_id)
    assert await host.claim_once() is None


async def test_a_host_answers_only_a_prepare_it_holds(api: Stack, tmp_path: Path) -> None:
    pool = await api.pool()
    host, _ = await directory_host(api, pool.id, tmp_path)
    async with host.client() as client:
        with pytest.raises(ApiError) as refused:
            await client.answer_prepare(new_id(), location="/srv/elsewhere")
    assert refused.value.status == 409
