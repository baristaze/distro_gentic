"""The operator permission that opens a tenant's session content. An
operator's `read` reads a session's shape; opening what it says takes this
grant, of one identity in one tenant, until it expires. `read` never
implies it, and no role holds it by default (ADR 2010)."""

from datetime import datetime
from uuid import UUID

from acme.om.base import Created, Identifiable


class ContentGrant(Identifiable, Created):
    """One operator's grant in one tenant: the tenant is the row's, the
    operator is `identity_id`. It opens content from `created_at` until
    `expires_at`, and a grant made again replaces it."""

    identity_id: UUID
    expires_at: datetime
