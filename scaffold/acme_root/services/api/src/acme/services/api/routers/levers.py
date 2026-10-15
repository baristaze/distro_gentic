"""Levers: what a tenant's sessions reached before they stalled. On the
operator plane, an operator who may read reads which levers a tenant's
sessions created in a window reached, each lever by its kind, id, and
version, never its name or its slug, with counts and session ids (ADR
2054)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.platform_resolve import AgentFleetService
from acme.services.api.types.levers import LeverReadingView

operator = APIRouter(prefix="/admin", tags=["levers"])


@operator.get("/orgs/{org_id}/levers", response_model=LeverReadingView)
async def read_levers(
    admin: OperatorCtx,
    service: AgentFleetService,
    org_id: UUID,
    since: Annotated[AwareDatetime, Query()],
    until: Annotated[AwareDatetime, Query()],
) -> LeverReadingView:
    """The agent playbooks and agent knowledge the org's sessions created in `[since,
    until)` reached, ranked by how much more often the sessions that
    reached them stalled, with the sessions behind each figure. A stall is
    read from the steps' headers, never from what a step says, and a lever
    is answered by its kind, id, and version, never by its name or its
    slug. A window that does not end after it starts is `422`."""
    return await service.read_levers(admin, org_id, since, until)
