"""Retention over the memory roots and the local key service.

A session takes its tenant's policy as a snapshot when it is created. The
sweep folds a tightening into the snapshot and never a loosening; when the
content expires, the tenant's key service destroys the session's key, the
engine revokes it, and the audit holds the destruction as the service
reported it; when the shape expires, the session is marked deleted, and a loop parked
past it, on a person, its own or a sub-agent's below it, is cancelled
first. A
tenant that revokes its own key makes its own content unreadable and no
other tenant's. And a crossing whose bytes do not match the hash they
crossed with is refused."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.doubles import APP, context
from contracts.step_storage import make_message, make_request, make_response
from contracts.tools import stand_ins

from acme.infra.exceptions import KeyRefused
from acme.infra.impl.local import InfraLocalImpl
from acme.infra.keys import KeyServiceInterface, WrappedKey
from acme.infra.keys.memory import KeyServiceMemoryImpl
from acme.om.agent_sessions.types.agent_session import AgentSession, SessionStatus
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.request import Spawn, Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.budgets.types.amount import Amount
from acme.om.context import RequestContext, Role, TenantContext
from acme.om.exceptions import NotAuthorized, NotFound, PreconditionFailed, ValidationFailed
from acme.om.privacy.types.session_privacy import StorageMode
from acme.om.retention.crossing import CrossingKind, CrossingRefused, declared, verified
from acme.om.retention.impl.keys import KeyServiceLocalImpl, TenantKeysImpl
from acme.om.retention.impl.manager import KEY_DESTROYED, RetentionManagerImpl, RetentionOptions
from acme.om.retention.impl.projects import SessionProjectNullImpl
from acme.om.retention.manager import RetentionManagerInterface
from acme.om.retention.projects import SessionProjectInterface
from acme.om.retention.rules import tighter
from acme.om.retention.types.policy import (
    MAX_LIFETIME,
    ProjectRetention,
    RetentionPolicy,
    TenantRetention,
)
from acme.om.root import Managers, build_managers
from acme.om.steps.types.content import ContentState
from acme.om.steps.types.header import (
    ControlCommand,
    ControlHeader,
    LoopEndedHeader,
    LoopOutcome,
    Park,
    ParkReason,
)
from acme.om.steps.types.step import Actor, Origin, Step, StepType
from acme.om.storage.impl.memory import StorageMemoryImpl

# What `make_session` names, so the agents manager classes every tool it
# offers.
TOOLS = stand_ins("read_log", "run_tests")
KIND = AgentKind(
    name="delivery",
    version=1,
    tools=("read_log", "run_tests"),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=2, count=4),
    share=Amount(cost_micros=1_000),
)
"""The kind `make_session` names, which a run takes its loop up as, and
which a session spawns under its share."""

DAY = timedelta(days=1)
WEEK = timedelta(days=7)
MONTH = timedelta(days=30)
SAID = "the pump log shows a pressure spike at 14:02"
"""What a session says, which no shape repeats."""


class Roots:
    """The memory roots with the platform's key service and a tenant's own
    one, and a retention manager whose clock a case moves. The platform's
    is the local key service, or, with `custody` off, infra's memory one,
    which holds the tenant's key alone, as a deployed root's does."""

    def __init__(
        self,
        tmp_path: Path,
        projects: SessionProjectInterface | None = None,
        *,
        custody: bool = True,
        options: RetentionOptions | None = None,
    ) -> None:
        self.platform = KeyServiceLocalImpl(KeyServiceMemoryImpl())
        self.own = KeyServiceLocalImpl(KeyServiceMemoryImpl())
        self.owners: dict[UUID, KeyServiceInterface] = {}
        platform: KeyServiceInterface = self.platform if custody else KeyServiceMemoryImpl()
        self.keys = TenantKeysImpl(platform, self.owners)
        self.storage = StorageMemoryImpl()
        self.projects = projects or SessionProjectNullImpl()
        self.managers: Managers = build_managers(
            self.storage,
            InfraLocalImpl(tmp_path),
            tool_catalog=TOOLS,
            agent_kinds=(KIND,),
            tenant_keys=self.keys,
            session_projects=self.projects,
        )
        self.options = options or RetentionOptions()
        self.now = utcnow()

    def at(self, later: timedelta) -> RetentionManagerInterface:
        """The retention manager as the sweep holds it, `later` from now."""
        moment = self.now + later

        def clock() -> datetime:
            return moment

        return RetentionManagerImpl(
            self.storage.get_retention_storage(),
            self.keys,
            self.managers.privacy,
            self.managers.agent_sessions,
            self.managers.tenancy,
            self.managers.events,
            self.managers.outbox,
            self.projects,
            self.options,
            clock=clock,
        )

    async def sweep(self, later: timedelta = timedelta(0)) -> int:
        return await self.at(later).sweep(RequestContext(request_id=new_id(), app=APP))

    async def tenant(self, *, own_keys: bool = False) -> TenantContext:
        """A live tenant's owner, whose org the sweep mints a context for;
        with its own key service when `own_keys`."""
        tail = new_id().hex[-8:]
        owner, org = await self.managers.tenancy.bootstrap(
            RequestContext(request_id=new_id(), app=APP),
            "Ajax",
            f"ajax-{tail}",
            f"a-{tail}@x.test",
            "Ann",
        )
        if own_keys:
            self.owners[org.id] = self.own
        return owner

    async def declare(
        self,
        ctx: TenantContext,
        policy: RetentionPolicy,
        projects: tuple[ProjectRetention, ...] = (),
    ) -> None:
        current = await self.managers.retention.get_policy(ctx)
        await self.managers.retention.write_policy(
            ctx, current.model_copy(update={"policy": policy, "projects": projects})
        )

    async def session_saying(self, ctx: TenantContext, text: str = SAID) -> AgentSession:
        session = await self.managers.agent_sessions.create_session(ctx, make_session())
        await self.managers.steps.append_inputs(ctx, session.id, [make_message(session.id, text)])
        return session

    async def said(self, ctx: TenantContext, session_id: UUID) -> list[str]:
        steps = (await self.managers.steps.get_steps(ctx, session_id, 0, 50)).items
        return [step.as_text() for step in steps if step.content.state is ContentState.PLAIN]

    async def audited(self, ctx: TenantContext) -> list[dict[str, object]]:
        events = await self.managers.events.get_events(ctx, 0, 100)
        return [dict(e.payload) for e in events if e.kind == KEY_DESTROYED]


class OneProject(SessionProjectInterface):
    def __init__(self) -> None:
        self.project_id = new_id()

    async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        return self.project_id


@pytest.fixture
def roots(tmp_path: Path) -> Roots:
    return Roots(tmp_path)


def a_policy(
    content: timedelta | None,
    shape: timedelta | None = None,
    mode: StorageMode = StorageMode.SEALED,
    region: str | None = None,
) -> RetentionPolicy:
    return RetentionPolicy(
        content_lifetime=content, shape_lifetime=shape, storage_mode=mode, region=region
    )


# The content's life: its key destroyed, and the destruction audited.


async def test_expired_content_is_unreadable_its_key_destroyed_and_audited_as_reported(
    roots: Roots,
) -> None:
    """Past its content's life, nothing the session said reads back through
    the engine or opens under the key service, a copy of its wrapped key
    kept from before included; the audit holds one entry, the key service's
    report as the service's own log holds it; the shape stays."""
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    session = await roots.session_saying(owner)
    assert await roots.said(owner, session.id) == [SAID]
    ring = await roots.storage.get_privacy_storage().read_keys(owner.org_id, session.id)
    (kept,) = ring.keys
    assert kept.wrapped is not None and kept.wrapping is not None
    copy = WrappedKey(blob=kept.wrapped, wrapping=kept.wrapping)

    assert await roots.sweep(WEEK - DAY) == 0, "within its life, nothing is due"
    assert await roots.said(owner, session.id) == [SAID]

    assert await roots.sweep(WEEK + DAY) == 1
    steps = (await roots.managers.steps.get_steps(owner, session.id, 0, 50)).items
    assert [step.content.state for step in steps] == [ContentState.ABSENT]
    assert SAID not in json.dumps([step.model_dump(mode="json") for step in steps])
    ring = await roots.storage.get_privacy_storage().read_keys(owner.org_id, session.id)
    assert ring.revoked and all(key.is_destroyed() for key in ring.keys)
    with pytest.raises(KeyRefused):
        await roots.platform.unwrap(owner.org_id, session.id, kept.version, copy)

    (report,) = roots.platform.log(owner.org_id)
    assert await roots.audited(owner) == [
        {
            "reported": True,
            "service": report.service,
            "key": report.key,
            "destroyed_at": report.destroyed_at.isoformat(),
            "receipt": report.receipt,
        }
    ]
    snapshot = await roots.managers.retention.get_snapshot(owner, session.id)
    assert snapshot.destruction == report and snapshot.content_expired_at is not None
    assert await roots.managers.agent_sessions.get_session(owner, session.id), "the shape stays"

    assert await roots.sweep(WEEK + DAY * 2) == 0, "taken up once"
    assert len(await roots.audited(owner)) == 1


