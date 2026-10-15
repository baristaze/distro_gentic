"""The levers swimlane over storage, as a root builds it: the operator's
reading, over the history at rest, read for its headers and never opened.

    levers = build_levers(storage)

The checks are pure rules (`rules.py`): the agent playbooks and the agent knowledge
swimlanes run them as a person publishes, against the reach `reach_of`
reads from the managers' kinds."""

from acme.om.levers.impl.manager import LeversManagerImpl, LeversOptions
from acme.om.levers.manager import LeversManagerInterface
from acme.om.storage.root import StorageInterface


def build_levers(
    storage: StorageInterface, *, options: LeversOptions | None = None
) -> LeversManagerInterface:
    return LeversManagerImpl(
        storage.get_agent_session_storage(),
        storage.get_agent_step_storage(),
        storage.get_agent_playbook_storage(),
        storage.get_agent_knowledge_storage(),
        options or LeversOptions(),
    )
