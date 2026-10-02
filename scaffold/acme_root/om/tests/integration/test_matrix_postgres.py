"""The model matrix over Postgres: what only the database holds (no serving
login rewrites or removes a benchmark's result), and a session end to end:
its fill resolved through the published matrix and called on the scripted
provider, kept across a publication, and switched off a retired model at
its next loop, every row in the database."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from contracts.loops import reply, said
from contracts.matrix import CATCH_ALL, OPUS, SONNET, fleet_over
from integration.test_money_postgres import an_owner, refused
from sqlalchemy import text

from acme.om.agents.types.run import RunEnd
from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.matrix.storage.impl.postgres import MatrixStoragePostgresImpl
from acme.om.matrix.types.matrix import MatrixKey, MatrixRow
from acme.om.matrix.types.record import BenchmarkResult, ModelRef
from acme.om.models.types.fill import MAIN, SwitchReason
from acme.om.steps.types.header import SwitchedHeader
from acme.om.storage.impl.pg_base import LoginSessions
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.migrate import ensure_logins_at
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration


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


async def test_no_serving_login_rewrites_or_removes_a_benchmarks_result(
    pg_sessions: LoginSessions, migration_settings: MigrationSettings
) -> None:
    """A result is written once: the serving logins may read and insert one
    and are refused an UPDATE and a DELETE by the database itself, after a
    deploy made the logins again."""
    settings = migration_settings
    await ensure_logins_at(settings.master_url(), settings.login_passwords())
    matrix = MatrixStoragePostgresImpl(pg_sessions)
    result = BenchmarkResult(
        id=new_id(),
        created_at=utcnow(),
        provider=SONNET.provider,
        model=SONNET.model,
        role=MAIN,
        benchmark="swe-lite",
        passed=False,
        run="run-1",
        recorded_by=new_id(),
    )
    await matrix.add_result(result)

    for factory in (pg_sessions[DatabaseRole.CORE], pg_sessions.system[DatabaseRole.CORE]):
        for statement in (
            text("UPDATE core.benchmark_results SET passed = true"),
            text("DELETE FROM core.benchmark_results"),
        ):
            error = await refused(factory, EMPTY_UUID, statement)
            assert "permission denied for table benchmark_results" in error, error
    assert await matrix.read_results(ModelRef.of(SONNET), 10) == [result]


async def test_a_session_resolves_keeps_and_renews_its_fill_through_the_matrix_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    """End to end over Postgres: an operator publishes the matrix, a
    session's loop resolves its fill through it and calls the scripted
    provider on that model, keeps it across the next publication, and
    switches off it at its next loop once the provider retires it."""
    owner = await an_owner(storage, tmp_path)
    fleet = await fleet_over(tmp_path, storage=storage, owner=owner)
    first = await fleet.publish()
    session_id = await fleet.loop.start()
    await fleet.loop.say(session_id, "What is the total?")
    fleet.loop.anthropic.add(reply(said("The total is 12.")))

    ran = await fleet.loop.loops.run(owner, session_id)

    assert ran.end is RunEnd.ENDED, ran
    assert [call.model for call in fleet.loop.anthropic.calls] == [SONNET.model]
    pin = await fleet.matrix.matrix.get_pin(owner, session_id)
    assert (pin.matrix_version, pin.fill_set_version) == (first.number, 1)

    second = await fleet.publish(
        (MatrixRow(key=MatrixKey(role=MAIN), fills=(OPUS,)), *CATCH_ALL[1:])
    )
    await fleet.loop.say(session_id, "And the average?")
    fleet.loop.anthropic.add(reply(said("The average is 3.")))
    assert (await fleet.loop.loops.run(owner, session_id)).end is RunEnd.ENDED
    assert fleet.loop.anthropic.calls[-1].model == SONNET.model, "kept across the publication"

    await fleet.matrix.matrix_operator.retire_model(fleet.admin, ModelRef.of(SONNET))
    await fleet.loop.say(session_id, "And the median?")
    fleet.loop.anthropic.add(reply(said("The median is 2."), model=OPUS.model))
    assert (await fleet.loop.loops.run(owner, session_id)).end is RunEnd.ENDED

    assert fleet.loop.anthropic.calls[-1].model == OPUS.model
    (switched,) = [
        step.header
        for step in await fleet.loop.history(session_id)
        if isinstance(step.header, SwitchedHeader)
    ]
    assert (switched.fills.from_fill, switched.fills.to_fill) == (SONNET, OPUS)
    assert switched.fills.reason is SwitchReason.RETIRED
    pin = await fleet.matrix.matrix.get_pin(owner, session_id)
    assert (pin.matrix_version, pin.fill_set_version) == (second.number, 2)
