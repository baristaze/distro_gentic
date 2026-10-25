"""A session's title through the platform over Postgres, read as a reader of
its tenant reads every table (ADR 1042): a session started with a title,
whose agent asks its requester a question the platform tells on its own list
and on a chat account, leaves the title in no row of any role's database. The
post on the chat account names the session by its title, opened."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import CursorResult, text

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.agent_sessions.rules import QUESTION
from acme.om.agent_steps.rules import message_step
from acme.om.agents.types.request import Start
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.platform_root import build_platform_managers
from acme.om.storage.impl.pg_base import LoginSessions, set_scope
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings

from contracts.intake import wired
from contracts.loops import call, reply, said

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")

TABLES = (
    "SELECT schemaname, tablename FROM pg_tables"
    " WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
    " AND has_table_privilege(format('%I.%I', schemaname, tablename), 'SELECT')"
    " ORDER BY schemaname, tablename"
)
"""Every table of a role's database its runtime login reads."""


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


async def an_owner(storage: StoragePostgresImpl, tmp_path: Path) -> TenantContext:
    settings = InfraSettings.model_validate(
        {"environment": "local", "buckets_root": tmp_path / "buckets"}
    )
    managers = build_platform_managers(storage, InfraConfiguredImpl(settings))
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    return owner


def marker() -> str:
    return f"zq-{new_id().hex[-12:]}"


async def holding(
    pg_sessions: LoginSessions, org_id: UUID, mark: str
) -> tuple[set[str], dict[str, int]]:
    """Every table each role's database holds, and those of them with rows
    that hold `mark` as text, read under the tenant's scope, with how many."""
    scanned: set[str] = set()
    found: dict[str, int] = {}
    for role in DatabaseRole:
        async with pg_sessions[role]() as session:
            await set_scope(session, org_id, None, None)
            tables = (await session.execute(text(TABLES))).all()
            for schema, table in tables:
                name = f"{schema}.{table}"
                scanned.add(name)
                result = cast(
                    CursorResult[Any],
                    await session.execute(
                        text(
                            f'SELECT count(*) FROM "{schema}"."{table}" t WHERE t::text LIKE :like'
                        ),
                        {"like": f"%{mark}%"},
                    ),
                )
                if n := result.scalar_one():
                    found[name] = n
            await session.commit()
    return scanned, found


async def test_a_title_the_platform_shows_and_tells_lands_in_no_row_over_postgres(
    storage: StoragePostgresImpl, pg_sessions: LoginSessions, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    platform = wired(tmp_path, storage=storage, owner=owner)
    linker, requester = await platform.member(Role.OWNER), await platform.member(Role.MEMBER)
    await platform.intake.link_account(linker, "chat", "U-MEMBER", requester.user_id)
    mark = marker()
    title = f"{mark} the weekly report"
    started = await platform.managers.agents.start_agent_session(
        requester, Start(id=new_id(), kind="asking", title=title)
    )
    platform.anthropic.add(reply(said("Which week?"), call("ask_person", question="Which week?")))
    message = message_step(new_id(), utcnow(), started.id, requester, "Fix the weekly report.")
    await platform.managers.agent_sessions.receive(requester, started.id, [message])
    run = await platform.loops.run(requester, started.id)
    assert run.end is RunEnd.PARKED and run.park == QUESTION

    notified = await platform.park_alerts.notify_park(platform.service, run)

    assert {n.channel for n in notified} == {"portal", "chat"}
    (posted,) = platform.chat.posted
    assert posted.text.startswith(f"{title} asks you: ")
    read = await platform.managers.agent_sessions.get_agent_session(requester, started.id)
    (opened,) = await platform.managers.agent_sessions.open_titles(requester, [read])
    assert opened.title.said() == title
    scanned, found = await holding(pg_sessions, owner.org_id, mark)
    assert {"core.agent_sessions", "core.park_alerts"} <= scanned
    assert found == {}
