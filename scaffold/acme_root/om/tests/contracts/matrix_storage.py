"""The matrix storage contract: the platform's versions of the matrix and
what its operators record of a model, global rows. The storage takes no
tenant, so it names no cross-tenant case; each tenant's pins and choices
are `contracts.matrix_tenant_storage`'s."""

from datetime import timedelta

import pytest

from acme.integrations.model_providers.types import ProviderName
from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed
from acme.om.language_models.types.fill import MAIN, SUMMARIZER, Eligibility, Fill
from acme.om.matrix.storage import MatrixStorageInterface
from acme.om.matrix.types.matrix import MatrixKey, MatrixRow, MatrixStatus, MatrixVersion
from acme.om.matrix.types.record import BenchmarkResult, ModelRef, Retirement

INTERFACE = MatrixStorageInterface
"""The storage interface whose cross-tenant cases this suite holds."""

CROSS_TENANT_CASES: frozenset[str] = frozenset()
"""`MatrixStorageInterface` takes no tenant: its rows are the platform's."""

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
