"""Statistical evidence: a rate is never shown to be zero, only bounded.
What a policy declares before the trials, and the claim the trials earn."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from acme.om.base import Platform
from acme.om.evidence.types.record import NAME, VERSION


class Bound(StrEnum):
    """How a one-sided upper bound on a rate is computed. There is no normal
    approximation: at zero failures it collapses to zero. An exact or a
    Wilson bound holds after a count of trials fixed before them; the
    sequential one holds wherever its test stops, so it may stop early."""

    EXACT = "exact"  # Clopper-Pearson
    WILSON = "wilson"  # the Wilson score interval
    SEQUENTIAL = "sequential"  # a likelihood-ratio test valid under optional stopping


class AbortRule(StrEnum):
    """How a trial an abort ended is classified. It is never dropped."""

    FAILURE = "failure"  # it counts as a failure
    INCONCLUSIVE = "inconclusive"  # any such trial leaves the claim without a conclusion


class RateRule(Platform):
    """A rate a check's failures must stay under, declared before its
    trials: the most failures it may show as a rate, the confidence of the
    bound, how the bound is computed, the trials to run, and the rule for a
    trial an abort ended. An exact or a Wilson bound runs `trials`
    trials, every one of them. A sequential test runs at most `trials`, and
    stops at the first trial where its bound falls under `max_rate`, or
    where no trial left could bring it there; `alternative` is the rate it
    is built to tell apart from `max_rate`, the lower the longer it runs."""

    max_rate: float = Field(gt=0, lt=1)
    confidence: float = Field(ge=0.5, lt=1)
    bound: Bound = Bound.EXACT
    trials: int = Field(ge=1, le=100_000)
    aborted: AbortRule = AbortRule.FAILURE
    alternative: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def _a_test_names_its_alternative(self) -> Self:
        sequential = self.bound is Bound.SEQUENTIAL
        if sequential != (self.alternative is not None):
            raise ValueError("a sequential test names its alternative rate, and only one")
        if self.alternative is not None and self.alternative >= self.max_rate:
            raise ValueError("a sequential test's alternative rate lies under its max_rate")
        return self


class RateClaim(Platform):
    """What a check's trials at one version show: never a rate, only the
    bound under it. `upper` is above zero for any count of trials, so a run
    with no failure still reports a rate that may be there. `trials`
    counts every trial at the version; `failures` counts each aborted one
    the rule made a failure."""

    check: str = Field(pattern=NAME)
    version: str = Field(pattern=VERSION)
    trials: int = Field(ge=1)
    failures: int = Field(ge=0)
    aborted: int = Field(ge=0)
    confidence: float = Field(gt=0, lt=1)
    bound: Bound
    upper: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _counts(self) -> Self:
        if self.failures > self.trials or self.aborted > self.trials:
            raise ValueError("a claim counts no more failures or aborts than trials")
        return self

    def render(self) -> str:
        """The claim as a report says it: a bound, with the counts and the
        confidence behind it, and never a rate of its own."""
        return (
            f"the failure rate is at most {self.upper:.2%} "
            f"({self.failures} failures in {self.trials} trials at {self.version}, "
            f"one-sided {self.confidence * 100:g}%, {self.bound.value} bound)"
        )