async def test_a_tenants_own_key_service_destroys_its_key_and_logs_it_alone(
    roots: Roots,
) -> None:
    """A tenant that brought its own key service finds the destruction in
    that service's log, the report the audit holds; the platform's service
    logs the other tenant's alone."""
    own = await roots.tenant(own_keys=True)
    other = await roots.tenant()
    for ctx in (own, other):
        await roots.declare(ctx, a_policy(WEEK))
    mine, theirs = await roots.session_saying(own), await roots.session_saying(other)
    assert await roots.sweep(WEEK + DAY) == 2
    (report,) = roots.own.log(own.org_id)
    assert report.key.endswith(str(mine.id))
    assert roots.own.log(other.org_id) == ()
    (platform_report,) = roots.platform.log(other.org_id)
    assert platform_report.key.endswith(str(theirs.id))
    assert roots.platform.log(own.org_id) == ()
    (entry,) = await roots.audited(own)
    assert entry["receipt"] == report.receipt
    assert await roots.said(own, mine.id) == [] and await roots.said(other, theirs.id) == []


async def test_a_key_service_holding_the_tenants_key_alone_leaves_the_engine_to_destroy(
    tmp_path: Path,
) -> None:
    """Infra's key service as a deployed root wires it holds no session's
    key: the engine's revocation is the destruction, and the audit says no
    service reported it, and when the engine revoked."""
    roots = Roots(tmp_path, custody=False)
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK))
    session = await roots.session_saying(owner)
    assert await roots.sweep(WEEK + DAY) == 1
    assert await roots.said(owner, session.id) == []
    privacy = await roots.managers.privacy.get_privacy(owner, session.id)
    assert privacy.revoked_at is not None
    assert await roots.audited(owner) == [
        {"reported": False, "revoked_at": privacy.revoked_at.isoformat()}
    ]
    assert (await roots.managers.retention.get_snapshot(owner, session.id)).destruction is None


