"""A step as an operator's `read` sees it: its shape, and nothing it says.
The header is shape by design (it carries ids, names, counts, and flags,
never what a person typed or a tool returned); the content and the
children are not here at all, only whether the content is kept."""

from datetime import datetime
from uuid import UUID

from acme.om.base import Platform
from acme.om.steps.types.content import ContentState
from acme.om.steps.types.header import StepHeader
from acme.om.steps.types.step import Actor, Origin, Step, StepType


class StepShape(Platform):
    id: UUID
    session_id: UUID
    seq: int
    loop_id: UUID
    type: StepType
    actor: Actor
    origin: Origin
    responds_to: UUID | None
    refs: tuple[UUID, ...]
    header: StepHeader
    created_at: datetime
    content: ContentState


class ShapePage(Platform):
    """Shapes in `seq` order, and whether more follow."""

    items: tuple[StepShape, ...]
    has_more: bool


def shape_of(step: Step) -> StepShape:
    """What an operator's `read` sees of a step."""
    return StepShape(
        id=step.id,
        session_id=step.session_id,
        seq=step.seq,
        loop_id=step.loop_id,
        type=step.type,
        actor=step.actor,
        origin=step.origin,
        responds_to=step.responds_to,
        refs=step.refs,
        header=step.header,
        created_at=step.created_at,
        content=step.content.state,
    )
