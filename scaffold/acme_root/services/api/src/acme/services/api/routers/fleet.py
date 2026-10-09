"""The platform's operator routes under /v1/admin/*, beside the
guideline's: a tenant's fair share, where one of its sessions' work stands,
what one of its hosts is handed, and a session's history, its shape under
`read` and its content under a grant of its own. Each takes
`OperatorContext` and names the tenant; the managers decide, and each read
is logged with the tenant and the operator.

The share is written whole, a new version each time, so the write is a PUT
and a retry lands the same terms: it takes no Idempotency-Key. The content
route opens what a session says only for an operator the grant job granted
in that tenant (`403 content_not_granted` otherwise), and the tenant's stream
names the operator at every opening (ADR 2010)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.resolve import FleetService
from acme.services.api.types.agent_sessions import StepPageView
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.fleet import (
    HostStandingView,
    SessionStandingView,
    SetShareRequest,
    ShapePageView,
    ShareView,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.put("/orgs/{org_id}/share", response_model=ShareView)
async def set_share(
    admin: OperatorCtx, service: FleetService, org_id: UUID, body: SetShareRequest
) -> ShareView:
    """Writes the org's fair share, a new version, with an entry in the
    org's stream that names the operator. Its loops enqueued from then on go
    to the lane it names. `concurrency` is the org's own cap on that lane,
    which the claim holds in place of its tier's share; with none, the
    tier's share holds. Requires the write permission."""
    return await service.set_share(admin, org_id, body)


@router.get("/orgs/{org_id}/sessions/{session_id}/standing", response_model=SessionStandingView)
async def session_standing(
    admin: OperatorCtx, service: FleetService, org_id: UUID, session_id: UUID
) -> SessionStandingView:
    """Why the session is or is not moving: its park, its loop's lease and
    lane, its place in line, its tenant's share, and where it runs."""
    return await service.get_session_standing(admin, org_id, session_id)


@router.get("/orgs/{org_id}/hosts/{host_id}/standing", response_model=HostStandingView)
async def host_standing(
    admin: OperatorCtx, service: FleetService, org_id: UUID, host_id: UUID
) -> HostStandingView:
    """Why the host takes no work: what it advertised and the version it
    reads, against the floor and what is ready on its lanes."""
    return await service.get_host_standing(admin, org_id, host_id)


@router.get("/orgs/{org_id}/sessions/{session_id}/shape", response_model=ShapePageView)
async def session_shape(
    admin: OperatorCtx,
    service: FleetService,
    org_id: UUID,
    session_id: UUID,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: int = LIMIT_DEFAULT,
) -> ShapePageView:
    """The session's steps past `after_seq` as `read` sees them: what each
    is and who wrote it, never what it says."""
    return await service.get_session_shape(admin, org_id, session_id, after_seq, limit)


@router.get("/orgs/{org_id}/sessions/{session_id}/content", response_model=StepPageView)
async def session_content(
    admin: OperatorCtx,
    service: FleetService,
    org_id: UUID,
    session_id: UUID,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: int = LIMIT_DEFAULT,
) -> StepPageView:
    """The session's steps past `after_seq`, opened: only under a live
    content grant of the operator in that tenant, and each opening is an
    entry in the tenant's stream."""
    return await service.get_session_content(admin, org_id, session_id, after_seq, limit)
