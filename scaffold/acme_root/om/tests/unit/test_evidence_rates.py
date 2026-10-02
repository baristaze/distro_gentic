"""A rate is never shown to be zero, only bounded: a one-sided exact or
Wilson bound at a declared confidence, never a normal approximation,
which collapses at zero failures. The trial count, or a sequential test
valid under optional stopping, is declared before the trials, and trials
stop only where that rule says."""

import math

import pytest
from contracts.evidence_storage import make_record

from acme.om.base import new_id
from acme.om.evidence.rates import (
    corrected,
    exact_upper,
    rate_claim,
    sequential_upper,
    sequential_verdict,
    stops_at,
    upper_bound,
    wilson_upper,
)
from acme.om.evidence.types.rate import Bound, RateClaim, RateRule
from acme.om.evidence.types.record import RunOutcome

ALTERNATIVE = 0.001
"""The rate a sequential bound in these cases is built to tell apart; the
fixed bounds take no alternative."""


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
        claim = rate_claim("trials", "c0ffee", clean, 0.95, bound, ALTERNATIVE)
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
    assert {bound.value for bound in Bound} == {"exact", "wilson", "sequential"}
    for bound in Bound:
        assert upper_bound(0, 300, 0.95, bound, ALTERNATIVE) > 0


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
        assert upper_bound(2, 100, 0.99, bound, ALTERNATIVE) > upper_bound(
            2, 100, 0.95, bound, ALTERNATIVE
        )
        assert upper_bound(0, 1000, 0.95, bound, ALTERNATIVE) < upper_bound(
            0, 100, 0.95, bound, ALTERNATIVE
        )


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


# The sequential test, and the fixed count it is the alternative to.

SEQUENTIAL = RateRule(
    max_rate=0.1, confidence=0.95, bound=Bound.SEQUENTIAL, trials=200, alternative=0.02
)
FIXED = RateRule(max_rate=0.1, confidence=0.95, trials=50)


def test_a_sequential_test_stops_only_where_its_rule_allows() -> None:
    # Clean trials: its bound falls under 10% at trial 36, and not before.
    assert [stops_at(SEQUENTIAL, [False] * n, 0.95) for n in (1, 20, 35)] == [None] * 3
    assert stops_at(SEQUENTIAL, [False] * 36, 0.95) == 36
    assert sequential_upper(0, 36, 0.95, 0.02) <= 0.1 < sequential_upper(0, 35, 0.95, 0.02)
    # More trials than it ran change nothing: it stopped at 36.
    assert stops_at(SEQUENTIAL, [False] * 80, 0.95) == 36
    # An early failure moves the stop later; it never stops on a guess.
    late = stops_at(SEQUENTIAL, [True] + [False] * 199, 0.95)
    assert late is not None and late > 36
    assert sequential_verdict(SEQUENTIAL, 1, late, 0.95) is True
    assert all(sequential_verdict(SEQUENTIAL, 1, n, 0.95) is None for n in range(37, late))
    # It stops for futility only where no trial left could bound the rate.
    short = SEQUENTIAL.model_copy(update={"trials": 40})
    assert stops_at(short, [True], 0.95) == 1
    assert sequential_verdict(short, 1, 1, 0.95) is False
    assert stops_at(short, [False, True], 0.95) == 2
    # And at its most trials, whatever they showed.
    assert sequential_verdict(SEQUENTIAL, 15, 200, 0.95) is False


def test_a_fixed_count_never_stops_early() -> None:
    # Hopeless or spotless, a fixed count runs every trial it declared.
    for shown in ([True] * 10, [False] * 49, [False] * 36):
        assert stops_at(FIXED, shown, 0.95) is None
    assert stops_at(FIXED, [False] * 50, 0.95) == 50
    assert stops_at(FIXED, [True] * 50, 0.95) == 50


def test_the_sequential_test_holds_its_confidence_however_it_is_watched() -> None:
    """At a true rate of exactly the declared 10%, the chance the test ever
    bounds the rate under it is at most 5%, computed exactly over every path
    it can take. Peeking at the exact bound after each trial, and stopping
    as soon as it holds, claims the same rate more than three times as
    often: a rate claimed by peeking."""
    rate = 0.1
    alive: dict[int, float] = {0: 1.0}
    bounded = 0.0
    for count in range(1, SEQUENTIAL.trials + 1):
        after: dict[int, float] = {}
        for failures, chance in alive.items():
            for seen, odds in ((failures + 1, rate), (failures, 1 - rate)):
                verdict = sequential_verdict(SEQUENTIAL, seen, count, 0.95)
                if verdict is True:
                    bounded += chance * odds
                elif verdict is None:
                    after[seen] = after.get(seen, 0.0) + chance * odds
        alive = after
    assert alive == {}, "every path stops by the most trials declared"
    assert bounded <= 0.05

    peeked = 0.0
    alive = {0: 1.0}
    for count in range(1, SEQUENTIAL.trials + 1):
        # The most failures at this count whose exact bound holds: the bound
        # grows with failures, so every count at or under it holds too.
        most = -1
        while exact_upper(most + 1, count, 0.95) <= rate:
            most += 1
        after = {}
        for failures, chance in alive.items():
            for seen, odds in ((failures + 1, rate), (failures, 1 - rate)):
                if seen <= most:
                    peeked += chance * odds
                else:
                    after[seen] = after.get(seen, 0.0) + chance * odds
        alive = after
    assert peeked > 3 * 0.05


@pytest.mark.parametrize(
    "fields",
    [
        {"bound": Bound.SEQUENTIAL},  # no alternative
        {"bound": Bound.SEQUENTIAL, "alternative": 0.2},  # not under max_rate
        {"bound": Bound.EXACT, "alternative": 0.01},  # a fixed count takes none
    ],
)
def test_a_sequential_test_names_an_alternative_under_its_rate(fields: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RateRule.model_validate({"max_rate": 0.1, "confidence": 0.95, "trials": 100, **fields})
