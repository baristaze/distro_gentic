"""What a product adds to the platform's API, declared once in
`product_api.py`: each namespace's routers, and its service factory, over
the managers its namespace builds (`acme.om.platform_root.ProductNamespace`),
the platform's managers, and the live parts the API builds (`ProductLive`).
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
from acme.om.watch import WatchManagerInterface
from acme.om.watch.kinds import KindStreamsInterface


@dataclass(frozen=True)
class ProductLive:
    """What the API builds over the live streams that a product's service
    may hold beside the managers: the watch, which opens a live read for a
    viewer of the session's or the item's tenant, and the streams of the
    product's own kinds, which its routes write where no claimant does and
    read where the product shows them. A kind's stream is grouped by an
    item's id and carries no permission of its own, so a service reads or
    writes one only for an item it read under the caller's context, with
    the permission the platform's routes require for the same act: READ to
    read, WRITE to write. A write names that item's tenant, whose claimant
    the append wakes."""

    watch: WatchManagerInterface
    kind_streams: KindStreamsInterface


@dataclass(frozen=True)
class ProductApiNamespace[M]:
    """A product's namespace as the API serves it: the namespace, its
    routers, and its service, built over the namespace's managers, the
    platform's, and the API's live parts."""

    namespace: ProductNamespace[M]
    routers: tuple[APIRouter, ...]
    service: Callable[[M, PlatformManagers, ProductLive], object]

    def service_over(
        self, storage: StorageInterface, managers: PlatformManagers, live: ProductLive
    ) -> object:
        """The namespace's service, over its managers built once here."""
        return self.service(self.namespace.build(storage, managers), managers, live)


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
        live: ProductLive,
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
            served.namespace.name: served.service_over(storage, managers, live)
            for served in self.namespaces
        }
