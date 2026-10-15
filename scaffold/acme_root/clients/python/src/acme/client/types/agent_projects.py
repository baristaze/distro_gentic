"""The agent_projects namespace's types: the views and requests its calls
carry, as consumers import them."""

from acme.client.schema.agent_projects import (
    AgentProjectView,
    FetchCredentialView,
)

__all__ = [
    "AgentProjectView",
    "FetchCredentialView",
]
