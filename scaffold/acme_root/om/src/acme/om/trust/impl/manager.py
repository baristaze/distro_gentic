from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field

from acme.infra.secrets import SecretsInterface
from acme.infra.transports import SecretUse
from acme.integrations.model_providers.types import ProviderName
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import ParkReason, ToolRequestHeader
from acme.om.attribution import AttributionManagerInterface
from acme.om.attribution.rules import PRINCIPAL_PARK, principal_of
from acme.om.attribution.types.authority import AgentSessionAuthority
from acme.om.base import OmBase, derived_id, new_id, utcnow
from acme.om.change_events import ChangeEventsManagerInterface
from acme.om.change_events.manager import audit_change_event
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import Conflict, NotFound, UniqueKeyTaken, ValidationFailed
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.tenancy import TenancyManagerInterface
from acme.om.trust.exceptions import SecretCrossesWall
from acme.om.trust.keys import KeyProbeInterface
from acme.om.trust.manager import TrustManagerInterface
from acme.om.trust.owners import SecretOwners
from acme.om.trust.placement import PlacementInterface
from acme.om.trust.rules import call_audit, first_crossing, key_unlocks
from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.types.identities import CallAudit
from acme.om.trust.types.provider_key import KeyStatus, ProviderKey, key_secret_name
from acme.om.trust.types.secret import (
    AGENT_PROJECT,
    SecretDeclaration,
    SecretStore,
    kept_as,
)

CALL_AUDITED = "trust.call.audited"
DECLARED = "trust.secret_declaration.created"
KEY_SAVED = "trust.provider_key.created"
KEY_ROTATED = "trust.provider_key.updated"


class TrustOptions(OmBase):
    # The steps one read of the history takes when it looks back from a call
    # for the model request that asked for it; it reads on until it finds it.
    read_back: int = Field(default=16, gt=0)
    # A key's use is written at most this often: its record says when it was
    # last used to this grain, and a model call costs no write.
    key_use_grain: timedelta = timedelta(minutes=5)
    # An operator's content grant lasts this long unless the grant job asks
    # for less, and never longer than the bound.
    grant_lifetime: timedelta = timedelta(hours=1)
    grant_bound: timedelta = timedelta(hours=8)
    # The most rows of each kind one purge call takes, and one operator read.
    purge_batch: int = Field(default=1000, gt=0)
    max_page: int = Field(default=200, gt=0)