async def test_content_expiring_after_its_tenant_revoked_its_key_is_revoked_all_the_same(
    roots: Roots,
) -> None:
    """A tenant's service that revoked the tenant's key destroys nothing more
    and reports nothing; the engine's revocation still takes the content,
    and the audit says no service reported it."""
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK))
    session = await roots.session_saying(owner)
    roots.platform.revoke(owner.org_id)
    assert await roots.sweep(WEEK + DAY) == 1
    privacy = await roots.managers.privacy.get_privacy(owner, session.id)
    assert privacy.revoked_at is not None
    assert roots.platform.log(owner.org_id) == ()
    assert await roots.audited(owner) == [
        {"reported": False, "revoked_at": privacy.revoked_at.isoformat()}
    ]


async def test_a_deleted_tenants_expired_content_is_destroyed_without_its_context(
    roots: Roots,
) -> None:
    """No context is minted for a tenant deleted, and its purge takes its
    sessions; its key service still destroys each expired key, and the
    snapshot keeps the report, so the sweep moves on past it."""
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    session = await roots.session_saying(owner)
    tenancy = roots.storage.get_tenancy_storage()
    org = await tenancy.read_org(owner.org_id)
    assert org is not None
    await tenancy.write_org(org.id, org.model_copy(update={"deleted_at": utcnow()}))

    assert await roots.sweep(MONTH + DAY) == 1
    (report,) = roots.platform.log(owner.org_id)
    snapshot = await roots.storage.get_retention_storage().read_snapshot(owner.org_id, session.id)
    assert snapshot is not None and snapshot.destruction == report
    assert snapshot.shape_expired_at is not None
    assert await roots.sweep(MONTH + DAY * 2) == 0, "nothing of it is due again"


@pytest.mark.parametrize("custody", [True, False])
async def test_content_of_a_session_deleted_before_it_expires_is_unreadable_after_a_restore(
    tmp_path: Path, custody: bool
) -> None:
    """A session marked deleted is hidden from every read, and its key is
    revoked all the same when its content expires: the engine reaches it,
    with or without a key service that holds the session's key, and a
    restore reads back nothing it said."""
    roots = Roots(tmp_path, custody=custody)
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    session = await roots.session_saying(owner)
    await roots.managers.agent_sessions.delete_session(owner, session.id)

    assert await roots.sweep(WEEK + DAY) == 1
    ring = await roots.storage.get_privacy_storage().read_keys(owner.org_id, session.id)
    assert ring.revoked and all(key.is_destroyed() for key in ring.keys)
    (entry,) = await roots.audited(owner)
    assert entry["reported"] is custody
    if not custody:
        assert entry["revoked_at"] is not None
    await roots.managers.agent_sessions.restore_session(owner, session.id)
    assert await roots.said(owner, session.id) == []


async def test_content_is_never_expired_while_nothing_says_its_key_is_gone(
    tmp_path: Path,
) -> None:
    """A deleted tenant has no context for the engine to revoke under, and a
    key service that holds the tenant's key alone reports nothing: the
    snapshot stays unexpired and waits out its next attempt, out of every
    pass's read meanwhile."""
    roots = Roots(tmp_path, custody=False)
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK))
    session = await roots.session_saying(owner)
    tenancy = roots.storage.get_tenancy_storage()
    org = await tenancy.read_org(owner.org_id)
    assert org is not None
    await tenancy.write_org(org.id, org.model_copy(update={"deleted_at": utcnow()}))

    assert await roots.sweep(WEEK + DAY) == 1
    retention = roots.storage.get_retention_storage()
    snapshot = await retention.read_snapshot(owner.org_id, session.id)
    assert snapshot is not None and snapshot.content_expired_at is None
    assert snapshot.next_attempt_at == roots.now + WEEK + DAY + roots.options.retry_after
    assert await roots.audited(owner) == []
    assert await roots.sweep(WEEK + DAY) == 0, "out of the read until its next attempt"
    assert await roots.sweep(WEEK + DAY + roots.options.retry_after) == 1


