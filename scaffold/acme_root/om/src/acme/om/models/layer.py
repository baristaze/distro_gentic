"""What a layer above the engine sets of its models: the resolver that picks
a session's fills, a face over the models manager, and the client each call
runs on. A root takes one layer, or none and keeps the engine's own: the
table resolver, the manager as it is, and the platform's key."""

from collections.abc import Callable
from dataclasses import dataclass

from acme.integrations.model_providers import ModelProvidersInterface
from acme.om.models.credentials import CallCredentialsInterface
from acme.om.models.manager import ModelsManagerInterface
from acme.om.models.prices import ModelPricesInterface
from acme.om.models.resolver import ModelResolverInterface
from acme.om.tenancy import TenancyManagerInterface


@dataclass(frozen=True)
class ModelsLayer:
    """`resolver` builds the resolver over the prices it asks before it
    answers a fill. `models` wraps the engine's models manager, with the
    tenancy manager that answers whether a tenant is past its retention.
    `credentials` builds the client each call runs on over the providers'
    registry, which holds the platform's key."""

    resolver: Callable[[ModelPricesInterface], ModelResolverInterface]
    models: Callable[[ModelsManagerInterface, TenancyManagerInterface], ModelsManagerInterface]
    credentials: Callable[[ModelProvidersInterface], CallCredentialsInterface]
