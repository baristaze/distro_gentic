"""A rate is never shown to be zero, only bounded: a one-sided exact or
Wilson bound at a declared confidence, never a normal approximation,
which collapses at zero failures."""

import math

import pytest
from contracts.evidence_storage import make_record

from acme.om.base import new_id
from acme.om.evidence.rates import (
    corrected,
    exact_upper,
    rate_claim,
    upper_bound,
    wilson_upper,
)
from acme.om.evidence.types.rate import Bound, RateClaim
from acme.om.evidence.types.record import RunOutcome


def test_zero_failures_in_300_trials_bound_the_rate_at_about_one_percent() -> None:
    """The bound a policy reads: 0 failures in 300 trials, one-sided 95%."""
    exact = exact_upper(0, 300, 0.95)
    wilson = wilson_upper(0, 300, 0.95)
    assert exact == pytest.approx(1 - 0.05 ** (1 / 300))
    assert exact == pytest.approx(0.00994, abs=1e-5)
    assert wilson == pytest.approx(0.00894, abs=1e-5)
    for bound in (exact, wilson):
        assert 0.008 < bound < 0.011, "about 1%, about 3/n"


def test_a_zero_failure_run_never_reports_a_rate_of_zero() -> None:
    session = new_id()
    clean = [make_record(session, check="trials") for _ in range(300)]
    for bound in Bound:
        claim = rate_claim("trials", "c0ffee", clean, 0.95, bound)
        assert claim.failures == 0 and claim.trials == 300
        assert claim.upper > 0
        assert claim.render().startswith("the failure rate is at most ")
        assert "at most 0.00%" not in claim.render()
        assert not hasattr(claim, "rate"), "a claim carries a bound, never a rate of its own"
    with pytest.raises(ValueError):
        RateClaim(
            check="trials",
            version="c0ffee",
            trials=300,
            failures=0,
            aborted=0,
            confidence=0.95,
            bound=Bound.EXACT,
            upper=0.0,
        )


def test_the_normal_approximation_is_no_bound_here() -> None:
    """At zero failures the normal approximation's interval is [0, 0]: it
    would claim the rate is zero. No bound offered is one."""
    rate = 0 / 300
    normal = rate + 1.645 * math.sqrt(rate * (1 - rate) / 300)
    assert normal == 0.0
    assert {bound.value for bound in Bound} == {"exact", "wilson"}
    for bound in Bound:
        assert upper_bound(0, 300, 0.95, bound) > 0


@pytest.mark.parametrize(
    ("failures", "trials", "expected"),
    [
        # One-sided 95% Clopper-Pearson upper bounds, as tables give them.
        (3, 300, 0.02564),
        (5, 10, 0.77756),
        (1, 20, 0.21611),
        (10, 10, 1.0),
    ],
)
def test_the_exact_bound_matches_its_tables(failures: int, trials: int, expected: float) -> None:
    assert exact_upper(failures, trials, 0.95) == pytest.approx(expected, abs=5e-5)


def test_a_bound_grows_with_confidence_and_shrinks_with_trials() -> None:
    for bound in Bound:
        assert upper_bound(2, 100, 0.99, bound) > upper_bound(2, 100, 0.95, bound)
        assert upper_bound(0, 1000, 0.95, bound) < upper_bound(0, 100, 0.95, bound)


def test_a_bound_needs_trials_and_a_confidence() -> None:
    for bad in ((0, 0, 0.95), (3, 2, 0.95), (0, 10, 1.0), (0, 10, 0.0)):
        with pytest.raises(ValueError):
            exact_upper(*bad)
        with pytest.raises(ValueError):
            wilson_upper(*bad)


def test_every_trial_counts_and_an_abort_is_a_failure() -> None:
    session = new_id()
    runs = [
        make_record(session, check="trials"),
        make_record(session, check="trials", outcome=RunOutcome.FAILED),
        make_record(session, check="trials", outcome=RunOutcome.ERRORED),
        make_record(session, check="trials", outcome=RunOutcome.ABORTED),
    ]
    claim = rate_claim("trials", "c0ffee", runs, 0.95, Bound.EXACT)
    assert (claim.trials, claim.failures, claim.aborted) == (4, 3, 1)


def test_many_comparisons_correct_the_confidence_of_each() -> None:
    assert corrected(0.95, 1) == 0.95
    assert corrected(0.95, 2) == pytest.approx(0.975)
    assert corrected(0.95, 10) == pytest.approx(0.995)
