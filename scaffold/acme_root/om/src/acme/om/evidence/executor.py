"""The fresh executor: where validation runs, never in the agent's
workspace. It takes the delivered commit, overlays the checks, fixtures,
and runner from the protected source, runs them under an environment it
sets, and writes and hashes the results. A root wires the platform's;
the null of a root that wired none refuses every run, loudly."""

from abc import ABC, abstractmethod

from acme.om.context import TenantContext
from acme.om.evidence.types.contract import Offer
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
