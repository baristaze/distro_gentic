"""The wait after a failure a claimant outlasts: an answer the platform
could not serve, a 429, or the wire. It doubles per failure in a row, half
of it jitter, so claimants that failed together do not return together;
it is longer when the server asked for longer, and never past the cap."""

import random
from collections.abc import Callable

BACKOFF_FIRST_SECONDS = 1.0
"""The wait after a first failure."""

BACKOFF_MAX_SECONDS = 120.0
"""However many failures in a row, no wait is longer, a 429's ask included."""

MOST_FAILURES_COUNTED = 32
"""Failures in a row past this many wait no longer: every cap is reached
well before, and the doubling never grows past what a float holds."""


class Backoff:
    """`most` is the cap. A caller that asks again sooner than
    `BACKOFF_MAX_SECONDS` names its own."""

    def __init__(
        self, jitter: Callable[[], float] = random.random, most: float = BACKOFF_MAX_SECONDS
    ) -> None:
        self._jitter = jitter
        self._most = most
        self._failures = 0

    def failed(self, server_asked: float | None) -> float:
        """The wait after one more failure in a row."""
        self._failures = min(self._failures + 1, MOST_FAILURES_COUNTED)
        full = min(BACKOFF_FIRST_SECONDS * 2 ** (self._failures - 1), self._most)
        curve = full / 2 + (full / 2) * self._jitter()
        return min(max(curve, server_asked or 0.0), self._most)

    def reset(self) -> None:
        """A call answered: the next failure waits the first wait again."""
        self._failures = 0
