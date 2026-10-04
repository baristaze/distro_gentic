"""The validation sessions service: one check of a project's policy started
at a delivered commit, as a CI job or a command line asks for it, and read
with its verdict once its run is recorded."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.validations import StartValidationRequest, ValidationSessionView


class ValidationsServiceInterface(ABC):
    @abstractmethod
    async def start_validation(
        self, ctx: TenantContext, body: StartValidationRequest, session_id: UUID
    ) -> ValidationSessionView:
        """A session under `session_id`, its work queued for the platform's
        worker. Started again under the same id, it answers the session as
        stored."""
        ...

    @abstractmethod
    async def get_validation(self, ctx: TenantContext, session_id: UUID) -> ValidationSessionView:
        """The session, with its verdict once its run is recorded; another
        tenant's answers as one that never existed."""
        ...
