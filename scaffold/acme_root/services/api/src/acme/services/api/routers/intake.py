"""A tenant's connections: a person who manages the tenant connects a
system's installation of the platform with the grant the system handed
them, and every delivery that names it reaches this tenant alone."""

from fastapi import APIRouter, Response

from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import IntakeService
from acme.services.api.types.common import ErrorResponse
from acme.services.api.types.intake import ConnectInstallationRequest, InstallationView

router = APIRouter(prefix="/integrations", tags=["intake"])


@router.post(
    "/{integration}/installations",
    response_model=InstallationView,
    status_code=201,
    responses={409: {"model": ErrorResponse, "description": "another tenant connected it"}},
)
async def connect_installation(
    ctx: Ctx, intake: IntakeService, integration: str, body: ConnectInstallationRequest, idem: Idem
) -> Response:
    """The installation the grant names, connected to the tenant; connected
    already, it answers as it stands."""
    return await idem.run(201, lambda _: intake.connect_installation(ctx, integration, body))
