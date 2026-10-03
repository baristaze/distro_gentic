"""The platform's evidence over a real storage, the way a process builds
it, with an executor whose check fails at the base and a work product the case delivers: what
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
from contracts.acceptance import DefectExecutor, EvidenceParts
from contracts.doubles import SessionProjectsMemory
from contracts.evidence import ARM, arm_policy

APP = AppContext(type=AppType.PORTAL, version="portal@test")


@dataclass
class World:
    managers: Managers
    parts: EvidenceParts
    owner: TenantContext


async def world_over(storage: StorageInterface, tmp_path: Path) -> World:
    """A tenant of its own, the `arm` project's policy written, and the
    evidence over `storage`, where every session belongs to `arm`."""
    settings = InfraSettings.model_validate(
        {"environment": "local", "buckets_root": tmp_path / "buckets"}
    )
    work, executor = WorkProductMemoryImpl(), DefectExecutor(name="station-1")
    projects = SessionProjectsMemory(default=ARM)
    managers = build_managers(
        storage,
        InfraConfiguredImpl(settings),
        executor=executor,
        work_product=work,
        session_policies=projects,
    )
    slug = f"export-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Export",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    await managers.evidence.write_policy(owner, arm_policy())
    gate = ResultGateEvidenceImpl(storage.get_evidence_storage(), work, projects)
    parts = EvidenceParts(managers.evidence, storage.get_evidence_storage(), work, executor, gate)
    return World(managers, parts, owner)
