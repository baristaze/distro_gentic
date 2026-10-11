"""The host as a machine of the cloud pool runs it: its settings come from
the seed the pool handed the machine, and from a file that names nothing
secret; it trades the seed's key once, asking again while its machine is
warm, and forgets the key once traded; its workspace is a folder of the
machine at the VM's level, which it neither snapshots nor starts from one,
and its commands run there as its own user."""

import base64
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import botocore.session
import pytest
from api_support import seed_request
from botocore import serialize
from contracts.agent_session_storage import make_session
from host_support import Stack, probes

from acme.apps.host.agent import HostAgent, RoutesHostImpl
from acme.apps.host.ceilings import Ceilings
from acme.apps.host.config import settings_from_env
from acme.apps.host.main import KEPT_WHOLE, host_transports, host_workspaces
from acme.apps.host.relay import ExecutorRelayImpl
from acme.apps.host.seed import forget_key, read_seed
from acme.client.claimant.credential import BadSetting
from acme.client.client import ApiError
from acme.client.types import AdvertisementBody, IssuedHostCredentialView
from acme.client.types import IsolationMode as HostMode
from acme.infra.machines import MachineSpec
from acme.infra.machines.ec2 import MachinesEc2Impl
from acme.infra.machines.seeded import GUEST_WRITE
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import CommandSpec
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.machine import TransportMachineImpl
from acme.infra.transports.twin import RecordSealTwin
from acme.infra.workspaces import (
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
    WorkspaceBase,
)
from acme.infra.workspaces.machine import WorkspaceMachineImpl
from acme.om.base import new_id, utcnow
from acme.om.cloud_pool.rules import new_key, seed
from acme.om.cloud_pool.types.machine import PoolMachine
from acme.om.tenancy.rules import hash_token

ROOT = Path(__file__).resolve().parents[3]
MACHINES = ROOT / "deployment" / "machines"
KEPT = IsolationSpec(
    mode=IsolationMode.VM,
    egress=EgressPolicy(mode=EgressMode.NONE),
    durability=Durability.SNAPSHOT,
)
ORG, SESSION = UUID(int=1), UUID(int=2)

NOTHING_OF_THE_PLATFORMS = re.compile(
    r"DATABASE|POSTGRES|VALKEY|REDIS|S3_|AWS_|KMS|SECRET|PASSWORD|ANTHROPIC|OPENAI|GEMINI|"
    r"MODEL|PROVIDER|LAUNCHDARKLY|SENTRY|ENROLLMENT_TOKEN|_KEY\b",
)
"""What the platform holds that a machine never does: a database's or a
cache's login, a cloud credential, a model's key, a vendor's key, or a
tenant's enrollment token."""


