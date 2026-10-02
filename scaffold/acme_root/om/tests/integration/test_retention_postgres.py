"""Retention over Postgres and the local key service, read the way a
database reader reads it: the rows of the session keys, the snapshot, and
the audit, under the tenant's own scope.

A session's content past its life leaves no wrapped key in its rows and
no content it said, its history's rows stay, and the audit row holds the
key service's report; a tightening of the tenant's policy reaches the
snapshot's row at the next sweep, and a loosening does not."""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from contracts.step_storage import make_message
from sqlalchemy import text

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.keys.memory import KeyServiceMemoryImpl
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.retention.impl.keys import KeyServiceLocalImpl, TenantKeysImpl
from acme.om.retention.impl.manager import KEY_DESTROYED, RetentionManagerImpl, RetentionOptions
from acme.om.retention.impl.projects import SessionProjectNullImpl
from acme.om.retention.types.policy import RetentionPolicy
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.pg_base import LoginSessions, set_scope
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")
DAY = timedelta(days=1)
WEEK = timedelta(days=7)
MONTH = timedelta(days=30)
SAID = "the pump log shows a pressure spike at 14:02"


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


@pytest.fixture
def keys() -> KeyServiceLocalImpl:
    return KeyServiceLocalImpl(KeyServiceMemoryImpl())


@pytest.fixture
def managers(storage: StoragePostgresImpl, keys: KeyServiceLocalImpl, tmp_path: Path) -> Managers:
    return build_managers(storage, InfraLocalImpl(tmp_path), tenant_keys=TenantKeysImpl(keys))


def sweeper(
    storage: StoragePostgresImpl, managers: Managers, keys: KeyServiceLocalImpl, later: timedelta
) -> RetentionManagerImpl:
    moment = utcnow() + later

    def clock() -> datetime:
        return moment

    return RetentionManagerImpl(
        storage.get_retention_storage(),
        TenantKeysImpl(keys),
        managers.privacy,
        managers.agent_sessions,
        managers.tenancy,
        managers.events,
        managers.outbox,
        SessionProjectNullImpl(),
        RetentionOptions(),
        clock=clock,
    )


async def sweep(
    storage: StoragePostgresImpl, managers: Managers, keys: KeyServiceLocalImpl, later: timedelta
) -> int:
    rctx = RequestContext(request_id=new_id(), app=APP)
    return await sweeper(storage, managers, keys, later).sweep(rctx)


async def an_org(managers: Managers, policy: RetentionPolicy) -> TenantContext:
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), "Ajax", slug, f"ann-{slug}@x.test", "Ann"
    )
    await declare(managers, owner, policy)
    return owner


async def declare(managers: Managers, ctx: TenantContext, policy: RetentionPolicy) -> None:
    current = await managers.retention.get_policy(ctx)
    await managers.retention.write_policy(ctx, current.model_copy(update={"policy": policy}))


async def a_session_saying(managers: Managers, ctx: TenantContext) -> UUID:
    session = await managers.agent_sessions.create_session(ctx, make_session())
    await managers.steps.append_inputs(ctx, session.id, [make_message(session.id, SAID)])
    return session.id


async def rows(
    pg_sessions: LoginSessions, role: DatabaseRole, statement: str, org_id: UUID, **values: Any
) -> list[dict[str, Any]]:
    """What a reader of the database sees, under the tenant's own scope."""
    async with pg_sessions[role]() as session:
        await set_scope(session, org_id, None, None)
        result = await session.execute(text(statement), {"org": org_id, **values})
        return [dict(row) for row in result.mappings()]


