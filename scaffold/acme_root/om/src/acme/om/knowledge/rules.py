"""Pure rules of knowledge: which entries a session's subject triggers, and
an entry as the input that brings it into a session. Values in, values out.

Only a reviewed entry is ever recalled, and it arrives as an event: data
the engine quotes and labels, never an instruction, whoever wrote it."""

import re
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from acme.om.attribution.types.principal import Principal
from acme.om.base import derived_id
from acme.om.knowledge.types.knowledge import Knowledge, KnowledgeStatus
from acme.om.steps.types.content import Content, TextBlock
from acme.om.steps.types.header import InputHeader
from acme.om.steps.types.step import Actor, Origin, Step, StepType

WORD = re.compile(r"[a-z0-9_.-]+")


def words(text: str) -> frozenset[str]:
    return frozenset(WORD.findall(text.lower()))


def recallable(entry: Knowledge) -> bool:
    """Whether a session may recall an entry: a person reviewed it."""
    return entry.status is KnowledgeStatus.REVIEWED and entry.reviewed_by is not None


def triggered(entries: Iterable[Knowledge], about: str) -> list[Knowledge]:
    """The recallable entries whose every trigger word appears in `about`."""
    said = words(about)
    return [
        entry
        for entry in entries
        if recallable(entry) and all(word in said for w in entry.trigger for word in words(w))
    ]


def recalled_step(entry: Knowledge, session_id: UUID, principal: Principal, now: datetime) -> Step:
    """An entry as the input a session receives: an event, which waits for
    the next model call and wakes nothing, and reads as data. Its id is
    derived from the entry's and the session's, so it arrives once."""
    step_id = derived_id(entry.id, entry.created_at, f"recall:{session_id}")
    return Step(
        id=step_id,
        created_at=now,
        session_id=session_id,
        loop_id=step_id,
        type=StepType.EVENT,
        actor=Actor.EXTERNAL,
        origin=Origin.ENGINE,
        header=InputHeader(waking=False, principal=principal),
        content=Content(blocks=(TextBlock(text=f"knowledge: {entry.title}\n{entry.text}"),)),
    )