class TrustManagerImpl(TrustManagerInterface):
    def __init__(
        self,
        storage: TrustStorageInterface,
        steps: AgentStepsManagerInterface,
        events: ChangeEventsManagerInterface,
        attribution: AttributionManagerInterface,
        sessions: AgentSessionsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        secrets: SecretsInterface,
        placement: PlacementInterface,
        owners: SecretOwners,
        probe: KeyProbeInterface,
        options: TrustOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._steps = steps
        self._change_events = events
        self._attribution = attribution
        self._sessions = sessions
        self._tenancy = tenancy
        self._relay = relay
        self._secrets = secrets
        self._placement = placement
        self._owners = owners
        self._probe = probe
        self._options = options
        self._clock = clock

    # Four identities.

    async def audit_call(self, ctx: TenantContext, request: AgentStep) -> CallAudit:
        ctx.require(Permission.WRITE)
        header = request.header
        if not isinstance(header, ToolRequestHeader) or not request.refs:
            raise ValidationFailed(f"step {request.id} is not a tool request")
        # The response that asked for the call, then the request it answers,
        # whose spender paid for the choice.
        response = await self._before(ctx, request.agent_session_id, request.refs[0], request.seq)
        if response.responds_to is None:
            raise ValidationFailed(f"step {response.id} answers no model request")
        asked = await self._before(
            ctx, request.agent_session_id, response.responds_to, response.seq
        )
        executor = await self._placement.executor_of(ctx.org_id, request.agent_session_id)
        try:
            # The call runs under the context it is handed: its principal's,
            # as the gate's authority answered it for this call.
            audit = call_audit(request, asked, principal_of(ctx), executor)
        except ValueError as error:
            raise ValidationFailed(f"tool request {request.id}: {error}") from error
        # One entry a request: a call run again after a crash finds its own.
        entry = audit_change_event(
            ctx,
            derived_id(request.id, request.created_at, "trust:call"),
            CALL_AUDITED,
            request.id,
            audit.model_dump(mode="json"),
        )
        await self._change_events.append_change_event(ctx, entry)
        return audit

    async def assign_principal(
        self, ctx: TenantContext, agent_session_id: UUID
    ) -> AgentSessionAuthority:
        ctx.require(Permission.WRITE)
        taken = await self._attribution.assign_principal(ctx, agent_session_id)
        await self._wake_on_principal(ctx, agent_session_id)
        await self._carry_down(ctx, agent_session_id)
        return taken

    # Secrets by placement.

    async def declare_secret(
        self, ctx: TenantContext, declaration: SecretDeclaration
    ) -> SecretDeclaration:
        ctx.require(Permission.MANAGE_MEMBERS)
        # A secret is declared on an owner of a registered kind the tenant
        # holds; a kind nobody registered owns nothing.
        owner = self._owners.get(declaration.owner_kind)
        if owner is None or not await owner.holds(ctx, declaration.owner_id):
            raise NotFound(f"no {declaration.owner_kind} {declaration.owner_id} of this tenant")
        now = self._clock()
        made = SecretDeclaration.model_validate(
            {
                **declaration.model_dump(),
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            }
        )
        rows = (versioned_row(ctx, DECLARED, made.id, 1),)
        try:
            landed = await self._storage.create_declaration(ctx.org_id, made, rows)
        except UniqueKeyTaken:
            landed = False
        stored = await self._storage.read_declaration(
            ctx.org_id, made.owner_kind, made.owner_id, made.name
        )
        if stored is None:
            raise Conflict(f"secret {made.name} was written under another id")
        if not landed and _declared(stored) != _declared(made):
            raise Conflict(f"secret {made.name} is declared already on its owner, otherwise")
        if landed:
            await self._relay_all(ctx, rows)
        return stored

    async def get_secrets(
        self, ctx: TenantContext, after: tuple[str, UUID] | None, limit: int
    ) -> tuple[SecretDeclaration, ...]:
        ctx.require(Permission.READ)
        bounded = max(1, min(limit, self._options.max_page))
        return tuple(await self._storage.read_declarations(ctx.org_id, after, bounded))

    async def put_secret(
        self,
        ctx: TenantContext,
        agent_project_id: UUID,
        name: str,
        value: str,
        *,
        owner_kind: str = AGENT_PROJECT,
    ) -> SecretDeclaration:
        ctx.require(Permission.MANAGE_MEMBERS)
        declaration = await self._storage.read_declaration(
            ctx.org_id, owner_kind, agent_project_id, name
        )
        if declaration is None:
            raise NotFound(f"no secret named {name} is declared on {owner_kind} {agent_project_id}")
        if declaration.store is not SecretStore.CLOUD:
            raise SecretCrossesWall(
                f"{name} is held inside a customer's wall; its host's store takes its value"
            )
        await self._secrets.put(ctx.org_id, kept_as(declaration), value, deadline=ctx.deadline)
        return declaration

    async def resolve_secrets(
        self, ctx: TenantContext, agent_session_id: UUID, uses: Sequence[SecretUse]
    ) -> dict[str, str]:
        ctx.require(Permission.READ)
        if not uses:
            return {}
        inside = await self._placement.inside_wall(ctx.org_id, agent_session_id)
        # A name means what the first owner the session is placed on declares
        # it as, in the registry's order: never what an owner it is not
        # placed on declares.
        placed = await self._owners.placed(ctx, agent_session_id)
        declared: dict[str, SecretDeclaration] = {}
        for use in uses:
            for kind, owner_id in placed.items():
                found = await self._storage.read_declaration(ctx.org_id, kind, owner_id, use.name)
                if found is not None:
                    declared[use.name] = found
                    break
        refusal = first_crossing(uses, declared, inside_wall=inside, placed=placed)
        if refusal is not None:
            raise SecretCrossesWall(refusal)
        # A secret held on a host is resolved there, by its name.
        return {
            name: kept_as(declaration)
            for name, declaration in declared.items()
            if declaration.store is SecretStore.CLOUD
        }

    # The tenant's provider keys.

    async def save_provider_key(
        self, ctx: TenantContext, provider: ProviderName, value: str
    ) -> ProviderKey:
        ctx.require(Permission.MANAGE_MEMBERS)
        # A key the provider refuses is never saved.
        await self._probe.probe(provider, value)
        now = self._clock()
        key = ProviderKey(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            provider=provider,
        )
        live = await self._storage.read_live_key(ctx.org_id, provider)
        rotated = (
            None
            if live is None
            else live.model_copy(
                update={
                    "status": KeyStatus.ROTATED,
                    "version": live.version + 1,
                    "updated_at": now,
                    "updated_by": ctx.user_id,
                }
            )
        )
        rows: tuple[OutboxRow, ...] = (versioned_row(ctx, KEY_SAVED, key.id, key.version),)
        if rotated is not None:
            rows += (versioned_row(ctx, KEY_ROTATED, rotated.id, rotated.version),)
        # The value under its new reference first: a record never names a
        # value the store does not hold. A crash before the commit leaves a
        # value no record names, and nothing serves it.
        await self._secrets.put(ctx.org_id, key_secret_name(key.id), value, deadline=ctx.deadline)
        try:
            await self._storage.create_key(ctx.org_id, key, rotated, rows)
        except Exception:
            await self._secrets.delete(ctx.org_id, key_secret_name(key.id), deadline=ctx.deadline)
            raise
        await self._relay_all(ctx, rows)
        if rotated is not None:
            # The rotated value leaves the store: nothing can resolve it again.
            await self._secrets.delete(
                ctx.org_id, key_secret_name(rotated.id), deadline=ctx.deadline
            )
        # The sessions that wait for a key to this provider, the org's missing
        # or refused one, go on with this one.
        for unlock in key_unlocks(provider):
            await self._sessions.wake_parked(ctx, ParkReason.PROVIDER, unlock)
        return key

    async def get_provider_keys(self, ctx: TenantContext, limit: int) -> tuple[ProviderKey, ...]:
        ctx.require(Permission.READ)
        bounded = max(1, min(limit, self._options.max_page))
        return tuple(await self._storage.read_keys(ctx.org_id, bounded))

    # The sweep.

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        batch = self._options.purge_batch
        # Each value leaves the store before the row that names it, and the
        # rows that go are exactly the ones whose values went: a value is
        # never left with nothing to find it by.
        keys = await self._storage.read_keys(ctx.org_id, batch)
        for key in keys:
            await self._secrets.delete(ctx.org_id, key_secret_name(key.id), deadline=ctx.deadline)
        gone = await self._storage.purge_keys(ctx.org_id, [key.id for key in keys])
        declared = await self._storage.read_declarations(ctx.org_id, None, batch)
        for declaration in declared:
            if declaration.store is SecretStore.CLOUD:
                await self._secrets.delete(ctx.org_id, kept_as(declaration), deadline=ctx.deadline)
        gone += await self._storage.purge_declarations(ctx.org_id, [d.id for d in declared])
        return gone + await self._storage.purge_grants(ctx.org_id, batch)

    # Helpers.

    async def _wake_on_principal(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        """Wakes a session parked because its principal no longer held; one
        parked for anything else stays parked."""
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        park = session.park
        if (
            park is not None
            and park.reason is ParkReason.PERSON
            and park.unlock == PRINCIPAL_PARK.unlock
        ):
            await self._sessions.wake_agent_session(ctx, agent_session_id, park)

    async def _carry_down(self, ctx: TenantContext, parent_id: UUID) -> None:
        """A take-over carries to the parent's sub-agents parked on their
        principal, and theirs: each follows its parent's principal and
        wakes. A sub-agent at work keeps its own until it parks, and a
        take-over of the parent again carries to it then."""
        after: UUID | None = None
        while True:
            page = await self._sessions.get_children(ctx, parent_id, after, self._options.max_page)
            for child in page.items:
                park = child.park
                if (
                    park is not None
                    and park.reason is ParkReason.PERSON
                    and park.unlock == PRINCIPAL_PARK.unlock
                ):
                    await self._attribution.follow_parent(ctx, child.id)
                    await self._sessions.wake_agent_session(ctx, child.id, park)
                await self._carry_down(ctx, child.id)
            if not page.has_more or not page.items:
                return
            after = page.items[-1].id

    async def _before(
        self, ctx: TenantContext, agent_session_id: UUID, agent_step_id: UUID, before_seq: int
    ) -> AgentStep:
        """The step `agent_step_id` of the session's history, read back from just
        before `before_seq`, a window at a time."""
        through = before_seq - 1
        while through > 0:
            after = max(0, through - self._options.read_back)
            page = await self._steps.get_agent_steps(ctx, agent_session_id, after, through - after)
            for step in page.items:
                if step.id == agent_step_id:
                    return step
            through = after
        raise ValidationFailed(f"step {agent_step_id} is not in the history of {agent_session_id}")

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        """The write has committed; a relay that fails is left to the sweep."""
        if rows:
            await self._relay.relay_all(ctx.org_id, rows)


def _declared(declaration: SecretDeclaration) -> tuple[object, ...]:
    """What a declaration says, its provenance aside."""
    return (
        declaration.name,
        declaration.variable,
        declaration.owner_kind,
        declaration.owner_id,
        declaration.scope,
        declaration.store,
    )
