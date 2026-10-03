"""A product's parts, declared once in `PRODUCT_KINDS`, reach every process
that builds the managers, each built as its binary builds it: the API's
container starts a session of the product's own kind, the session runner
runs it, its tool reading a manager the runner built, and the maintenance
worker knows the kind too. The roots are memory and the local infra, the
model is scripted, and nothing is passed to any `build` but its settings."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from api_support import TOTP_KEY, seed_request, sign_in_as
from contracts.product import LEDGER, ReadTitleImpl, ledger_product
from httpx import ASGITransport
from runner_support import SONNET, answers

from acme.infra.impl.local import InfraLocalImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.calls import ModelReply
from acme.integrations.model_providers.content import TextBlock, ToolUseBlock
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.types import ProviderName, StopReason, Usage
from acme.integrations.root import IntegrationsInterface
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.types.request import Start
from acme.om.base import new_id
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.services.api import container as api_container
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer
from acme.services.api.seed import seed_platform
from acme.services.api.settings import ApiSettings
from acme.workers.maintenance import container as maintenance_container
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.settings import MaintenanceSettings
from acme.workers.session_runner import container as runner_container
from acme.workers.session_runner.container import RunnerContainer
from acme.workers.session_runner.main import build_runner
from acme.workers.session_runner.settings import SessionRunnerSettings

TITLE = "the ledger that will not balance"
PURGE = "postgresql+asyncpg://acme_purge@127.0.0.1:1/acme"


@dataclass
class Processes:
    """The three processes over one memory storage, and the titles the
    product's tool read."""

    api: AppContainer
    runner: RunnerContainer
    maintenance: WorkerContainer
    read: list[str]


@pytest.fixture
def processes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Processes:
    """Each process's container from its `build`, as its binary calls it,
    with `PRODUCT_KINDS` the product's and the database, the infra, and
    the providers swapped for memory, the local infra, and the scripted
    models, each one root the processes share, as they share the
    deployment's."""
    read: list[str] = []
    storage = StorageMemoryImpl()
    infra = InfraLocalImpl(tmp_path)
    providers = IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers())

    def integrations(*_: object) -> IntegrationsInterface:
        return providers

    for module in (api_container, runner_container, maintenance_container):
        monkeypatch.setattr(module, "PRODUCT_KINDS", ledger_product(read))
        monkeypatch.setattr(module, "InfraConfiguredImpl", lambda _: infra)
        monkeypatch.setattr(module, "IntegrationsConfiguredImpl", integrations)
    monkeypatch.setattr(api_container, "postgres_storage", lambda _: storage)
    for module in (runner_container, maintenance_container):
        monkeypatch.setattr(module, "StoragePostgresImpl", lambda *_, **__: storage)
    local = {"_env_file": None, "environment": "local"}
    return Processes(
        api=AppContainer.build(
            ApiSettings.model_validate(
                {**local, "totp_encryption_key": TOTP_KEY, "dev_sign_in_enabled": True}
            )
        ),
        runner=RunnerContainer.build(
            SessionRunnerSettings.model_validate({**local, "runner_id": "runner-test"})
        ),
        maintenance=WorkerContainer.build(
            MaintenanceSettings.model_validate(
                # The purge login it opens, which the memory storage never reaches.
                {**local, "worker_id": "maintenance-test", "database_purge_url": PURGE}
            )
        ),
        read=read,
    )


@pytest.fixture
async def client(processes: Processes) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(processes.api)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def created(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(new_id())}


# Check 1: a product's kind, tool, and classes, handed to the root once,
# start a session through the API and run in the runner, the tool reading
# a manager; the maintenance worker knows the kind too.


async def test_a_products_kind_starts_through_the_api_and_runs_in_the_runner(
    processes: Processes, client: httpx.AsyncClient
) -> None:
    api = processes.api
    owner, org = await api.managers.tenancy.bootstrap(
        seed_request(), "Ajax", "ajax", "ann@example.test", "Ann"
    )
    seeded = await seed_platform(api.storage, api.managers, owner, (LEDGER,))
    assert seeded.project is not None
    headers = await sign_in_as(client, "ann@example.test", org.id)
    started = await client.post(
        "/v1/agent-sessions",
        headers=created(headers),
        json={"kind": LEDGER.name, "title": TITLE, "project_id": str(seeded.project.id)},
    )
    assert started.status_code == 201, started.text
    assert started.json()["kind"] == LEDGER.name
    session_id = started.json()["id"]

    twin = processes.runner.integrations.get_model_providers().get(ProviderName.ANTHROPIC)
    asks = ToolUseBlock(id=f"use_{new_id().hex[:12]}", name=ReadTitleImpl.SPEC.name, input={})
    twin.add(  # pyright: ignore[reportAttributeAccessIssue]
        ModelReply(
            blocks=(TextBlock(text="Reading the title."), asks),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input=10, output=5),
            model=SONNET,
        )
    )
    twin.add(answers("It is the ledger that will not balance."))  # pyright: ignore[reportAttributeAccessIssue]
    said = await client.post(
        f"/v1/agent-sessions/{session_id}/messages",
        headers=created(headers),
        json={"text": "Which ledger is this?"},
    )
    assert said.status_code == 201, said.text

    runner = build_runner(processes.runner)
    running = asyncio.create_task(runner.run())
    status = ""
    try:
        for _ in range(500):
            read = await client.get(f"/v1/agent-sessions/{session_id}", headers=headers)
            status = read.json()["status"]
            if status == SessionStatus.IDLE.value and processes.read:
                break
            await asyncio.sleep(0.01)
    finally:
        runner.stop()
        await running

    assert processes.read == [TITLE], "the product's tool ran in the runner, reading its manager"
    assert status == SessionStatus.IDLE.value


async def test_the_maintenance_worker_knows_a_products_kind(processes: Processes) -> None:
    managers = processes.maintenance.managers
    owner, _ = await managers.tenancy.bootstrap(
        seed_request(), "Ajax", "ajax", "ann@example.test", "Ann"
    )
    session = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=LEDGER.name, title=TITLE)
    )
    assert (session.kind, session.kind_version) == (LEDGER.name, LEDGER.version)
