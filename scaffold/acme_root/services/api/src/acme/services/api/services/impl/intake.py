from acme.om.context import TenantContext
from acme.om.intake import IntakeManagerInterface
from acme.services.api.services.intake import IntakeServiceInterface
from acme.services.api.types.intake import ConnectInstallationRequest, InstallationView


class IntakeServiceImpl(IntakeServiceInterface):
    def __init__(self, intake: IntakeManagerInterface) -> None:
        self._intake = intake

    async def connect_installation(
        self, ctx: TenantContext, integration: str, body: ConnectInstallationRequest
    ) -> InstallationView:
        held = await self._intake.connect_installation(ctx, integration, body.grant)
        return InstallationView.model_validate(held)
