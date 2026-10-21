"""How a person signs in on the platform's graph, in the unit suites: the
base's `managers_signing_in`, over every manager of the engine and the
platform. The graph is handed a twin of its own, and `provider_login`
signs a person in through it."""

from typing import Any

from acme.infra.root import InfraInterface
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import absent_model_providers
from acme.om.platform_root import PlatformManagers, build_platform_managers
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.impl.manager import TenancyOptions

from contracts.signing_in import signing_in


def platform_managers_signing_in(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy_options: TenancyOptions | None = None,
    **options: Any,
) -> PlatformManagers:
    """`build_platform_managers` over a twin of its own."""
    twin = IdentityProviderTwinImpl()
    managers = build_platform_managers(
        storage,
        infra,
        tenancy_options,
        None,
        IntegrationsOverImpl(twin, absent_model_providers()),
        **options,
    )
    signing_in(managers.tenancy, twin)
    return managers