async def test_a_session_stuck_past_its_shapes_life_holds_back_no_other_tenant(
    tmp_path: Path,
) -> None:
    """A batch of one. A session with a loop open past its shape's life
    cannot be marked: its content expires all the same, it waits for its
    next attempt, and the next pass takes up another tenant's expired
    content."""
    roots = Roots(tmp_path, options=RetentionOptions(sweep_batch=1))
    busy = await roots.tenant()
    await roots.declare(busy, a_policy(WEEK, MONTH))
    stuck = await roots.session_saying(busy)
    await roots.managers.agent_sessions.receive(busy, stuck.id, [make_message(stuck.id, "more")])
    other = await roots.tenant()
    await roots.declare(other, a_policy(WEEK))
    waiting = await roots.session_saying(other)

    assert await roots.sweep(MONTH + DAY) == 1
    taken = await roots.managers.retention.get_snapshot(busy, stuck.id)
    assert taken.content_expired_at is not None and taken.shape_expired_at is None
    assert taken.next_attempt_at is not None
    assert await roots.managers.agent_sessions.get_session(busy, stuck.id), "not marked yet"
    assert await roots.said(other, waiting.id) == [SAID]

    assert await roots.sweep(MONTH + DAY) == 1
    assert await roots.said(other, waiting.id) == []


async def test_a_snapshot_that_cannot_fold_holds_back_no_other_tenant(
    roots: Roots, caplog: pytest.LogCaptureFixture
) -> None:
    """A stored policy whose lifetime runs a snapshot's expiry past a date's
    last year cannot fold into it. The pass records the failure and goes on:
    another tenant's tightening folds, and its content, due by it, goes."""
    broken = await roots.tenant()
    stuck = await roots.session_saying(broken)
    now = utcnow()
    stored = TenantRetention(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=broken.user_id,
        updated_by=broken.user_id,
        policy=a_policy(timedelta(days=3_000_000)),
        version=1,
    )
    retention = roots.storage.get_retention_storage()
    assert await retention.create_policy(broken.org_id, stored, ())
    other = await roots.tenant()
    await roots.declare(other, a_policy(MONTH))
    waiting = await roots.session_saying(other)
    await roots.declare(other, a_policy(WEEK))

    await roots.sweep(WEEK + DAY)
    assert await roots.said(other, waiting.id) == []
    folded = await roots.managers.retention.get_snapshot(other, waiting.id)
    assert folded.policy.content_lifetime == WEEK and folded.content_expired_at is not None
    behind = await roots.managers.retention.get_snapshot(broken, stuck.id)
    assert behind.policy_version == 0, "it stays behind for the next pass"
    failed = [r for r in caplog.records if "its fold failed" in r.getMessage()]
    assert [str(stuck.id) in r.getMessage() for r in failed] == [True]
    assert failed[0].exc_info is not None and failed[0].exc_info[0] is OverflowError


async def test_a_batch_of_snapshots_that_cannot_fold_waits_and_still_expires_on_time(
    tmp_path: Path,
) -> None:
    """A batch of two, both a tenant's snapshots that cannot fold its stored
    policy. A pass leaves the failures out of its count and puts them out of
    the read, so the next pass folds another tenant's tightening and its
    content goes. At the expiry the stuck snapshots hold, their content goes
    all the same, under the policy they hold."""
    roots = Roots(tmp_path, options=RetentionOptions(sweep_batch=2))
    broken = await roots.tenant()
    await roots.declare(broken, a_policy(MONTH))
    stuck = [await roots.session_saying(broken) for _ in range(2)]
    held = await roots.managers.retention.get_policy(broken)
    retention = roots.storage.get_retention_storage()
    unfoldable = a_policy(MONTH, timedelta(days=3_000_000))
    await retention.write_policy(
        broken.org_id, held.model_copy(update={"policy": unfoldable, "version": 2}), 1, ()
    )
    other = await roots.tenant()
    await roots.declare(other, a_policy(MONTH))
    waiting = await roots.session_saying(other)
    await roots.declare(other, a_policy(WEEK))

    assert await roots.sweep(WEEK + DAY) == 0, "two failed folds are no batch"
    assert await roots.said(other, waiting.id) == [SAID]
    assert await roots.sweep(WEEK + DAY) == 1
    assert await roots.said(other, waiting.id) == []

    assert await roots.sweep(MONTH + DAY) == 2
    for session in stuck:
        assert await roots.said(broken, session.id) == []
        snapshot = await roots.managers.retention.get_snapshot(broken, session.id)
        assert snapshot.policy_version == 1 and snapshot.content_expired_at is not None


# The snapshot: tightening reaches it at the next sweep, loosening never.


async def test_a_tightening_reaches_an_existing_session_at_the_next_sweep(roots: Roots) -> None:
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(MONTH))
    session = await roots.session_saying(owner)
    taken = await roots.managers.retention.get_snapshot(owner, session.id)
    assert taken.content_expires_at == taken.created_at + MONTH

    await roots.declare(owner, a_policy(WEEK))
    unswept = await roots.managers.retention.get_snapshot(owner, session.id)
    assert unswept.policy.content_lifetime == MONTH, "nothing reaches it before the sweep"

    await roots.sweep()
    swept = await roots.managers.retention.get_snapshot(owner, session.id)
    assert swept.policy.content_lifetime == WEEK
    assert swept.content_expires_at == taken.created_at + WEEK
    await roots.sweep(WEEK + DAY)
    assert await roots.said(owner, session.id) == []


