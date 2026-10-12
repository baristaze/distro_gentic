"""What a session may call beyond its kind: toolsets an adopter attaches to
the session, held from the start or deferred, with the tools they hold.

A kind is the product's, one version shared by every tenant. A toolset
attached to a session is one tenant's own, a connector to its own server
say, so it rides on the session and never on the kind. The loop asks once a
run, before it renders anything, and reads the session's kind with the
attached toolsets folded in: held ones join its registry, deferred ones its
`load_toolset` line, and a load of one is recorded as any load is (ADR
1031). An adopter answers the same for a session for its whole life, so its
tool definitions keep their bytes and its cached prefix holds."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents.types.kind import AgentKind
from acme.om.context import TenantContext
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.toolset import LOAD_TOOLSET, Toolset


@dataclass(frozen=True)
class Attached:
    """The toolsets a session holds beyond its kind's, and a tool for each
    name they hold. `held` joins the registry from the start; `deferred`
    waits for a load. Each tool is named by exactly one of them."""

    held: tuple[Toolset, ...] = ()
    deferred: tuple[Toolset, ...] = ()
    tools: tuple[ToolInterface, ...] = ()

    def __post_init__(self) -> None:
        named = [tool for toolset in (*self.held, *self.deferred) for tool in toolset.tools]
        given = [tool.spec.name for tool in self.tools]
        if len(set(named)) != len(named) or sorted(named) != sorted(given):
            raise ValueError("an attached toolset's tools are given once, each by one toolset")

    @property
    def names(self) -> tuple[str, ...]:
        """Every tool a session may come to call through them, `load_toolset`
        included when one is deferred."""
        load = (LOAD_TOOLSET,) if self.deferred else ()
        return (*(tool.spec.name for tool in self.tools), *load)


NOTHING = Attached()


def with_attached(kind: AgentKind, attached: Attached) -> AgentKind:
    """`kind` with the attached toolsets folded in, as a kind declared with
    them would be: its tools, its waiting tools, and its `load_toolset`
    line. Nothing attached is the kind itself."""
    if attached == NOTHING:
        return kind
    return AgentKind.model_validate(
        {
            **dict(kind),
            "toolsets": (*kind.toolsets, *attached.held),
            "deferred": (*kind.deferred, *attached.deferred),
        }
    )


class AttachedToolsetsInterface(ABC):
    @abstractmethod
    async def of(self, ctx: TenantContext, session: AgentSession) -> Attached:
        """What `session` holds beyond its kind: the same answer every time
        it is asked for the same session. None of its toolsets shares a name
        with one its kind names, and none of its tools a name with a tool of
        the catalog."""
        ...


class AttachedToolsetsNoneImpl(AttachedToolsetsInterface):
    """An adopter that attaches nothing: every session holds its kind's."""

    async def of(self, ctx: TenantContext, session: AgentSession) -> Attached:
        return NOTHING
