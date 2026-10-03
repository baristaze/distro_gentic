"""The knowledge swimlane over the engine's managers, as a root builds it.

    knowledge = build_knowledge(storage, managers)

A root that runs loops wraps its tools in the layer, so a session recalls
what its subject triggers as its first loop starts:

    layer = KnowledgeLayer(storage)
    managers = build_managers(storage, infra, ..., tools_layer=layer.tools)
    knowledge = layer.build(managers)"""

from collections.abc import Callable
from datetime import datetime

from acme.om.base import utcnow
from acme.om.knowledge.impl.manager import KnowledgeManagerImpl, KnowledgeOptions
from acme.om.knowledge.impl.tools import ToolsManagerRecallImpl
from acme.om.knowledge.manager import KnowledgeManagerInterface
from acme.om.root import Managers
from acme.om.storage.root import StorageInterface
from acme.om.tools.manager import ToolsManagerInterface


def build_knowledge(
    storage: StorageInterface,
    managers: Managers,
    *,
    options: KnowledgeOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> KnowledgeManagerInterface:
    return KnowledgeManagerImpl(
        storage.get_knowledge_storage(),
        managers.agent_sessions,
        managers.tenancy,
        managers.outbox,
        options or KnowledgeOptions(),
        clock,
    )


class KnowledgeLayer:
    def __init__(
        self,
        storage: StorageInterface,
        *,
        options: KnowledgeOptions | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._options = options
        self._clock = clock
        self._built: tuple[KnowledgeManagerInterface, Managers] | None = None

    def tools(self, inner: ToolsManagerInterface) -> ToolsManagerInterface:
        """The tools manager beneath, recalling a session's knowledge as its
        first loop prepares the workspace."""
        return ToolsManagerRecallImpl(
            inner,
            lambda: self._managers()[0],
            lambda: self._managers()[1].agent_sessions,
            lambda: self._managers()[1].steps,
        )

    def build(self, managers: Managers) -> KnowledgeManagerInterface:
        """The knowledge manager over the engine's, once; built again, the same."""
        if self._built is None:
            knowledge = build_knowledge(
                self._storage, managers, options=self._options, clock=self._clock
            )
            self._built = (knowledge, managers)
        return self._built[0]

    def _managers(self) -> tuple[KnowledgeManagerInterface, Managers]:
        if self._built is None:
            raise RuntimeError("the knowledge layer is used before its manager is built")
        return self._built
