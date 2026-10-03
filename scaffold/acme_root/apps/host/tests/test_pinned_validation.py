"""A delivery of a session pinned to a host pool, validated as the platform
validates any: the runner's root, as it boots, and hosts of the tenant's
pools, each the host's own agent against the API in process. The checks
run on a host of the session's pool, in an instance made for the run alone
under an id of its own, never in the session's workspace and never on the
platform's machines. Its results stream is read back through the relay and
hashed, the gate confirms the success it shows, and the instance goes with
its files and its records once the run ends, whatever ended it. A host of
another pool of the tenant, or of another tenant, is handed nothing.

The first case runs over Postgres and needs a migrated database (`make
migrate`); the others run over the memory storage."""

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import UUID

import pytest
from api_support import seed_request
from contracts.checks_repository import UNIT, OnDisk, Repository
from contracts.evidence_storage import make_policy
from contracts.project_storage import in_project
from host_support import Stack, directory_host, postgres, stack, started_host
from runner_support import assistant

from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ceilings
from acme.client.types import IsolationMode
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import DEFAULT_PATH, TransportLocalImpl
from acme.infra.workspaces import IsolationMode as ProviderMode
from acme.infra.workspaces import Workspace
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.om import root as platform_root
from acme.om.agents.types.request import Start
from acme.om.agents.types.result import Claim, Result
from acme.om.base import new_id
from acme.om.evidence.collector import digest
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.evidence.rules import policy_key
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.evidence.types.policy import ValidationPolicy
from acme.om.evidence.types.record import RunOutcome, RunPurpose
from acme.om.evidence.types.validation import Delivery
from acme.om.placement.types.work import WorkspaceOperation, WorkspacePayload
from acme.om.relay.rules import READ_BYTES
from acme.om.root import PlatformPorts
from acme.om.storage.root import StorageInterface
from acme.om.work.types.work_item import WorkKind, WorkStatus
from acme.om.workspaces.impl.reader import RepositoryReaderGitImpl
from acme.services.api.seed import seed_platform
from acme.workers.session_runner.container import RunnerContainer
from acme.workers.session_runner.settings import SessionRunnerSettings

KIND = assistant()
"""The session's kind: its workspace is a directory on a host, as the
pool's hosts make one."""
SETTINGS = SessionRunnerSettings.model_validate(
    {"_env_file": None, "environment": "test", "runner_id": "runner-validation"}
)
SILENT = CheckDeclaration(
    name="unit",
    version="1",
    command=("python3", "-c", "pass", "{version}", "{out}"),
    kind="suite",
    schema_version=1,
)
"""A check that runs and writes no results stream."""
LONG = CheckDeclaration(
    name="unit",
    version="1",
    command=(
        "python3",
        "-c",
        f"import sys; open(sys.argv[2], 'w').write('r' * {2 * READ_BYTES})",
        "{version}",
        "{out}",
    ),
    kind="suite",
    schema_version=1,
)
"""A check whose results stream is longer than one relayed result carries,
and well within the run's bound."""


class ReadBack(TransportLocalImpl):
    """A host's local transport that finds this interpreter first, as the
    checks' runner needs, and keeps where it read each file back."""

    def __init__(self, where: Path) -> None:
        super().__init__(
            where / "records",
            SecretsLocalImpl(None),
            BrokerNullImpl(),
            search_path=f"{Path(sys.executable).parent}:{DEFAULT_PATH}",
        )
        self.records = where / "records"
        self.read: list[tuple[str, bytes]] = []

    async def read_file(self, workspace: Workspace, path: str, max_bytes: int) -> bytes:
        data = await super().read_file(workspace, path, max_bytes)
        self.read.append((workspace.location, data))
        return data


@dataclass
class Hosted:
    """The host of the session's pool, its provider, its transport, and
    where it makes each workspace."""

    agent: HostAgent
    provider: WorkspaceHostImpl
    transport: ReadBack
    root: Path
    claimed: list[UUID] = field(default_factory=list)


async def pool_host(api: Stack, pool_id: UUID, where: Path) -> Hosted:
    """A host of the pool that makes a directory per workspace under its
    root, as `directory_host` does, through a transport that keeps what it
    read back."""
    root = where / "workspaces"
    provider = WorkspaceHostImpl(root)
    transport = ReadBack(where)
    agent = await started_host(
        api,
        pool_id,
        replace(api.settings(where / "home", None), name="host-a"),
        Ceilings(
            projects=None,
            min_isolation=IsolationMode.directory,
            egress=None,
            readable=(str(root),),
        ),
        IsolationMode.directory,
        {ProviderMode.HOST: transport},
        {ProviderMode.HOST: provider},
    )
    return Hosted(agent=agent, provider=provider, transport=transport, root=root)


