import logging
from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.base import Platform
from acme.om.context import OperatorContext, OperatorPermission
from acme.om.exceptions import ValidationFailed
from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.levers.manager import LeversManagerInterface
from acme.om.levers.rules import id_floor, spin_of, standings
from acme.om.levers.types.lever import LeverKind, LeverReading, LeverRef, SessionLevers
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.steps.storage import StepStorageInterface
from acme.om.trust.types.shape import StepShape, shape_of

log = logging.getLogger(__name__)


class LeversOptions(Platform):
    # The most sessions one reading reads, newest first; past it, the
    # reading says it is not complete.
    sessions: int = Field(default=200, gt=0)
    # The most steps of one session it reads, a page at a time.
    steps: int = Field(default=10_000, gt=0)
    page: int = Field(default=500, gt=0)
    # The most playbooks, and knowledge entries, of one session it names.
    levers: int = Field(default=50, gt=0)
    # The most sessions a standing names behind its figure.
    named: int = Field(default=20, gt=0)


class LeversManagerImpl(LeversManagerInterface):
    """`shapes` is the history as it lies at rest, read for its headers and
    never opened, as the operator's shape of a session is."""

    def __init__(
        self,
        sessions: AgentSessionStorageInterface,
        shapes: StepStorageInterface,
        playbooks: PlaybookStorageInterface,
        knowledge: KnowledgeStorageInterface,
        options: LeversOptions,
    ) -> None:
        self._sessions = sessions
        self._shapes = shapes
        self._playbooks = playbooks
        self._knowledge = knowledge
        self._options = options

    async def read_levers(
        self, admin: OperatorContext, org_id: UUID, since: datetime, until: datetime
    ) -> LeverReading:
        admin.require(OperatorPermission.READ)
        if since >= until:
            raise ValidationFailed("a reading's window ends after it starts")
        log.info(
            "operator reading of a tenant's levers",
            extra={"org_id": str(org_id), "operator": str(admin.identity_id)},
        )
        read: list[SessionLevers] = []
        complete = True
        # Newest first, from the window's end: ids are minted in time order.
        after: UUID | None = id_floor(until)
        while after is not None:
            page = await self._sessions.read_sessions(org_id, None, after, self._options.page)
            after = page[-1].id if len(page) == self._options.page else None
            for session in page:
                if session.created_at < since:
                    after = None
                    break
                if session.created_at >= until:
                    continue
                if len(read) == self._options.sessions:
                    complete, after = False, None
                    break
                levers, whole = await self._session(org_id, session)
                read.append(levers)
                complete = complete and whole
        return LeverReading(
            since=since,
            until=until,
            sessions=len(read),
            spun=sum(1 for session in read if session.spin.spun),
            complete=complete,
            standings=standings(read, self._options.named),
        )

    async def _session(self, org_id: UUID, session: AgentSession) -> tuple[SessionLevers, bool]:
        """One session's stall and levers, and whether every step was read."""
        shapes: list[StepShape] = []
        whole = True
        while True:
            after_seq = shapes[-1].seq if shapes else 0
            room = self._options.steps - len(shapes)
            if room <= 0:
                whole = False
                break
            rows = await self._shapes.read_steps(
                org_id, session.id, after_seq, min(self._options.page, room)
            )
            shapes.extend(shape_of(step) for step in rows)
            if len(rows) < min(self._options.page, room):
                break
        # A lever is answered by its kind, its id, and its version alone: its
        # name or its slug is the tenant's words, which `read` never sees.
        levers = [
            LeverRef(kind=LeverKind.PLAYBOOK, id=invocation.playbook_id, version=invocation.version)
            for invocation in await self._playbooks.read_invocations(
                org_id, session.id, self._options.levers
            )
        ]
        levers += [
            LeverRef(kind=LeverKind.KNOWLEDGE, id=recall.entry_id, version=recall.version)
            for recall in await self._knowledge.read_recalls(
                org_id, session.id, self._options.levers
            )
        ]
        return SessionLevers(
            session_id=session.id, spin=spin_of(shapes), levers=tuple(levers)
        ), whole
