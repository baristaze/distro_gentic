"""The agent_knowledge namespace's types: the views and requests its calls
carry, as consumers import them."""

from acme.client.schema.agent_knowledge import (
    AgentKnowledgeStatus,
    AgentKnowledgeView,
)

__all__ = [
    "AgentKnowledgeStatus",
    "AgentKnowledgeView",
]
