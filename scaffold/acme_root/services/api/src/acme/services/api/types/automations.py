"""Wire types of the tenant's automation principal: the role a person grants
it, and the grant as it stands."""

from datetime import datetime
from uuid import UUID

from acme.om.context import Role
from acme.services.api.types.common import RequestBody, View


class GrantRequest(RequestBody):
    """The role the automation principal holds: never above the granter's."""

    role: Role


class AutomationPrincipalView(View):
    """The tenant's automation principal: its id, the role it holds, and who
    granted it."""

    id: UUID
    role: Role
    granted_by: UUID
    created_at: datetime
