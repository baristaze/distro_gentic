"""Pure rules of statistical evidence: a one-sided upper bound on a rate,
exact or Wilson, never a normal approximation, which collapses at zero
failures; the sequential test, valid under optional stopping, and where a
declared rule lets trials stop; the claim a check's trials earn; and the
correction a claim across many comparisons takes. Values in, values out."""

import math
from collections.abc import Sequence
from statistics import NormalDist

from acme.om.evidence.types.rate import Bound, RateClaim, RateRule
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


def sequential_upper(failures: int, trials: int, confidence: float, alternative: float) -> float:
    """The sequential test's bound, valid wherever the trials stop: the
    lowest rate `p` the likelihood ratio of `alternative` against `p`
    rejects, at `1 / (1 - confidence)`. For any true rate at or above `p`
    that ratio is a martingale of mean one, so by Ville's inequality it ever
    reaches the threshold with a chance of at most `1 - confidence`, however
    the trials are watched and stopped. Above the larger of `alternative` and
    the observed rate the ratio grows with `p`, so the bound is one root."""
    _counts(failures, trials, confidence)
    if not 0 < alternative < 1:
        raise ValueError("an alternative rate lies strictly between 0 and 1")
    threshold = math.log(1 / (1 - confidence))
    if failures >= trials or _log_ratio(failures, trials, alternative, 1 - PRECISION) < threshold:
        return 1.0
    low, high = max(alternative, failures / trials), 1 - PRECISION
    while high - low > PRECISION:
        middle = (low + high) / 2
        if _log_ratio(failures, trials, alternative, middle) >= threshold:
            high = middle
        else:
            low = middle
    return high


def upper_bound(
    failures: int,
    trials: int,
    confidence: float,
    bound: Bound,
    alternative: float | None = None,
) -> float:
    if bound is Bound.SEQUENTIAL:
        if alternative is None:
            raise ValueError("a sequential bound needs the alternative its test declared")
        return sequential_upper(failures, trials, confidence, alternative)
    if bound is Bound.WILSON:
        return wilson_upper(failures, trials, confidence)
    return exact_upper(failures, trials, confidence)


def stops_at(rule: RateRule, failed: Sequence[bool], confidence: float) -> int | None:
    """Where the declared rule ends a run of trials, `failed` in the order
    they ran: the count of trials at which it stops, or None while it runs
    on. A fixed count stops at its count and nowhere sooner, whatever the
    trials show. A sequential test stops where `sequential_verdict` first
    gives one. Nothing else stops either one: a run that stops sooner, or
    goes on past, is not the test declared."""
    if rule.bound is not Bound.SEQUENTIAL:
        return rule.trials if len(failed) >= rule.trials else None
    failures = 0
    for count, failure in enumerate(failed[: rule.trials], start=1):
        failures += failure
        if sequential_verdict(rule, failures, count, confidence) is not None:
            return count
    return None


def sequential_verdict(rule: RateRule, failures: int, count: int, confidence: float) -> bool | None:
    """What a sequential test says after `count` trials with `failures`
    among them, had it not stopped sooner: True where its bound has fallen
    under the declared rate, False where no trial left could bring it there
    or its most trials have run, and None where it runs on."""
    if rule.alternative is None:
        raise ValueError("a sequential test declares its alternative rate")
    threshold = math.log(1 / (1 - confidence))
    ratio = _log_ratio(failures, count, rule.alternative, rule.max_rate)
    if ratio >= threshold:
        return True
    passing = math.log1p(-rule.alternative) - math.log1p(-rule.max_rate)
    if count >= rule.trials or ratio + (rule.trials - count) * passing < threshold:
        return False
    return None


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
    alternative: float | None = None,
) -> RateClaim:
    """What every trial of a check at a version shows. A trial that did not
    pass, or passed no case, is a failure; one an abort ended counts as
    one too, under the rule that lets it be counted at all. No trial is
    dropped. A sequential bound takes the alternative its test declared."""
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
        upper=upper_bound(failures, len(trials), confidence, bound, alternative),
    )


def _counts(failures: int, trials: int, confidence: float) -> None:
    if trials < 1 or not 0 <= failures <= trials:
        raise ValueError("a bound needs at least one trial and a count of failures among them")
    if not 0 < confidence < 1:
        raise ValueError("a confidence lies strictly between 0 and 1")


def _log_ratio(failures: int, trials: int, alternative: float, rate: float) -> float:
    """The log of the likelihood of the trials under `alternative` over their
    likelihood under `rate`."""
    passes = trials - failures
    return failures * (math.log(alternative) - math.log(rate)) + passes * (
        math.log1p(-alternative) - math.log1p(-rate)
    )


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
