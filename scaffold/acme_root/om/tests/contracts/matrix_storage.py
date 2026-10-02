"""The matrix storage contract: the platform's versions of the matrix and
what its operators record of a model, global rows; and each tenant's pins
and choices. The cases named in `TENANT_CROSS_TENANT_CASES` are the tenant
fence's evidence: each one presents another tenant's identifier and asserts
that nothing is found and nothing changes. The global storage takes no
tenant, so it names none."""

from datetime import timedelta
from uuid import UUID

import pytest

from acme.integrations.model_providers.types import ProviderName
from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed
from acme.om.matrix.storage import MatrixStorageInterface, MatrixTenantStorageInterface
from acme.om.matrix.types.matrix import MatrixKey, MatrixRow, MatrixStatus, MatrixVersion
from acme.om.matrix.types.record import BenchmarkResult, ModelRef, Retirement
from acme.om.matrix.types.tenant import FillOverride, MatrixPin
from acme.om.models.types.fill import MAIN, SUMMARIZER, Eligibility, Fill

CROSS_TENANT_CASES: frozenset[str] = frozenset()
"""`MatrixStorageInterface` takes no tenant: its rows are the platform's."""

TENANT_CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "write_pin",
        "read_pin",
        "write_override",
        "delete_override",
        "read_overrides",
        "purge_tenant",
    }
)
"""Every method of `MatrixTenantStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""

SONNET = Fill(
    provider=ProviderName.ANTHROPIC,
    model="claude-sonnet-5-5",
    max_output_tokens=32_000,
    context_window=1_000_000,
)
GPT = Fill(
    provider=ProviderName.OPENAI,
    model="gpt-6.1-sol",
    max_output_tokens=32_000,
    context_window=1_050_000,
    eligibility=Eligibility(zero_retention=True, region="eu-central-1"),
)


def make_version(number: int = 1) -> MatrixVersion:
    return MatrixVersion(
        id=new_id(),
        number=number,
        roles=(MAIN, SUMMARIZER),
        rows=(
            MatrixRow(fills=(SONNET, GPT)),
            MatrixRow(key=MatrixKey(role=MAIN, plan_tier="pro"), fills=(GPT,)),
        ),
        created_at=utcnow(),
        created_by=new_id(),
    )


def make_result(model: ModelRef, *, passed: bool = True, minutes: int = 0) -> BenchmarkResult:
    return BenchmarkResult(
        id=new_id(),
        created_at=utcnow() + timedelta(minutes=minutes),
        provider=model.provider,
        model=model.model,
        role=MAIN,
        benchmark="swe-lite",
        passed=passed,
        run="run-1",
        recorded_by=new_id(),
    )


def make_retirement(model: ModelRef) -> Retirement:
    return Retirement(
        id=new_id(),
        created_at=utcnow(),
        provider=model.provider,
        model=model.model,
        recorded_by=new_id(),
    )


def make_pin(
    session_id: UUID | None = None, fill_set_version: int = 1, matrix_version: int = 1
) -> MatrixPin:
    return MatrixPin(
        id=new_id(),
        created_at=utcnow(),
        session_id=session_id or new_id(),
        fill_set_version=fill_set_version,
        matrix_version=matrix_version,
    )


def make_choice(fill: Fill = SONNET, role: str = MAIN) -> FillOverride:
    now = utcnow()
    actor = new_id()
    return FillOverride(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        role=role,
        fill=fill,
    )


class MatrixStorageContract:
    @pytest.fixture
    def storage(self) -> MatrixStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_version_round_trips_and_its_number_is_taken_once(
        self, storage: MatrixStorageInterface
    ) -> None:
        version = make_version()
        await storage.create_version(version)
        assert await storage.read_version(1) == version
        with pytest.raises(PreconditionFailed):
            await storage.create_version(make_version())
        assert await storage.read_version(1) == version
        assert await storage.read_version(2) is None

    async def test_the_latest_is_the_highest_number_of_a_status(
        self, storage: MatrixStorageInterface
    ) -> None:
        assert await storage.read_latest(None) is None
        await storage.create_version(make_version(1))
        await storage.create_version(make_version(2))
        latest = await storage.read_latest(None)
        assert latest is not None and latest.number == 2
        assert await storage.read_latest(MatrixStatus.PUBLISHED) is None
        published = await storage.publish_version(1, utcnow(), new_id())
        assert published is not None and published.status is MatrixStatus.PUBLISHED
        current = await storage.read_latest(MatrixStatus.PUBLISHED)
        assert current == published

    async def test_publishing_changes_the_status_alone_and_only_once(
        self, storage: MatrixStorageInterface
    ) -> None:
        version = make_version()
        await storage.create_version(version)
        at, by = utcnow(), new_id()
        published = await storage.publish_version(1, at, by)
        assert published == version.model_copy(
            update={"status": MatrixStatus.PUBLISHED, "published_at": at, "published_by": by}
        )
        assert await storage.publish_version(1, utcnow(), new_id()) is None
        assert await storage.read_version(1) == published
        assert await storage.publish_version(7, utcnow(), new_id()) is None

    async def test_a_version_older_than_a_published_one_is_never_published(
        self, storage: MatrixStorageInterface
    ) -> None:
        await storage.create_version(make_version(1))
        await storage.create_version(make_version(2))
        assert await storage.publish_version(2, utcnow(), new_id()) is not None
        assert await storage.publish_version(1, utcnow(), new_id()) is None
        older = await storage.read_version(1)
        assert older is not None and older.status is MatrixStatus.PENDING

    async def test_results_are_read_newest_first_by_model(
        self, storage: MatrixStorageInterface
    ) -> None:
        sonnet, gpt = ModelRef.of(SONNET), ModelRef.of(GPT)
        first = make_result(sonnet, passed=False)
        second = make_result(sonnet, minutes=1)
        await storage.add_result(first)
        await storage.add_result(second)
        await storage.add_result(second)
        await storage.add_result(make_result(gpt))
        assert await storage.read_results(sonnet, 10) == [second, first]
        assert await storage.read_results(sonnet, 1) == [second]

    async def test_a_model_is_retired_once(self, storage: MatrixStorageInterface) -> None:
        sonnet = ModelRef.of(SONNET)
        first = make_retirement(sonnet)
        assert await storage.add_retirement(first) == first
        assert await storage.add_retirement(make_retirement(sonnet)) == first
        second = make_retirement(ModelRef.of(GPT))
        await storage.add_retirement(second)
        assert {r.id for r in await storage.read_retirements(10)} == {first.id, second.id}
        assert len(await storage.read_retirements(1)) == 1


class MatrixTenantStorageContract:
    @pytest.fixture
    def storage(self) -> MatrixTenantStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_pin_is_written_once_a_fill_set_version(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org = new_id()
        first = make_pin()
        assert await storage.write_pin(org, first) == first
        again = make_pin(first.session_id, matrix_version=9)
        assert await storage.write_pin(org, again) == first
        later = make_pin(first.session_id, fill_set_version=3, matrix_version=2)
        assert await storage.write_pin(org, later) == later
        assert await storage.read_pin(org, first.session_id) == later
        assert await storage.read_pin(org, new_id()) is None

    async def test_write_pin_of_another_tenant_lands_nothing_here(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        pin = make_pin()
        await storage.write_pin(org_a, pin)
        with pytest.raises(PreconditionFailed):
            await storage.write_pin(org_b, pin)
        assert await storage.read_pin(org_b, pin.session_id) is None
        assert await storage.read_pin(org_a, pin.session_id) == pin

    async def test_read_pin_of_another_tenant_finds_nothing(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        pin = make_pin()
        await storage.write_pin(new_id(), pin)
        assert await storage.read_pin(new_id(), pin.session_id) is None

    async def test_a_choice_replaces_the_last_for_its_role(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org = new_id()
        first = make_choice()
        assert await storage.write_override(org, first) == first
        later = make_choice(GPT)
        stored = await storage.write_override(org, later)
        assert stored.id == first.id and stored.fill == GPT
        summary = make_choice(role=SUMMARIZER)
        await storage.write_override(org, summary)
        assert await storage.read_overrides(org, 10) == [stored, summary]
        assert await storage.read_overrides(org, 1) == [stored]
        assert await storage.delete_override(org, MAIN)
        assert not await storage.delete_override(org, MAIN)
        assert await storage.read_overrides(org, 10) == [summary]

    async def test_write_override_of_another_tenant_leaves_this_ones(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        mine = make_choice()
        await storage.write_override(org_a, mine)
        await storage.write_override(org_b, make_choice(GPT))
        assert await storage.read_overrides(org_a, 10) == [mine]

    async def test_delete_override_of_another_tenant_changes_nothing(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org = new_id()
        mine = make_choice()
        await storage.write_override(org, mine)
        assert not await storage.delete_override(new_id(), MAIN)
        assert await storage.read_overrides(org, 10) == [mine]

    async def test_read_overrides_of_another_tenant_finds_nothing(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        await storage.write_override(new_id(), make_choice())
        assert await storage.read_overrides(new_id(), 10) == []

    async def test_purge_tenant_takes_the_tenants_rows_and_no_other(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        gone, kept = new_id(), new_id()
        await storage.write_pin(gone, make_pin())
        await storage.write_pin(gone, make_pin())
        await storage.write_override(gone, make_choice())
        stays = make_pin()
        await storage.write_pin(kept, stays)
        choice = make_choice()
        await storage.write_override(kept, choice)
        assert await storage.purge_tenant(gone, 2) == 2
        assert await storage.purge_tenant(gone, 2) == 1
        assert await storage.purge_tenant(gone, 2) == 0
        assert await storage.read_overrides(gone, 10) == []
        assert await storage.read_pin(kept, stays.session_id) == stays
        assert await storage.read_overrides(kept, 10) == [choice]
