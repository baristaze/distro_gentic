"""The operator plane of the trust swimlane: what an operator reads of a
tenant's sessions. Every read names the tenant and takes `OperatorContext`,
so no tenant manager is reachable from here. `read` reads a session's
shape. Opening what it says takes a grant of its own in that tenant, which
`read` never implies (ADR 2010); each opening is written into the tenant's
event stream, so the tenant sees who opened what.

The grant is the grant job's to write, like the operator allowlist, and no
route writes it."""

from abc import ABC, abstractmethod
from datetime import timedelta
from uuid import UUID

from acme.om.agent_steps.types.page import AgentStepPage
from acme.om.context import OperatorContext, RequestContext, transition
from acme.om.trust.types.grant import ContentGrant
from acme.om.trust.types.shape import ShapePage


class TrustOperatorManagerInterface(ABC):
    @abstractmethod
    async def get_session_shape(
        self,
        admin: OperatorContext,
        org_id: UUID,
        agent_session_id: UUID,
        after_seq: int,
        limit: int,
    ) -> ShapePage:
        """The shape of the named tenant's session past `after_seq`: each
        step's place, type, actor, origin, header, and whether its content is
        kept, never the content. Requires `OperatorPermission.READ`, and is
        logged with the tenant and the operator. `NotFound` for a session the
        tenant does not hold."""
        ...

    @abstractmethod
    async def get_session_content(
        self,
        admin: OperatorContext,
        org_id: UUID,
        agent_session_id: UUID,
        after_seq: int,
        limit: int,
    ) -> AgentStepPage:
        """The named tenant's session past `after_seq`, opened. Requires
        `OperatorPermission.READ` and a live content grant of the operator's
        identity in that tenant (`ContentNotGranted` otherwise, `read` alone
        included). Each opening is an audit entry in the tenant's stream,
        naming the operator and the session. `NotFound` for a session the
        tenant does not hold."""
        ...

    @abstractmethod
    @transition
    async def grant_content(
        self,
        rctx: RequestContext,
        identity_id: UUID,
        org_id: UUID,
        expires_in: timedelta | None = None,
    ) -> ContentGrant:
        """System-internal: the grant job opens one tenant's session content
        to one operator's identity, for `expires_in` (the options' default
        when None), never past the options' bound (`ValidationFailed`). A
        grant made again replaces the one before. Audited in the tenant's
        stream."""
        ...

    @abstractmethod
    @transition
    async def revoke_content(self, rctx: RequestContext, identity_id: UUID, org_id: UUID) -> bool:
        """System-internal: the grant job ends an operator's content grant
        in a tenant at once, audited. False when none was held."""
        ...
