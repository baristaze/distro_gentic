"""Who claims work through the gateway: a host or a daemon outside the
platform's processes. The gateway resolves one from the caller's own
credential; nothing in the call names a lane or a kind."""

from enum import StrEnum
from uuid import UUID

from pydantic import model_validator

from acme.om.base import Platform


class ClaimantKind(StrEnum):
    HOST = "host"  # prepares workspaces and runs commands in them
    DAEMON = "daemon"  # serves the stations of one lab


class Claimant(Platform):
    """A claimant's identity, as its credential says it. `org_id` is the
    tenant whose wall it sits in; None is a host of the platform's own
    cloud pool, which serves every tenant. A host names its pool and a
    daemon its lab, and a daemon always sits in a tenant's wall."""

    kind: ClaimantKind
    id: UUID
    org_id: UUID | None = None
    pool_id: UUID | None = None
    lab_id: UUID | None = None

    @model_validator(mode="after")
    def _names_where_it_serves(self) -> Claimant:
        hosting = self.kind is ClaimantKind.HOST
        if hosting != (self.pool_id is not None) or hosting == (self.lab_id is not None):
            raise ValueError("a host names its pool alone, and a daemon its lab")
        if not hosting and self.org_id is None:
            raise ValueError("a daemon sits in a tenant's wall")
        return self

    @property
    def worker_id(self) -> str:
        """The name its claims carry, for an operator who reads the row."""
        return f"{self.kind.value}:{self.id}"
