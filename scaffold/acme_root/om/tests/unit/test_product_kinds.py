"""A product adds its own kind of work at its root: a work kind with its
payload, its claimant kind, and its lane; a secret owner kind with the
placement that reaches it; a stream kind with its bounds; and an executor
for a validation's environment. Each registers beside the platform's own,
which go through the same registries, and each is held as the platform's
is. The example is a `render` job on a `batch` pool."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.doubles import SessionProjectsMemory, context
from contracts.evidence import (
    CHECKOUT,
    ScriptedExecutor,
    checkout_policy,
    delivered,
    evidence_over,
)
from contracts.evidence_storage import make_record
from contracts.factories import make_org
from contracts.tools import INJECTED_TOKEN
from contracts.trust import trusted
from pydantic import Field, ValidationError

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.streams import StreamBounds
from acme.om.agents.types.result import Claim, Result
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import AppContext, AppType, Permission, RequestContext, Role, TenantContext
from acme.om.evidence.executor import Executors
from acme.om.evidence.types.contract import PLATFORM_ENVIRONMENT
from acme.om.evidence.types.policy import ValidationPolicy
from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.record import RunPurpose
from acme.om.exceptions import NotAuthorized, NotFound, PreconditionFailed, ValidationFailed
from acme.om.outbox.types.row import outbox_row
from acme.om.placement.impl.manager import PlacementManagerImpl
from acme.om.placement.kinds import (
    HOST,
    ClaimantKindSpec,
    platform_claimant_kinds,
    platform_work_kinds,
)
from acme.om.placement.types.claimant import Claimant, ClaimantReport, ReportOutcome
from acme.om.root import Managers, ProductKinds, build_managers
from acme.om.steps.types.header import LoopOutcome
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.trust.owners import ProjectOwnerImpl, SecretOwnerInterface, SecretOwners
from acme.om.trust.rules import crossing
from acme.om.trust.types.secret import PROJECT, SecretDeclaration, SecretStore, kept_as
from acme.om.watch.impl.stream import StreamOptions, step_kinds
from acme.om.watch.kinds import STEP, StreamKind
from acme.om.watch.root import build_kind_streams, build_stream
from acme.om.work.kinds import WorkKindSpec
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus, work_row_kind

LEASE = timedelta(seconds=30)
APP = AppContext(type=AppType.PORTAL, version="portal@test")
GATEWAY = AppContext(type=AppType.API, version="api@test")

RENDER = "RENDER"
BATCH = "batch"


class RenderPayload(Platform):
    """A render job: the batch pool that runs it, and its frames."""

    pool_id: UUID
    frames: int = Field(ge=1, le=1000)


def batch_lane(pool_id: UUID) -> str:
    return f"batch:{pool_id}"


def _render_lane(payload: RenderPayload) -> str:
    return batch_lane(payload.pool_id)


RENDER_KIND = WorkKindSpec(RENDER, RenderPayload, Permission.WRITE, _render_lane, claimant=BATCH)
BATCH_CLAIMANT = ClaimantKindSpec(BATCH, lambda node: ((batch_lane(node.pool_id), (RENDER,)),))
# A claimant kind that names a kind which does not name it back.
GREEDY = ClaimantKindSpec("greedy", lambda node: ((batch_lane(node.pool_id), (RENDER,)),))
PRODUCT = ProductKinds(work=(RENDER_KIND,), claimants=(BATCH_CLAIMANT, GREEDY))


def request(app: AppContext = GATEWAY) -> RequestContext:
    return RequestContext(request_id=new_id(), app=app)


@pytest.fixture
def managers(tmp_path: Path) -> Managers:
    return build_managers(StorageMemoryImpl(), InfraLocalImpl(tmp_path), product_kinds=PRODUCT)


async def an_owner(managers: Managers, slug: str) -> TenantContext:
    owner, _ = await managers.tenancy.bootstrap(
        request(APP), slug.title(), slug, f"ann@{slug}.test", "Ann"
    )
    return owner


def an_item(ctx: TenantContext, kind: str, payload: dict[str, Any]) -> WorkItem:
    now = utcnow()
    return WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=kind,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload=payload,
        lane="default",  # what a producer names is never where the item goes
        available_at=now,
    )


def a_render(ctx: TenantContext, pool_id: UUID, frames: int = 24) -> WorkItem:
    return an_item(ctx, RENDER, {"pool_id": str(pool_id), "frames": frames})


def node(pool_id: UUID, org_id: UUID | None, kind: str = BATCH) -> Claimant:
    return Claimant(kind=kind, id=new_id(), org_id=org_id, pool_id=pool_id)


# A work kind, its claimant kind, and its lane.


async def test_a_products_kind_goes_to_its_lane_and_only_its_claimant_kind_takes_it(
    managers: Managers,
) -> None:
    ajax = await an_owner(managers, "ajax")
    pool = new_id()
    render = await managers.work.enqueue(ajax, a_render(ajax, pool))
    assert render.lane == batch_lane(pool), "the lane its registered rule reads off its payload"

    for other in (node(pool, ajax.org_id, "greedy"), node(pool, ajax.org_id, HOST)):
        assert await managers.placement.claim_for(request(), other, LEASE) is None
    claimed = await managers.placement.claim_for(request(), node(pool, ajax.org_id), LEASE)
    assert claimed is not None
    ctx, item = claimed
    assert (ctx.org_id, item.id, item.kind) == (ajax.org_id, render.id, RENDER)
    assert item.claimed_by is not None and item.claimed_by.startswith(f"{BATCH}:")


async def test_a_write_that_asks_for_a_products_kind_lands_it_on_its_lane(
    managers: Managers,
) -> None:
    ajax = await an_owner(managers, "ajax")
    pool = new_id()
    row = outbox_row(ajax, work_row_kind(RENDER), new_id(), {"pool_id": str(pool), "frames": 2})
    relayed = await managers.work.enqueue_relayed(ajax.org_id, row)
    assert (relayed.kind, relayed.lane) == (RENDER, batch_lane(pool))
    off_shape = outbox_row(ajax, work_row_kind(RENDER), new_id(), {"frames": 2})
    with pytest.raises(ValidationFailed, match="payload of RENDER"):
        await managers.work.enqueue_relayed(ajax.org_id, off_shape)


async def test_a_claimant_in_a_tenants_wall_is_never_handed_another_tenants_render(
    managers: Managers,
) -> None:
    ajax, beta = await an_owner(managers, "ajax"), await an_owner(managers, "beta")
    pool = new_id()
    stray = await managers.work.enqueue(beta, a_render(beta, pool))
    ours = await managers.work.enqueue(ajax, a_render(ajax, pool))

    claimed = await managers.placement.claim_for(request(), node(pool, ajax.org_id), LEASE)
    assert claimed is not None and claimed[1].id == ours.id
    failed = await managers.work.get_item(beta, stray.id)
    assert failed.status is WorkStatus.FAILED and "another tenant" in (failed.last_error or "")
    # A node of the product's own pool serves every tenant.
    served = await managers.work.enqueue(beta, a_render(beta, pool))
    shared = await managers.placement.claim_for(request(), node(pool, None), LEASE)
    assert shared is not None and (shared[0].org_id, shared[1].id) == (beta.org_id, served.id)


async def test_a_claimant_reads_and_answers_only_the_items_it_holds(managers: Managers) -> None:
    ajax, beta = await an_owner(managers, "ajax"), await an_owner(managers, "beta")
    pool = new_id()
    await managers.work.enqueue(ajax, a_render(ajax, pool))
    await managers.work.enqueue(ajax, a_render(ajax, pool))
    holder = node(pool, ajax.org_id)
    claimed = await managers.placement.claim_for(request(), holder, LEASE)
    assert claimed is not None
    item = claimed[1]
    placement = managers.placement
    assert (await placement.held_for(request(), holder, ajax.org_id, item.id)).id == item.id

    done = ClaimantReport(item_id=item.id, outcome=ReportOutcome.DONE)
    strangers = (
        (node(pool, ajax.org_id), ajax.org_id),  # another node of its kind and tenant
        (holder, beta.org_id),  # its own, asked in another tenant
        (node(pool, None), ajax.org_id),  # a node of the product's own pool
        (holder.model_copy(update={"kind": HOST}), ajax.org_id),  # a host by its id
        (holder.model_copy(update={"kind": "greedy"}), ajax.org_id),  # another kind by its id
    )
    for who, org_id in strangers:
        with pytest.raises(NotFound):
            await placement.held_for(request(), who, org_id, item.id)
        with pytest.raises(NotFound):
            await placement.report_for(request(), who, org_id, done)
        with pytest.raises(NotFound):
            await placement.extend_for(request(), who, org_id, item.id, LEASE)
    with pytest.raises(NotFound):
        await placement.held_for(request(), holder, ajax.org_id, new_id())

    # A report is held to its shape before anything reads it.
    malformed: tuple[dict[str, Any], ...] = (
        {"item_id": str(item.id), "outcome": "failed"},
        {"item_id": str(item.id), "outcome": "done", "error": "late"},
        {"item_id": str(item.id), "outcome": "failed", "error": "x" * 501},
        {"item_id": str(item.id), "outcome": "lost"},
        {"item_id": "not-an-id", "outcome": "done"},
    )
    for report in malformed:
        with pytest.raises(ValidationError):
            ClaimantReport.model_validate(report)

    renewed = await placement.extend_for(request(), holder, ajax.org_id, item.id, LEASE)
    assert renewed.lease_expires_at is not None
    finished = await placement.report_for(request(), holder, ajax.org_id, done)
    assert finished.status is WorkStatus.DONE
    with pytest.raises(NotFound):
        await placement.held_for(request(), holder, ajax.org_id, item.id)

    second = await placement.claim_for(request(), holder, LEASE)
    assert second is not None
    failure = ClaimantReport(item_id=second[1].id, outcome=ReportOutcome.FAILED, error="no disk")
    failed = await placement.report_for(request(), holder, ajax.org_id, failure)
    assert failed.status is WorkStatus.QUEUED, "retried until its attempts are spent"
    assert failed.last_error == f"{holder.worker_id}: no disk"


async def test_an_unregistered_kind_or_a_payload_off_its_shape_is_refused(
    managers: Managers, tmp_path: Path
) -> None:
    ajax = await an_owner(managers, "ajax")
    with pytest.raises(NotAuthorized, match="no permission asks for work of kind UNREGISTERED"):
        await managers.work.enqueue(ajax, an_item(ajax, "UNREGISTERED", {}))
    with pytest.raises(ValidationFailed, match="payload of RENDER"):
        await managers.work.enqueue(ajax, a_render(ajax, new_id(), frames=0))
    with pytest.raises(ValueError, match="capitals"):
        WorkKindSpec("render", RenderPayload, Permission.WRITE)
    with pytest.raises(ValueError, match="names its lane"):
        WorkKindSpec("UNPLACED", RenderPayload, Permission.WRITE, claimant=BATCH)

    # A product never takes over a kind of the platform's, nor leaves its
    # work to a claimant kind nobody registered.
    takeovers = (
        ProductKinds(work=(replace(RENDER_KIND, name=WorkKind.EXEC),), claimants=(BATCH_CLAIMANT,)),
        ProductKinds(claimants=(ClaimantKindSpec(HOST, lambda _: ()),)),
        ProductKinds(work=(RENDER_KIND,)),
    )
    for product in takeovers:
        with pytest.raises(ValueError):
            build_managers(StorageMemoryImpl(), InfraLocalImpl(tmp_path), product_kinds=product)
    # No worker of the platform's runs a product's kind, so it names who claims it.
    with pytest.raises(ValueError, match="names no claimant kind"):
        ProductKinds(work=(WorkKindSpec("UNCLAIMED", RenderPayload, Permission.WRITE),))


def test_the_platforms_kinds_go_through_the_same_registries(managers: Managers) -> None:
    work = platform_work_kinds()
    assert {spec.name for spec in work} == set(WorkKind)
    assert work.claimed_by(HOST) == {WorkKind.EXEC, WorkKind.WORKSPACE}
    assert [spec.name for spec in platform_claimant_kinds()] == [HOST]
    placement = managers.placement
    assert isinstance(placement, PlacementManagerImpl)
    held = placement._kinds  # pyright: ignore[reportPrivateUsage] (the root's one registry)
    assert {spec.name for spec in held} == set(WorkKind) | {RENDER}
    assert held.claimed_by(BATCH) == {RENDER} and held.claimed_by("greedy") == frozenset()
    platform = ScriptedExecutor()
    with pytest.raises(ValueError, match="registered twice"):
        Executors(platform, {PLATFORM_ENVIRONMENT: ScriptedExecutor(name="batch-1")})


# A secret owner kind, reached only from its owner's placement.


class BatchPools(SecretOwnerInterface):
    """The product's owner kind: a batch pool, whose secrets reach the
    sessions placed on it."""

    kind = BATCH

    def __init__(self) -> None:
        self.held: set[UUID] = set()
        self.placed: dict[UUID, UUID] = {}

    async def holds(self, ctx: TenantContext, owner_id: UUID) -> bool:
        return owner_id in self.held

    async def owner_of(self, ctx: TenantContext, session_id: UUID) -> UUID | None:
        return self.placed.get(session_id)


def on_pool(pool_id: UUID, store: SecretStore = SecretStore.CLOUD) -> SecretDeclaration:
    now = utcnow()
    return SecretDeclaration(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        name=INJECTED_TOKEN.name,
        variable=INJECTED_TOKEN.env or "",
        owner_kind=BATCH,
        owner_id=pool_id,
        scope="call:render-farm",
        store=store,
    )


async def test_a_products_secret_reaches_only_the_sessions_placed_on_its_owner(
    tmp_path: Path,
) -> None:
    pools = BatchPools()
    platform = trusted(tmp_path, product_kinds=ProductKinds(secret_owners=(pools,)))
    trust, owner = platform.trust.trust, platform.owner
    ours, theirs = new_id(), new_id()
    pools.held |= {ours, theirs}
    declared = await trust.declare_secret(owner, on_pool(ours))
    await trust.put_secret(owner, ours, INJECTED_TOKEN.name, "value-ours", owner_kind=BATCH)
    on_ours, on_theirs, loose = [await platform.start() for _ in range(3)]
    pools.placed |= {on_ours: ours, on_theirs: theirs}

    resolved = await trust.resolve_secrets(owner, on_ours, (INJECTED_TOKEN,))
    assert resolved == {INJECTED_TOKEN.name: kept_as(declared)}
    for elsewhere in (on_theirs, loose):
        resolved = await trust.resolve_secrets(owner, elsewhere, (INJECTED_TOKEN,))
        assert resolved == {}, "the name alone, never the pool's value"
    # Handed a declaration of an owner it is not placed on, the rule refuses it.
    refusal = crossing(INJECTED_TOKEN, declared, inside_wall=False, placed={BATCH: theirs})
    assert refusal == f"{INJECTED_TOKEN.name} is declared on another batch, " + (
        "and never reaches this session"
    )
    assert crossing(INJECTED_TOKEN, declared, inside_wall=False, placed={PROJECT: ours})
    # An owner the tenant does not hold, or of a kind nobody registered, owns nothing.
    for unowned in (on_pool(new_id()), on_pool(ours).model_copy(update={"owner_kind": "farm"})):
        with pytest.raises(NotFound):
            await trust.declare_secret(owner, unowned)


def test_a_product_never_takes_over_the_projects_secrets() -> None:
    class Impostor(BatchPools):
        kind = PROJECT

    project = ProjectOwnerImpl(SessionProjectsMemory())
    assert [owner.kind for owner in SecretOwners((project, BatchPools()))] == [PROJECT, BATCH]
    with pytest.raises(ValueError, match="registered twice"):
        SecretOwners((project, Impostor()))


# A stream kind, bounded like the step's.


async def test_a_products_stream_kind_is_held_to_its_bounds(tmp_path: Path) -> None:
    infra = InfraLocalImpl(tmp_path)
    frames = StreamKind("frames", entries=2, bytes=1024, streams=1)
    product = ProductKinds(streams=(frames,))
    # The open streams of every group and the idle time bound the shared
    # cache, so a product's kind is held to the step's: it never closes the
    # step's streams sooner than the step's own bounds do.
    cache = StreamOptions()
    bounds = step_kinds(cache, frames).bounds("frames")
    assert bounds == StreamBounds(
        entries=2, bytes=1024, streams=1, open=cache.max_open, idle=cache.idle
    )
    streams = build_kind_streams(infra, product)
    job, first, second = new_id(), new_id(), new_id()

    await streams.append("frames", job, first, [(0, b"a"), (1, b"b"), (2, b"c")])
    (held,) = await streams.read("frames", job, {})
    assert (held.first, [entry for _, entry in held.entries]) == (1, [b"b", b"c"])
    await streams.append("frames", job, second, [(0, b"x")])
    assert [slice.stream for slice in await streams.read("frames", job, {})] == [second]
    # Its group is its own: the step's reads of the same id find none of it.
    step = build_stream(infra, lambda: pytest.fail("no stream opens"), product_kinds=product)
    assert await step.read(job, ()) == ()
    for unbounded in ("unregistered", STEP):
        with pytest.raises(NotFound):
            await streams.append(unbounded, job, first, [(3, b"d")])
        with pytest.raises(NotFound):
            await streams.read(unbounded, job, {})
    with pytest.raises(ValueError, match="positive"):
        StreamKind("frames", entries=0, bytes=1024, streams=1)
    loosened = ProductKinds(streams=(StreamKind(STEP, entries=1_000_000, bytes=1, streams=1),))
    with pytest.raises(ValueError, match="registered twice"):
        build_kind_streams(infra, loosened)


# An executor for a validation's environment, held at the gate as the
# platform's is.


def policy_in(environment: str) -> ValidationPolicy:
    """The `checkout` policy, its `unit` check run in `environment`."""
    policy = checkout_policy()
    checks = tuple(
        check.model_copy(update={"environment": environment}) if check.name == "unit" else check
        for check in policy.checks
    )
    return policy.model_copy(update={"checks": checks})


SCRIPTS: dict[str, dict[str, Any]] = {
    "passes": {},
    "fails": {"outcome": lambda check, trial: "failed"},
    "a double's": {"provenance": Provenance.DOUBLE},
    "tampered": {"tamper": lambda results: results + b"\n"},
}


async def gate_reads(environment: str, script: dict[str, Any]) -> str:
    """What the gate makes of a success whose `unit` check ran in
    `environment`, on an executor scripted as `script` says: the platform's
    under its own environment, and the product's under `batch`."""
    runs = ScriptedExecutor(name=f"{environment}-1", **script)
    idle = ScriptedExecutor(name="idle-1")
    if environment == PLATFORM_ENVIRONMENT:
        evidence = evidence_over(runs, executors={BATCH: idle})
    else:
        evidence = evidence_over(idle, executors={BATCH: runs})
    org = make_org()
    owner, ctx = context(Role.OWNER, org), context(Role.MEMBER, org)
    session = new_id()
    await evidence.manager.write_policy(owner, policy_in(environment))
    work = make_record(session, step_id=new_id())
    await evidence.manager.record_run(ctx, work)
    evidence.work.deliver(org.id, session, delivered())
    try:
        await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    except ValidationFailed as error:
        kept = await evidence.storage.read_validations(org.id, session, None, 10)
        return f"not kept ({len(kept)}): {error}"
    finally:
        assert idle.requests == [], "only the check's own environment ran it"
    assert [check.name for request in runs.requests for check in request.checks] == ["unit"]
    result = Result(claim=Claim.SUCCEEDED, evidence=(work.id,))
    verdict = await evidence.gate.check(ctx, session, result)
    if verdict.accepted and verdict.verified and verdict.outcome is LoopOutcome.SUCCEEDED:
        return "succeeded"
    return f"refused: {verdict.reason}"


