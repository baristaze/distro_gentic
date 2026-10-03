"""What the matrix keeps of one tenant: the version each of its sessions
resolved at, and the fill a tenant on its own keys chose for a model role;
and what it may choose from."""

from uuid import UUID

from pydantic import Field

from acme.om.base import Created, Identifiable, Platform, Trackable
from acme.om.models.types.fill import Fill, ModelRole


class MatrixPin(Identifiable, Created):
    """The version of the matrix a session's fill set took a version from:
    its first, at the session's first loop, and each switch the matrix made
    since. A fallback a provider's failure forced takes no pin: it is drawn
    from the fallbacks the pinned version declared. Written once."""

    session_id: UUID
    fill_set_version: int = Field(ge=1)
    matrix_version: int = Field(ge=1)


class FillOverride(Identifiable, Trackable):
    """The fill a tenant on its own keys chose for one model role: a fill
    the matrix qualified for that role, from a provider it holds a key for.
    One a role: a new choice replaces the last."""

    role: ModelRole
    fill: Fill


class FillOptions(Platform):
    """What a tenant on its own keys may choose for one model role of the
    published matrix: the fills it qualified for the role, from a provider
    the tenant holds a live key for. Never stored: read from the version and
    the tenant's keys."""

    role: ModelRole
    fills: tuple[Fill, ...]
