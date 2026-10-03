"""The acceptance harness over Postgres: a scripted run whose chain is
whole passes, and one that edited the system under test does not; the
hidden suite's runs stay with the verdict, out of what the session
reads."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from contracts.acceptance import COMPLETE, ScriptedRun, whole
from contracts.rehearsal import world_over

from acme.om.evidence.types.acceptance import Link
from acme.om.storage.impl.postgres import StoragePostgresImpl
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


async def test_a_whole_chain_passes_and_an_edit_of_the_system_under_test_does_not(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    world = await world_over(storage, tmp_path)
    run = ScriptedRun(world.parts, world.owner)
    verdict = await run.judge(await whole(run))
    assert verdict.passed, verdict.breaks
    assert [found.check for found in verdict.hidden] == [COMPLETE.name]
    runs = await world.managers.evidence.get_runs(world.owner, run.session, None, 200)
    assert COMPLETE.name not in {found.check for found in runs.items}

    # The project's policy leaves the service open, so its gate lets the
    # edit through; the scenario forbids the system under test on its own.
    edited = ScriptedRun(world.parts, world.owner)
    verdict = await edited.judge(await whole(edited, "src/export.py", "service/app.py"))
    assert verdict.broken() == {Link.UNTOUCHED}
