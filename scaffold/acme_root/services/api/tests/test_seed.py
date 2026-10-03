"""A local org is seeded ready to run a session: its account on a plan,
its first project, its retention policy, and the published matrix, and a
seed run twice writes nothing new. The matrix is published by the
provisioner, admitted on a token the seed ends when it is done."""

import re
from pathlib import Path

from api_support import build_container, seed_request

from acme.om.matrix.types.matrix import MatrixStatus
from acme.services.api.seed import (
    CONTENT_LIFETIME,
    PLAN,
    PROVISIONER,
    REPOSITORY,
    seed_platform,
)

ROOT = Path(__file__).resolve().parents[3]


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
    assert first.project is not None and second.project is None
    project = await container.managers.projects.get_project(owner, first.project.id)
    assert project.repository == REPOSITORY
    assert (await container.managers.retention.get_policy(owner)).policy.content_lifetime == (
        CONTENT_LIFETIME
    )
    matrix = container.storage.get_matrix_storage()
    published = await matrix.read_latest(MatrixStatus.PUBLISHED)
    assert published is not None
    assert first.matrix_version == second.matrix_version == published.number
    assert (
        published.created_by
        == (await container.managers.tenancy.operator_identity(seed_request(), PROVISIONER)).id
    )


async def test_make_seed_readies_both_local_orgs_each_with_its_account(tmp_path: Path) -> None:
    """`make seed` seeds each org it bootstraps, so a session in either finds
    who pays at its first model call; the matrix is published once."""
    recipe = (ROOT / "Makefile").read_text().split("\nseed:", 1)[1].split("\n\n", 1)[0]
    slugs = re.findall(r'seed-platform --slug "\$\((\w+)\)"', recipe)
    assert slugs == ["SEED_SLUG", "SEED_SECOND_SLUG"]
    container = build_container(tmp_path)
    tenancy = container.managers.tenancy
    first = await tenancy.bootstrap(seed_request(), "Ajax", "ajax", "ann@example.test", "Ann")
    second = await tenancy.bootstrap(seed_request(), "Brio", "brio", "bo@example.test", "Bo")

    seeded = [
        await seed_platform(container.storage, container.managers, owner)
        for owner, _ in (first, second)
    ]

    accounts = container.storage.get_account_storage()
    for _, org in (first, second):
        account = await accounts.read_account(org.id)
        assert account is not None and account.plan_id == PLAN, org.slug
    assert all(each.project is not None for each in seeded)
    assert seeded[0].matrix_version == seeded[1].matrix_version