async def test_a_loosening_leaves_an_existing_sessions_snapshot_as_it_was(roots: Roots) -> None:
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    session = await roots.session_saying(owner)
    taken = await roots.managers.retention.get_snapshot(owner, session.id)

    await roots.declare(owner, a_policy(None))
    await roots.sweep()
    swept = await roots.managers.retention.get_snapshot(owner, session.id)
    assert (swept.policy, swept.content_expires_at, swept.shape_expires_at) == (
        taken.policy,
        taken.content_expires_at,
        taken.shape_expires_at,
    )
    later = await roots.session_saying(owner)
    assert (await roots.managers.retention.get_snapshot(owner, later.id)).policy == a_policy(None)

    await roots.sweep(WEEK + DAY)
    assert await roots.said(owner, session.id) == [], "the old session keeps its own life"
    assert await roots.said(owner, later.id) == [SAID], "a new one takes the loosened policy"


async def test_content_at_rest_goes_at_the_next_sweep_when_the_policy_keeps_none(
    roots: Roots,
) -> None:
    """Tightened to memory-only, a sealed session's content at rest expires
    when the sweep folds it, whatever its lifetime said."""
    owner = await roots.tenant()
    session = await roots.session_saying(owner)
    assert (await roots.managers.retention.get_snapshot(owner, session.id)).at_rest
    await roots.declare(owner, a_policy(None, mode=StorageMode.MEMORY_ONLY))
    await roots.sweep()
    assert (await roots.managers.retention.get_snapshot(owner, session.id)).content_expired_at
    await roots.sweep()
    assert await roots.said(owner, session.id) == []


async def test_a_memory_only_policy_chooses_the_engines_storage_before_the_history(
    roots: Roots,
) -> None:
    owner = await roots.tenant()
    await roots.declare(owner, RetentionPolicy(storage_mode=StorageMode.MEMORY_ONLY))
    session = await roots.managers.agent_sessions.create_session(owner, make_session())
    privacy = await roots.managers.privacy.get_privacy(owner, session.id)
    assert privacy.policy.mode is StorageMode.MEMORY_ONLY
    assert not (await roots.managers.retention.get_snapshot(owner, session.id)).at_rest


async def test_a_project_narrows_its_tenants_policy_and_never_widens_it(tmp_path: Path) -> None:
    project = OneProject()
    roots = Roots(tmp_path, project)
    owner = await roots.tenant()
    narrowing = ProjectRetention(project_id=project.project_id, policy=a_policy(WEEK))
    widening = ProjectRetention(project_id=project.project_id, policy=a_policy(None))
    await roots.declare(owner, a_policy(MONTH, region="eu-central-1"), (narrowing,))
    narrowed = await roots.session_saying(owner)
    snapshot = await roots.managers.retention.get_snapshot(owner, narrowed.id)
    assert (snapshot.project_id, snapshot.policy.content_lifetime) == (project.project_id, WEEK)
    assert snapshot.policy.region == "eu-central-1"

    await roots.declare(owner, a_policy(MONTH), (widening,))
    widened = await roots.session_saying(owner)
    snapshot = await roots.managers.retention.get_snapshot(owner, widened.id)
    assert snapshot.policy.content_lifetime == MONTH, "a project never loosens its tenant"

    elsewhere = ProjectRetention(
        project_id=project.project_id, policy=RetentionPolicy(region="us-east-1")
    )
    with pytest.raises(ValidationFailed):
        await roots.declare(owner, RetentionPolicy(region="eu-central-1"), (elsewhere,))


async def test_a_child_session_belongs_to_its_parents_project(tmp_path: Path) -> None:
    project = OneProject()
    roots = Roots(tmp_path, project)
    owner = await roots.tenant()
    narrowing = ProjectRetention(project_id=project.project_id, policy=a_policy(WEEK))
    await roots.declare(owner, a_policy(MONTH), (narrowing,))
    parent = await roots.managers.agent_sessions.create_session(owner, make_session())
    project.project_id = new_id()
    child = await roots.managers.agent_sessions.create_session(owner, make_session(parent=parent))
    snapshot = await roots.managers.retention.get_snapshot(owner, child.id)
    assert snapshot.project_id == narrowing.project_id
    assert snapshot.policy.content_lifetime == WEEK


# The shape's life.


async def test_expired_shape_marks_the_session_deleted_for_good(roots: Roots) -> None:
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    session = await roots.session_saying(owner)
    await roots.sweep(WEEK + DAY)
    assert await roots.managers.agent_sessions.get_session(owner, session.id)
    await roots.sweep(MONTH + DAY)
    with pytest.raises(NotFound):
        await roots.managers.agent_sessions.get_session(owner, session.id)
    with pytest.raises(NotFound):
        await roots.managers.agent_sessions.restore_session(owner, session.id)
    assert (await roots.managers.retention.get_snapshot(owner, session.id)).shape_expired_at


