"""The agent knowledge swimlane over the engine's managers, as a root builds it.

    agent_knowledge = build_agent_knowledge(storage, managers)

A root that runs loops wraps its loop's hooks in the layer, so a session
recalls what its subject triggers before its first model call, and hands
the agents' agent knowledge tools its manager, which answers once it is
built:

    layer = AgentKnowledgeLayer(storage)
    options = PlatformRootOptions(
        loop_hooks=layer.loop_hooks(hooks), agent_knowledge=layer.manager
    )
    managers = build_platform_managers(storage, infra, ..., platform_root_options=options)
    agent_knowledge = layer.build(managers)

A session's agent project is read from the agent projects' rows."""

from collections.abc import Callable
from datetime import datetime

from acme.om.agent_knowledge.impl.hooks import LoopHooksRecallImpl
from acme.om.agent_knowledge.impl.manager import AgentKnowledgeManagerImpl, AgentKnowledgeOptions
from acme.om.agent_knowledge.manager import AgentKnowledgeManagerInterface
from acme.om.agent_projects.impl.policies import SessionAgentProjectsBoundImpl
from acme.om.agents.hooks import LoopHooksInterface
from acme.om.base import utcnow
from acme.om.levers.rules import reach_of
from acme.om.platform_root import PlatformManagers
from acme.om.storage.root import StorageInterface


def build_agent_knowledge(
    storage: StorageInterface,
    managers: PlatformManagers,
    *,
    options: AgentKnowledgeOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> AgentKnowledgeManagerInterface:
    return AgentKnowledgeManagerImpl(
        storage.get_agent_knowledge_storage(),
        managers.agent_sessions,
        SessionAgentProjectsBoundImpl(storage.get_agent_project_storage()),
        managers.tenancy,
        managers.outbox,
        options or AgentKnowledgeOptions(),
        reach_of(managers.kinds),
        clock,
    )


class AgentKnowledgeLayer:
    def __init__(
        self,
        storage: StorageInterface,
        *,
        options: AgentKnowledgeOptions | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._options = options
        self._clock = clock
        self._built: tuple[AgentKnowledgeManagerInterface, PlatformManagers] | None = None

    def loop_hooks(self, inner: LoopHooksInterface) -> LoopHooksInterface:
        """The loop's hooks beneath, recalling a session's agent knowledge
        before its first model call."""
        return LoopHooksRecallImpl(
            inner,
            lambda: self._managers()[0],
            lambda: self._managers()[1].agent_sessions,
            lambda: self._managers()[1].agent_steps,
        )

    def build(self, managers: PlatformManagers) -> AgentKnowledgeManagerInterface:
        """The agent knowledge manager over the engine's, once; built again, the same."""
        if self._built is None:
            agent_knowledge = build_agent_knowledge(
                self._storage, managers, options=self._options, clock=self._clock
            )
            self._built = (agent_knowledge, managers)
        return self._built[0]

    def manager(self) -> AgentKnowledgeManagerInterface:
        """The agent knowledge manager, once `build` has built it: what the agents'
        agent knowledge tools call."""
        return self._managers()[0]

    def _managers(self) -> tuple[AgentKnowledgeManagerInterface, PlatformManagers]:
        if self._built is None:
            raise RuntimeError("the agent knowledge layer is used before its manager is built")
        return self._built
