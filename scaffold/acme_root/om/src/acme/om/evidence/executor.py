"""The fresh executor: where validation runs, never in the agent's
workspace. It takes the delivered commit, overlays the checks, fixtures,
and runner from the protected source, runs them under an environment it
sets, and writes and hashes the results. A root wires the platform's;
the null of a root that wired none refuses every run, loudly. A product
registers an executor of its own for an environment of its own, beside
the platform's (`Executors`); what any of them writes is held to the same
rules before it is kept, and the result gate reads it as it reads the
platform's."""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import MappingProxyType

from acme.om.context import TenantContext
from acme.om.evidence.types.contract import PLATFORM_ENVIRONMENT, Offer
from acme.om.evidence.types.record import NAME
from acme.om.evidence.types.validation import ExecutionRequest, ExecutorReport


class ExecutorInterface(ABC):
    @abstractmethod
    async def offer(self, ctx: TenantContext) -> Offer:
        """What the executor can run: its capabilities and the results
        schemas its runner writes. Asked before anything is leased or run."""
        ...

    @abstractmethod
    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        """Runs the request's checks on an executor nobody used before, each
        its count of trials, and answers the results stream it wrote, its
        own name, and its hash of the stream."""
        ...


class Executors:
    """The executors a process holds, one per validation environment: the
    platform's under `PLATFORM_ENVIRONMENT`, and each a product registered
    at its root under a name of its own. A product never takes over the
    platform's environment."""

    def __init__(
        self, platform: ExecutorInterface, others: Mapping[str, ExecutorInterface] | None = None
    ) -> None:
        found: dict[str, ExecutorInterface] = {PLATFORM_ENVIRONMENT: platform}
        for environment, executor in (others or {}).items():
            if environment in found:
                raise ValueError(f"the {environment} environment is registered twice")
            if not re.match(NAME, environment):
                raise ValueError(f"an environment is named in lower case, never {environment!r}")
            found[environment] = executor
        self._executors: Mapping[str, ExecutorInterface] = MappingProxyType(found)

    def get(self, environment: str) -> ExecutorInterface | None:
        """The executor of that environment; None for one nobody registered."""
        return self._executors.get(environment)

    @property
    def platform(self) -> ExecutorInterface:
        return self._executors[PLATFORM_ENVIRONMENT]
