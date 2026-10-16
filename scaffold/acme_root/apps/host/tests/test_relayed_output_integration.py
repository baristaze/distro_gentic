"""A hosted command's output over the compose stack: the API in process over
Postgres, the shared cache on Valkey, a host of the pool that runs the
command in a directory it made, and the runner's exec relay that waits on
it. What the command prints streams to the runner through the cache while
it runs, and its result lands on its item.

Needs the compose stack and a migrated database (`make infra-up migrate`)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from host_support import Pace, Stack, directory_host, postgres, stack

from acme.infra.agent_workspaces import (
    AgentWorkspace,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
)
from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.infra.transports import CommandSpec, RecordSeal
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.exec_relay.impl.manager import ExecRelayOptions
from acme.om.exec_relay.impl.transport import TransportRelayImpl
from acme.om.exec_relay.types.exec import ExecState
from acme.om.placement.types.work import ExecPayload

from contracts.agent_session_storage import make_agent_session

pytestmark = pytest.mark.integration

RUNNER = AppContext(type=AppType.WORKER, version="runner@test")
# A directory on the host's own disk shares the host's network.
DIRECTORY = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
LINES = "".join(f"line {n}\n" for n in range(3))


async def _nothing(data: bytes) -> bytes | None:
    return None


NO_SEAL = RecordSeal(seal=_nothing, open=_nothing)


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Stack]:
    storage = postgres()
    settings = InfraSettings.model_validate(
        {
            "environment": "local",
            "cache_backend": "valkey",
            "valkey_url": InfraSettings().valkey_url,
            "buckets_root": tmp_path / "buckets",
        }
    )
    async with stack(tmp_path / "api", storage, InfraConfiguredImpl(settings)) as running:
        yield running
    await storage.close()


async def test_a_hosted_commands_output_streams_through_the_cache_and_its_result_lands(
    api: Stack, tmp_path: Path
) -> None:
    owner, managers = api.owner, api.container.managers
    pool = await api.pool()
    host, _ = await directory_host(api, pool.id, tmp_path / "host")
    session = await managers.agent_sessions.create_agent_session(owner, make_agent_session())
    await managers.hosts.place_session(owner, session.id, pool.id)
    await managers.exec_relay.ask_prepare(owner, session.id, DIRECTORY)
    assert await host.claim_once() is not None
    await host.idle()
    epoch = await managers.agent_steps.begin_run(owner, session.id)
    workspace = AgentWorkspace(id=session.id, org_id=owner.org_id, spec=DIRECTORY, location="")
    runner = TransportRelayImpl(
        lambda: managers.exec_relay, lambda: RequestContext(request_id=new_id(), app=RUNNER)
    )
    printed: list[tuple[str, str]] = []

    async def sink(stream: str, text: str) -> None:
        printed.append((stream, text))

    script = "for n in 0 1 2; do echo line $n; sleep 0.3; done"
    spec = CommandSpec(
        argv=("sh", "-c", script),
        key=new_id(),
        epoch=epoch,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
        effect="unsafe",
    )
    waiting = asyncio.ensure_future(runner.run(workspace, spec, sink, seal=NO_SEAL))
    streams = api.container.infra.get_streams()
    item_id = None
    live_while_running: list[tuple[str, str]] = []
    on_cache = 0
    pace = Pace()
    while not waiting.done():
        one = await host.tick()
        if one is not None and item_id is None:
            item_id = ExecPayload.model_validate(one.item.payload).item_id
        if item_id is not None and not live_while_running and printed:
            # The runner has read output while the command still runs, and
            # the cache on Valkey holds it.
            live_while_running = list(printed)
            held = await streams.read(item_id, {}, ExecRelayOptions().output)
            on_cache = sum(len(run.entries) for run in held)
        await pace.after(one is not None)
    ran = await waiting
    assert item_id is not None
    assert live_while_running and live_while_running[0] == ("stdout", "line 0\n")
    assert on_cache >= 1
    assert printed == [("stdout", f"line {n}\n") for n in range(3)]
    assert (ran.exit_code, ran.stdout) == (0, LINES)
    rctx = RequestContext(request_id=new_id(), app=RUNNER)
    done = await managers.exec_relay.watch(rctx, owner.org_id, item_id, len(printed) - 1)
    assert done.state is ExecState.DONE and done.parts == ()
    assert done.output is not None and done.output.stdout == LINES
