"""The kinds of resource, as a registry. A kind is a name, the shape of what
its ask carries, its hooks, and, when it refuses some asks, its check of
one. The mechanism's own kind, `noop`, registers here as a product's do at
its roots (`root.ProductKinds.resources`), so no kind is an enum a product
edits: each root builds the one registry its process holds, and hands the
leases manager every kind's hooks, shape, and check from it."""

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from acme.om.base import Platform
from acme.om.leases.hooks import AskCheckInterface, ResourceKindInterface
from acme.om.leases.types.resource import KIND_NAME

_NAME = re.compile(KIND_NAME)


@dataclass(frozen=True)
class ResourceKindSpec:
    """One kind of resource. `ask` is the shape every ask for it carries,
    which the ask holds its payload to; `hooks` say what a grant of it
    starts and whether a request may still be granted; `check`, for a kind
    that refuses some asks, is asked before an ask lands. A kind with no
    check accepts every ask."""

    name: str
    ask: type[Platform]
    hooks: ResourceKindInterface
    check: AskCheckInterface | None = None

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError(f"a resource kind is named in lower case, never {self.name!r}")


class ResourceKinds:
    """The kinds a process knows, each once. Built at a root from the
    mechanism's own and a product's; a name registered twice is refused, so
    a product never takes over a kind of the platform's."""

    def __init__(self, specs: Iterable[ResourceKindSpec]) -> None:
        found: dict[str, ResourceKindSpec] = {}
        for spec in specs:
            if spec.name in found:
                raise ValueError(f"resource kind {spec.name} is registered twice")
            found[spec.name] = spec
        self._specs: Mapping[str, ResourceKindSpec] = MappingProxyType(found)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __iter__(self) -> Iterator[ResourceKindSpec]:
        return iter(self._specs.values())

    def hooks(self) -> Mapping[str, ResourceKindInterface]:
        """Each kind's hooks, by its name."""
        return MappingProxyType({name: spec.hooks for name, spec in self._specs.items()})

    def asks(self) -> Mapping[str, type[Platform]]:
        """The shape of each kind's ask, by its name."""
        return MappingProxyType({name: spec.ask for name, spec in self._specs.items()})

    def checks(self) -> Mapping[str, AskCheckInterface]:
        """The check of each kind that refuses some asks, by its name."""
        return MappingProxyType(
            {name: spec.check for name, spec in self._specs.items() if spec.check is not None}
        )
