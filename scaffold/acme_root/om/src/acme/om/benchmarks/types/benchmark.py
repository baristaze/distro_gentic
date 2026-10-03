"""A benchmark: what one scenario showed of a candidate against a
baseline, each arm pinned to the agent kind, its version, and the fill
set that produced it. Its trials are preserved, each with its acceptance
verdict, its judged score, and its cost, and a candidate that scores
under its baseline is flagged. Written once, and never changed."""

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Created, Identifiable, Platform
from acme.om.evidence.types.acceptance import AcceptanceVerdict
from acme.om.evidence.types.record import NAME
from acme.om.models.types.fill import RoleFill


class Arm(StrEnum):
    CANDIDATE = "candidate"  # what is being measured: a new kind version, or a new fill set
    BASELINE = "baseline"  # what it is measured against: what runs today


class Contender(Platform):
    """What an arm's sessions run: the agent kind, its version, and the fill
    set, each model role's fill."""

    kind: str = Field(pattern=NAME)
    kind_version: int = Field(ge=1)
    fills: tuple[RoleFill, ...] = Field(min_length=1, max_length=50)


class Trial(Platform):
    """One preserved run of the scenario: the arm it ran for, its session,
    the executor it ran on and when it started, the acceptance verdict that
    judged it, kept whole with the hidden suite's runs, and its cost in
    millionths of a dollar. Its score and whether it passed are the
    verdict's, never a caller's."""

    arm: Arm
    session_id: UUID
    executor: str = Field(min_length=1, max_length=200)
    started_at: datetime
    verdict: AcceptanceVerdict
    cost_micros: int = Field(ge=0)

    @model_validator(mode="after")
    def _its_sessions_verdict(self) -> Self:
        if self.verdict.session_id != self.session_id:
            raise ValueError("a trial keeps the verdict of its own session")
        return self

    @property
    def passed(self) -> bool:
        return self.verdict.passed

    @property
    def score(self) -> float:
        return self.verdict.score


class BenchmarkTrials(Platform):
    """What a benchmark run hands in: the scenario, both arms, and every
    trial of both, in any order."""

    scenario: str = Field(pattern=NAME)
    candidate: Contender
    baseline: Contender
    trials: tuple[Trial, ...] = Field(min_length=2, max_length=10_000)


class ArmResult(Platform):
    """What one arm's trials showed: their mean score, how many passed, and
    what they cost together."""

    trials: int = Field(ge=1)
    passed: int = Field(ge=0)
    score: float = Field(ge=0, le=1)
    cost_micros: int = Field(ge=0)


class Benchmark(BenchmarkTrials, Identifiable, Created):
    """A recorded benchmark. The arms' results and the flag are the
    manager's, computed from the trials: `regressed` is set when the
    candidate scored under its baseline."""

    candidate_result: ArmResult
    baseline_result: ArmResult
    regressed: bool
    recorded_by: UUID  # the operator's identity
