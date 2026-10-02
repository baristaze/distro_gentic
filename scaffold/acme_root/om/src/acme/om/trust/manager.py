"""The trust swimlane: who stands behind each act and what crosses a
customer's wall.

It writes the audit entry of every tool call with its four answers apart:
the machine that ran it, whom it ran under, who paid for the model call
that chose it, and the agent that asked. It lets a person take over a
steady session whose principal no longer holds, and wakes it. It keeps the
tenant's secrets by name, where each is held, and refuses a call whose
secrets would cross the session's wall. And it keeps the tenant's own
provider keys by reference, never shown."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.infra.transports import SecretUse
from acme.integrations.model_providers.types import ProviderName
from acme.om.attribution.types.authority import SessionAuthority
from acme.om.context import TenantContext
from acme.om.steps.types.step import Step
from acme.om.trust.types.identities import CallAudit
from acme.om.trust.types.provider_key import ProviderKey
from acme.om.trust.types.secret import SecretDeclaration


class TrustManagerInterface(ABC):
    # Four identities.

    @abstractmethod
    async def audit_call(self, ctx: TenantContext, request: Step) -> CallAudit:
        """Writes the audit entry of a tool call, before it runs, under the
        context the call runs under, its principal's: the executor the
        session's placement answers, that principal, the agent the request
        names, and the spender of the model request whose response asked for
        the call, read back from the history. One entry a request: asked again, it writes
        nothing new. `ValidationFailed` for a step that is no tool request,
        or one whose model request the history does not hold."""
        ...

    @abstractmethod
    async def assign_principal(self, ctx: TenantContext, session_id: UUID) -> SessionAuthority:
        """The caller takes a session over, as attribution's take-over does,
        and a session parked because its principal no longer held is woken,
        so its calls run under the caller from its next run. A session parked
        for anything else stays parked."""
        ...

    # Secrets by placement.

    @abstractmethod
    async def declare_secret(
        self, ctx: TenantContext, declaration: SecretDeclaration
    ) -> SecretDeclaration:
        """Declares a secret by name, as one who writes the tenant's own
        configuration may (`manage_members`, ADR 2010): its variable, its scope, what it is declared on, and the store
        that holds it. The same declaration made again is answered as
        stored; another under a name taken is `Conflict`. No value is taken
        here."""
        ...

    @abstractmethod
    async def get_secrets(
        self, ctx: TenantContext, after: str | None, limit: int
    ) -> tuple[SecretDeclaration, ...]:
        """The tenant's declarations by name, after `after`, at most `limit`:
        names and where each is held, never a value."""
        ...

    @abstractmethod
    async def put_secret(self, ctx: TenantContext, name: str, value: str) -> SecretDeclaration:
        """Writes the value of a declared cloud secret into the platform's
        store, as one who writes the tenant's configuration may. A secret held inside
        a customer's wall never takes its value here
        (`SecretCrossesWall`): its host's store holds it. `NotFound` for a
        name never declared."""
        ...

    @abstractmethod
    async def refuse_crossing(
        self, ctx: TenantContext, session_id: UUID, uses: Sequence[SecretUse]
    ) -> None:
        """Refuses (`SecretCrossesWall`) secrets that would be resolved on the
        far side of the session's wall: a cloud secret, or one never declared,
        for a session inside a customer's wall; a secret held inside the wall
        for a session in the cloud; an injected one aimed at a variable its
        declaration does not name. Returns when every one may be used."""
        ...

    # The tenant's provider keys.

    @abstractmethod
    async def save_provider_key(
        self, ctx: TenantContext, provider: ProviderName, value: str
    ) -> ProviderKey:
        """Saves the tenant's own key to `provider`, as one who writes the
        tenant's configuration may: probed first, and refused (`KeyRefused`) when the provider
        does not take it. A key saved mints a new reference and becomes the
        live one; the key it replaces is marked rotated and its value leaves
        the store. Answers the record, which never holds the value."""
        ...

    @abstractmethod
    async def get_provider_keys(self, ctx: TenantContext, limit: int) -> tuple[ProviderKey, ...]:
        """The tenant's keys, newest first, at most `limit`: who added each,
        when, its state, and when it was last used, never a value."""
        ...

    # The sweep.

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its
        declarations, its keys' records, and its content grants, a batch at
        most a call. Any other tenant returns 0 and reads nothing."""
        ...