async def pumped[T](call: Awaitable[T], hosts: dict[HostAgent, list[UUID]]) -> T:
    """What `call` answers, or raises, while every host claims and runs what
    it is handed, as each does beside the runner; and then what is left on
    their lanes, such as a purge the run's end asked for. Each host's
    claimed items are kept under it."""

    async def turn() -> bool:
        took = False
        for host, claimed in hosts.items():
            handled = await host.claim_once()
            if handled is not None:
                claimed.append(handled.item.id)
                took = True
        return took

    running = asyncio.ensure_future(call)
    while not running.done():
        if not await turn():
            await asyncio.sleep(0.01)
    for host in hosts:
        await host.idle()
    while await turn():
        for host in hosts:
            await host.idle()
    return await running


@dataclass
class Runner:
    """The runner's root, the project's repository its projects bind, and
    the work product its sessions deliver to."""

    container: RunnerContainer
    repository: Repository
    work: WorkProductMemoryImpl


def runner(storage: StorageInterface, api: Stack, where: Path) -> Runner:
    """The runner's root over `storage`, as it boots outside `local`: its
    executor is the platform's fresh one, which reaches a pinned session's
    pool through the relay."""
    where.mkdir()
    repository, work = Repository(where), WorkProductMemoryImpl()
    container = RunnerContainer.over(
        SETTINGS,
        storage,
        api.container.infra,
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        agent_kinds=(KIND,),
        ports=PlatformPorts(workspace_projects=OnDisk(repository), work_product=work),
    )
    return Runner(container=container, repository=repository, work=work)


async def delivered(
    run: Runner, api: Stack, pool_id: UUID, check: CheckDeclaration = UNIT
) -> tuple[UUID, str]:
    """A session of the tenant pinned to the pool, in a project whose policy
    runs `check` from the base, and the head it delivered, whose cart the
    base's fixture passes."""
    container, repository = run.container, run.repository
    owner, managers = api.owner, container.managers
    await seed_platform(container.storage, managers, owner, (KIND,))
    session = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=KIND.name, title="Fix the cart's total")
    )
    await api.container.managers.hosts.place_session(owner, session.id, pool_id)
    project_id = await in_project(container.storage.get_project_storage(), owner.org_id, session.id)
    policy = make_policy(policy_key(project_id))
    await managers.evidence.write_policy(
        owner,
        ValidationPolicy.model_validate(
            {**dict(policy), "checks": (check,), "protected": ("checks/**",)}
        ),
    )
    head = repository.deliver({"src/cart.py": "TOTAL = 3\n"})
    run.work.deliver(
        owner.org_id,
        session.id,
        Delivery(
            project=policy.project,
            base=repository.base,
            head=head,
            dirty=False,
            changed=("src/cart.py",),
        ),
    )
    return session.id, head


def instance_of(executor: str) -> UUID:
    return UUID(executor.removeprefix("executor:"))


def gone(path: Path | str) -> bool:
    """Whether nothing is left at `path`, or under it."""
    return not Path(path).exists() or not any(Path(path).iterdir())


