"""A lease as a claimant times it. A renewal may keep two things: a hold
the claimant's own kind keeps on something of its own, and the platform's
claim on the item it holds, which may run for less time.

The hold is the client's lease clock (`acme.client.leases`), so it counts
from the moment the claimant asked, and an answer's travel time only
shortens it. The kit keeps only the claim's part beside it: the claimant
renews at half the shorter of the two, and the claim never lapses under
its work while the platform answers. A claimant that holds the claim alone
gives one length. A kind that acts on a resource it holds guards it with
the client's `Fence`."""

from dataclasses import dataclass

from acme.client.leases import MIN_RENEW_SECONDS
from acme.client.leases import LeaseClock as HoldClock


@dataclass
class LeaseClock:
    hold: HoldClock
    """The hold's time: when it ends, and whether a renewal was refused."""
    claim_deadline: float
    """When the item's claim lapses unless a renewal extends it."""
    renew_at: float
    """When the next renewal is asked."""
    ended: str | None = None
    """What ended the hold, once an answer said so: the work stops."""

    @classmethod
    def started(
        cls, asked: float, seconds: float, claim_seconds: float | None = None
    ) -> LeaseClock:
        lease = cls(hold=HoldClock.granted(asked, seconds), claim_deadline=asked, renew_at=asked)
        lease._claimed(asked, seconds if claim_seconds is None else claim_seconds)
        return lease

    @property
    def deadline(self) -> float:
        """When the hold ends unless a renewal extends it."""
        return self.hold.deadline

    @property
    def refused(self) -> bool:
        """The platform refused the claimant's credential: the work stops."""
        return self.hold.refused

    @refused.setter
    def refused(self, refused: bool) -> None:
        self.hold.refused = refused

    def renewed(self, asked: float, seconds: float, claim_seconds: float | None = None) -> None:
        """Renewed at half the shorter of the hold and the claim again."""
        self.hold.renewed(asked, seconds)
        self._claimed(asked, seconds if claim_seconds is None else claim_seconds)

    def unanswered(self, asked: float, wait: float | None = None) -> None:
        """The deadline holds, and the renewal is asked again sooner, so a
        platform that comes back in time keeps the work going: before the
        claim lapses while it holds, then before the hold ends. A wait the
        platform named, as a 429 does, is waited out, though never past the
        last second before that horizon."""
        self.hold.unanswered(asked)
        claim_holds = asked < self.claim_deadline
        if wait is None:
            self.renew_at = self.hold.renew_at
            if claim_holds:
                self.renew_at = min(self.renew_at, _half_left(asked, self.claim_deadline))
            return
        horizon = min(self.claim_deadline, self.deadline) if claim_holds else self.deadline
        again = min(wait, horizon - asked - MIN_RENEW_SECONDS)
        self.renew_at = asked + max(MIN_RENEW_SECONDS, again)

    def out(self, now: float) -> bool:
        return self.ended is not None or self.hold.lost(now)

    def _claimed(self, asked: float, claim_seconds: float) -> None:
        """The claim runs `claim_seconds` from `asked`, and the next renewal
        comes at the hold's time or the claim's, whichever is first."""
        self.claim_deadline = asked + claim_seconds
        self.renew_at = min(self.hold.renew_at, _half_left(asked, self.claim_deadline))


def _half_left(now: float, until: float) -> float:
    """Half of what is left before `until`, and never sooner than the
    client's least wait."""
    return now + max(MIN_RENEW_SECONDS, (until - now) / 2)