@pytest.mark.parametrize("script", SCRIPTS)
async def test_a_products_executor_passes_the_gate_only_as_the_platforms_does(
    script: str,
) -> None:
    platforms = await gate_reads(PLATFORM_ENVIRONMENT, SCRIPTS[script])
    products = await gate_reads(BATCH, SCRIPTS[script])
    assert products == platforms
    assert (platforms == "succeeded") == (script == "passes")


async def test_a_check_runs_only_in_an_environment_an_executor_is_registered_for() -> None:
    platform, product = ScriptedExecutor(), ScriptedExecutor(name="batch-1")
    evidence = evidence_over(platform, executors={BATCH: product})
    org = make_org()
    owner, ctx = context(Role.OWNER, org), context(Role.MEMBER, org)
    session = new_id()
    evidence.work.deliver(org.id, session, delivered())
    await evidence.manager.write_policy(owner, policy_in("nowhere"))
    with pytest.raises(PreconditionFailed, match="no executor here runs the nowhere environment"):
        await evidence.manager.validate(ctx, session, RunPurpose.VALIDATION)
    assert platform.requests == product.requests == []

    # A validation session's one check runs on its environment's executor.
    evidence = evidence_over(platform, executors={BATCH: product})
    await evidence.manager.write_policy(owner, policy_in(BATCH))
    validation = await evidence.manager.run_check(
        ctx, new_id(), CHECKOUT, "unit", "c0ffee", "base0"
    )
    assert validation.executor == "batch-1" and platform.requests == []
    assert [check.environment for check in product.requests[0].checks] == [BATCH]
