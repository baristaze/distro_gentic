"""A local org is seeded ready to run a session: its account on a plan,
its first project, its retention policy, and the published matrix, and a
seed run twice writes nothing new. The matrix is published by the
provisioner, admitted on a token the seed ends when it is done. Where the
forge is its twin, each seeded org connects the twin's installation that
holds its project's repository, so its sessions write through it."""

import re
from pathlib import Path

from api_support import build_container, seed_request

from acme.integrations.events.twin import IntegrationTwinImpl
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import absent_model_providers
from acme.om.matrix.types.matrix import MatrixStatus
from acme.om.workspaces.impl.forge import SourceControlForgeImpl
from acme.om.workspaces.impl.projects import WorkspaceProjectsBoundImpl
from acme.services.api.seed import (
    CONTENT_LIFETIME,
    FORGE,
    PLAN,
    PROVISIONER,
    first_repository,
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
    assert project.repository == first_repository("ajax")
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


async def test_after_the_seed_a_session_in_each_seeded_org_pushes_and_opens_a_pull_request(
    tmp_path: Path,
) -> None:
    """The forge's twin holds each owner's repositories by an installation
    of their own, and the seed connects each org's, so a write of a session
    in either org goes through source control as the root wires it."""
    forge = IntegrationTwinImpl(FORGE)
    integrations = IntegrationsOverImpl(
        IdentityProviderTwinImpl(), absent_model_providers(), {FORGE: forge}
    )
    container = build_container(tmp_path, integrations=integrations)
    tenancy = container.managers.tenancy
    owners = [
        (await tenancy.bootstrap(seed_request(), "Ajax", "ajax", "ann@example.test", "Ann"))[0],
        (await tenancy.bootstrap(seed_request(), "Brio", "brio", "bo@example.test", "Bo"))[0],
    ]
    writes = SourceControlForgeImpl(
        integrations.get_integration, container.storage.get_intake_storage().read_installation_org
    )
    projects = WorkspaceProjectsBoundImpl(container.storage.get_project_storage())

    for owner in owners:
        seeded = await seed_platform(container.storage, container.managers, owner, forge=forge)
        assert seeded.project is not None
        binding = await projects.binding_of(owner, seeded.project.id)
        assert binding is not None
        await writes.push(owner, binding, "refs/heads/sessions/one", "9a8b7c6", b"bundle")
        await writes.open_pull_request(owner, binding, "sessions/one", "A fix", "Fixes it.")

    assert [pull.repository for pull in forge.pull_requests] == [
        "https://example.test/ajax/first.git",
        "https://example.test/brio/first.git",
    ]
