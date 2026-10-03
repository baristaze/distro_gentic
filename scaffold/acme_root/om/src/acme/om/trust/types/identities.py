"""Who stands behind one act, in four answers: the machine that ran it (the
executor), on whose authority it ran (the principal), who paid for the
model call that chose it (the spender), and who acted (the actor). The
engine names the last three on its steps; the platform adds the first, a
machine's credential. Each is a field of its own, read from its own
source, and none stands for another."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.attribution.types.principal import AgentRef, Principal
from acme.om.base import Platform
from acme.om.steps.types.content import MAX_NAME, Stored
from acme.om.steps.types.step import Actor


class ExecutorKind(StrEnum):
    """What kind of machine holds the credential that ran an act."""

    CLOUD = "cloud"  # a machine of the platform's own pool, in its cloud
    HOST = "host"  # a workspace host inside a customer's wall


class Executor(Platform):
    """A machine's credential: its kind, the id of the credential it ran
    under, and what the machine is called (a host's name, a runner's id). It
    names a machine, never a person and never a key a person speaks
    through, so it lends no authority and pays for nothing."""

    kind: ExecutorKind
    credential_id: UUID
    label: Stored = Field(min_length=1, max_length=MAX_NAME)


class ActorRef(Platform):
    """Who acted, as the step that records the act says: its actor, and the
    agent with its kind and session when the actor is an agent."""

    actor: Actor
    agent: AgentRef | None = None

    @model_validator(mode="after")
    def _an_agent_is_named(self) -> Self:
        if (self.actor is Actor.AGENT) != (self.agent is not None):
            raise ValueError("an agent's act names the agent, and no other act names one")
        return self


class CallAudit(Platform):
    """The audit entry of one tool call: the four answers, apart.

    The actor is the agent that asked for the call, never its principal. The
    principal is whom the call ran under. The spender paid for the model
    request whose response asked for the call. The executor is the machine
    that ran it. A machine's credential that stands for a person or a key is
    refused here, so no entry is written with one answer in two fields."""

    request_id: UUID
    session_id: UUID
    tool: Stored = Field(min_length=1, max_length=MAX_NAME)
    executor: Executor
    principal: Principal
    spender: Principal
    actor: ActorRef

    @model_validator(mode="after")
    def _four_apart(self) -> Self:
        if self.actor.actor is not Actor.AGENT or self.actor.agent is None:
            raise ValueError("a tool call is the agent's act, never its principal's")
        if self.actor.agent.session_id != self.session_id:
            raise ValueError("a tool call is the act of its own session's agent")
        people = {self.principal.id, self.spender.id}
        keys = {key for key in (self.principal.key_id, self.spender.key_id) if key is not None}
        if self.executor.credential_id in people | keys:
            raise ValueError("a machine's credential stands for no person and no key")
        return self
