"""Statistical evidence: a rate is never shown to be zero, only bounded.
What a policy declares before the trials, and the claim the trials earn."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from acme.om.base import Platform
from acme.om.evidence.types.record import NAME, VERSION


class Bound(StrEnum):
    """How a one-sided upper bound on a rate is computed. There is no normal
    approximation: at zero failures it collapses to zero."""

    EXACT = "exact"  # Clopper-Pearson
    WILSON = "wilson"  # the Wilson score interval


class AbortRule(StrEnum):
    """How a trial a safety stop ended is classified. It is never dropped."""

    FAILURE = "failure"  # it counts as a failure
    INCONCLUSIVE = "inconclusive"  # any such trial leaves the claim without a conclusion


class RateRule(Platform):
    """A rate a check's failures must stay under, declared before its
    trials: the most failures it may show as a rate, the confidence of the
    bound, how the bound is computed, the trials to run, and the rule for a
    trial a safety stop ended."""

    max_rate: float = Field(gt=0, lt=1)
    confidence: float = Field(ge=0.5, lt=1)
    bound: Bound = Bound.EXACT
    trials: int = Field(ge=1, le=100_000)
    aborted: AbortRule = AbortRule.FAILURE


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