def test_a_machine_names_nothing_secret_in_its_settings_and_its_seed_holds_two_things() -> None:
    names = [
        line.split("=", 1)[0]
        for line in (MACHINES / "host.env").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert names == ["ACME_HOST_MACHINE_SEED", "ACME_HOST_HOME", "ACME_HOST_MACHINE_WORKSPACE"]
    assert not [name for name in names if NOTHING_OF_THE_PLATFORMS.search(name)]
    unit = (MACHINES / "acme-host.service").read_text()
    assert re.findall(r"^Environment\w*=(.*)$", unit, flags=re.MULTILINE) == [
        "/etc/acme-host/host.env"
    ], "the unit reads that file and sets nothing more"
    assert "/run/acme-host" in (MACHINES / "host.env").read_text(), "its home is in memory"
    assert "seed.json" in GUEST_WRITE and "systemctl restart acme-host" in GUEST_WRITE


def resolved(location: str) -> Path:
    return Path(location).resolve()


def made_under(location: str, root: Path) -> bool:
    """Whether what a location names stands, under `root`."""
    return Path(location).exists() and resolved(location).is_relative_to(root.resolve())


def write_seed(path: Path, *, key: str | None = "hmk_the-key") -> Path:
    path.write_text(json.dumps({"api_url": "http://gateway.test/", "key": key}))
    return path


def test_the_seed_says_where_to_call_and_its_key_goes_once_traded(tmp_path: Path) -> None:
    seed = write_seed(tmp_path / "seed.json")
    assert read_seed(seed) == ("http://gateway.test", "hmk_the-key")
    forget_key(seed)
    assert read_seed(seed) == ("http://gateway.test", None)
    assert json.loads(seed.read_text()) == {"api_url": "http://gateway.test"}
    assert read_seed(tmp_path / "none.json") is None
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(BadSetting):
        read_seed(tmp_path / "bad.json")


class Ec2Wire:
    """The cloud as a new machine's start reaches it: each call's parameters
    through botocore's own parameter-build handlers and its serializer, as
    a client runs them before it sends, and the user data the machine reads
    as EC2 decodes it from the query."""

    def __init__(self) -> None:
        self.user_data: bytes | None = None
        self.instances: list[dict[str, Any]] = []
        self._session = botocore.session.get_session()
        self._model = self._session.get_service_model("ec2")

    def _sent(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        model = self._model.operation_model(operation)
        params = dict(request)
        self._session.emit(
            f"before-parameter-build.ec2.{operation}", params=params, model=model, context={}
        )
        query: dict[str, Any] = serialize.create_serializer("ec2").serialize_to_request(
            params, model
        )["body"]
        return query

    async def run_instances(self, **request: Any) -> dict[str, Any]:
        query = self._sent("RunInstances", request)
        if "UserData" in query:
            self.user_data = base64.b64decode(query["UserData"])
        self.instances.append(
            {
                "InstanceId": "i-0001",
                "State": {"Name": "running"},
                "Tags": request["TagSpecifications"][0]["Tags"],
            }
        )
        return {}

    async def describe_instances(self, **_: Any) -> dict[str, Any]:
        return {"Reservations": [{"Instances": self.instances}] if self.instances else []}


class _Cloud:
    def __init__(self, ec2: Ec2Wire) -> None:
        self._ec2 = ec2

    def client(self, service: str, **_: Any) -> Any:
        @asynccontextmanager
        async def opened() -> AsyncIterator[Ec2Wire]:
            yield self._ec2

        return opened()


async def _no_wait(_: float) -> None:
    return None


async def test_a_new_ec2_machine_reads_its_seed_whole_from_its_first_boot_data(
    tmp_path: Path,
) -> None:
    ec2 = Ec2Wire()
    machines = MachinesEc2Impl(
        _Cloud(ec2),  # type: ignore[arg-type]
        region="eu-west-1",
        timeout=timedelta(seconds=10),
        boot=timedelta(seconds=30),
        template="lt-0pool",
        subnets=("subnet-0a",),
        closed="sg-closed",
        open_="sg-open",
        encrypted=True,
        sleep=_no_wait,
    )
    key = new_key()
    await machines.start()
    try:
        spec = MachineSpec(image="ami-0123456789abcdef0", egress_open=False)
        await machines.launch_seeded("acme-vm-p0", spec, None, seed("http://gateway.test", key))
    finally:
        await machines.close()
    assert ec2.user_data is not None
    # The machine's seed unit writes the endpoint's user data as it stands.
    written = tmp_path / "seed.json"
    written.write_bytes(ec2.user_data)
    assert read_seed(written) == ("http://gateway.test", key)


def test_a_machines_settings_take_the_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed = write_seed(tmp_path / "seed.json")
    monkeypatch.setenv("ACME_HOST_MACHINE_SEED", str(seed))
    monkeypatch.setenv("ACME_HOST_MACHINE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.delenv("ACME_ENROLLMENT_TOKEN", raising=False)
    settings = settings_from_env()
    assert settings.machine and settings.api_url == "http://gateway.test"
    assert settings.enrollment_token == "hmk_the-key"
    assert settings.machine_workspace == tmp_path / "workspace"
    forget_key(seed)
    assert settings_from_env().enrollment_token is None
    monkeypatch.delenv("ACME_HOST_MACHINE_SEED")
    assert not settings_from_env().machine


class Client:
    """The gateway's answers to a machine's key: unbound twice, then a
    credential."""

    def __init__(self, unbound: int) -> None:
        self.unbound = unbound
        self.asked: list[str] = []

    async def enroll_machine(
        self, key: str, name: str, advertisement: AdvertisementBody, exec_version: int
    ) -> IssuedHostCredentialView:
        self.asked.append(key)
        if len(self.asked) <= self.unbound:
            raise ApiError(409, "machine_unbound", "serves no session yet", None)
        return IssuedHostCredentialView.model_validate(
            {
                "token": "hst_the-credential",
                "credential_id": str(UUID(int=3)),
                "host_id": str(UUID(int=4)),
                "pool_id": str(UUID(int=5)),
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        )


async def test_a_machines_host_asks_again_while_its_machine_is_warm(tmp_path: Path) -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    routes = RoutesHostImpl(lambda: AdvertisementBody(os="Linux"), sleep=sleep, most_wait=1.5)
    client = Client(unbound=3)
    issued = await routes.enroll(client, "hmk_the-key", "machine")  # type: ignore[arg-type]
    assert issued.claimant_id == UUID(int=4)
    assert client.asked == ["hmk_the-key"] * 4
    assert waits == [1.0, 1.5, 1.5], "a wait that grows to its most"


async def test_a_machines_host_gives_up_on_any_other_refusal() -> None:
    class Refusing(Client):
        async def enroll_machine(self, *args: object, **kwargs: object) -> IssuedHostCredentialView:
            raise ApiError(401, "invalid_credential", "spent", None)

    routes = RoutesHostImpl(lambda: AdvertisementBody(os="Linux"))
    with pytest.raises(ApiError):
        await routes.enroll(Refusing(0), "hmk_spent", "machine")  # type: ignore[arg-type]


async def test_a_machines_workspace_is_a_folder_at_the_vms_level_kept_by_its_pool(
    tmp_path: Path,
) -> None:
    provider = WorkspaceMachineImpl(tmp_path / "workspace")
    workspace = await provider.prepare(ORG, SESSION, KEPT)
    assert made_under(workspace.location, tmp_path / "workspace")
    opened = KEPT.model_copy(update={"egress": EgressPolicy(mode=EgressMode.OPEN)})
    assert (await provider.prepare(ORG, SESSION, opened)).location == workspace.location
    assert [held.id for held in await provider.held_instances()] == [SESSION]

    with pytest.raises(SnapshotRefused, match="pool keeps"):
        await provider.snapshot(workspace)
    with pytest.raises(IsolationRefused, match="as its pool started it"):
        await provider.prepare(ORG, SESSION, KEPT, snapshot=b"a snapshot")
    based = KEPT.model_copy(
        update={"base": WorkspaceBase(image="ubuntu", egress=EgressPolicy(mode=EgressMode.NONE))}
    )
    with pytest.raises(IsolationRefused, match="as its pool started it"):
        await provider.prepare(ORG, SESSION, based)
    listed = KEPT.model_copy(
        update={"egress": EgressPolicy(mode=EgressMode.ALLOWLIST, hosts=("pypi.org",))}
    )
    with pytest.raises(IsolationRefused, match="allowlist"):
        await provider.prepare(ORG, SESSION, listed)
    container = KEPT.model_copy(update={"mode": IsolationMode.CONTAINER})
    with pytest.raises(IsolationRefused):
        await provider.prepare(ORG, SESSION, container)

    await provider.release(workspace)
    assert await provider.held_instances() == []


async def test_a_machines_command_runs_in_its_workspace_as_the_host(tmp_path: Path) -> None:
    provider = WorkspaceMachineImpl(tmp_path / "workspace")
    workspace = await provider.prepare(ORG, SESSION, KEPT)
    transport = TransportMachineImpl(
        tmp_path / "records", SecretsLocalImpl(tmp_path / "secrets"), BrokerNullImpl()
    )
    command = CommandSpec(
        argv=("sh", "-c", "pwd && touch made-here"),
        key=UUID(int=9),
        epoch=1,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    ran = await transport.run(workspace, command, seal=RecordSealTwin().seal)
    assert ran.exit_code == 0, ran.stderr
    assert ran.stdout.strip() == str(resolved(workspace.location))
    assert made_under(str(resolved(workspace.location) / "made-here"), tmp_path / "workspace")


async def test_a_machines_host_enrolls_with_its_key_and_holds_its_sessions_workspace(
    api: Stack, tmp_path: Path
) -> None:
    """Against the live app in process: the host of a machine the pool
    started for a session trades its key, once, for a credential of the
    session's pool of one, and prepares the session's workspace, kept by
    snapshots, which its pool keeps whole."""
    managers = api.container.managers
    session = await managers.agent_sessions.create_session(api.owner, make_session())
    service = await managers.tenancy.service_context(
        seed_request(), api.owner.org_id, api.owner.user_id
    )
    pool = await managers.hosts.session_pool(service, session.id, "cloud")
    key = new_key()
    now = utcnow()
    await api.container.storage.get_cloud_pool_storage().create_machine(
        PoolMachine(
            id=new_id(),
            created_at=now,
            name="acme-vm-ptest0000000000",
            egress_open=True,
            tenant_id=api.owner.org_id,
            session_id=session.id,
            pool_id=pool.id,
            bound_by=api.owner.user_id,
            key_digest=hash_token(key),
            started_at=now,
        )
    )
    settings = replace(
        api.settings(tmp_path / "home", key),
        machine_seed=tmp_path / "seed.json",
        machine_workspace=tmp_path / "workspace",
    )
    agents: list[HostAgent] = []
    executor = ExecutorRelayImpl(
        lambda: agents[0].client(),
        host_transports(settings),
        host_workspaces(settings),
        kept_whole=KEPT_WHOLE,
        flush_seconds=0.0,
        renew_seconds=0.2,
    )
    host = HostAgent(
        settings,
        Ceilings(projects=None, min_isolation=HostMode.vm, egress=None, readable=("/",)),
        probes(HostMode.vm),
        api.client,
        executor,
    )
    agents.append(host)
    await host.start()
    assert UUID(host.credential.pool_id) == pool.id
    identity = await managers.hosts.authenticate(seed_request(), host.credential.token)
    assert identity.session_id == session.id

    kept = KEPT.model_copy(update={"egress": EgressPolicy(mode=EgressMode.OPEN)})
    assert await managers.relay.ask_prepare(api.owner, session.id, kept)
    assert await host.claim_once() is not None
    await host.idle()
    binding = await managers.relay.binding_of(api.owner, session.id)
    assert binding is not None and binding.host_id == identity.id
    assert made_under(binding.location, tmp_path / "workspace")

    with pytest.raises(ApiError) as spent:
        await api.client(None).enroll_machine(key, "again", AdvertisementBody(os="Linux"), 1)
    assert spent.value.status == 401
