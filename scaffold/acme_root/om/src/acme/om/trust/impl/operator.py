import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.context import OperatorContext, OperatorPermission, RequestContext
from acme.om.events.storage import EventStorageInterface
from acme.om.events.types.event import Event
from acme.om.exceptions import NotFound, ValidationFailed
from acme.om.steps.storage import StepStorageInterface
from acme.om.steps.types.page import StepPage
from acme.om.trust.exceptions import ContentNotGranted
from acme.om.trust.impl.manager import TrustOptions
from acme.om.trust.operator import TrustOperatorManagerInterface
from acme.om.trust.rules import grant_expiry, grant_holds
from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.types.grant import ContentGrant
from acme.om.trust.types.shape import ShapePage, shape_of

log = logging.getLogger(__name__)

CONTENT_OPENED = "trust.session.content_opened"
GRANTED = "trust.content_grant.granted"
REVOKED = "trust.content_grant.revoked"


class TrustOperatorManagerImpl(TrustOperatorManagerInterface):
    """`shapes` is the history as it lies at rest, read for its headers and
    never opened; `history` is the history opened by each session's key, as
    the engine reads it. Only a content grant reaches the second."""

    def __init__(
        self,
        storage: TrustStorageInterface,
        sessions: AgentSessionStorageInterface,
        shapes: StepStorageInterface,
        history: StepStorageInterface,
        events: EventStorageInterface,
        options: TrustOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._sessions = sessions
        self._shapes = shapes
        self._history = history
        self._events = events
        self._options = options
        self._clock = clock

    async def get_session_shape(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID, after_seq: int, limit: int
    ) -> ShapePage:
        admin.require(OperatorPermission.READ)
        await self._held(org_id, session_id)
        log.info(
            "operator read of a session's shape",
            extra={"org_id": str(org_id), "operator": str(admin.identity_id)},
        )
        bounded = self._bounded(limit)
        rows = await self._shapes.read_steps(org_id, session_id, max(0, after_seq), bounded + 1)
        return ShapePage(
            items=tuple(shape_of(step) for step in rows[:bounded]), has_more=len(rows) > bounded
        )

    async def get_session_content(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID, after_seq: int, limit: int
    ) -> StepPage:
        admin.require(OperatorPermission.READ)
        grant = await self._storage.read_grant(org_id, admin.identity_id)
        if not grant_holds(grant, self._clock()):
            raise ContentNotGranted("opening a session's content takes a grant in its tenant")
        await self._held(org_id, session_id)
        log.info(
            "operator read of a session's content",
            extra={"org_id": str(org_id), "operator": str(admin.identity_id)},
        )
        # The tenant sees each opening in its own stream, before anything is
        # opened: an opening that fails is still on the record.
        await self._audit(
            admin,
            org_id,
            CONTENT_OPENED,
            session_id,
            {"session_id": str(session_id), "operator": str(admin.identity_id)},
            actor_id=admin.identity_id,
        )
        bounded = self._bounded(limit)
        rows = await self._history.read_steps(org_id, session_id, max(0, after_seq), bounded + 1)
        return StepPage(items=tuple(rows[:bounded]), has_more=len(rows) > bounded)

    async def grant_content(
        self,
        rctx: RequestContext,
        identity_id: UUID,
        org_id: UUID,
        expires_in: timedelta | None = None,
    ) -> ContentGrant:
        now = self._clock()
        try:
            expires_at = grant_expiry(
                now, expires_in, self._options.grant_lifetime, self._options.grant_bound
            )
        except ValueError as error:
            raise ValidationFailed(str(error)) from error
        grant = await self._storage.write_grant(
            org_id,
            ContentGrant(
                id=new_id(), created_at=now, identity_id=identity_id, expires_at=expires_at
            ),
        )
        await self._audit(
            rctx,
            org_id,
            GRANTED,
            grant.id,
            {"operator": str(identity_id), "expires_at": expires_at.isoformat()},
            actor_id=EMPTY_UUID,
        )
        return grant

    async def revoke_content(self, rctx: RequestContext, identity_id: UUID, org_id: UUID) -> bool:
        revoked = await self._storage.delete_grant(org_id, identity_id)
        if revoked:
            await self._audit(
                rctx,
                org_id,
                REVOKED,
                identity_id,
                {"operator": str(identity_id)},
                actor_id=EMPTY_UUID,
            )
        return revoked

    async def _held(self, org_id: UUID, session_id: UUID) -> None:
        """A session the tenant holds, deleted or not: an operator reads what
        the tenant still keeps."""
        if await self._sessions.read_session(org_id, session_id) is None:
            raise NotFound(f"agent session {session_id} is not in {org_id}")

    async def _audit(
        self,
        rctx: RequestContext,
        org_id: UUID,
        kind: str,
        target_id: UUID,
        facts: dict[str, str],
        *,
        actor_id: UUID,
    ) -> None:
        """An entry in the tenant's stream, naming who acted: the operator, or
        the platform for the grant job, which acts for no person."""
        await self._events.append_events(
            org_id,
            [
                Event(
                    id=new_id(),
                    org_id=org_id,
                    kind=kind,
                    target_id=target_id,
                    payload=facts,
                    produced_at=utcnow(),
                    actor_id=actor_id,
                    request_id=rctx.request_id,
                    app=rctx.app.type.value,
                )
            ],
        )

    def _bounded(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_page))
