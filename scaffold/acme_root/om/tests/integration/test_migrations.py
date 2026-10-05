"""Every role's migrated schema agrees with the ORM metadata, the latest
revision of every role downgrades and upgrades again, a session row the
previous release writes takes its private-data default, the logins are safe to
make twice, a migration behind a held lock gives up within its bound, a
data migration passes the fence it runs under and fails when it misses rows,
a workspace's notices move to the one notice and back, every tenant's, the
one notice leaves the table with every notice kept in the list, the
validation sessions' station columns leave the table with every session this
release wrote kept, and a platform automation this release writes reads as the
previous release's after a downgrade, which drops the automations of a
product's kind."""

import asyncio
import time
from datetime import datetime
from uuid import UUID

import pytest
from contracts.automation_storage import make_automation
from contracts.event_storage import make_event
from contracts.platform_agents_storage import finished, make_validation
from contracts.workspace_storage import make_workspace
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine

from acme.om.automations.storage.impl.postgres import AutomationStoragePostgresImpl
from acme.om.automations.types.automation import Action
from acme.om.base import new_id
from acme.om.events.storage.impl.postgres import EventStoragePostgresImpl
from acme.om.platform_agents.storage.impl.postgres import PlatformAgentsStoragePostgresImpl
from acme.om.platform_agents.types.validation import ValidationSession
from acme.om.storage.impl.pg_base import LoginSessions
from acme.om.storage.migrate import (
    RUN_AGAIN,
    VERSION_TABLE,
    backfill,
    check,
    downgrade,
    ensure_logins_at,
    head,
    main,
    upgrade,
)
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings
from acme.om.workspaces.storage.impl.postgres import WorkspaceStoragePostgresImpl

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("role", list(DatabaseRole))
async def test_orm_and_schema_agree(migrated: dict[DatabaseRole, str], role: DatabaseRole) -> None:
    assert await check(role, migrated[role]) == []


@pytest.mark.parametrize("role", list(DatabaseRole))
async def test_latest_revision_round_trips(
    migrated: dict[DatabaseRole, str], role: DatabaseRole
) -> None:
    if head(role) is None:
        pytest.skip(f"role {role.value} has no migrations yet")
    await downgrade(role, migrated[role], "-1")
    await upgrade(role, migrated[role])
    assert await check(role, migrated[role]) == []


async def test_a_session_row_written_without_its_private_data_mark_holds_private_data(
    migrated: dict[DatabaseRole, str],
) -> None:
    """The previous release writes no `holds_private`, during a roll and
    after a rollback: the column keeps its default, so such a row is taken
    to hold private data rather than refused."""
    engine = create_async_engine(migrated[DatabaseRole.CORE])
    try:
        async with engine.connect() as connection:
            default = await connection.scalar(
                text(
                    "SELECT column_default FROM information_schema.columns"
                    " WHERE table_schema = 'core' AND table_name = 'agent_sessions'"
                    " AND column_name = 'holds_private'"
                )
            )
    finally:
        await engine.dispose()
    assert default == "true"


async def test_ensure_logins_runs_again_on_a_migrated_database(
    migration_settings: MigrationSettings, migrated: dict[DatabaseRole, str]
) -> None:
    """The deploy runs it before every migrate, so the second run over a
    database it already shaped changes nothing and fails nothing."""
    settings = migration_settings
    await ensure_logins_at(settings.master_url(), settings.login_passwords())
    for role in DatabaseRole:
        assert await check(role, migrated[role]) == []


