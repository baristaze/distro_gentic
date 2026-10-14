"""What a product adds to the platform's API, declared once in
`product_api.py`: each namespace's routers, and its service factory, over
the managers its namespace builds (`acme.om.platform_root.ProductNamespace`).
Its routers name the service through the resolver
`gateway.platform_resolve.product_service`. HOSTED serves the routers
beside the platform's, and the services root holds the service by the
namespace's name."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from acme.om.platform_root import PlatformManagers, ProductNamespace, ProductNamespaces
from acme.om.storage.root import StorageInterface


@dataclass(frozen=True)
class ProductApiNamespace[M]:
    """A product's namespace as the API serves it: the namespace, its
    routers, and its service, built over the namespace's managers and the
    platform's."""

    namespace: ProductNamespace[M]
    routers: tuple[APIRouter, ...]
    service: Callable[[M, PlatformManagers], object]

    def service_over(self, storage: StorageInterface, managers: PlatformManagers) -> object:
        """The namespace's service, over its managers built once here."""
        return self.service(self.namespace.build(storage, managers), managers)


@dataclass(frozen=True)
class ProductApi:
    """Every namespace a product serves, each once."""

    namespaces: tuple[ProductApiNamespace[Any], ...] = ()

    def __post_init__(self) -> None:
        names = [served.namespace.name for served in self.namespaces]
        if len(set(names)) != len(names):
            raise ValueError("the product serves a namespace twice")

    def hosted(self) -> dict[str, tuple[APIRouter, ...]]:
        """Each namespace's routers, by its name."""
        return {served.namespace.name: served.routers for served in self.namespaces}

    def services(
        self,
        storage: StorageInterface,
        managers: PlatformManagers,
        declared: ProductNamespaces,
    ) -> dict[str, object]:
        """Each namespace's service, by its name. A namespace served here and
        not `declared` beside the product's kinds is refused at boot, since
        the maintenance worker would never purge its rows."""
        swept = {namespace.name for namespace in declared.namespaces}
        for served in self.namespaces:
            if served.namespace.name not in swept:
                raise ValueError(
                    f"namespace {served.namespace.name} is served and not declared, "
                    "so nothing purges it"
                )
        return {
            served.namespace.name: served.service_over(storage, managers)
            for served in self.namespaces
        }
