"""A tenant's own keys to its model providers. A key's value goes in and
never comes back: the routes answer the record alone, who added the key,
when, its state, and when it was last used. A key is probed before it is
saved, and one the provider refuses is not saved. Saving mints a new
reference and makes it the live key, so the write is a PUT, and a retry
lands the same live value: it takes no Idempotency-Key.

On the operator plane, an operator who may read reads a session's shape,
never what it says. Its content opens only under a grant the grant job
wrote in that tenant (`403 content_not_granted` otherwise), and the
tenant's stream names the operator at every opening (ADR 2010)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.platform_resolve import AgentFleetService, ProviderKeysService
from acme.services.api.types.agent_sessions import AgentStepPageView
from acme.services.api.types.common import LIMIT_DEFAULT
from acme.services.api.types.matrix import ProviderName
from acme.services.api.types.trust import ProviderKeyView, SaveKeyRequest, ShapePageView

router = APIRouter(prefix="/provider-keys", tags=["trust"])


operator = APIRouter(prefix="/admin", tags=["trust"])


@router.get("", response_model=list[ProviderKeyView])
async def get_keys(
    ctx: Ctx, service: ProviderKeysService, limit: int = LIMIT_DEFAULT
) -> list[ProviderKeyView]:
    """The tenant's keys, the newest first, a rotated or refused one among
    them; never a value."""
    return await service.get_keys(ctx, limit)


@router.put("/{provider}", response_model=ProviderKeyView)
async def save_key(
    ctx: Ctx, service: ProviderKeysService, provider: ProviderName, body: SaveKeyRequest
) -> ProviderKeyView:
    """The tenant's live key to `provider`, the one before it rotated out.
    Requires managing the org. `key_refused` when the provider does not take
    it, and 503 when no probe can ask."""
    return await service.save_key(ctx, provider, body)


@operator.get("/orgs/{org_id}/sessions/{agent_session_id}/shape", response_model=ShapePageView)
async def session_shape(
    admin: OperatorCtx,
    service: AgentFleetService,
    org_id: UUID,
    agent_session_id: UUID,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: int = LIMIT_DEFAULT,
) -> ShapePageView:
    """The session's steps past `after_seq` as `read` sees them: what each
    is and who wrote it, never what it says."""
    return await service.get_session_shape(admin, org_id, agent_session_id, after_seq, limit)


@operator.get(
    "/orgs/{org_id}/sessions/{agent_session_id}/content", response_model=AgentStepPageView
)
async def session_content(
    admin: OperatorCtx,
    service: AgentFleetService,
    org_id: UUID,
    agent_session_id: UUID,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: int = LIMIT_DEFAULT,
) -> AgentStepPageView:
    """The session's steps past `after_seq`, opened: only under a live
    content grant of the operator in that tenant, and each opening is an
    entry in the tenant's stream."""
    return await service.get_session_content(admin, org_id, agent_session_id, after_seq, limit)
