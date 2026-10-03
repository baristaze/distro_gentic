"""Who claims work through the gateway: a machine outside the platform's
processes, such as a workspace host or a product's own. The gateway
resolves one from the caller's own credential; nothing in the call names a
lane or a kind."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Platform


class Claimant(Platform):
    """A claimant's identity, as its credential says it: its kind, a name
    the claimant kinds' registry knows (`placement.kinds`), its id, the
    tenant whose wall it sits in, and the pool it serves. `org_id` None is
    a claimant of the platform's own pool, which serves every tenant."""

    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    id: UUID
    org_id: UUID | None = None
    pool_id: UUID

    @property
    def worker_id(self) -> str:
        """The name its claims carry, for an operator who reads the row."""
        return f"{self.kind}:{self.id}"


class ReportOutcome(StrEnum):
    DONE = "done"  # the work is done: the item completes
    FAILED = "failed"  # the work failed: the item is retried until its attempts are spent


class ClaimantReport(Platform):
    """What a claimant answers for an item it holds: done, or failed with
    why, under the claim token its claim was handed. It comes from outside
    the platform's processes, so it is held to its shape before anything
    reads it: a failure names its reason, within bounds, and a success
    names none."""

    item_id: UUID
    claim_token: UUID
    outcome: ReportOutcome
    error: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _a_failure_says_why(self) -> Self:
        if (self.outcome is ReportOutcome.FAILED) != (self.error is not None):
            raise ValueError("a failure names its reason, and a success names none")
        return self