async def test_expired_content_leaves_no_key_and_the_audit_row_holds_the_report(
    storage: StoragePostgresImpl,
    managers: Managers,
    keys: KeyServiceLocalImpl,
    pg_sessions: LoginSessions,
) -> None:
    owner = await an_org(managers, RetentionPolicy(content_lifetime=WEEK, shape_lifetime=MONTH))
    session = await a_session_saying(managers, owner)
    org = owner.org_id
    key_sql = (
        "SELECT wrapped, destroyed_at FROM core.session_keys"
        " WHERE org_id = :org AND session_id = :session"
    )
    (live,) = await rows(pg_sessions, DatabaseRole.CORE, key_sql, org, session=session)
    assert live["wrapped"] is not None and live["destroyed_at"] is None

    assert await sweep(storage, managers, keys, WEEK + DAY) == 1

    (gone,) = await rows(pg_sessions, DatabaseRole.CORE, key_sql, org, session=session)
    assert gone["wrapped"] is None and gone["destroyed_at"] is not None
    history = await rows(
        pg_sessions,
        DatabaseRole.ACTIVITY,
        "SELECT content::text AS content FROM activity.steps"
        " WHERE org_id = :org AND session_id = :session",
        org,
        session=session,
    )
    assert len(history) == 1 and SAID not in history[0]["content"]
    steps = (await managers.steps.get_steps(owner, session, 0, 10)).items
    assert [step.content.state.value for step in steps] == ["absent"]

    (report,) = keys.log(org)
    (audit,) = await rows(
        pg_sessions,
        DatabaseRole.ACTIVITY,
        "SELECT target_id, payload::text AS payload FROM activity.events"
        " WHERE org_id = :org AND kind = :kind",
        org,
        kind=KEY_DESTROYED,
    )
    assert audit["target_id"] == session
    assert json.loads(audit["payload"]) == {
        "reported": True,
        "service": report.service,
        "key": report.key,
        "destroyed_at": report.destroyed_at.isoformat(),
        "receipt": report.receipt,
    }
    (snapshot,) = await rows(
        pg_sessions,
        DatabaseRole.CORE,
        "SELECT content_expired_at, destruction::text AS destruction FROM core.session_retention"
        " WHERE org_id = :org AND session_id = :session",
        org,
        session=session,
    )
    assert snapshot["content_expired_at"] is not None
    assert json.loads(snapshot["destruction"])["receipt"] == report.receipt


async def test_a_tightening_reaches_the_snapshot_row_and_a_loosening_does_not(
    storage: StoragePostgresImpl,
    managers: Managers,
    keys: KeyServiceLocalImpl,
    pg_sessions: LoginSessions,
) -> None:
    owner = await an_org(managers, RetentionPolicy(content_lifetime=MONTH))
    session = await a_session_saying(managers, owner)
    taken = await managers.retention.get_snapshot(owner, session)

    await declare(managers, owner, RetentionPolicy(content_lifetime=WEEK))
    await sweep(storage, managers, keys, timedelta(0))
    tightened = await managers.retention.get_snapshot(owner, session)
    assert tightened.content_expires_at == taken.created_at + WEEK

    await declare(managers, owner, RetentionPolicy())
    await sweep(storage, managers, keys, timedelta(0))
    loosened = await managers.retention.get_snapshot(owner, session)
    assert (loosened.policy, loosened.content_expires_at) == (
        tightened.policy,
        tightened.content_expires_at,
    )
    assert loosened.policy_version == 3


async def test_a_session_deleted_before_its_content_expires_has_its_key_rows_emptied(
    storage: StoragePostgresImpl,
    managers: Managers,
    keys: KeyServiceLocalImpl,
    pg_sessions: LoginSessions,
) -> None:
    owner = await an_org(managers, RetentionPolicy(content_lifetime=WEEK, shape_lifetime=MONTH))
    session = await a_session_saying(managers, owner)
    await managers.agent_sessions.delete_session(owner, session)

    assert await sweep(storage, managers, keys, WEEK + DAY) == 1

    (gone,) = await rows(
        pg_sessions,
        DatabaseRole.CORE,
        "SELECT wrapped, destroyed_at FROM core.session_keys"
        " WHERE org_id = :org AND session_id = :session",
        owner.org_id,
        session=session,
    )
    assert gone["wrapped"] is None and gone["destroyed_at"] is not None
    await managers.agent_sessions.restore_session(owner, session)
    steps = (await managers.steps.get_steps(owner, session, 0, 10)).items
    assert [step.content.state.value for step in steps] == ["absent"]
