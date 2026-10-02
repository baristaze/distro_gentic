"""The benchmark storage contract: what the benchmark job showed of a
candidate against its baseline, global rows, each written once and read
back whole. The storage takes no tenant, so it names no cross-tenant
case."""

from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

import pytest

from acme.integrations.model_providers.types import ProviderName
from acme.om.base import new_id, utcnow
from acme.om.benchmarks.rules import arm_result, regressed, schedule
from acme.om.benchmarks.storage import BenchmarkStorageInterface
from acme.om.benchmarks.types.benchmark import (
    Arm,
    Benchmark,
    BenchmarkTrials,
    Contender,
    Trial,
)
from acme.om.context import AppContext, AppType, CredentialKind, OperatorContext, OperatorRole
from acme.om.evidence.types.acceptance import AcceptanceVerdict, Break, Link
from acme.om.models.types.fill import MAIN, Fill, RoleFill
from acme.om.tenancy.rules import operator_permissions_of

CROSS_TENANT_CASES: frozenset[str] = frozenset()
"""`BenchmarkStorageInterface` takes no tenant: its rows are the platform's."""

SONNET = Fill(
    provider=ProviderName.ANTHROPIC,
    model="claude-sonnet-5-5",
    max_output_tokens=32_000,
    context_window=1_000_000,
)
OPUS = Fill(
    provider=ProviderName.ANTHROPIC,
    model="claude-opus-5-5",
    max_output_tokens=32_000,
    context_window=1_000_000,
)
CANDIDATE = Contender(kind="engineer", kind_version=2, fills=(RoleFill(role=MAIN, fill=OPUS),))
BASELINE = Contender(kind="engineer", kind_version=2, fills=(RoleFill(role=MAIN, fill=SONNET),))
"""The candidate changes the model alone: both arms run one kind at one
version, so what the run shows is the model's."""


def operator(role: OperatorRole = OperatorRole.WRITE) -> OperatorContext:
    """A test double of the operator stage that records a benchmark run;
    admission is the tenancy manager's."""
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="provisioner@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(role),
    )


def make_trials(
    candidate: Sequence[int],
    baseline: Sequence[int],
    *,
    station: str = "station-1",
    order: Sequence[Arm] | None = None,
    cost_micros: int = 120_000,
) -> BenchmarkTrials:
    """Trials of both arms, each judged with as many links of its chain
    broken as given (0 is a whole chain), run in `order` (the schedule's
    interleaving unless a case names its own), one minute apart."""
    broken = {Arm.CANDIDATE: list(candidate), Arm.BASELINE: list(baseline)}
    start = utcnow()
    trials = []
    for at, arm in enumerate(order or schedule(len(candidate))):
        session = new_id()
        trials.append(
            Trial(
                arm=arm,
                session_id=session,
                station=station,
                started_at=start + timedelta(minutes=at),
                verdict=judged(session, broken[arm].pop(0)),
                cost_micros=cost_micros,
            )
        )
    return BenchmarkTrials(
        scenario="orders-vanish", candidate=CANDIDATE, baseline=BASELINE, trials=tuple(trials)
    )


def judged(session_id: UUID, broken: int) -> AcceptanceVerdict:
    """A verdict on a session's chain with its first `broken` links broken."""
    return AcceptanceVerdict(
        id=new_id(),
        created_at=utcnow(),
        scenario="orders-vanish",
        session_id=session_id,
        head="c0ffee",
        breaks=tuple(Break(link=link, reason="it is missing") for link in list(Link)[:broken]),
    )


def make_benchmark(run: BenchmarkTrials | None = None, minutes: int = 0) -> Benchmark:
    run = run or make_trials([0, 0], [0, 7])
    candidate = arm_result(run.trials, Arm.CANDIDATE)
    baseline = arm_result(run.trials, Arm.BASELINE)
    return Benchmark(
        **dict(run),
        id=new_id(),
        created_at=utcnow() + timedelta(minutes=minutes),
        candidate_result=candidate,
        baseline_result=baseline,
        regressed=regressed(candidate, baseline),
        recorded_by=new_id(),
    )


class BenchmarkStorageContract:
    @pytest.fixture
    def storage(self) -> BenchmarkStorageInterface:
        raise NotImplementedError

    async def test_a_benchmark_is_read_back_whole(self, storage: BenchmarkStorageInterface) -> None:
        benchmark = make_benchmark()
        assert await storage.create_benchmark(benchmark)
        assert await storage.read_benchmark(benchmark.id) == benchmark
        assert await storage.read_benchmark(new_id()) is None

    async def test_a_benchmark_is_written_once(self, storage: BenchmarkStorageInterface) -> None:
        benchmark = make_benchmark()
        assert await storage.create_benchmark(benchmark)
        changed = benchmark.model_copy(update={"regressed": not benchmark.regressed})
        assert not await storage.create_benchmark(changed)
        assert await storage.read_benchmark(benchmark.id) == benchmark

    async def test_a_scenarios_history_is_newest_first(
        self, storage: BenchmarkStorageInterface
    ) -> None:
        older, newer = make_benchmark(minutes=-5), make_benchmark(minutes=-1)
        other = make_benchmark(make_trials([0], [0]).model_copy(update={"scenario": "other"}))
        for benchmark in (older, newer, other):
            assert await storage.create_benchmark(benchmark)
        history = await storage.read_history("orders-vanish", 10)
        ours = [found.id for found in history if found.id in {older.id, newer.id}]
        assert ours == [newer.id, older.id]
        assert other.id not in {found.id for found in history}
        assert len(await storage.read_history("orders-vanish", 1)) == 1
