"""A session pinned to a host pool, over Postgres, as the session runner and
a host of the pool run it: the runner's container, wired as it boots, and
the host's own agent against the API in process, each over a storage root
of its own, as two processes hold them, and one key service, as a cloud's.

While no host of the pool is online, the loop parks on the resource before
any model call, and a prepare waits on the pool's lane. A host that comes
online claims it, makes the workspace, and the session is bound to it; the
next loop's tool call runs there, in the directory that host made, and
nowhere on the runner.

Needs a migrated database (`make migrate`)."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from host_support import Stack, directory_host, stack
from runner_support import TOOLS, answers, assistant, runs

from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.agents.types.request import Start
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.steps.rules import message_step
from acme.om.steps.types.header import LoopOutcome, ParkReason
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.work.types.work_item import WorkKind
from acme.services.api.seed import seed_platform
from acme.workers.session_runner.container import RunnerContainer
from acme.workers.session_runner.settings import SessionRunnerSettings

pytestmark = pytest.mark.integration

KIND = assistant()


SETTINGS = SessionRunnerSettings.model_validate(
    {"_env_file": None, "environment": "test", "runner_id": "runner-pinned"}
)


def postgres() -> StoragePostgresImpl:
    """A storage root over the database the integration suites read."""
    settings = MigrationSettings()
    settings.refuse_remote()
    return StoragePostgresImpl(
        settings.role_urls(), settings.role_pools(), system_urls=settings.system_role_urls()
    )


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Stack]:
    storage = postgres()
    async with stack(tmp_path / "api", storage) as running:
        yield running
    await storage.close()


@pytest.fixture
async def runner(api: Stack) -> AsyncIterator[RunnerContainer]:
    container = RunnerContainer.over(
        SETTINGS,
        postgres(),
        api.container.infra,
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        agent_kinds=(KIND,),
        tool_catalog=TOOLS,
    )
    yield container
    await container.storage.close()


def resolved(location: str) -> str:
    """The workspace's directory as the command run in it prints it."""
    return str(Path(location).resolve())


async def test_a_pinned_session_waits_with_no_call_then_runs_its_tool_on_its_pools_host(
    runner: RunnerContainer, api: Stack, tmp_path: Path
) -> None:
    owner = api.owner
    managers = runner.managers
    await seed_platform(runner.storage, managers, owner, (KIND,))
    model = runner.integrations.get_model_providers().get(ProviderName.ANTHROPIC)
    assert isinstance(model, ModelProviderScriptedImpl)
    pool = await api.pool()
    session = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=KIND.name, title="where it runs")
    )
    await api.container.managers.hosts.place_session(owner, session.id, pool.id)
    said = message_step(new_id(), utcnow(), session.id, owner, "Where do you run?")
    await managers.agent_sessions.receive(owner, session.id, [said])

    # No host of the pool is online: the loop waits on the resource, and no
    # model call is made.
    parked = await managers.loop.run(owner, session.id)
    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert parked.park.reason is ParkReason.RESOURCE
    assert model.calls == []
    assert await managers.work.has_open(owner, WorkKind.WORKSPACE, session.id)
    assert await managers.relay.binding_of(owner, session.id) is None

    # A host comes online, claims the prepare, and makes the workspace: the
    # session is bound to it.
    host, root = await directory_host(api, pool.id, tmp_path / "host")
    assert await host.tick() is not None  # its first beat, and the prepare it claims
    await host.idle()
    binding = await managers.relay.binding_of(owner, session.id)
    assert binding is not None and binding.host_id == UUID(host.credential.host_id)
    assert Path(binding.location).is_relative_to(root.resolve())
    assert not await managers.work.has_open(owner, WorkKind.WORKSPACE, session.id)

    # The next loop's tool call runs on that host, in the directory it made.
    await managers.agent_sessions.wake_session(owner, session.id, parked.park)
    model.add(runs("pwd"))
    model.add(answers("On a host of my pool."))
    running = asyncio.ensure_future(managers.loop.run(owner, session.id))
    while not running.done():
        if await host.claim_once() is None:
            await asyncio.sleep(0.01)
    ended = await running
    assert ended.outcome is LoopOutcome.SUCCEEDED, ended
    page = await managers.steps.get_steps(owner, session.id, 0, 100)
    assert [s.type for s in page.items].count(StepType.TOOL_RESPONSE) == 1
    # What the command printed, as the model read it on its second call: the
    # directory the host made.
    assert len(model.calls) == 2
    assert resolved(binding.location) in repr(model.calls[1])
