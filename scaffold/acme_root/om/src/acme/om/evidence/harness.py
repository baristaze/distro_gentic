"""The acceptance harness: it judges an agent's work on a scenario from the
chain of evidence the session left, with the hidden suite run beside the
visible one on a fresh executor. It runs in the non-gating benchmark job,
never in a gate a code change needs."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from uuid import UUID

from acme.om.agents.types.result import Result
from acme.om.context import TenantContext
from acme.om.evidence.types.acceptance import AcceptanceVerdict, Scenario, Surface


class AcceptanceHarnessInterface(ABC):
    @abstractmethod
    async def judge(
        self,
        ctx: TenantContext,
        scenario: Scenario,
        session_id: UUID,
        result: Result,
        surfaces: Mapping[Surface, Mapping[str, str]],
    ) -> AcceptanceVerdict:
        """Judges the session's work on `scenario`: the result it submitted,
        passed through the gate again; its baselines, validations, and
        hypotheses and findings; the hidden suite, run at the head delivered
        and kept with the verdict alone; the paths the change touched; and a
        scan of every surface the agent read, the objective and the session's
        own evidence added to what `surfaces` names. A scenario whose
        objective names what it hides, or `surfaces` that leave out one the
        agent reads, is `ValidationFailed`, before anything runs."""
        ...
