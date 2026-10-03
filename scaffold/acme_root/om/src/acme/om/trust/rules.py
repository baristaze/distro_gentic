"""Pure rules of trust: the four answers of a tool call, read each from its
own source; where a secret may be resolved, given the session's wall and
its project; and
whether an operator's content grant holds. Values in, values out; no
clock, no storage."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.transports import SecretUse, SecretVia
from acme.om.attribution.types.principal import Principal
from acme.om.steps.types.header import ModelRequestHeader, ToolRequestHeader
from acme.om.steps.types.step import Step
from acme.om.trust.types.grant import ContentGrant
from acme.om.trust.types.identities import ActorRef, CallAudit, Executor
from acme.om.trust.types.secret import SecretDeclaration, SecretOwnerKind, SecretStore


def call_audit(
    request: Step, model_request: Step, principal: Principal, executor: Executor
) -> CallAudit:
    """The audit entry of a tool call, each answer from its own source: the
    actor from the tool request (the agent that asked), the principal from
    the context the call runs under (which a take-over may have moved since
    the request was written), the spender from the model request whose
    response asked for the call, and the executor from the machine that runs
    it. `ValueError` when either step is not what it is named, or when an
    answer would stand for another."""
    header = request.header
    if not isinstance(header, ToolRequestHeader):
        raise ValueError(f"step {request.id} is not a tool request")
    paid = model_request.header
    if not isinstance(paid, ModelRequestHeader):
        raise ValueError(f"step {model_request.id} is not a model request")
    return CallAudit(
        request_id=request.id,
        session_id=request.session_id,
        tool=header.tool,
        executor=executor,
        principal=principal,
        spender=paid.spender,
        actor=ActorRef(actor=request.actor, agent=header.agent),
    )


def store_of(declaration: SecretDeclaration | None) -> SecretStore:
    """The store a secret is resolved from. One the tenant never declared is
    resolved where the engine resolves every secret, the platform's own
    store, so it is a cloud secret."""
    return SecretStore.CLOUD if declaration is None else declaration.store


def crossing(
    use: SecretUse,
    declaration: SecretDeclaration | None,
    *,
    inside_wall: bool,
    project_id: UUID | None,
) -> str | None:
    """Why a command may not use `use` in a session on this side of a wall,
    of the project `project_id`, or None when it may. A project's secret
    reaches that project's sessions alone, never a session of another
    project or of none. A cloud secret never reaches a customer's host, and
    a secret held inside the wall never crosses into the cloud. An injected
    secret lands in the variable its declaration names, or not at all. The
    reason names the secret and never its value."""
    if (
        declaration is not None
        and declaration.owner_kind is SecretOwnerKind.PROJECT
        and declaration.owner_id != project_id
    ):
        return f"{use.name} is declared on another project, and never reaches this session"
    store = store_of(declaration)
    if inside_wall and store is SecretStore.CLOUD:
        return f"{use.name} is a cloud secret, and never reaches a customer's host"
    if not inside_wall and store is SecretStore.HOST:
        return f"{use.name} is held inside a customer's wall, and never crosses into the cloud"
    if (
        declaration is not None
        and use.via is SecretVia.INJECTED
        and use.env != declaration.variable
    ):
        return f"{use.name} is declared for {declaration.variable}, never {use.env}"
    return None


def first_crossing(
    uses: Sequence[SecretUse],
    declarations: Mapping[str, SecretDeclaration],
    *,
    inside_wall: bool,
    project_id: UUID | None,
) -> str | None:
    """The first of `uses` that may not be used on this side of the wall, in
    a session of the project `project_id`, with its reason; None when every
    one may."""
    for use in uses:
        refusal = crossing(
            use, declarations.get(use.name), inside_wall=inside_wall, project_id=project_id
        )
        if refusal is not None:
            return refusal
    return None


def grant_holds(grant: ContentGrant | None, at: datetime) -> bool:
    """Whether a content grant opens content at `at`: one exists and has not
    expired."""
    return grant is not None and grant.created_at <= at < grant.expires_at


def grant_expiry(
    at: datetime, asked: timedelta | None, default: timedelta, bound: timedelta
) -> datetime:
    """When a grant made at `at` expires: what was asked, else the default,
    and never later than the bound. `ValueError` for a lifetime that is not
    positive or passes the bound."""
    lifetime = default if asked is None else asked
    if lifetime <= timedelta(0) or lifetime > bound:
        raise ValueError(f"a content grant lasts more than nothing and at most {bound}")
    return at + lifetime


def used_since(last_used_at: datetime | None, at: datetime, granularity: timedelta) -> bool:
    """Whether a key's use at `at` is worth writing down: never used, or last
    written at least `granularity` before."""
    return last_used_at is None or at - last_used_at >= granularity
