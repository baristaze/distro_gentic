"""The retention swimlane: how long a tenant keeps what its sessions say and
their shape, the snapshot each session takes of that as it is created, and
the sweep that holds every session to its snapshot.

A tenant declares one policy, and each of its projects may narrow it. A
session takes the policy of its project as a snapshot, before its row is
written. A tightening of the tenant's policy reaches every session at the
next sweep; a loosening reaches none. When a session's content expires,
the sweep destroys its key in the tenant's key service, revokes it through
the engine, and audits the destruction as the key service reported it.
When its shape expires, the sweep marks the session deleted, and the
engine's purge removes it (ADR 1010)."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.context import RequestContext, TenantContext
from acme.om.retention.types.policy import TenantRetention
from acme.om.retention.types.snapshot import SessionRetention


class RetentionManagerInterface(ABC):
    @abstractmethod
    async def get_policy(self, ctx: TenantContext) -> TenantRetention:
        """The tenant's policy with its projects' narrowings; the loosest, at
        version 0 and never stored, when it has declared none."""
        ...

    @abstractmethod
    async def write_policy(self, ctx: TenantContext, policy: TenantRetention) -> TenantRetention:
        """Writes the tenant's policy, as one who manages its members may: a
        compare-and-set on the version the caller read, 0 for the first
        (`PreconditionFailed` when another landed first). A project that
        names another region than its tenant's is `ValidationFailed`.
        Announced. Sessions created from now on take it; existing ones take
        what it tightens at the next sweep, and nothing it loosens."""
        ...

    @abstractmethod
    async def take_snapshot(self, ctx: TenantContext, session: AgentSession) -> SessionRetention:
        """The snapshot of `session`, taken before the session is written: the
        policy its project takes now, and its expiries from now. A session
        spawned or handed over belongs to the project of the session it came
        from. Taken again, the first is answered."""
        ...

    @abstractmethod
    async def get_snapshot(self, ctx: TenantContext, session_id: UUID) -> SessionRetention:
        """The session's snapshot; `NotFound` when the tenant holds none."""
        ...

    @abstractmethod
    async def sweep(self, rctx: RequestContext) -> int:
        """Platform-internal: the sweep, across tenants, once a pass, under a
        service context minted for each tenant from `rctx`. First, at most a
        batch of snapshots take what their tenant's policy has tightened
        since they last read it. Then, at most a batch of sessions past an
        expiry: each whose content expired has its key destroyed by the
        tenant's key service, revoked through the engine, and the
        destruction audited as the service reported it; each whose shape
        expired is marked deleted. A session that fails fails no other, and
        the next pass takes it up again. Returns the larger of the two
        counts, so a whole batch says there may be more."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its snapshots
        and its policy, a batch at most a call. Any other tenant returns 0
        and reads nothing."""
        ...
