"""Wire types of a tenant's connections: the grant a system handed the
person who installed the platform there, and the installation it names."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.services.api.types.common import RequestBody, View

MAX_GRANT = 4096


class ConnectInstallationRequest(RequestBody):
    """The grant the system handed the person who installed the platform:
    the integration reads the installation from it, never from the caller."""

    grant: str = Field(min_length=1, max_length=MAX_GRANT)


class InstallationView(View):
    """An installation of the platform in a system, connected by the tenant:
    every delivery that names it reaches this tenant alone."""

    id: UUID
    integration: str
    installation: str
    created_at: datetime
    created_by: UUID
