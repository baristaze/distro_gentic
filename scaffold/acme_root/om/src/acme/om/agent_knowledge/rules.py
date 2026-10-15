"""Pure rules of agent knowledge: which entries a session reaches, which of them
its subject triggers or a search finds, an entry's slug, and an entry as
the input that brings it into a session. Values in, values out.

Only a reviewed entry is ever recalled or read, and only by a session of
its tenant whose agent project is the entry's, or by any session of the tenant
for an entry of no agent project. A recalled entry arrives as an event: data the
engine quotes and labels, never an instruction, whoever wrote it."""

import re
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from acme.om.agent_knowledge.types.agent_knowledge import (
    MAX_SLUG,
    AgentKnowledge,
    AgentKnowledgeStatus,
)
from acme.om.agent_steps.types.agent_step import Actor, AgentStepType, Origin, AgentStep
from acme.om.agent_steps.types.content import Content, TextBlock
from acme.om.agent_steps.types.header import InputHeader
from acme.om.attribution.types.principal import Principal
from acme.om.base import derived_id

WORD = re.compile(r"[a-z0-9_.-]+")
SLUG_CUT = re.compile(r"[^a-z0-9]+")


def words(text: str) -> frozenset[str]:
    return frozenset(WORD.findall(text.lower()))


def recallable(entry: AgentKnowledge) -> bool:
    """Whether a session may recall an entry: a person reviewed it."""
    return entry.status is AgentKnowledgeStatus.REVIEWED and entry.reviewed_by is not None


def reaches(entry: AgentKnowledge, agent_project_id: UUID | None) -> bool:
    """Whether a session of the entry's tenant whose agent project is `agent_project_id`
    (None for a session of no agent project) may recall or read it: a person
    reviewed it, and it is the session's agent project's or the whole tenant's,
    never another agent project's."""
    return recallable(entry) and entry.agent_project_id in (None, agent_project_id)


def triggered(entries: Iterable[AgentKnowledge], about: str) -> list[AgentKnowledge]:
    """The recallable entries whose every trigger word appears in `about`."""
    said = words(about)
    return [
        entry
        for entry in entries
        if recallable(entry) and all(word in said for w in entry.trigger for word in words(w))
    ]


def ranked(entries: Iterable[AgentKnowledge], query: str, limit: int) -> list[AgentKnowledge]:
    """The recallable entries that share the most of the query's words with
    their title, trigger, and text, best first, at most `limit`. An entry
    that shares none is never an answer."""
    asked = words(query)
    scored: list[tuple[int, int, AgentKnowledge]] = []
    for entry in entries:
        if not recallable(entry):
            continue
        held = words(" ".join((entry.title, *entry.trigger, entry.text)))
        shared = len(asked & held)
        if shared:
            scored.append((-shared, len(scored), entry))
    scored.sort(key=lambda scored_entry: scored_entry[:2])
    return [entry for _, _, entry in scored[:limit]]


def slug_of(title: str, entry_id: UUID) -> str:
    """The handle an agent reads an entry by: its title's words, lowercase
    and hyphenated, then the last eight hex digits of its id, the random
    ones of a v7, so two entries of one title keep two slugs."""
    tail = entry_id.hex[-8:]
    head = SLUG_CUT.sub("-", title.lower()).strip("-")[: MAX_SLUG - len(tail) - 1].strip("-")
    return f"{head or 'entry'}-{tail}"


def recalled_step(
    entry: AgentKnowledge, agent_session_id: UUID, principal: Principal, now: datetime
) -> AgentStep:
    """An entry as the input a session receives: an event, which waits for
    the next model call and wakes nothing, and reads as data. Its id is
    derived from the entry's and the session's, so it arrives once."""
    agent_step_id = derived_id(entry.id, entry.created_at, f"recall:{agent_session_id}")
    return AgentStep(
        id=agent_step_id,
        created_at=now,
        agent_session_id=agent_session_id,
        loop_id=agent_step_id,
        type=AgentStepType.EVENT,
        actor=Actor.EXTERNAL,
        origin=Origin.ENGINE,
        header=InputHeader(waking=False, principal=principal),
        content=Content(blocks=(TextBlock(text=f"agent knowledge: {entry.title}\n{entry.text}"),)),
    )
