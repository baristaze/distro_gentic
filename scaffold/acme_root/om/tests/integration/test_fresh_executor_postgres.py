"""A delivery's validation over Postgres and the local Docker, through the
root a deployed process builds: its checks run in a container made for
the run alone, on the delivered commit the platform read from the
project's repository, with the checks and their fixture from the base,
and the container is gone after. The validation hashes to the results the
run wrote, and the result gate confirms the success they show. A
validation session runs as the platform's own work on the same executor,
a head that plants a runner of its own still runs the base's, a head's
`.gitattributes` leaves nothing out of the tree the checks run on, a
head whose code changes the base's fixture while it runs has no verdict,
and a check may write a new file beside that fixture."""

import subprocess
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.checks_repository import RUNNER, UNIT, OnDisk, Repository
from contracts.evidence_storage import make_policy
from contracts.loops import DELIVERY
from contracts.project_storage import in_project
from contracts.tools import stand_ins

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.infra.secrets import SecretsInterface
from acme.infra.transports import TransportInterface
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.container import TransportContainerImpl
from acme.infra.workspaces import Workspace
from acme.infra.workspaces.container import container_name
from acme.om.agents.types.request import Start
from acme.om.agents.types.result import Claim, Result
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.evidence.collector import digest
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.evidence.rules import policy_key
from acme.om.evidence.types.policy import ValidationPolicy
from acme.om.evidence.types.record import RunOutcome, RunPurpose
from acme.om.evidence.types.validation import Delivery
from acme.om.platform_agents.types.validation import ValidationStart, ValidationStatus
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.work.types.work_item import WorkKind
from acme.om.workspaces.impl.reader import RepositoryReaderGitImpl


def docker_runs() -> bool:
    try:
        reply = subprocess.run(["docker", "version"], capture_output=True, timeout=20)
    except OSError, subprocess.TimeoutExpired:
        return False
    return reply.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not docker_runs(), reason="needs a local Docker"),
]

APP = AppContext(type=AppType.PORTAL, version="portal@test")
WORKER = AppContext(type=AppType.WORKER, version="worker@test")
PLANTED = RUNNER.replace('cart.get("TOTAL") == expected', "True")
"""A runner a head plants: it passes whatever the cart holds."""
REWRITES = """\
import os

os.chmod("checks/expected.txt", 0o644)
with open("checks/expected.txt", "w") as fixture:
    fixture.write("4")
TOTAL = 4
"""
"""A cart whose code makes the base's fixture writable, while the check
runs, and writes its own total there."""

BUILDS = """\
with open("checks/built.txt", "w") as built:
    built.write("3")
TOTAL = 3
"""
"""A cart that totals right, and whose code, while the check runs, writes
a new file beside the base's fixture."""
REPLACES = """\
import os

os.remove("checks/expected.txt")
with open("checks/expected.txt", "w") as fixture:
    fixture.write("4")
TOTAL = 4
"""
"""A cart whose code removes the base's fixture from its folder, which
stays writable, while the check runs, and writes its own total there."""


class ReadBack(TransportContainerImpl):
    """The container transport, keeping every file it read back."""

    def __init__(self, records: Path, secrets: SecretsInterface) -> None:
        super().__init__(records, secrets, BrokerNullImpl(), timedelta(seconds=120))
        self.read: list[bytes] = []

    async def read_file(
        self, workspace: Workspace, path: str, max_bytes: int, offset: int = 0
    ) -> bytes:
        data = await super().read_file(workspace, path, max_bytes, offset)
        self.read.append(data)
        return data


class OnDocker(InfraConfiguredImpl):
    """The configured infra over the local Docker: a container for each
    workspace, reached by a transport that keeps what it read back."""

    def __init__(self, root: Path) -> None:
        workspaces = root / "workspaces"
        super().__init__(
            InfraSettings.model_validate(
                {
                    "environment": "local",
                    "buckets_root": root / "buckets",
                    "workspaces_root": workspaces,
                    "workspace_backend": "container",
                }
            )
        )
        self.transport = ReadBack(workspaces / ".records", self.get_secrets())

    def get_transport(self) -> TransportInterface:
        return self.transport


