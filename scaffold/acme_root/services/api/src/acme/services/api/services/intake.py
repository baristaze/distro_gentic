"""The intake service: a tenant connects a system's installation of the
platform, so the system's deliveries reach it."""

from abc import ABC, abstractmethod

from acme.om.context import TenantContext
from acme.services.api.types.intake import ConnectInstallationRequest, InstallationView


class IntakeServiceInterface(ABC):
    @abstractmethod
    async def connect_installation(
        self, ctx: TenantContext, integration: str, body: ConnectInstallationRequest
    ) -> InstallationView: ...
