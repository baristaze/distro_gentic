"""The hosts namespace's types: the views and requests its calls carry, as
consumers import them."""

from acme.client.schema.hosts import (
    AdvertisementBody,
    ClaimantClaimView,
    ClaimantControlKind,
    ClaimantControlView,
    ClaimantWorkView,
    ClaimedWorkView,
    ClaimView,
    HostView,
    IsolationMode,
    IssuedClaimantCredentialView,
    IssuedHostCredentialView,
)

__all__ = [
    "AdvertisementBody",
    "ClaimView",
    "ClaimantClaimView",
    "ClaimantControlKind",
    "ClaimantControlView",
    "ClaimantWorkView",
    "ClaimedWorkView",
    "HostView",
    "IsolationMode",
    "IssuedClaimantCredentialView",
    "IssuedHostCredentialView",
]
