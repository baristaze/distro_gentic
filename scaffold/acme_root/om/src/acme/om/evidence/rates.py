"""Pure rules of statistical evidence: a one-sided upper bound on a rate,
exact or Wilson, never a normal approximation, which collapses at zero
failures; the claim a check's trials earn; and the correction a claim
across many comparisons takes. Values in, values out."""

import math
from collections.abc import Sequence
from statistics import NormalDist

from acme.om.evidence.types.rate import Bound, RateClaim
from acme.om.evidence.types.record import ExecutionRecord, RunOutcome

PRECISION = 1e-12
"""How close the exact bound's search comes to the bound."""


def exact_upper(failures: int, trials: int, confidence: float) -> float:
    """The one-sided Clopper-Pearson upper bound: the rate at which seeing
    `failures` or fewer in `trials` is as unlikely as `1 - confidence`. At
    zero failures it is `1 - (1 - confidence) ** (1 / trials)`: about 3/n
    at 95%."""
    _counts(failures, trials, confidence)
    if failures >= trials:
        return 1.0
    alpha = 1 - confidence
    if failures == 0:
        return 1 - alpha ** (1 / trials)
    low, high = failures / trials, 1.0
    while high - low > PRECISION:
        middle = (low + high) / 2
        if _at_most(failures, trials, middle) > alpha:
            low = middle
        else:
            high = middle
    return high


def wilson_upper(failures: int, trials: int, confidence: float) -> float:
    """The one-sided Wilson score upper bound. At zero failures it is
    `z² / (n + z²)`, above zero for any count of trials."""
    _counts(failures, trials, confidence)
    z = NormalDist().inv_cdf(confidence)
    rate = failures / trials
    spread = z * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials))
    upper = (rate + z * z / (2 * trials) + spread) / (1 + z * z / trials)
    return min(upper, 1.0)


def upper_bound(failures: int, trials: int, confidence: float, bound: Bound) -> float:
    if bound is Bound.WILSON:
        return wilson_upper(failures, trials, confidence)
    return exact_upper(failures, trials, confidence)


def corrected(confidence: float, comparisons: int) -> float:
    """The confidence each of `comparisons` claims judged together takes so
    the family holds at `confidence`: Bonferroni's correction."""
    if comparisons <= 1:
        return confidence
    return 1 - (1 - confidence) / comparisons


def rate_claim(
    check: str,
    version: str,
    trials: Sequence[ExecutionRecord],
    confidence: float,
    bound: Bound,
) -> RateClaim:
    """What every trial of a check at a version shows. A trial that did not
    pass, or passed no case, is a failure; one a safety stop ended counts as
    one too, under the rule that lets it be counted at all. No trial is
    dropped."""
    failures = sum(1 for record in trials if not record.passing)
    aborted = sum(1 for record in trials if record.outcome is RunOutcome.ABORTED)
    return RateClaim(
        check=check,
        version=version,
        trials=len(trials),
        failures=failures,
        aborted=aborted,
        confidence=confidence,
        bound=bound,
        upper=upper_bound(failures, len(trials), confidence, bound),
    )


def _counts(failures: int, trials: int, confidence: float) -> None:
    if trials < 1 or not 0 <= failures <= trials:
        raise ValueError("a bound needs at least one trial and a count of failures among them")
    if not 0 < confidence < 1:
        raise ValueError("a confidence lies strictly between 0 and 1")


def _at_most(failures: int, trials: int, rate: float) -> float:
    """P(X <= failures) for X ~ Binomial(trials, rate), summed in log space
    so a large count of trials neither underflows nor overflows."""
    if rate <= 0:
        return 1.0
    if rate >= 1:
        return 0.0
    log_rate, log_rest = math.log(rate), math.log1p(-rate)
    term = trials * log_rest  # log P(X = 0)
    terms = [term]
    for k in range(failures):
        term += math.log(trials - k) - math.log(k + 1) + log_rate - log_rest
        terms.append(term)
    top = max(terms)
    return math.exp(top) * math.fsum(math.exp(found - top) for found in terms)
