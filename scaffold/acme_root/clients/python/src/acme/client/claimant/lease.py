"""A lease as a claimant times it: on its own monotonic clock, from the
moment it asked, so a wall-clock jump never stretches or cuts a lease,
and an answer's travel time only shortens it.

A renewal may keep two things: a hold the claimant's own kind keeps on
something of its own, and the platform's claim on the item it holds,
which may run for less time. So the claimant renews at half the shorter
of the two, and the claim never lapses under its work while the platform
answers. A claimant that holds the claim alone gives one length."""

from dataclasses import dataclass

RETRY_FLOOR_SECONDS = 1.0
"""The least wait before a renewal is asked, or asked again."""


@dataclass
class LeaseClock:
    deadline: float
    """When the hold ends unless a renewal extends it."""
    renew_at: float
    claim_deadline: float
    """When the item's claim lapses unless a renewal extends it."""
    ended: str | None = None
    """What ended the hold, once an answer said so: the work stops."""
    refused: bool = False
    """The platform refused the claimant's credential: the work stops."""

    @classmethod
    def started(
        cls, asked: float, seconds: float, claim_seconds: float | None = None
    ) -> LeaseClock:
        lease = cls(deadline=asked, renew_at=asked, claim_deadline=asked)
        lease.renewed(asked, seconds, claim_seconds)
        return lease

    def renewed(self, asked: float, seconds: float, claim_seconds: float | None = None) -> None:
        """Renewed at half the shorter of the hold and the claim again."""
        claim = seconds if claim_seconds is None else claim_seconds
        self.deadline = asked + seconds
        self.claim_deadline = asked + claim
        self.renew_at = asked + max(RETRY_FLOOR_SECONDS, min(seconds, claim) / 2)

    def unanswered(self, asked: float, wait: float | None = None) -> None:
        """The deadline holds, and the renewal is asked again sooner, so a
        platform that comes back in time keeps the work going: before the
        claim lapses while it holds, then before the hold ends. A wait the
        platform named, as a 429 does, is waited out, though never past the
        last second before that horizon."""
        horizon = self.claim_deadline if asked < self.claim_deadline else self.deadline
        left = min(horizon, self.deadline) - asked
        again = left / 2 if wait is None else min(wait, left - RETRY_FLOOR_SECONDS)
        self.renew_at = asked + max(RETRY_FLOOR_SECONDS, again)

    def out(self, now: float) -> bool:
        return self.refused or self.ended is not None or now >= self.deadline
