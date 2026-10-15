"""The agent_automations namespace's types: the views and requests its calls
carry, as consumers import them."""

from acme.client.schema.agent_automations import (
    AgentAutomationRequest,
    AgentAutomationView,
)

__all__ = [
    "AgentAutomationRequest",
    "AgentAutomationView",
]
