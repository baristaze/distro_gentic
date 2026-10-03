"""Who claims work through the gateway: a host outside the platform's
processes. The gateway resolves one from the caller's own credential;
nothing in the call names a lane or a kind."""

from enum import StrEnum
from uuid import UUID

from acme.om.base import Platform


class ClaimantKind(StrEnum):
    HOST = "host"  # prepares workspaces and runs commands in them


class Claimant(Platform):
    """A claimant's identity, as its credential says it. `org_id` is the
    tenant whose wall it sits in; None is a host of the platform's own
    cloud pool, which serves every tenant. A host names its pool."""

    kind: ClaimantKind
    id: UUID
    org_id: UUID | None = None
    pool_id: UUID

    @property
    def worker_id(self) -> str:
        """The name its claims carry, for an operator who reads the row."""
        return f"{self.kind.value}:{self.id}"
