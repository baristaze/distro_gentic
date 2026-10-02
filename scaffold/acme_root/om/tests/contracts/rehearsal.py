"""The platform's evidence over a real storage, the way a process builds
it, with the line's executor and a work product the case delivers: what
the acceptance suite over Postgres and the benchmark job's rehearsal
share."""

from dataclasses import dataclass
from pathlib import Path

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.root import Managers, build_managers
from acme.om.storage.root import StorageInterface
from contracts.acceptance import GRIP, Line, LineExecutor
from contracts.evidence import arm_policy

APP = AppContext(type=AppType.PORTAL, version="portal@test")


@dataclass
class Bench:
    managers: Managers
    line: Line
    owner: TenantContext


async def bench_over(storage: StorageInterface, tmp_path: Path) -> Bench:
    """A tenant of its own, the `arm` project's policy written, and the
    evidence over `storage`."""
    settings = InfraSettings.model_validate(
        {"environment": "local", "buckets_root": tmp_path / "buckets"}
    )
    work, executor = WorkProductMemoryImpl(), LineExecutor(name="station-1")
    managers = build_managers(
        storage, InfraConfiguredImpl(settings), executor=executor, work_product=work
    )
    slug = f"line-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Line",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    await managers.evidence.write_policy(owner, arm_policy())
    gate = ResultGateEvidenceImpl(storage.get_evidence_storage(), work)
    line = Line(managers.evidence, storage.get_evidence_storage(), work, executor, gate)
    assert GRIP.project == "arm"
    return Bench(managers, line, owner)
