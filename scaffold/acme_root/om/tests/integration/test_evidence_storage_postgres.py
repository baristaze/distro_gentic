from uuid import UUID

import pytest
from contracts.evidence_storage import EvidenceStorageContract, make_record, make_validation
from sqlalchemy import TextClause, text
from sqlalchemy.exc import DBAPIError

from acme.om.base import EMPTY_UUID, new_id
from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.storage.impl.postgres import EvidenceStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions, SessionFactory, set_scope
from acme.om.storage.logins import RUNTIME_LOGIN, SYSTEM_LOGIN
from acme.om.storage.migrate import ensure_logins_at
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration

WRITTEN_ONCE = ("execution_records", "validations", "inferences")


class TestEvidenceStoragePostgres(EvidenceStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> EvidenceStorageInterface:
        return EvidenceStoragePostgresImpl(pg_sessions)


async def refused(factory: SessionFactory, org_id: UUID, statement: TextClause) -> str:
    """The error a statement meets under the given scope, on a session of
    its own, since a refused statement ends its transaction."""
    async with factory() as session:
        await set_scope(session, org_id, None, None)
        with pytest.raises(DBAPIError) as error:
            await session.execute(statement)
        return str(error.value)


async def test_no_serving_login_rewrites_or_removes_a_run(
    pg_sessions: LoginSessions, migration_settings: MigrationSettings
) -> None:
    """A run, a validation, and a hypothesis or finding are written once:
    the serving logins may read and insert them and are refused an UPDATE
    and a DELETE by the database itself, after a deploy made the logins
    again. Only the purge login deletes them."""
    settings = migration_settings
    await ensure_logins_at(settings.master_url(), settings.login_passwords())
    storage = EvidenceStoragePostgresImpl(pg_sessions)
    org, session = new_id(), new_id()
    validation, runs = make_validation(session, 1)
    assert await storage.create_validation(org, validation, runs)
    assert await storage.create_record(org, make_record(session))

    for factory, scope in (
        (pg_sessions[DatabaseRole.ACTIVITY], org),
        (pg_sessions.system[DatabaseRole.ACTIVITY], EMPTY_UUID),
    ):
        for table in WRITTEN_ONCE:
            for statement in (
                text(f"UPDATE activity.{table} SET created_at = created_at"),
                text(f"DELETE FROM activity.{table}"),
            ):
                error = await refused(factory, scope, statement)
                assert f"permission denied for table {table}" in error, error

    privilege = text("SELECT has_table_privilege(:login, :table, :privilege)")
    async with pg_sessions[DatabaseRole.ACTIVITY]() as db:
        for table in WRITTEN_ONCE:
            held: set[tuple[str, str]] = set()
            for login in (RUNTIME_LOGIN, SYSTEM_LOGIN):
                for kind in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    found = await db.execute(
                        privilege,
                        {"login": login, "table": f"activity.{table}", "privilege": kind},
                    )
                    if found.scalar_one():
                        held.add((login, kind))
            assert held == {
                (RUNTIME_LOGIN, "SELECT"),
                (RUNTIME_LOGIN, "INSERT"),
                (SYSTEM_LOGIN, "SELECT"),
                (SYSTEM_LOGIN, "INSERT"),
            }, table
    assert await storage.read_validation_records(org, session, [validation.id], 10) == list(
        sorted(runs, key=lambda run: run.id)
    )