async def test_a_migration_behind_a_held_lock_gives_up_within_its_bound(
    migrated: dict[DatabaseRole, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transaction holds core's version table, which every run of core's
    chain reads first, so it stands for a lock on any table a migration
    touches. With the bound at one second, `migrate upgrade` gives up after
    that second, applies nothing, and exits RUN_AGAIN, which the deploy's
    pre-rollout task runs again on. Once the transaction ends, the same
    command applies the revision. Without the bound, the run waited for as
    long as the transaction stayed open."""
    core = migrated[DatabaseRole.CORE]
    await downgrade(DatabaseRole.CORE, core, "-1")
    before = await on_core(core, f"SELECT version_num FROM core.{VERSION_TABLE}")
    monkeypatch.setenv("ACME_DATABASE_MIGRATION_LOCK_TIMEOUT_SECONDS", "1")
    holder = create_async_engine(core)
    try:
        async with holder.begin() as held:
            await held.execute(text(f"LOCK TABLE core.{VERSION_TABLE} IN ACCESS EXCLUSIVE MODE"))
            started = time.monotonic()
            code = await asyncio.to_thread(main, ["upgrade", "--role", "core"])
            waited = time.monotonic() - started
    finally:
        await holder.dispose()
    assert code == RUN_AGAIN
    # The second of waiting, and what it costs to open a connection and read
    # the chain around it.
    assert 1.0 <= waited < 3.0
    assert "core: a lock was not granted within 1 s" in capsys.readouterr().err
    assert await on_core(core, f"SELECT version_num FROM core.{VERSION_TABLE}") == before
    assert await asyncio.to_thread(main, ["upgrade", "--role", "core"]) == 0
    assert await check(DatabaseRole.CORE, core) == []


async def seed_two_tenants(pg_sessions: LoginSessions) -> None:
    events = EventStoragePostgresImpl(pg_sessions)
    for org in (new_id(), new_id()):
        await events.append_events(org, [make_event(org)])


def forced(connection: Connection) -> bool:
    return connection.exec_driver_sql(
        "SELECT relforcerowsecurity FROM pg_class WHERE oid = 'activity.events'::regclass"
    ).scalar_one()


COUNT = "SELECT count(*) FROM activity.events"
UPDATE = "UPDATE activity.events SET kind = kind"


async def test_a_backfill_under_the_fence_touches_every_tenant(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """A migration names no tenant, and FORCE binds the migration login that
    owns the table, so a bare UPDATE matches no row and succeeds; its count
    says zero too, and zero equals zero. Seeded with two tenants' rows, the
    backfill counts and touches both, and the fence is back after it."""
    await seed_two_tenants(pg_sessions)
    engine = create_async_engine(migrated[DatabaseRole.ACTIVITY])
    try:
        async with engine.connect() as connection:

            def bare(sync: Connection) -> tuple[int, int]:
                expected = sync.exec_driver_sql(COUNT).scalar_one()
                return expected, sync.exec_driver_sql(UPDATE).rowcount

            assert await connection.run_sync(bare) == (0, 0)
            await connection.rollback()

            def fenced(sync: Connection) -> tuple[int, bool]:
                touched = backfill(sync, DatabaseRole.ACTIVITY, "events", COUNT, UPDATE)
                return touched, forced(sync)

            assert await connection.run_sync(fenced) == (2, True)
            await connection.rollback()
    finally:
        await engine.dispose()


async def test_a_backfill_that_misses_rows_fails_and_keeps_the_fence(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    await seed_two_tenants(pg_sessions)
    engine = create_async_engine(migrated[DatabaseRole.ACTIVITY])
    try:
        async with engine.connect() as connection:
            partial = (
                "UPDATE activity.events SET kind = kind WHERE seq = 1"
                " AND org_id = (SELECT org_id FROM activity.events ORDER BY org_id LIMIT 1)"
            )
            with pytest.raises(RuntimeError, match="touched 1 rows of 2"):
                await connection.run_sync(
                    lambda sync: backfill(sync, DatabaseRole.ACTIVITY, "events", COUNT, partial)
                )
            await connection.rollback()
            assert await connection.run_sync(forced) is True
    finally:
        await engine.dispose()


async def on_core(url: str, sql: str) -> list[tuple[object, ...]]:
    """One statement on the core role, as the migration login, which owns the
    version table the lock test reads."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            result = await connection.exec_driver_sql(sql)
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


async def notices_of(url: str, org: UUID, session_id: UUID, column: str = "notices") -> object:
    """A workspace's notices, or another of its columns, as the migration
    login reads them, inside its tenant's fence."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f"SET LOCAL app.org_id = '{org}'")
            read = await connection.exec_driver_sql(
                f"SELECT {column} FROM core.session_workspaces WHERE id = '{session_id}'"
            )
            return read.scalar_one()
    finally:
        await engine.dispose()


async def test_a_workspaces_notices_move_to_the_one_notice_and_back_for_every_tenant(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """Down, the last notice written is the one the previous release holds;
    up, it is the list's one entry, in both tenants' rows."""
    storage = WorkspaceStoragePostgresImpl(pg_sessions)
    held: dict[UUID, UUID] = {}
    for org in (new_id(), new_id()):
        workspace = make_workspace().model_copy(update={"notices": ("older", "newer")})
        assert await storage.create_workspace(org, workspace)
        held[org] = workspace.id
    core = migrated[DatabaseRole.CORE]

    await downgrade(DatabaseRole.CORE, core, "202610035400")
    await upgrade(DatabaseRole.CORE, core)

    for org, session_id in held.items():
        assert await notices_of(core, org, session_id) == ["newer"]
    assert await check(DatabaseRole.CORE, core) == []


V0_2_0_HEAD = "202610036100"
"""The core head of the release before the one notice left the table."""


async def notice_shape(url: str) -> list[tuple[object, ...]]:
    """The notice columns of a workspace row and the default of each."""
    return await on_core(
        url,
        "SELECT column_name, column_default FROM information_schema.columns"
        " WHERE table_schema = 'core' AND table_name = 'session_workspaces'"
        " AND column_name IN ('notice', 'notices') ORDER BY column_name",
    )


async def told_before(url: str, org: UUID, session_id: UUID) -> None:
    """The one notice a release before the list wrote and a loop was told,
    as the column still holds it, inside its tenant's fence."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f"SET LOCAL app.org_id = '{org}'")
            await connection.exec_driver_sql(
                f"UPDATE core.session_workspaces SET notice = 'told' WHERE id = '{session_id}'"
            )
    finally:
        await engine.dispose()


async def seed_notices(
    pg_sessions: LoginSessions, *notices: tuple[str, ...]
) -> dict[UUID, tuple[UUID, tuple[str, ...]]]:
    """One workspace a tenant, each holding its notices."""
    storage = WorkspaceStoragePostgresImpl(pg_sessions)
    held: dict[UUID, tuple[UUID, tuple[str, ...]]] = {}
    for listed in notices:
        org = new_id()
        workspace = make_workspace().model_copy(update={"notices": listed})
        assert await storage.create_workspace(org, workspace)
        held[org] = (workspace.id, listed)
    return held


async def test_the_one_notice_leaves_the_table_and_every_notice_stays_in_the_list(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """Rows written at the release before, the one notice beside each list,
    migrate forward with the column and the list's default gone and every
    entry of every tenant's list kept."""
    core = migrated[DatabaseRole.CORE]
    await downgrade(DatabaseRole.CORE, core, V0_2_0_HEAD)
    held = await seed_notices(pg_sessions, ("older", "newer"), ("only",), ())
    for org, (session_id, _) in held.items():
        await told_before(core, org, session_id)
    assert await notice_shape(core) == [("notice", None), ("notices", "'[]'::jsonb")]

    await upgrade(DatabaseRole.CORE, core)

    assert await notice_shape(core) == [("notices", None)]
    for org, (session_id, listed) in held.items():
        assert await notices_of(core, org, session_id) == list(listed)
    assert await check(DatabaseRole.CORE, core) == []


async def test_the_one_notice_comes_back_as_the_lists_last_entry(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """Down, each tenant's row holds its last notice in the column, an empty
    list leaves it null, and the list keeps every entry and its default; up
    again, the schema agrees with the mapping."""
    held = await seed_notices(pg_sessions, ("older", "newer"), ("only",), ())
    core = migrated[DatabaseRole.CORE]

    await downgrade(DatabaseRole.CORE, core, V0_2_0_HEAD)

    assert await notice_shape(core) == [("notice", None), ("notices", "'[]'::jsonb")]
    for org, (session_id, listed) in held.items():
        last = listed[-1] if listed else None
        assert await notices_of(core, org, session_id, "notice") == last
        assert await notices_of(core, org, session_id) == list(listed)

    await upgrade(DatabaseRole.CORE, core)
    assert await check(DatabaseRole.CORE, core) == []


async def in_tenant(url: str, org: UUID, sql: str) -> list[tuple[object, ...]]:
    """One statement on the core role, as the migration login, inside a
    tenant's fence."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f"SET LOCAL app.org_id = '{org}'")
            result = await connection.exec_driver_sql(sql)
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


async def session_shape(url: str) -> list[tuple[object, ...]]:
    """The validation session's station and commit columns, each with
    whether it takes a null."""
    return await on_core(
        url,
        "SELECT column_name, is_nullable FROM information_schema.columns"
        " WHERE table_schema = 'core' AND table_name = 'validation_sessions'"
        " AND column_name IN"
        " ('base', 'check_version', 'head', 'lab_id', 'parameters', 'project_id')"
        " ORDER BY column_name",
    )


V0_2_0_SESSION_SHAPE = [
    ("base", "YES"),
    ("check_version", "YES"),
    ("head", "YES"),
    ("lab_id", "YES"),
    ("parameters", "YES"),
    ("project_id", "YES"),
]
"""The columns at the release before the station's columns left: all
nullable, so both releases' rows fit."""

SESSION_SHAPE = [("base", "NO"), ("head", "NO"), ("project_id", "NO")]


async def written_on_a_station(url: str, org: UUID) -> UUID:
    """A session as the release before the executor wrote it: a lab, a check
    version, and parameters, and no project or commit."""
    session_id = new_id()
    actor = new_id()
    await in_tenant(
        url,
        org,
        "INSERT INTO core.validation_sessions (id, org_id, created_at, updated_at,"
        " created_by, updated_by, lab_id, check_name, check_version, parameters,"
        " status, version) VALUES"
        f" ('{session_id}', '{org}', now(), now(), '{actor}', '{actor}', '{new_id()}',"
        " 'report.totals', '1', '{}'::jsonb, 'queued', 1)",
    )
    return session_id


async def seed_sessions(pg_sessions: LoginSessions) -> dict[UUID, ValidationSession]:
    """Two tenants, each with a session this release wrote: one queued, one
    finished with its run."""
    storage = PlatformAgentsStoragePostgresImpl(pg_sessions)
    held: dict[UUID, ValidationSession] = {}
    for session in (make_validation(), finished(make_validation())):
        org = new_id()
        assert await storage.create_validation(org, session, ())
        held[org] = session
    return held


def as_sql(value: object) -> str:
    """A value as a SQL literal: null, or its text quoted."""
    if value is None:
        return "NULL"
    return f"'{value.isoformat() if isinstance(value, datetime) else value}'"


async def written_before(url: str) -> dict[UUID, ValidationSession]:
    """Two tenants, each with a session as the release before wrote it, one
    queued and one finished with its run: its project and its commits, and
    none of the columns a later release added, which the storage now maps."""
    held: dict[UUID, ValidationSession] = {}
    for session in (make_validation(), finished(make_validation())):
        org = new_id()
        values = (
            session.id,
            org,
            session.created_at,
            session.updated_at,
            session.created_by,
            session.updated_by,
            session.project_id,
            session.check_name,
            session.head,
            session.base,
            session.status.value,
            session.run_id,
            session.finished_at,
            session.version,
        )
        await in_tenant(
            url,
            org,
            "INSERT INTO core.validation_sessions (id, org_id, created_at, updated_at,"
            " created_by, updated_by, project_id, check_name, head, base, status, run_id,"
            f" finished_at, version) VALUES ({', '.join(as_sql(v) for v in values)})",
        )
        held[org] = session
    return held


async def test_the_station_columns_leave_and_every_session_this_release_wrote_stays(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """At the release before, each tenant holds a session that release wrote
    and one written on a station. Forward, the station's columns are gone,
    the commit columns take no null, the station session is gone, and every
    value of the other is kept."""
    core = migrated[DatabaseRole.CORE]
    storage = PlatformAgentsStoragePostgresImpl(pg_sessions)
    await downgrade(DatabaseRole.CORE, core, V0_2_0_HEAD)
    held = await written_before(core)
    for org in held:
        await written_on_a_station(core, org)
    assert await session_shape(core) == V0_2_0_SESSION_SHAPE

    await upgrade(DatabaseRole.CORE, core)

    assert await session_shape(core) == SESSION_SHAPE
    for org, session in held.items():
        assert await storage.read_validation(org, session.id) == session
        kept = await in_tenant(core, org, "SELECT count(*) FROM core.validation_sessions")
        assert kept == [(1,)]
    assert await check(DatabaseRole.CORE, core) == []


async def test_the_station_columns_come_back_null_and_the_sessions_stay(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """Down, the station's columns are back, nullable and null, the commit
    columns take a null again, and every session is kept and read; up again,
    the schema agrees with the mapping."""
    held = await seed_sessions(pg_sessions)
    core = migrated[DatabaseRole.CORE]
    storage = PlatformAgentsStoragePostgresImpl(pg_sessions)

    await downgrade(DatabaseRole.CORE, core, V0_2_0_HEAD)

    assert await session_shape(core) == V0_2_0_SESSION_SHAPE
    for org, session in held.items():
        assert await in_tenant(
            core,
            org,
            "SELECT project_id::text, head, base, status, run_id::text, version,"
            " lab_id, check_version, parameters FROM core.validation_sessions"
            f" WHERE id = '{session.id}'",
        ) == [
            (
                str(session.project_id),
                session.head,
                session.base,
                session.status.value,
                None if session.run_id is None else str(session.run_id),
                session.version,
                None,
                None,
                None,
            )
        ]

    await upgrade(DatabaseRole.CORE, core)
    assert await check(DatabaseRole.CORE, core) == []
    for org, session in held.items():
        assert await storage.read_validation(org, session.id) == session


PREVIOUS_ACTION = {"kind", "brief", "agent_kind", "title", "project_id", "session_id"}
"""The fields of an action the release before product action kinds holds,
which forbids any other."""


async def actions_of(url: str, org: UUID) -> dict[UUID, dict[str, object]]:
    """A tenant's stored actions by automation, as the migration login reads
    them inside the tenant's fence."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f"SET LOCAL app.org_id = '{org}'")
            read = await connection.exec_driver_sql("SELECT id, action FROM core.automations")
            return {row[0]: row[1] for row in read}
    finally:
        await engine.dispose()


async def test_a_platform_automation_reads_as_the_previous_releases_after_a_downgrade(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """This release writes a platform action with no `params`, and the
    downgrade strips the key from one that carries it; an automation of a
    product's kind goes."""
    storage = AutomationStoragePostgresImpl(pg_sessions)
    org = new_id()
    written, carried = make_automation(), make_automation()
    product = make_automation().model_copy(
        update={"action": Action(kind="run_job", params={"steps": 2})}
    )
    for automation in (written, carried, product):
        assert await storage.create_automation(org, automation, ())
    core = migrated[DatabaseRole.CORE]
    assert "params" not in (await actions_of(core, org))[written.id]
    engine = create_async_engine(core)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f"SET LOCAL app.org_id = '{org}'")
            await connection.exec_driver_sql(
                """UPDATE core.automations SET action = action || '{"params": {}}'"""
                f" WHERE id = '{carried.id}'"
            )
    finally:
        await engine.dispose()

    await downgrade(DatabaseRole.CORE, core, "202610036300")
    previous = await actions_of(core, org)
    await upgrade(DatabaseRole.CORE, core)

    assert set(previous) == {written.id, carried.id}
    assert all(set(action) == PREVIOUS_ACTION for action in previous.values())
    assert await storage.read_automation(org, written.id) == written
    assert await check(DatabaseRole.CORE, core) == []
