"""Placement: where each kind of a tenant's work runs. On the operator plane,
under /v1/admin/*, an operator who may write sets a tenant's fair share,
its plan tier, its own lane, and how many of its loops run at once, a new
version each time, on the tenant's own record; the share is written whole,
so the write is a PUT and a retry lands the same terms, with no
Idempotency-Key. An operator who may read reads why a session is or is not
moving, as ids, counts, times, and states.
Each route takes `OperatorContext` and names the tenant."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.platform_resolve import AgentFleetService
from acme.services.api.types.placement import AgentSessionStandingView, SetShareRequest, ShareView

operator = APIRouter(prefix="/admin", tags=["placement"])


@operator.put("/orgs/{org_id}/share", response_model=ShareView)
async def set_share(
    admin: OperatorCtx, service: AgentFleetService, org_id: UUID, body: SetShareRequest
) -> ShareView:
    """Writes the org's fair share, a new version, with an entry in the
    org's stream that names the operator. Its loops enqueued from then on go
    to the lane it names. `concurrency` is the org's own cap on that lane,
    which the claim holds in place of its tier's share; with none, the
    tier's share holds. Requires the write permission."""
    return await service.set_share(admin, org_id, body)


@operator.get(
    "/orgs/{org_id}/agent-sessions/{agent_session_id}/standing",
    response_model=AgentSessionStandingView,
)
async def agent_session_standing(
    admin: OperatorCtx, service: AgentFleetService, org_id: UUID, agent_session_id: UUID
) -> AgentSessionStandingView:
    """Why the session is or is not moving: its park, its loop's lease and
    lane, its place in line, its tenant's share, and where it runs."""
    return await service.get_session_standing(admin, org_id, agent_session_id)
