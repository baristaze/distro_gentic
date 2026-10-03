"""A local org is seeded ready to run a session: its account on a plan,
its first project, its retention policy, and the published matrix, and a
seed run twice writes nothing new."""

from pathlib import Path

from api_support import build_container, seed_request

from acme.om.matrix.types.matrix import MatrixStatus
from acme.services.api.seed import CONTENT_LIFETIME, PLAN, project_id_of, seed_platform


async def test_a_seed_readies_the_tenant_once_and_a_second_run_writes_nothing(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    owner, org = await container.managers.tenancy.bootstrap(
        seed_request(), "Ajax", "ajax", "ann@example.test", "Ann"
    )

    first = await seed_platform(container.storage, container.managers, owner)
    second = await seed_platform(container.storage, container.managers, owner)

    account = await container.storage.get_account_storage().read_account(org.id)
    assert account is not None and account.plan_id == PLAN
    assert first.project.id == second.project.id == project_id_of(org.id)
    assert (await container.managers.retention.get_policy(owner)).policy.content_lifetime == (
        CONTENT_LIFETIME
    )
    matrix = container.storage.get_matrix_storage()
    published = await matrix.read_latest(MatrixStatus.PUBLISHED)
    assert published is not None
    assert first.matrix_version == second.matrix_version == published.number
