"""The playbooks swimlane over the engine's managers: the layer a root wraps
its tools in, so a session's playbook gates hold around every call, the
layer it wraps its agents in, so each new session is made with its kind's
manual, and the playbooks manager built over the managers it returns.

    layer = PlaybooksLayer(storage)
    managers = build_managers(
        storage, infra, ..., tools_layer=layer.tools, agents_layer=layer.agents
    )
    playbooks = layer.build(managers)

A root with another tools layer composes the two: `lambda inner:
layer.tools(other.tools(inner))`. A root that makes sessions and runs no
loop takes the agents layer alone."""

from collections.abc import Callable
from datetime import datetime

from acme.om.agents import AgentsManagerInterface
from acme.om.base import utcnow
from acme.om.levers.rules import reach_of
from acme.om.playbooks.impl.agents import AgentsManagerManualImpl
from acme.om.playbooks.impl.manager import PlaybooksManagerImpl, PlaybooksOptions
from acme.om.playbooks.impl.tools import ToolsManagerPlaybooksImpl
from acme.om.playbooks.manager import PlaybooksManagerInterface
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.root import Managers
from acme.om.steps import StepsManagerInterface
from acme.om.storage.root import StorageInterface
from acme.om.tools.manager import ToolsManagerInterface


class PlaybooksLayer:
    def __init__(
        self,
        storage: StorageInterface,
        *,
        options: PlaybooksOptions | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self.options = options or PlaybooksOptions()
        self._clock = clock
        self._built: tuple[PlaybooksManagerInterface, StepsManagerInterface] | None = None

    def tools(self, inner: ToolsManagerInterface) -> ToolsManagerInterface:
        """The tools manager beneath, held to each session's playbook gates."""
        return ToolsManagerPlaybooksImpl(
            inner, lambda: self._managers()[0], lambda: self._managers()[1], self._clock
        )

    def agents(self, inner: AgentsManagerInterface) -> AgentsManagerInterface:
        """The agents manager beneath, each new session made with its kind's
        manual."""
        return AgentsManagerManualImpl(
            inner,
            self._storage.get_playbook_storage(),
            self._storage.get_agent_session_storage(),
            SessionProjectsBoundImpl(self._storage.get_project_storage()),
            self.options.per_session,
            self._clock,
        )

    def build(self, managers: Managers) -> PlaybooksManagerInterface:
        """The playbooks manager over the engine's, once; built again, the same."""
        if self._built is None:
            playbooks = PlaybooksManagerImpl(
                self._storage.get_playbook_storage(),
                managers.agent_sessions,
                self._storage.get_agent_session_storage(),
                managers.agents,
                managers.tenancy,
                managers.outbox,
                self.options,
                reach_of(managers.kinds),
                managers.kinds,
                SessionProjectsBoundImpl(self._storage.get_project_storage()),
                self._clock,
            )
            self._built = (playbooks, managers.steps)
        return self._built[0]

    def _managers(self) -> tuple[PlaybooksManagerInterface, StepsManagerInterface]:
        if self._built is None:
            raise RuntimeError("the playbooks layer is used before its manager is built")
        return self._built
