"""What the host that prepares a session's workspace offers beyond its
provider's own refusals: where it sits, how a bare directory runs on it,
and what its egress holds. Its owner sets it and its probe finds it, and
the platform never raises it."""

from pydantic import Field

from acme.om.base import Platform


class HostOffer(Platform):
    """The default offers nothing beyond the provider: a host of the
    platform's cloud, with no directory, no egress proxy, and nothing that
    holds open egress off the platform's insides."""

    inside_wall: bool = False  # it sits inside a customer's wall
    # A directory workspace runs as a dedicated, unprivileged user, who reads
    # neither the host's credential, its secret store, nor another workspace.
    dedicated_user: bool = False
    # Its workspaces never reach the platform's internal network, a cloud
    # metadata endpoint, or a station's network, whatever their egress.
    blocks_internal: bool = False
    # An egress proxy holds an allowlist's destinations and methods.
    enforces_allowlist: bool = False
    directory_only: bool = False  # a bare directory is all it offers
    # How many sessions a directory-only host runs at once, as its owner says.
    directory_sessions: int = Field(default=1, ge=1)
