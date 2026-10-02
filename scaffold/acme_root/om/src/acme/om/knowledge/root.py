"""The knowledge swimlane over the engine's managers, as a root builds it.

knowledge = build_knowledge(storage, managers)"""

from collections.abc import Callable
from datetime import datetime

from acme.om.base import utcnow
from acme.om.knowledge.impl.manager import KnowledgeManagerImpl, KnowledgeOptions
from acme.om.knowledge.manager import KnowledgeManagerInterface
from acme.om.root import Managers
from acme.om.storage.root import StorageInterface


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
