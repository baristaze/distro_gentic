"""The playbooks swimlane over the engine's managers: the layer a root wraps
its tools in, so a session's playbook gates hold around every call, and
the playbooks manager built over the managers it returns.

    layer = PlaybooksLayer(storage)
    managers = build_managers(storage, infra, ..., tools_layer=layer.tools)
    playbooks = layer.build(managers)

A root with another layer composes the two: `lambda inner:
layer.tools(other.tools(inner))`."""

from collections.abc import Callable
from datetime import datetime

from acme.om.base import utcnow
from acme.om.playbooks.impl.manager import PlaybooksManagerImpl, PlaybooksOptions
from acme.om.playbooks.impl.tools import ToolsManagerPlaybooksImpl
from acme.om.playbooks.manager import PlaybooksManagerInterface
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

    def build(self, managers: Managers) -> PlaybooksManagerInterface:
        """The playbooks manager over the engine's, once; built again, the same."""
        if self._built is None:
            playbooks = PlaybooksManagerImpl(
                self._storage.get_playbook_storage(),
                managers.agent_sessions,
                managers.agents,
                managers.tenancy,
                managers.outbox,
                self.options,
                self._clock,
            )
            self._built = (playbooks, managers.steps)
        return self._built[0]

    def _managers(self) -> tuple[PlaybooksManagerInterface, StepsManagerInterface]:
        if self._built is None:
            raise RuntimeError("the playbooks layer is used before its manager is built")
        return self._built