async def test_a_session_parked_on_a_person_past_its_shapes_life_is_cancelled_then_marked(
    roots: Roots,
) -> None:
    """A loop parked on a person never ends by itself, so it would hold the
    session's shape for good. Past the shape's life, the sweep cancels it
    under the service context; the run that ends it leaves the session idle,
    and the next pass marks it deleted."""
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    sessions, steps = roots.managers.agent_sessions, roots.managers.steps
    start = Start(id=new_id(), kind=KIND.name, title="the weekly report")
    session = await roots.managers.agents.start_session(owner, start)
    (message,) = await steps.append_inputs(owner, session.id, [make_message(session.id)])
    epoch = await steps.begin_run(owner, session.id)
    await steps.append_steps(
        owner, session.id, epoch, [make_request(session.id, message.id, (message.id,))]
    )
    person = Park(reason=ParkReason.PERSON, unlock="approval")
    parked = await sessions.park(owner, session.id, epoch, message.id, person)
    assert parked.status is SessionStatus.PARKED

    await roots.sweep(MONTH + DAY)
    await roots.sweep(MONTH + DAY)  # a pass before its next attempt asks for nothing more

    waiting = await roots.managers.retention.get_snapshot(owner, session.id)
    assert waiting.shape_expired_at is None and waiting.next_attempt_at is not None
    history = (await steps.get_steps(owner, session.id, 0, 50)).items
    cancels = [s for s in history if isinstance(s.header, ControlHeader)]
    assert [(s.header.command, s.actor) for s in cancels] == [  # type: ignore[union-attr]
        (ControlCommand.CANCEL, Actor.ENGINE)
    ]
    assert (await sessions.get_session(owner, session.id)).status is SessionStatus.PENDING

    await roots.managers.loop.run(owner, session.id)
    assert (await sessions.get_session(owner, session.id)).status is SessionStatus.IDLE
    await roots.sweep(MONTH + DAY + roots.options.retry_after)

    with pytest.raises(NotFound):
        await sessions.get_session(owner, session.id)
    assert (await roots.managers.retention.get_snapshot(owner, session.id)).shape_expired_at


async def a_tree(
    roots: Roots, owner: TenantContext
) -> tuple[AgentSession, AgentSession, Step, int]:
    """An idle root and a sub-agent a run holds below it: the model request
    that carries its objective, and the run's epoch. The sub-agent's shape outlives
    its root's by a month, as one spawned a month later does, so no pass of
    its own reaches it before its root's shape expires."""
    sessions, steps = roots.managers.agent_sessions, roots.managers.steps
    start = Start(id=new_id(), kind=KIND.name, title="the weekly report")
    root = await roots.managers.agents.start_session(owner, start)
    spawn = Spawn(id=new_id(), kind=KIND.name, title="the pump log", objective="read it")
    child = await roots.managers.agents.spawn(owner, root.id, spawn)
    (objective,) = (await steps.get_steps(owner, child.id, 0, 1)).items
    epoch = await steps.begin_run(owner, child.id)
    request = make_request(child.id, objective.id, (objective.id,))
    await steps.append_steps(owner, child.id, epoch, [request])
    assert (await sessions.project_status(owner, root.id)).status is SessionStatus.IDLE
    assert (await sessions.project_status(owner, child.id)).status is SessionStatus.RUNNING
    store = roots.storage.get_retention_storage()
    taken = await store.read_snapshot(owner.org_id, child.id)
    assert taken is not None and taken.shape_expires_at and taken.content_expires_at
    later = taken.model_copy(
        update={
            "shape_expires_at": taken.shape_expires_at + MONTH,
            "content_expires_at": taken.content_expires_at + MONTH,
            "version": taken.version + 1,
        }
    )
    assert await store.write_snapshot(owner.org_id, later, taken.version)
    return root, child, request, epoch


def cancels_of(history: tuple[Step, ...]) -> list[tuple[ControlCommand, Actor]]:
    return [(s.header.command, s.actor) for s in history if isinstance(s.header, ControlHeader)]


async def test_a_sub_agent_parked_below_a_session_past_its_shapes_life_is_cancelled(
    roots: Roots,
) -> None:
    """A sub-agent parked on a person holds the session above it, and its
    own shape may outlive that session's by far. Past the session's shape
    life, the sweep cancels the sub-agent's loop; the run that ends it
    leaves the sub-agent idle, and the next pass marks the session, long
    before the sub-agent's own pass."""
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    sessions, steps = roots.managers.agent_sessions, roots.managers.steps
    root, child, request, epoch = await a_tree(roots, owner)
    person = Park(reason=ParkReason.PERSON, unlock="approval")
    parked = await sessions.park(owner, child.id, epoch, request.loop_id, person)
    assert parked.status is SessionStatus.PARKED

    await roots.sweep(MONTH + DAY)

    waiting = await roots.managers.retention.get_snapshot(owner, root.id)
    assert waiting.shape_expired_at is None and waiting.next_attempt_at is not None
    history = (await steps.get_steps(owner, child.id, 0, 50)).items
    assert cancels_of(history) == [(ControlCommand.CANCEL, Actor.ENGINE)]
    assert (await sessions.get_session(owner, child.id)).status is SessionStatus.PENDING

    await roots.managers.loop.run(owner, child.id)
    assert (await sessions.get_session(owner, child.id)).status is SessionStatus.IDLE
    await roots.sweep(MONTH + DAY + roots.options.retry_after)

    with pytest.raises(NotFound):
        await sessions.get_session(owner, root.id)
    assert (await roots.managers.retention.get_snapshot(owner, root.id)).shape_expired_at
    below = await roots.managers.retention.get_snapshot(owner, child.id)
    assert below.shape_expired_at is None, "the sub-agent's own shape lives on"


