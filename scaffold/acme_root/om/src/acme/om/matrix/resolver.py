"""The matrix as the engine's resolver, with what the face over the models
manager asks of it besides: the switches a session owes at the start of a
loop."""

from abc import abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.models.resolver import ModelResolverInterface
from acme.om.models.types.fill import Eligibility, Fill, FillSet, ModelRole, SwitchReason

Renewal = tuple[int, tuple[tuple[ModelRole, Fill, SwitchReason], ...]]
"""The number of the version a renewal answers at, and each switch it
makes: the model role, the fill it switches to, and why."""


class MatrixResolverInterface(ModelResolverInterface):
    @abstractmethod
    async def renewal(
        self, ctx: TenantContext, session_id: UUID, head: FillSet, required: Eligibility
    ) -> Renewal | None:
        """The switches a session owes at the start of a loop: each role of
        `head` whose fill's model was retired, or whose fill `required`, the
        session's retention now, no longer admits, with the fill the latest
        published version answers it now and why, and that version's number.
        None when it owes none. `UnresolvedRole` when a role has nothing
        left to run on."""
        ...
