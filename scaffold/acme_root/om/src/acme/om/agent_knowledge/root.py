"""The agent knowledge swimlane over the engine's managers, as a root builds it.

    agent_knowledge = build_agent_knowledge(storage, managers)

A root that runs loops wraps its tools in the layer, so a session recalls
what its subject triggers as its first loop starts, and hands the agents'
agent knowledge tools its manager, which answers once it is built:

    layer = AgentKnowledgeLayer(storage)
    options = PlatformRootOptions(tools_layer=layer.tools, agent_knowledge=layer.manager)
    managers = build_platform_managers(storage, infra, ..., platform_root_options=options)
    agent_knowledge = layer.build(managers)

A session's agent project is read from the agent projects' rows."""

from collections.abc import Callable
from datetime import datetime

from acme.om.agent_knowledge.impl.manager import AgentKnowledgeManagerImpl, AgentKnowledgeOptions
from acme.om.agent_knowledge.impl.tools import ToolsManagerRecallImpl
from acme.om.agent_knowledge.manager import AgentKnowledgeManagerInterface
from acme.om.agent_projects.impl.policies import SessionAgentProjectsBoundImpl
from acme.om.base import utcnow
from acme.om.levers.rules import reach_of
from acme.om.platform_root import PlatformManagers
from acme.om.storage.root import StorageInterface
from acme.om.tools.manager import ToolsManagerInterface


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

    def tools(self, inner: ToolsManagerInterface) -> ToolsManagerInterface:
        """The tools manager beneath, recalling a session's agent knowledge as its
        first loop prepares the workspace."""
        return ToolsManagerRecallImpl(
            inner,
            lambda: self._managers()[0],
            lambda: self._managers()[1].agent_sessions,
            lambda: self._managers()[1].steps,
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