async def test_a_sub_agent_at_work_below_a_session_past_its_shapes_life_ends_by_itself(
    roots: Roots,
) -> None:
    """A sub-agent a run holds is never cancelled: the session above it is
    marked at the first pass after the sub-agent's loop ends."""
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    sessions, steps = roots.managers.agent_sessions, roots.managers.steps
    root, child, request, epoch = await a_tree(roots, owner)

    await roots.sweep(MONTH + DAY)
    await roots.sweep(MONTH + DAY + roots.options.retry_after)

    waiting = await roots.managers.retention.get_snapshot(owner, root.id)
    assert waiting.shape_expired_at is None and waiting.next_attempt_at is not None
    assert await sessions.get_session(owner, root.id), "not marked yet"
    assert cancels_of((await steps.get_steps(owner, child.id, 0, 50)).items) == []
    assert (await sessions.project_status(owner, child.id)).status is SessionStatus.RUNNING

    ended = Step(
        id=new_id(),
        created_at=utcnow(),
        session_id=child.id,
        loop_id=request.loop_id,
        type=StepType.LOOP_ENDED,
        actor=Actor.ENGINE,
        origin=Origin.ENGINE,
        header=LoopEndedHeader(outcome=LoopOutcome.SUCCEEDED),
    )
    done = [make_response(child.id, request.loop_id, request.id), ended]
    await steps.append_steps(owner, child.id, epoch, done)
    assert (await sessions.project_status(owner, child.id)).status is SessionStatus.IDLE
    await roots.sweep(MONTH + DAY + 2 * roots.options.retry_after)

    with pytest.raises(NotFound):
        await sessions.get_session(owner, root.id)
    assert (await roots.managers.retention.get_snapshot(owner, root.id)).shape_expired_at


# The tenant's key, revoked.


async def test_a_revoked_tenant_key_makes_its_content_unreadable_and_nothing_else(
    roots: Roots,
) -> None:
    """Both tenants on the one platform key service: the tenant that revokes
    its key can neither read nor write content, and the other reads and
    writes as before."""
    revoking, other = await roots.tenant(), await roots.tenant()
    gone = await roots.session_saying(revoking, "the revoking tenant's notes")
    kept = await roots.session_saying(other, "the other tenant's notes")

    roots.platform.revoke(revoking.org_id)

    with pytest.raises(KeyRefused):
        await roots.said(revoking, gone.id)
    with pytest.raises(KeyRefused):
        await roots.managers.steps.append_inputs(revoking, gone.id, [make_message(gone.id, "more")])
    assert await roots.said(other, kept.id) == ["the other tenant's notes"]
    await roots.managers.steps.append_inputs(other, kept.id, [make_message(kept.id, "more")])
    assert await roots.said(other, kept.id) == ["the other tenant's notes", "more"]
    fresh = await roots.session_saying(other, "a new session")
    assert await roots.said(other, fresh.id) == ["a new session"]


# One session's content, erased before its life ends.


async def test_an_admins_erasure_is_the_sweeps_destruction_audited_once_under_the_admin(
    roots: Roots,
) -> None:
    """The admin's erasure destroys the key in the key service, revokes it
    through the engine, and audits the service's report under the admin's
    name; the shape stays, a second erasure changes nothing, and the sweep
    at the content's end takes nothing up again."""
    owner = await roots.tenant()
    await roots.declare(owner, a_policy(WEEK, MONTH))
    org = await roots.storage.get_tenancy_storage().read_org(owner.org_id)
    assert org is not None
    admin = context(Role.ADMIN, org)
    session = await roots.session_saying(owner)

    erased = await roots.managers.retention.erase_content(admin, session.id)

    assert await roots.said(owner, session.id) == []
    ring = await roots.storage.get_privacy_storage().read_keys(owner.org_id, session.id)
    assert ring.keys and ring.revoked and all(key.is_destroyed() for key in ring.keys)
    (report,) = roots.platform.log(owner.org_id)
    assert erased.destruction == report and erased.content_expired_at is not None
    events = await roots.managers.events.get_events(owner, 0, 100)
    (entry,) = [event for event in events if event.kind == KEY_DESTROYED]
    assert entry.actor_id == admin.user_id and entry.payload["receipt"] == report.receipt
    assert await roots.managers.agent_sessions.get_session(owner, session.id), "the shape stays"
    assert await roots.managers.retention.erase_content(owner, session.id) == erased
    assert await roots.sweep(WEEK + DAY) == 0, "nothing is due"
    assert len(await roots.audited(owner)) == 1
    assert roots.platform.log(owner.org_id) == (report,)