@pytest.fixture(autouse=True)
def reads_from_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reader the runner's root builds, allowed to read the project's
    repository from a path, as a deployed one is not."""
    monkeypatch.setattr(
        platform_root,
        "RepositoryReaderGitImpl",
        lambda **options: RepositoryReaderGitImpl(**{**options, "on_disk": True}),
    )


# Check 1: a pinned project's delivery is validated on a host of its pool,
# in an instance nobody used, the record hashes to its results, and the
# gate confirms it.


@pytest.fixture
async def over_postgres(tmp_path: Path) -> AsyncIterator[tuple[Stack, Runner]]:
    storage = postgres()
    async with stack(tmp_path / "api", storage) as api:
        run = runner(postgres(), api, tmp_path / "project")
        yield api, run
        await run.container.storage.close()
    await storage.close()


@pytest.mark.integration
async def test_a_pinned_projects_delivery_is_validated_on_its_pools_host_and_the_gate_confirms_it(
    over_postgres: tuple[Stack, Runner], tmp_path: Path
) -> None:
    api, run = over_postgres
    owner, managers = api.owner, run.container.managers
    pool = await api.pool("pool-a")
    host = await pool_host(api, pool.id, tmp_path / "host")
    session_id, head = await delivered(run, api, pool.id)

    (validation,) = await pumped(
        managers.evidence.validate(owner, session_id, RunPurpose.VALIDATION),
        {host.agent: host.claimed},
    )

    instance = instance_of(validation.executor)
    assert instance != session_id, "the run's instance is never the session's workspace"
    ((location, stream),) = host.transport.read
    assert Path(location) == host.root.resolve() / owner.org_id.hex / instance.hex, (
        "the results stream was read on the pool's host, in the run's own instance"
    )
    assert validation.results_sha256 == digest(stream.rstrip(b"\n"))
    (record,) = (await managers.evidence.get_runs(owner, session_id, None, 10)).items
    assert validation.records == (record.id,) and record.executor == validation.executor
    assert (record.version, record.outcome, record.purpose) == (
        head,
        RunOutcome.PASSED,
        RunPurpose.VALIDATION,
    ), "the delivered commit's cart, against the base's fixture"
    verdict = await managers.agents.judge_result(
        owner, session_id, Result(claim=Claim.SUCCEEDED, evidence=(record.id,))
    )
    assert (verdict.accepted, verdict.verified) == (True, True), verdict.reason
    assert gone(location), "the instance went when the run ended"


# Check 2: the host's instance is destroyed after the run, and a host of
# another pool or of another tenant never runs it.


@pytest.fixture
def over_memory(api: Stack, tmp_path: Path) -> Runner:
    return runner(api.container.storage, api, tmp_path / "project")


async def other_tenant(api: Stack) -> Stack:
    """The same API, under the owner of a second tenant."""
    owner, _ = await api.container.managers.tenancy.bootstrap(
        seed_request(), "Brix", "brix", "bob@example.test", "Bob"
    )
    return replace(api, owner=owner)


async def test_the_instance_goes_after_its_run_and_no_other_pools_or_tenants_host_runs_it(
    api: Stack, over_memory: Runner, tmp_path: Path
) -> None:
    owner, managers = api.owner, over_memory.container.managers
    pool = await api.pool("pool-a")
    host = await pool_host(api, pool.id, tmp_path / "host-a")
    other_pool = await api.pool("pool-b")
    beside, beside_root = await directory_host(
        api, other_pool.id, tmp_path / "host-b", name="host-b"
    )
    brix = await other_tenant(api)
    theirs, theirs_root = await directory_host(
        brix, (await brix.pool("pool-c")).id, tmp_path / "host-c", name="host-c"
    )
    session_id, _ = await delivered(over_memory, api, pool.id)
    elsewhere: dict[HostAgent, list[UUID]] = {beside: [], theirs: []}

    (validation,) = await pumped(
        managers.evidence.validate(owner, session_id, RunPurpose.VALIDATION),
        {host.agent: host.claimed, **elsewhere},
    )

    instance = instance_of(validation.executor)
    ((location, _),) = host.transport.read
    assert Path(location).name == instance.hex
    assert gone(location), "the instance's files went with it"
    assert await host.provider.held() == []
    assert gone(host.transport.records / instance.hex), "and its records"
    assert await managers.relay.binding_of(owner, instance) is None
    purge = await managers.work.latest_for_target(owner, WorkKind.WORKSPACE, instance)
    assert purge is not None and purge.status is WorkStatus.DONE
    assert WorkspacePayload.model_validate(purge.payload).operation is WorkspaceOperation.PURGE
    assert purge.id in host.claimed, "the host of the session's pool destroyed it"
    assert elsewhere == {beside: [], theirs: []}, "no other host was handed any of it"
    assert gone(beside_root) and gone(theirs_root)


async def test_the_instance_goes_when_its_check_ends_the_run(
    api: Stack, over_memory: Runner, tmp_path: Path
) -> None:
    owner, managers = api.owner, over_memory.container.managers
    pool = await api.pool("pool-a")
    host = await pool_host(api, pool.id, tmp_path / "host-a")
    session_id, _ = await delivered(over_memory, api, pool.id, SILENT)

    (validation,) = await pumped(
        managers.evidence.validate(owner, session_id, RunPurpose.VALIDATION),
        {host.agent: host.claimed},
    )

    (record,) = (await managers.evidence.get_runs(owner, session_id, None, 10)).items
    assert validation.records == (record.id,)
    assert record.outcome is RunOutcome.ERRORED, "a check that wrote no results counts, failed"
    assert host.claimed, "the run's instance was made on the pool's host"
    assert await host.provider.held() == [], "and it went when the check ended the run"
    assert gone(host.root / owner.org_id.hex)


async def test_a_results_stream_longer_than_one_relayed_read_is_an_errored_run_read_once(
    api: Stack, over_memory: Runner, tmp_path: Path
) -> None:
    owner, managers = api.owner, over_memory.container.managers
    pool = await api.pool("pool-a")
    host = await pool_host(api, pool.id, tmp_path / "host-a")
    session_id, _ = await delivered(over_memory, api, pool.id, LONG)

    (validation,) = await asyncio.wait_for(
        pumped(
            managers.evidence.validate(owner, session_id, RunPurpose.VALIDATION),
            {host.agent: host.claimed},
        ),
        timeout=60,
    )

    (record,) = (await managers.evidence.get_runs(owner, session_id, None, 10)).items
    assert validation.records == (record.id,) and record.outcome is RunOutcome.ERRORED
    ((_, read),) = host.transport.read
    assert len(read) == READ_BYTES + 1, "one read, of what crosses, and no more"
    assert await host.provider.held() == [], "and the instance went"
