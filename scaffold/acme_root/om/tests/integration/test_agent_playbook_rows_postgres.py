"""An agent playbook's rows as the release before writes them through a roll,
on the head's schema: a version written with no findings reads as never
checked, and an invocation written with no `pinned` reads as a principal's,
never a session's kind manual."""

import json
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from acme.om.agent_playbooks.storage.impl.postgres import AgentPlaybookStoragePostgresImpl
from acme.om.base import new_id
from acme.om.storage.impl.pg_base import LoginSessions
from acme.om.storage.roles import DatabaseRole

from contracts.agent_playbook_storage import make_agent_playbook

pytestmark = pytest.mark.integration


async def in_tenant(url: str, org: UUID, sql: str) -> None:
    """One statement on the core role, as the migration login, inside a
    tenant's fence."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(f"SET LOCAL app.org_id = '{org}'")
            await connection.exec_driver_sql(sql)
    finally:
        await engine.dispose()


async def test_a_version_written_with_no_findings_reads_as_never_checked(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """A version written with no findings column reads as never checked,
    which is not checked and clean."""
    org, agent_playbook = new_id(), make_agent_playbook()
    gates = json.dumps([gate.model_dump(mode="json") for gate in agent_playbook.gates])
    await in_tenant(
        migrated[DatabaseRole.CORE],
        org,
        "INSERT INTO core.agent_playbooks (id, org_id, created_at, name, version, description,"
        " body, gates, published_by) VALUES"
        f" ('{agent_playbook.id}', '{org}', now(), '{agent_playbook.name}', 1, 'Cut a build.',"
        f" 'Build.', '{gates}'::jsonb, '{agent_playbook.published_by}')",
    )

    stored = await AgentPlaybookStoragePostgresImpl(pg_sessions).read_agent_playbook(
        org, agent_playbook.id
    )

    assert stored is not None and stored.findings is None


async def test_an_invocation_written_with_no_pinned_reads_as_no_kind_manual(
    pg_sessions: LoginSessions, migrated: dict[DatabaseRole, str]
) -> None:
    """An invocation written with no `pinned` column reads as a principal's:
    its brief was a message, and the session's standing text holds none of
    it."""
    org, agent_session_id, agent_playbook = new_id(), new_id(), make_agent_playbook()
    await in_tenant(
        migrated[DatabaseRole.CORE],
        org,
        "INSERT INTO core.agent_playbook_invocations (id, org_id, created_at,"
        " agent_session_id, agent_playbook_id, name, version, invoked_by) VALUES"
        f" ('{new_id()}', '{org}', now(), '{agent_session_id}', '{agent_playbook.id}',"
        f" '{agent_playbook.name}', 1, '{new_id()}')",
    )

    (stored,) = await AgentPlaybookStoragePostgresImpl(pg_sessions).read_invocations(
        org, agent_session_id, 10
    )

    assert not stored.pinned