async def test_a_session_marked_deleted_is_erased_and_a_restore_reads_nothing(
    roots: Roots,
) -> None:
    owner = await roots.tenant()
    session = await roots.session_saying(owner)
    await roots.managers.agent_sessions.delete_session(owner, session.id)

    await roots.managers.retention.erase_content(owner, session.id)

    await roots.managers.agent_sessions.restore_session(owner, session.id)
    assert await roots.said(owner, session.id) == []


async def test_a_member_erases_nothing_and_another_tenant_finds_no_session(
    roots: Roots,
) -> None:
    owner, other = await roots.tenant(), await roots.tenant()
    org = await roots.storage.get_tenancy_storage().read_org(owner.org_id)
    assert org is not None
    session = await roots.session_saying(owner)

    with pytest.raises(NotAuthorized):
        await roots.managers.retention.erase_content(context(Role.MEMBER, org), session.id)
    with pytest.raises(NotFound):
        await roots.managers.retention.erase_content(other, session.id)

    assert await roots.said(owner, session.id) == [SAID]
    assert roots.platform.log(owner.org_id) == () and await roots.audited(owner) == []


# The policy's own rules.


async def test_the_policy_is_written_by_who_manages_members_and_by_its_version(
    roots: Roots,
) -> None:
    owner = await roots.tenant()
    first = await roots.managers.retention.get_policy(owner)
    assert first.version == 0
    member = context(Role.MEMBER)
    with pytest.raises(NotAuthorized):
        await roots.managers.retention.write_policy(member, first)
    written = await roots.managers.retention.write_policy(
        owner, first.model_copy(update={"policy": a_policy(WEEK)})
    )
    assert written.version == 1
    with pytest.raises(PreconditionFailed):
        await roots.managers.retention.write_policy(owner, first)
    assert await roots.managers.retention.get_policy(owner) == written


async def test_a_lifetime_past_a_century_is_refused_in_a_policy_and_in_a_narrowing(
    roots: Roots,
) -> None:
    owner = await roots.tenant()
    first = await roots.managers.retention.get_policy(owner)
    past = MAX_LIFETIME + DAY
    with pytest.raises(ValidationFailed, match="at most"):
        await roots.managers.retention.write_policy(
            owner, first.model_copy(update={"policy": a_policy(past)})
        )
    narrowing = ProjectRetention(project_id=new_id(), policy=a_policy(WEEK, past))
    with pytest.raises(ValidationFailed, match="past"):
        await roots.managers.retention.write_policy(
            owner, first.model_copy(update={"projects": (narrowing,)})
        )
    assert (await roots.managers.retention.get_policy(owner)).version == 0, "nothing stored"

    at_bound = first.model_copy(update={"policy": a_policy(MAX_LIFETIME, MAX_LIFETIME)})
    assert (await roots.managers.retention.write_policy(owner, at_bound)).version == 1


def test_tighter_takes_the_stricter_of_each_field_and_is_its_own_identity() -> None:
    loose = RetentionPolicy()
    strict = RetentionPolicy(
        content_lifetime=DAY,
        shape_lifetime=WEEK,
        storage_mode=StorageMode.MEMORY_ONLY,
        zero_retention=True,
        region="eu-central-1",
    )
    assert tighter(loose, strict) == strict == tighter(strict, loose)
    assert tighter(loose, loose) == loose
    mixed = tighter(a_policy(DAY, MONTH), a_policy(WEEK, WEEK))
    assert (mixed.content_lifetime, mixed.shape_lifetime) == (DAY, WEEK)
    assert tighter(RetentionPolicy(region="a"), RetentionPolicy(region="b")).region == "a"


def test_a_policy_keeps_content_within_its_shape_and_nothing_at_rest_at_zero() -> None:
    with pytest.raises(ValueError, match="outlives"):
        a_policy(MONTH, WEEK)
    with pytest.raises(ValueError, match="outlives"):
        a_policy(None, WEEK)
    with pytest.raises(ValueError, match="memory only"):
        RetentionPolicy(zero_retention=True)


# What crosses the wall.


def test_a_crossing_whose_hash_does_not_verify_is_refused() -> None:
    """The payload a sender declared reads back; a byte changed, a payload
    swapped for another of the same size, or a size that differs is
    refused, and the refusal never carries what crossed."""
    payload = b"result: 412 checks passed at 9f2c1e0"
    crossing = declared(CrossingKind.RESULT, payload)
    assert verified(crossing, payload) == payload
    changed = payload[:-1] + b"1"
    swapped = b"result: 000 checks passed at 9f2c1e0"
    for other in (changed, swapped, payload + b" ", b""):
        with pytest.raises(CrossingRefused) as refused:
            verified(crossing, other)
        assert "checks" not in str(refused.value)
    forged = crossing.model_copy(update={"sha256": declared(CrossingKind.RESULT, swapped).sha256})
    with pytest.raises(CrossingRefused):
        verified(forged, payload)