@pytest.fixture
async def storage(
    migration_settings: MigrationSettings, migrated: object
) -> AsyncIterator[StoragePostgresImpl]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield root
    await root.close()


class Delivered:
    """A deployed root over Postgres and the local Docker, a delivery
    session in a project whose policy runs `unit` from the base, and what
    the session delivered."""

    project_id: UUID
    """The project of the session `session` started."""

    def __init__(self, storage: StoragePostgresImpl, tmp_path: Path) -> None:
        self.storage = storage
        self.repository = Repository(tmp_path)
        self.infra = OnDocker(tmp_path)
        self.work = WorkProductMemoryImpl()
        self.managers: Managers = build_managers(
            storage,
            self.infra,
            agent_kinds=(DELIVERY,),
            tool_catalog=stand_ins(*DELIVERY.tools),
            environment="production",
            work_product=self.work,
            workspace_projects=OnDisk(self.repository),
            workspace_reader=RepositoryReaderGitImpl(on_disk=True),
        )

    async def session(self, files: dict[str, str]) -> tuple[TenantContext, UUID, str]:
        """A tenant, its delivery session in a project, and the head the
        session delivered, whose files are `files` over the base."""
        slug = f"ajax-{new_id().hex[-8:]}"
        owner, _ = await self.managers.tenancy.bootstrap(
            RequestContext(request_id=new_id(), app=APP), "Ajax", slug, f"ann-{slug}@x.test", "Ann"
        )
        session = await self.managers.agents.start_session(
            owner, Start(id=new_id(), kind="delivery", title="Fix the cart's total")
        )
        self.project_id = await in_project(
            self.storage.get_project_storage(), owner.org_id, session.id
        )
        policy = make_policy(policy_key(self.project_id))
        await self.managers.evidence.write_policy(
            owner,
            ValidationPolicy.model_validate(
                {**dict(policy), "checks": (UNIT,), "protected": ("checks/**",)}
            ),
        )
        head = self.repository.deliver(files)
        self.work.deliver(
            owner.org_id,
            session.id,
            Delivery(
                project=policy.project,
                base=self.repository.base,
                head=head,
                dirty=False,
                changed=tuple(sorted(files)),
            ),
        )
        return owner, session.id, head


def gone(instance: UUID) -> bool:
    """Whether nothing of an instance is left on the Docker: no container
    and no volume of its name."""
    name = container_name(instance)
    for listing in (("ps", "-a"), ("volume", "ls")):
        done = subprocess.run(
            ["docker", *listing, "-q", "--filter", f"name=^{name}$"],
            check=True,
            capture_output=True,
        )
        if done.stdout.strip():
            return False
    return True


# Check 1: a delivery's checks run in a fresh container from the delivered
# commit, the validation hashes to the results, and the gate confirms it.


