"""Validation sessions: one check of a project's policy, run on a fresh
executor with no agent, started at a delivered commit under an
Idempotency-Key, and read with its verdict once its run is recorded. A
member who may write starts one; any member reads one. Another tenant's
session, or its project, answers as one that never existed."""

from uuid import UUID

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import ValidationsService
from acme.services.api.types.validations import StartValidationRequest, ValidationSessionView

router = APIRouter(prefix="/validation-sessions", tags=["platform_agents"])


@router.post("", response_model=ValidationSessionView, status_code=201)
async def start_validation(
    ctx: Ctx, validations: ValidationsService, body: StartValidationRequest, idem: Idem
) -> Response:
    """A session queued for the platform's worker, which runs its check once.
    404 when the tenant holds no validation policy for the project; 422
    when the policy declares no such check."""
    return await idem.run(
        201, lambda attempt: validations.start_validation(ctx, body, attempt.target_id)
    )


@router.get("/{session_id}", response_model=ValidationSessionView)
async def get_validation(
    ctx: Ctx, validations: ValidationsService, session_id: UUID
) -> ValidationSessionView:
    """The session: `queued` while its check waits or runs, `finished` with
    its verdict and its run once the run is recorded, and `refused` with its
    reason when its check cannot run here, for good."""
    return await validations.get_validation(ctx, session_id)