async def test_a_deliverys_checks_run_in_a_fresh_container_and_the_gate_confirms_them(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    delivered = Delivered(storage, tmp_path)
    owner, session_id, head = await delivered.session({"src/cart.py": "TOTAL = 3\n"})
    evidence = delivered.managers.evidence

    (validation,) = await evidence.validate(owner, session_id, RunPurpose.VALIDATION)

    (stream,) = delivered.infra.transport.read
    assert validation.results_sha256 == digest(stream.rstrip(b"\n")), (
        "the validation hashes to the results stream the run wrote"
    )
    (record,) = (await evidence.get_runs(owner, session_id, None, 10)).items
    assert validation.records == (record.id,)
    assert (record.version, record.outcome, record.purpose) == (
        head,
        RunOutcome.PASSED,
        RunPurpose.VALIDATION,
    ), "the delivered commit's cart, against the base's fixture"
    assert record.isolation == "container", "it ran in a container, never on this host"
    instance = UUID(validation.executor.removeprefix("executor:"))
    assert record.executor == validation.executor and gone(instance)

    verdict = await delivered.managers.agents.judge_result(
        owner, session_id, Result(claim=Claim.SUCCEEDED, evidence=(record.id,))
    )
    assert (verdict.accepted, verdict.verified) == (True, True), verdict.reason


# Check 1, under a head's attributes: a root `.gitattributes` that leaves
# the base's fixture out of an export changes nothing the checks run on.


async def test_a_heads_attributes_leave_nothing_out_of_the_checks(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    delivered = Delivered(storage, tmp_path)
    owner, session_id, head = await delivered.session(
        {"src/cart.py": "TOTAL = 4\n", ".gitattributes": "checks/expected.txt export-ignore\n"}
    )
    evidence = delivered.managers.evidence

    await evidence.validate(owner, session_id, RunPurpose.VALIDATION)

    (record,) = (await evidence.get_runs(owner, session_id, None, 10)).items
    assert (record.version, record.outcome) == (head, RunOutcome.FAILED), (
        "the base's runner read the base's fixture against the head's cart"
    )
    verdict = await delivered.managers.agents.judge_result(
        owner, session_id, Result(claim=Claim.SUCCEEDED, evidence=(record.id,))
    )
    assert not verdict.accepted, "the gate refuses a success the checks never showed"


# Check 1, while the head runs: the base's fixture is read-only in the
# container, and a head whose code changes it anyway has no verdict.


async def test_a_head_whose_code_changes_the_bases_fixture_while_it_runs_has_no_verdict(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    delivered = Delivered(storage, tmp_path)
    owner, session_id, head = await delivered.session({"src/cart.py": REWRITES})
    evidence = delivered.managers.evidence

    await evidence.validate(owner, session_id, RunPurpose.VALIDATION)

    (record,) = (await evidence.get_runs(owner, session_id, None, 10)).items
    assert (record.version, record.outcome, record.isolation) == (
        head,
        RunOutcome.ERRORED,
        "container",
    ), "a changed protected path leaves the trial without a verdict"
    assert gone(UUID(record.executor.removeprefix("executor:")))


# Check 3: a new file in a protected folder fails no check, and a head
# whose code replaces a file there still has no verdict.


@pytest.mark.parametrize(
    ("cart", "outcome"),
    [(BUILDS, RunOutcome.PASSED), (REPLACES, RunOutcome.ERRORED)],
    ids=["writes-beside", "replaces"],
)
async def test_a_new_file_in_a_protected_folder_passes_and_a_replaced_one_has_no_verdict(
    storage: StoragePostgresImpl, tmp_path: Path, cart: str, outcome: RunOutcome
) -> None:
    delivered = Delivered(storage, tmp_path)
    owner, session_id, head = await delivered.session({"src/cart.py": cart})
    evidence = delivered.managers.evidence

    await evidence.validate(owner, session_id, RunPurpose.VALIDATION)

    (record,) = (await evidence.get_runs(owner, session_id, None, 10)).items
    assert (record.version, record.outcome, record.isolation) == (head, outcome, "container")
    assert gone(UUID(record.executor.removeprefix("executor:")))


# Check 2: a validation session is platform work, run on the same fresh
# container, and its checks are the base's whatever the head holds there.


async def test_a_validation_session_runs_the_bases_runner_whatever_the_head_plants(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    delivered = Delivered(storage, tmp_path)
    owner, _, head = await delivered.session(
        {"src/cart.py": "TOTAL = 4\n", "checks/run.py": PLANTED}
    )
    validations = delivered.managers.platform_agents
    start = ValidationStart(
        id=new_id(),
        project_id=delivered.project_id,
        check_name="unit",
        head=head,
        base=delivered.repository.base,
    )
    session = await validations.start_validation(owner, start)

    claimed = await delivered.managers.work.claim(
        RequestContext(request_id=new_id(), app=WORKER),
        "default",
        (WorkKind.VALIDATION,),
        "maintenance-1",
        timedelta(seconds=30),
    )
    assert claimed is not None
    ctx, item = claimed
    finished = await validations.run_validation(ctx, item.target_id)

    (record,) = (await delivered.managers.evidence.get_runs(ctx, session.id, None, 10)).items
    assert (finished.status, finished.run_id) == (ValidationStatus.FINISHED, record.id)
    assert (record.version, record.outcome, record.isolation) == (
        head,
        RunOutcome.FAILED,
        "container",
    ), "the base's runner ran on the head's cart, in a container"
    assert gone(UUID(record.executor.removeprefix("executor:")))
